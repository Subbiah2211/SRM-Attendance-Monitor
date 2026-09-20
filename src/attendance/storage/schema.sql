-- Phase 1 schema.
--
-- Follows spec section 4, with additions the prose requires but the DDL omitted.
-- Every deviation is commented inline.

CREATE EXTENSION IF NOT EXISTS vector;

-- Camera registry. The spec carries camera_id as free text on events, which leaves
-- nothing to validate against and no home for per-camera config (RTSP URL, ROI,
-- enabled flag). Credentials are deliberately NOT stored here; the source column holds
-- a reference resolved from the secret store at runtime.
CREATE TABLE IF NOT EXISTS cameras (
    camera_id       TEXT PRIMARY KEY,
    location_label  TEXT NOT NULL,
    source_ref      TEXT NOT NULL,
    roi             REAL[4],
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS students (
    student_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    university_id     TEXT UNIQUE NOT NULL,       -- existing SIS identifier
    full_name         TEXT NOT NULL,
    enrollment_status TEXT NOT NULL DEFAULT 'active'
        CHECK (enrollment_status IN ('active', 'withdrawn', 'graduated', 'opted_out')),
    consent_granted_at TIMESTAMPTZ,               -- section 8 requires explicit consent
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 'opted_out' is a first-class status rather than a deletion, so the opt-out path in
-- section 8 can be honoured without losing the record that a choice was made.

CREATE TABLE IF NOT EXISTS face_embeddings (
    embedding_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id    UUID NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    embedding     VECTOR(512) NOT NULL,           -- ArcFace output dimension
    model_version TEXT NOT NULL,                  -- e.g. 'insightface-buffalo_l-v1'
    source        TEXT NOT NULL CHECK (source IN ('enrollment', 're-enrollment')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Vectors are stored L2-normalized, which makes cosine distance and inner product
-- agree and lets the application treat (1 - distance) as cosine similarity directly.
CREATE INDEX IF NOT EXISTS face_embeddings_model_version_idx
    ON face_embeddings (model_version);
CREATE INDEX IF NOT EXISTS face_embeddings_student_idx
    ON face_embeddings (student_id);

-- No HNSW index here on purpose. At pilot scale (hundreds to low thousands of
-- embeddings) an exact scan is sub-millisecond and has perfect recall, whereas HNSW is
-- approximate and can silently miss the true nearest neighbour -- a bad trait during
-- the exact phase where the pilot is trying to measure real accuracy. See
-- 002_hnsw_index.sql to add it once the enrolled population justifies it.

CREATE TABLE IF NOT EXISTS identification_events (
    event_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id        UUID NOT NULL REFERENCES students(student_id),
    camera_id         TEXT NOT NULL REFERENCES cameras(camera_id),
    confidence        REAL NOT NULL,
    -- The spec's DDL had only matched_at. Phase 2's late-arrival rules need the time
    -- the frame was captured, which is earlier than the time the match completed and
    -- is the only one that reflects when the student actually walked past.
    frame_captured_at TIMESTAMPTZ NOT NULL,
    matched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Present in the section 5 event JSON but missing from the section 4 table. Needed
    -- to interpret a confidence value after any model upgrade.
    model_version     TEXT NOT NULL,
    track_id          INTEGER,
    consumed          BOOLEAN NOT NULL DEFAULT false,
    consumed_at       TIMESTAMPTZ
);

-- student_id is NOT NULL here, unlike the spec's nullable column: section 5 is explicit
-- that a low-confidence detection is never published as an event with a null student.
-- The constraint enforces what the prose promises.

-- Supports the polling consumer's "oldest unconsumed first" query without scanning
-- history. Partial, so it stays small as consumed rows accumulate.
CREATE INDEX IF NOT EXISTS identification_events_unconsumed_idx
    ON identification_events (matched_at)
    WHERE NOT consumed;

CREATE INDEX IF NOT EXISTS identification_events_student_time_idx
    ON identification_events (student_id, frame_captured_at DESC);

-- Required by sections 3.4, 6.4 and 9 ("never silently dropped", and the pilot must be
-- able to measure false rejects), but absent from the spec's data model.
CREATE TABLE IF NOT EXISTS unresolved_detections (
    detection_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id         TEXT NOT NULL REFERENCES cameras(camera_id),
    frame_captured_at TIMESTAMPTZ NOT NULL,
    logged_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    track_id          INTEGER,
    stage             TEXT NOT NULL CHECK (stage IN ('quality', 'match')),
    reason            TEXT NOT NULL,
    detector_score    REAL NOT NULL,
    box               REAL[4] NOT NULL,
    best_similarity   REAL,
    margin            REAL,
    quality_metrics   JSONB NOT NULL DEFAULT '{}'::jsonb,
    model_version     TEXT NOT NULL,
    -- Nullable and off by default. Retaining embeddings of people who were NOT
    -- identified is a privacy decision (section 6.5), not an engineering default, so
    -- writing this column requires opting in via configuration.
    embedding         VECTOR(512)
);

CREATE INDEX IF NOT EXISTS unresolved_detections_time_idx
    ON unresolved_detections (frame_captured_at DESC);
CREATE INDEX IF NOT EXISTS unresolved_detections_stage_idx
    ON unresolved_detections (stage);
