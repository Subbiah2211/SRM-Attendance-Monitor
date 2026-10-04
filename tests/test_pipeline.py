from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from attendance.config import (
    CameraSettings,
    MatchingSettings,
    QualitySettings,
    SamplingSettings,
    Settings,
    TrackingSettings,
)
from attendance.events import InMemoryEventPublisher
from attendance.matching import InMemoryEmbeddingStore, Matcher
from attendance.pipeline import CameraPipeline
from attendance.tracking import Track
from attendance.types import BoundingBox, DetectedFace, Frame, SourceMode
from attendance.video import FileVideoSource, open_source
from attendance.video.sampler import FrameSampler
from tests.conftest import (
    FRAME_HEIGHT,
    FRAME_WIDTH,
    StubBackend,
    _frontal_landmarks,
    checkerboard,
    enrolled_for,
)

FACE_BOX = BoundingBox(200, 150, 320, 300)


def build_settings(**overrides) -> Settings:
    settings = Settings(
        sampling=SamplingSettings(target_fps=3.0),
        quality=QualitySettings(min_face_height_px=100, min_blur_variance=10.0),
        matching=MatchingSettings(similarity_threshold=0.55, min_margin=0.05),
        tracking=TrackingSettings(reconfirm_interval_seconds=2.0),
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def run_pipeline(video: Path, backend, settings: Settings, store: InMemoryEmbeddingStore):
    publisher = InMemoryEventPublisher()
    pipeline = CameraPipeline(
        camera=CameraSettings(camera_id="GATE-2-NORTH", source=str(video)),
        settings=settings,
        backend=backend,
        matcher=Matcher(store, settings.matching),
        publisher=publisher,
    )
    metrics = pipeline.run()
    return publisher, metrics


def test_source_selection_by_string():
    assert isinstance(open_source("CAM-1", "/tmp/clip.mp4"), FileVideoSource)
    live = open_source("CAM-1", "rtsp://camera/stream")
    assert live.mode is SourceMode.LATEST


def test_file_sampler_downsamples_to_target_fps(synthetic_video: Path):
    """90 frames at 30 FPS sampled at 3 FPS should yield about 9 frames, not 90."""
    with FileVideoSource("CAM-1", synthetic_video) as source:
        sampled = list(FrameSampler(source, SamplingSettings(target_fps=3.0)))

    assert source.mode is SourceMode.SEQUENTIAL
    assert 8 <= len(sampled) <= 10
    assert all(f.camera_id == "CAM-1" for f in sampled)


def test_frame_timestamps_advance_with_presentation_time(synthetic_video: Path):
    """captured_at must track the footage timeline, not the wall clock, or Phase 2's
    late-arrival rules would be measured against processing time."""
    with FileVideoSource("CAM-1", synthetic_video) as source:
        sampled = list(FrameSampler(source, SamplingSettings(target_fps=3.0)))

    deltas = [
        (b.captured_at - a.captured_at).total_seconds()
        for a, b in zip(sampled, sampled[1:], strict=False)
    ]
    assert all(0.3 <= d <= 0.4 for d in deltas), deltas


def test_enrolled_face_produces_exactly_one_event_per_track(synthetic_video: Path):
    settings = build_settings()
    backend = StubBackend(boxes=[FACE_BOX])
    store = InMemoryEmbeddingStore(
        [enrolled_for("CS21B045", backend.vectors[0], backend.model_version)]
    )

    publisher, metrics = run_pipeline(synthetic_video, backend, settings, store)

    assert len(publisher.events) == 1, "a single person walking past is one identification"
    event = publisher.events[0]
    assert event.university_id == "CS21B045"
    assert event.camera_id == "GATE-2-NORTH"
    assert event.confidence > 0.99
    assert event.model_version == backend.model_version
    assert event.frame_captured_at < event.matched_at
    assert metrics.events_published == 1


def test_unknown_face_is_logged_unresolved_and_never_published(synthetic_video: Path):
    settings = build_settings()
    backend = StubBackend(boxes=[FACE_BOX])
    orthogonal = np.zeros(8, dtype=np.float32)
    orthogonal[3] = 1.0
    store = InMemoryEmbeddingStore([enrolled_for("CS21B045", orthogonal, backend.model_version)])

    publisher, metrics = run_pipeline(synthetic_video, backend, settings, store)

    assert publisher.events == [], "a non-match must never reach the event stream"
    assert len(publisher.unresolved) > 0
    assert all(u.stage == "match" for u in publisher.unresolved)
    assert metrics.unresolved_match > 0


def test_unresolved_embeddings_are_not_retained_by_default(synthetic_video: Path):
    settings = build_settings()
    backend = StubBackend(boxes=[FACE_BOX])
    store = InMemoryEmbeddingStore([enrolled_for("CS21B045", _basis(3), backend.model_version)])

    publisher, _ = run_pipeline(synthetic_video, backend, settings, store)

    assert publisher.unresolved
    assert all(u.embedding is None for u in publisher.unresolved)
    assert all(u.to_dict().get("embedding") is None for u in publisher.unresolved)


def test_small_face_is_gated_before_embedding(synthetic_video: Path):
    """The gate must run before the embedder, so a junk face costs no inference."""
    settings = build_settings()
    tiny = BoundingBox(200, 150, 230, 185)
    backend = StubBackend(boxes=[tiny])
    store = InMemoryEmbeddingStore(
        [enrolled_for("CS21B045", backend.vectors[0], backend.model_version)]
    )

    publisher, metrics = run_pipeline(synthetic_video, backend, settings, store)

    assert publisher.events == []
    assert backend.embed_calls == 0, "gated faces must not reach the embedder"
    assert metrics.faces_gated > 0
    assert all(u.stage == "quality" for u in publisher.unresolved)
    assert any("face_height" in u.reason for u in publisher.unresolved)


def test_low_detector_score_is_gated(synthetic_video: Path):
    settings = build_settings()
    backend = StubBackend(boxes=[FACE_BOX], detector_scores=[0.2])
    store = InMemoryEmbeddingStore(
        [enrolled_for("CS21B045", backend.vectors[0], backend.model_version)]
    )

    publisher, _ = run_pipeline(synthetic_video, backend, settings, store)

    assert publisher.events == []
    assert any("detector_score" in u.reason for u in publisher.unresolved)


def test_recognition_is_throttled_but_not_skipped_for_the_whole_track(synthetic_video: Path):
    """Across ~3s of footage with a 2s reconfirm interval the same face should be
    recognized more than once, so an identity swap can still be caught."""
    settings = build_settings()
    settings.tracking.reconfirm_interval_seconds = 1.0
    backend = StubBackend(boxes=[FACE_BOX])
    store = InMemoryEmbeddingStore(
        [enrolled_for("CS21B045", backend.vectors[0], backend.model_version)]
    )

    _, metrics = run_pipeline(synthetic_video, backend, settings, store)

    assert metrics.faces_embedded >= 2
    assert metrics.recognitions_skipped > 0, "throttling should still save most inferences"


def test_roi_excludes_detections_outside_the_region(synthetic_video: Path):
    settings = build_settings()
    backend = StubBackend(boxes=[FACE_BOX])
    store = InMemoryEmbeddingStore(
        [enrolled_for("CS21B045", backend.vectors[0], backend.model_version)]
    )
    publisher = InMemoryEventPublisher()
    pipeline = CameraPipeline(
        camera=CameraSettings(
            camera_id="CAM-1", source=str(synthetic_video), roi=(0.0, 0.0, 0.1, 0.1)
        ),
        settings=settings,
        backend=backend,
        matcher=Matcher(store, settings.matching),
        publisher=publisher,
    )
    metrics = pipeline.run()

    assert metrics.faces_detected == 0
    assert publisher.events == []


def test_latency_metrics_are_recorded(synthetic_video: Path):
    settings = build_settings()
    backend = StubBackend(boxes=[FACE_BOX])
    store = InMemoryEmbeddingStore(
        [enrolled_for("CS21B045", backend.vectors[0], backend.model_version)]
    )

    _, metrics = run_pipeline(synthetic_video, backend, settings, store)
    summary = metrics.as_dict()

    assert {"detect_ms", "align_ms", "embed_ms", "match_ms"} <= summary["latency"].keys()
    assert summary["latency"]["detect_ms"]["p95_ms"] >= 0


def _basis(index: int, dim: int = 8) -> np.ndarray:
    vector = np.zeros(dim, dtype=np.float32)
    vector[index] = 1.0
    return vector


T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _pipeline_for(backend: StubBackend, store: InMemoryEmbeddingStore, settings: Settings):
    publisher = InMemoryEventPublisher()
    pipeline = CameraPipeline(
        camera=CameraSettings(camera_id="CAM-1", source="unused.mp4"),
        settings=settings,
        backend=backend,
        matcher=Matcher(store, settings.matching),
        publisher=publisher,
    )
    return pipeline, publisher


def _face_frame(captured_at: datetime, sequence: int = 0) -> tuple[Frame, DetectedFace]:
    frame = Frame(
        camera_id="CAM-1",
        image=checkerboard(FRAME_HEIGHT, FRAME_WIDTH),
        captured_at=captured_at,
        sequence=sequence,
    )
    face = DetectedFace(
        box=FACE_BOX,
        detector_score=0.95,
        landmarks=_frontal_landmarks(FACE_BOX),
    )
    return frame, face


def _new_track(track_id: int, at: datetime) -> Track:
    return Track(track_id=track_id, box=FACE_BOX, first_seen_at=at, last_seen_at=at)


def test_second_track_for_same_student_is_debounced():
    settings = build_settings()
    backend = StubBackend(boxes=[FACE_BOX])
    store = InMemoryEmbeddingStore(
        [enrolled_for("CS21B045", backend.vectors[0], backend.model_version)]
    )
    pipeline, publisher = _pipeline_for(backend, store, settings)

    frame_a, face_a = _face_frame(T0)
    pipeline._process_face(frame_a, face_a, _new_track(1, T0), time.perf_counter())

    later = T0 + timedelta(seconds=5)
    frame_b, face_b = _face_frame(later, sequence=1)
    pipeline._process_face(frame_b, face_b, _new_track(2, later), time.perf_counter())

    assert [e.university_id for e in publisher.events] == ["CS21B045"]
    assert pipeline.metrics.events_published == 1
    assert pipeline.metrics.events_debounced == 1


def test_same_student_emits_again_after_debounce_window():
    settings = build_settings()
    backend = StubBackend(boxes=[FACE_BOX])
    store = InMemoryEmbeddingStore(
        [enrolled_for("CS21B045", backend.vectors[0], backend.model_version)]
    )
    pipeline, publisher = _pipeline_for(backend, store, settings)

    frame_a, face_a = _face_frame(T0)
    pipeline._process_face(frame_a, face_a, _new_track(1, T0), time.perf_counter())

    later = T0 + timedelta(seconds=30)
    frame_b, face_b = _face_frame(later, sequence=1)
    pipeline._process_face(frame_b, face_b, _new_track(2, later), time.perf_counter())

    assert len(publisher.events) == 2
    assert pipeline.metrics.events_debounced == 0


def test_identity_change_emits_even_inside_debounce_window():
    from attendance.enrollment import student_id_for

    settings = build_settings()
    backend = StubBackend(boxes=[FACE_BOX])
    store = InMemoryEmbeddingStore(
        [enrolled_for("CS21B045", backend.vectors[0], backend.model_version)]
    )
    pipeline, publisher = _pipeline_for(backend, store, settings)

    frame_a, face_a = _face_frame(T0)
    pipeline._process_face(frame_a, face_a, _new_track(1, T0), time.perf_counter())

    later = T0 + timedelta(seconds=2)
    frame_b, face_b = _face_frame(later, sequence=1)
    track = _new_track(2, later)
    track.student_id = student_id_for("CS21B046")
    track.university_id = "CS21B046"
    pipeline._process_face(frame_b, face_b, track, time.perf_counter())

    assert [e.university_id for e in publisher.events] == ["CS21B045", "CS21B045"]
    assert pipeline.metrics.events_debounced == 0
