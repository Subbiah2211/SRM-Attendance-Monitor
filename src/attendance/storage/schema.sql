-- Phase 1 identity schema (subset of DB/init_postgresql.sql).
--
-- Prefer running the full init script for a new database:
--   psql -U postgres -f DB/00_create_database.sql
--   psql -U postgres -d srm_attendance -f DB/init_postgresql.sql
--
-- This file stays in lock-step with the identity tables so `attendance db migrate`
-- can still bootstrap embeddings/events on an existing database.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS identity;

CREATE TABLE IF NOT EXISTS identity.cameras (
    camera_id       TEXT PRIMARY KEY,
    location_label  TEXT NOT NULL,
    source_ref      TEXT NOT NULL,
    classroom_id    INTEGER,
    roi             REAL[4],
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS identity.students (
    student_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    university_id      TEXT UNIQUE NOT NULL,
    full_name          TEXT NOT NULL,
    user_id            BIGINT UNIQUE,
    section_id         INTEGER,
    register_no        TEXT UNIQUE,
    admission_no       TEXT,
    roll_no            TEXT,
    batch_year         INTEGER,
    gender             TEXT CHECK (gender IN ('male', 'female', 'other')),
    dob                DATE,
    enrollment_status  TEXT NOT NULL DEFAULT 'active'
        CHECK (enrollment_status IN ('active', 'withdrawn', 'graduated', 'opted_out')),
    consent_granted_at TIMESTAMPTZ,
    face_registered    BOOLEAN NOT NULL DEFAULT false,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS identity.face_embeddings (
    embedding_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id    UUID NOT NULL REFERENCES identity.students (student_id) ON DELETE CASCADE,
    embedding     VECTOR(512) NOT NULL,
    model_version TEXT NOT NULL,
    source        TEXT NOT NULL CHECK (source IN ('enrollment', 're-enrollment')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS face_embeddings_model_version_idx
    ON identity.face_embeddings (model_version);
CREATE INDEX IF NOT EXISTS face_embeddings_student_idx
    ON identity.face_embeddings (student_id);

CREATE TABLE IF NOT EXISTS identity.identification_events (
    event_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id        UUID NOT NULL REFERENCES identity.students (student_id),
    camera_id         TEXT NOT NULL REFERENCES identity.cameras (camera_id),
    confidence        REAL NOT NULL,
    frame_captured_at TIMESTAMPTZ NOT NULL,
    matched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    model_version     TEXT NOT NULL,
    track_id          INTEGER,
    consumed          BOOLEAN NOT NULL DEFAULT false,
    consumed_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS identification_events_unconsumed_idx
    ON identity.identification_events (matched_at)
    WHERE NOT consumed;

CREATE INDEX IF NOT EXISTS identification_events_student_time_idx
    ON identity.identification_events (student_id, frame_captured_at DESC);

CREATE TABLE IF NOT EXISTS identity.unresolved_detections (
    detection_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id         TEXT NOT NULL REFERENCES identity.cameras (camera_id),
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
    embedding         VECTOR(512)
);

CREATE INDEX IF NOT EXISTS unresolved_detections_time_idx
    ON identity.unresolved_detections (frame_captured_at DESC);
CREATE INDEX IF NOT EXISTS unresolved_detections_stage_idx
    ON identity.unresolved_detections (stage);
