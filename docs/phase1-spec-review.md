# Phase 1 Spec Review — Implementation Notes & Deviations

Reviewing: *Technical Specification, Automated Attendance Capture System, Phase 1*, v1.0 (draft, 19 Sept 2026).

This records where the implementation departs from the spec and why, what has been measured
so far, and what still needs a decision from outside engineering. Section numbers refer to
the spec.

**Verdict: the spec is implementable as designed.** Every component is mature and
well-trodden, and nothing in it requires research. The scoping decision — stopping at "a
student was identified" and deferring attendance logic — is sound, and the §5 event contract
is a clean seam. The notes below are refinements, not objections.

Two things the spec gets right that are commonly gotten wrong, and which the implementation
preserves deliberately: routing enrollment photos through the *identical* detection and
embedding path as runtime frames (§3.5), and tagging every stored vector with a
`model_version` so a model upgrade cannot silently corrupt matching (§4).

---

## 1. Measured so far

Measured on an Apple Silicon development machine using the CoreML execution provider, on
the sample group photo shipped with InsightFace. **This is not the CUDA pilot target**, so
treat the latency figures as an upper bound and the accuracy figures as a smoke test rather
than a benchmark.

| What | Result |
| --- | --- |
| Faces detected in a 1280×886 group photo | 6 |
| Worst cross-identity cosine similarity | 0.213 (threshold 0.55) |
| Self-similarity, same frame | > 0.9999 |
| Self-similarity across JPEG re-encode at quality 70 | > 0.9 |
| Detection, full frame | 22.5 ms |
| Embedding, per face | 10.9 ms |

The separation figure is the important one: different people scored 0.213 while the same
person scored above 0.9 across re-encoding. That gap is what makes a threshold meaningful,
and it is now asserted in a test rather than assumed.

### 1.1 The §7 sizing arithmetic needs redoing

§6.1 and §7 both quote "8–10 ms per face" for detection plus embedding, and §7 extrapolates
that to "on the order of 100 face-inferences/second" and a double-digit camera count.

Two corrections. First, the measured 33 ms combined is well above 8–10 ms, and while CUDA
will beat CoreML, the published figure looks optimistic. Second and more importantly,
**detection cost is per frame, not per face** — the two are different units and the spec's
extrapolation mixes them. The real per-camera cost is:

```
one detection per sampled frame  +  one embedding per face in that frame
```

At 3 FPS on this hardware that is ~67 ms/second of detection per camera before a single
embedding, i.e. roughly 7% of one accelerator per camera from detection alone. The spec's
conclusion (a single mid-tier GPU suffices for a pilot) still holds comfortably, but the
arithmetic should be redone against real footage before hardware is ordered, as §7 itself
advises.

---

## 2. Deviations from the spec

### 2.1 Recognition is no longer skipped for the lifetime of a track

**Spec (§2.1 step 3, §3.2):** a detected face matching an existing track is skipped
entirely — "no need to re-run the expensive recognition step on a face that hasn't left the
frame."

**Implemented:** tracks suppress duplicate *events*, but recognition re-runs on a short
configurable interval (`reconfirm_interval_seconds`, default 2s).

**Why:** at a 2–3 FPS sampling rate a subject moves a long way between observations. When two
people cross in a doorway, an IOU tracker will sometimes hand track A's box to person B. If
recognition is skipped on the strength of the track alone, person B silently inherits student
A's identity and **nothing downstream can detect it** — no low confidence, no unresolved log,
just a confident wrong answer. That is precisely the false-accept case §6.3 says to keep
rarest, and it is the one failure mode in the design that is invisible after the fact.

Re-running recognition costs inference the §7 headroom comfortably allows. A re-confirmation
that disagrees with the first match now emits a `track_identity_changed` warning, which turns
a silent failure into an observable one. §3.2 already anticipates this with its
"re-confirmation interval … to guard against a bad first match"; this makes it the primary
mechanism rather than an optional extra.

### 2.2 A face quality gate has been added

**Spec:** no equivalent stage. Detection feeds straight into embedding.

**Implemented:** between detection and embedding, faces are gated on minimum height in
pixels, detector score, blur (variance of the Laplacian over the aligned crop), and
landmark-derived yaw and roll. Rejections are logged with their reason and all computed
metrics.

**Why:** a 30-pixel, motion-blurred or strongly profiled face still produces a well-formed
512-d vector, and that vector still has a nearest neighbour above almost any threshold. On
entrance cameras this is the dominant source of false accepts, and no amount of threshold
tuning fixes it — the bad vector is confidently wrong, not weakly wrong. Gating on input
quality does more for the false-accept rate than tuning the decision boundary.

The gate runs *before* the embedder so junk faces cost no inference, and there is a test
asserting zero embedder calls for a gated face so that ordering cannot silently regress.

### 2.3 The match decision adds a margin rule

**Spec (§3.4):** return the nearest neighbour if cosine similarity clears a threshold
(0.55–0.65). "Ties / low-confidence matches are logged as unresolved."

**Implemented:** clearing the threshold is necessary but not sufficient. The best student
must also beat the best candidate *from a different student* by `min_margin` (default 0.05).

**Why:** "ties" is not a decidable condition as written — two students at 0.98 and 0.97 are
not a tie by any literal reading, yet picking the first is close to a coin flip. The gap
between the top two distinct identities is usually a stronger accept/reject signal than the
absolute score, because it is robust to the whole frame being slightly off-distribution. This
turns the spec's intent into an implementable rule.

### 2.4 Per-student aggregation is defined explicitly

**Spec:** silent on this. §3.5 stores 1–3 embeddings per student; §3.4 describes
nearest-neighbour search.

**Implemented:** search returns *embeddings*, which are then collapsed per student (`max` by
default, `mean` available). The runner-up used by the margin rule is guaranteed to come from
a **different student**, not the same student's other reference photo.

**Why:** without this, a student with three reference photos occupies the top three
nearest-neighbour slots and any margin or runner-up logic compares them against themselves,
which is meaningless. This is easy to get wrong and hard to notice.

### 2.5 Similarity vs. distance is pinned down

**Spec:** §3.4 discusses a cosine *similarity* threshold; §4 indexes with
`vector_cosine_ops`, which is cosine *distance* (1 − similarity).

**Implemented:** everything above the storage layer speaks similarity only. The Postgres layer
converts (`1 - (embedding <=> query)`) at its own boundary. Separately, `FaceEmbedding`
rejects any vector that is not L2-normalized at construction time.

**Why:** the inversion is an easy and quiet bug — thresholds still "work", just backwards, and
the system confidently matches the *least* similar student. Normalization is what makes cosine
similarity, dot product and distance mutually consistent, so it is enforced rather than
assumed.

### 2.6 Pipeline stages 1–4 run in one process per camera

**Spec (§2):** five separately deployable processes connected by lightweight queues.

**Implemented:** capture, sampling, detection and embedding in a single supervised process per
camera. The only real process boundary is the §3.6 event hand-off.

**Why:** stages 1–4 pass whole video frames, and serializing 1080p frames across process
boundaries costs considerably more than the 8–10 ms of inference the spec budgets around —
it would dominate the §6.1 latency budget. The resilience property §6.4 asks for is preserved,
because it is one process *per camera*: a single camera's decode trouble still cannot stall
another, and the matcher and event consumer remain independently restartable behind their
interfaces.

### 2.7 Vector matching uses exact search, not HNSW

**Spec (§3.4, §4):** HNSW index with `m = 16, ef_construction = 200`.

**Implemented:** exact scan. The HNSW index ships as a separate, deliberately applied
migration (`002_hnsw_index.sql`).

**Why:** at pilot scale — hundreds to low thousands of embeddings — an exact scan over 512-d
unit vectors is a single matrix multiply taking well under a millisecond, with **perfect
recall**. HNSW is approximate: it can miss the true nearest neighbour. That is an awkward
property during exactly the phase where the pilot is trying to measure real accuracy, because
a missed match is indistinguishable from a model failure. Add the index when the enrolled
population makes it necessary, and re-measure accuracy when you do.

Two related gaps worth noting for when that happens. The spec never specifies `ef_search`,
the runtime recall/latency knob (default 40), which matters as much as the build parameters
it does specify. And because the matching query filters to active students and a single
`model_version`, an approximate index applies those filters *after* returning candidates, so a
query can come back short — or empty — even when matching rows exist.

### 2.8 Session and cache control for the detector

Not a spec deviation, but a deployment trap worth recording. InsightFace's SCRFD wrapper
compiles a second, input-size-specialized session at detect time. Left alone it does this
through its own factory, which on CoreML writes a compiled cache under `$HOME` and builds the
session with its *own* provider options rather than the configured ones. That breaks in
containers and on read-only home directories, and it silently ignores provider configuration.
The implementation disables that path; it can be re-enabled once a deployment can write to a
controlled cache location.

---

## 3. Data model changes

The spec's §4 DDL is missing several things its own prose requires.

**Two new tables.** `cameras`, a registry, because §5 carries `camera_id` as free text with
nothing to validate against and no home for per-camera configuration (source reference, ROI,
enabled flag). And `unresolved_detections`, which §3.4, §6.4 and §9 all require — "never
silently dropped", plus the pilot must be able to measure false rejects — but which has no
table in §4.

**Changes to `identification_events`:**

- `frame_captured_at` added, distinct from `matched_at`. The spec has only the latter. Phase 2's
  late-arrival rules need the time the student actually walked past, not the time the match
  completed.
- `model_version` added. It appears in the §5 event JSON but not the §4 table, and without it a
  stored confidence value cannot be interpreted after a model upgrade.
- `student_id` made **NOT NULL**. The spec declares it nullable, while §5 states plainly that a
  low-confidence detection is never published as an event with a null student. The constraint
  now enforces what the prose promises.
- `track_id` and `consumed_at` added, for traceability and for measuring consumer lag.
- The unconsumed-events index is **partial** (`WHERE NOT consumed`) so it stays small as
  consumed history accumulates.

**Changes to `students`:** `enrollment_status` gains a `CHECK` constraint including
`opted_out` as a first-class value, so the §8 opt-out path is honoured without deleting the
record that a choice was made. `consent_granted_at` added, since §8 requires explicit consent
before enrollment.

**Queue semantics.** The spec's `consumed` boolean with a polling consumer is not safe for more
than one worker — two pollers race on the same rows. The reference consumer uses
`FOR UPDATE ... SKIP LOCKED` so workers claim disjoint batches.

**Retention of unresolved embeddings.** The `unresolved_detections.embedding` column is
nullable and **off by default**. Tuning benefits from retaining the embeddings of people who
were *not* identified, but doing so is a privacy decision under §6.5 and §8, not an
engineering default, so it requires explicit configuration.

---

## 4. Ambiguities worth resolving in the spec text

**The §6.1 latency target has no defined start point.** "Frame captured → identification event
published" under 500 ms reads clearly until you combine it with §6.2's 2–3 FPS sampling. If
the clock starts at the *sampled* frame's capture time, 500 ms is comfortable. If it starts
when the face physically enters frame, the sampling interval alone consumes 330–500 ms of the
budget before any work begins. The implementation reports both, as `processing_latency`
(what the code controls) and presence latency (what a student experiences). The spec should
say which one it is committing to.

**§6.3 defers the accuracy target correctly but leaves no way to measure it.** Refusing a
number before pilot data is right. But the pilot cannot produce false-accept and false-reject
rates without ground truth, and how that ground truth gets collected is not specified. It
needs deciding before the pilot starts, not during: a human logging who passed the gate, a
badge-scan cross-check, or something else.

**The enrollment domain gap is not addressed.** §3.5 correctly insists enrollment and runtime
embeddings come from an identical pipeline. It does not address the *other* half: if reference
photos come from SIS records (frontal, studio-lit, possibly years old) while runtime frames are
angled, overhead and motion-blurred, accuracy suffers regardless of model quality. Either
capture enrollment photos at similar angles and resolution, or plan to re-enroll from
high-confidence runtime detections — the `source` column already anticipates the latter with
its `'re-enrollment'` value.

**Observability has no home in the scope.** §9 makes latency, accuracy rates and GPU
utilisation the Phase 2 exit criteria, and §6.4 mentions an ops dashboard, but §1 puts
dashboards out of scope. Something has to export per-stage latency, match rates and camera
uptime or the pilot cannot report on its own exit criteria. Per-stage metrics are collected
in-process today; exporting them is a small addition, but it should be explicitly in scope.

**Camera credentials.** RTSP URLs embed credentials. §8 covers encryption and access control
for the embeddings table but says nothing about camera secrets, which should not live in
config files or version control.

### 4.1 The licensing flag is real and should be closed early

§3.3 already flags it, correctly: InsightFace's code is MIT, but the pretrained packs
(including `buffalo_l`) are published for non-commercial research use. Weights are currently
being used for evaluation only, and the backend interface exists so the production model can
be swapped without touching the pipeline.

One related point on expectations: the "~99.9% LFW" figure in §3.3 is a saturated benchmark
and says very little about entrance-camera performance. IJB-C TAR@FAR=1e-4 is a more
predictive reference. Expect materially worse numbers on real footage than any published
headline, and set stakeholder expectations accordingly.

---

## 5. Not yet validated

Being explicit about what has *not* been demonstrated:

- **Live RTSP capture.** The reconnect-with-backoff path (§3.1, §6.4) is written but has never
  run against a real camera or a stream that actually drops.
- **Accuracy on real conditions.** Validation so far uses a handful of faces in a single
  well-lit photo. Nothing here speaks to the university's cameras, lighting, angles or student
  population, which is what §6.3 and §9 exist to establish.
- **CUDA.** All measurements are CoreML on a laptop. The pilot target is untested.
- **Multi-camera operation.** One pipeline per camera is the design; concurrent cameras have
  not been run.
- **Threshold choice.** 0.55 is the spec's suggested starting point, carried over unchanged. It
  has not been tuned against any false-accept/false-reject data, which §3.4 explicitly warns
  against treating as fixed.

---

## 6. Open questions

§10's questions still stand, particularly whether an SIS can supply enrollment photos and who
owns consent operationally. The ones that block implementation specifically:

1. **Does the target Postgres have pgvector available?** It is a server-side extension needing
   elevated privileges to install; without it the §4 data model cannot be used as written.
   `attendance db check` answers this with read-only access, so it can be run before anyone
   grants schema privileges.
2. **Which latency definition is being committed to** (§4 above).
3. **How ground truth will be collected** during the pilot (§4 above).
4. **Where camera credentials will live.**
5. **Is the licensing position acceptable for a pilot**, and what is the production model?
