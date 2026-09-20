from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from attendance.config import QualitySettings, TrackingSettings
from attendance.faces.quality import QualityGate
from attendance.tracking import IouTracker
from attendance.types import BoundingBox, DetectedFace

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def sharp_crop(size: int = 112) -> np.ndarray:
    """High-frequency checkerboard: passes any blur threshold."""
    grid = np.indices((size, size)).sum(axis=0) % 2
    return np.stack([grid * 255] * 3, axis=-1).astype(np.uint8)


def flat_crop(size: int = 112) -> np.ndarray:
    return np.full((size, size, 3), 128, dtype=np.uint8)


def frontal_landmarks(cx: float = 56, cy: float = 56) -> np.ndarray:
    return np.array(
        [
            [cx - 15, cy - 10],
            [cx + 15, cy - 10],
            [cx, cy + 5],
            [cx - 10, cy + 20],
            [cx + 10, cy + 20],
        ],
        dtype=np.float32,
    )


def profile_landmarks() -> np.ndarray:
    """Nose pushed hard toward the left eye, as when the head is strongly turned."""
    return np.array(
        [[40, 46], [70, 46], [43, 61], [45, 76], [65, 76]],
        dtype=np.float32,
    )


def face(height: float = 120, score: float = 0.9, landmarks=None) -> DetectedFace:
    return DetectedFace(
        box=BoundingBox(0, 0, height * 0.8, height),
        detector_score=score,
        landmarks=landmarks if landmarks is not None else frontal_landmarks(),
    )


def test_good_face_passes():
    gate = QualityGate(QualitySettings())
    assert gate.assess(face(), sharp_crop()).passed


def test_small_face_is_rejected():
    gate = QualityGate(QualitySettings(min_face_height_px=100))
    result = gate.assess(face(height=40), sharp_crop())
    assert not result.passed
    assert any("face_height" in r for r in result.reasons)


def test_blurry_face_is_rejected():
    gate = QualityGate(QualitySettings())
    result = gate.assess(face(), flat_crop())
    assert not result.passed
    assert any("blur_variance" in r for r in result.reasons)


def test_low_detector_score_is_rejected():
    gate = QualityGate(QualitySettings(min_detector_score=0.6))
    result = gate.assess(face(score=0.3), sharp_crop())
    assert not result.passed
    assert any("detector_score" in r for r in result.reasons)


def test_strong_profile_is_rejected():
    gate = QualityGate(QualitySettings(max_yaw_ratio=0.45))
    result = gate.assess(face(landmarks=profile_landmarks()), sharp_crop())
    assert not result.passed
    assert any("yaw_ratio" in r for r in result.reasons)


def test_rejection_reports_all_metrics_for_tuning():
    gate = QualityGate(QualitySettings())
    metrics = gate.assess(face(height=30), flat_crop()).metrics
    assert {"detector_score", "face_height_px", "blur_variance", "yaw_ratio"} <= metrics.keys()


def test_overlapping_detection_keeps_the_same_track():
    tracker = IouTracker(TrackingSettings(min_iou=0.3))
    first = DetectedFace(box=BoundingBox(100, 100, 200, 220), detector_score=0.9)
    second = DetectedFace(box=BoundingBox(110, 105, 210, 225), detector_score=0.9)

    [(_, track_a)] = tracker.update([first], T0)
    [(_, track_b)] = tracker.update([second], T0 + timedelta(milliseconds=330))

    assert track_a.track_id == track_b.track_id
    assert track_b.observations == 2


def test_distant_detection_starts_a_new_track():
    tracker = IouTracker(TrackingSettings(min_iou=0.3))
    [(_, track_a)] = tracker.update(
        [DetectedFace(box=BoundingBox(0, 0, 100, 120), detector_score=0.9)], T0
    )
    [(_, track_b)] = tracker.update(
        [DetectedFace(box=BoundingBox(600, 400, 700, 520), detector_score=0.9)], T0
    )
    assert track_a.track_id != track_b.track_id


def test_two_faces_get_distinct_tracks_in_one_frame():
    tracker = IouTracker(TrackingSettings())
    faces = [
        DetectedFace(box=BoundingBox(0, 0, 100, 120), detector_score=0.9),
        DetectedFace(box=BoundingBox(300, 0, 400, 120), detector_score=0.9),
    ]
    tracks = {track.track_id for _, track in tracker.update(faces, T0)}
    assert len(tracks) == 2


def test_stale_tracks_are_evicted():
    tracker = IouTracker(TrackingSettings(max_age_frames=2))
    tracker.update([DetectedFace(box=BoundingBox(0, 0, 100, 120), detector_score=0.9)], T0)
    for _ in range(4):
        tracker.update([], T0)
    assert tracker.active_tracks == []


def test_recognition_reruns_after_the_reconfirm_interval():
    """Recognition is re-run rather than skipped for the life of the track, so an IOU
    identity swap cannot silently persist."""
    tracker = IouTracker(TrackingSettings(reconfirm_interval_seconds=2.0))
    [(_, track)] = tracker.update(
        [DetectedFace(box=BoundingBox(0, 0, 100, 120), detector_score=0.9)], T0
    )

    assert tracker.needs_recognition(track, T0) is True
    track.last_recognized_at = T0
    assert tracker.needs_recognition(track, T0 + timedelta(seconds=1)) is False
    assert tracker.needs_recognition(track, T0 + timedelta(seconds=2.5)) is True
