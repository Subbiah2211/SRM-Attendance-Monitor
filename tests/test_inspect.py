from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from attendance.config import QualitySettings, SamplingSettings
from attendance.inspect import InspectionReport, extract_reference_candidates, inspect_source
from attendance.types import BoundingBox
from tests.conftest import StubBackend

FACE_BOX = BoundingBox(200, 150, 320, 300)
TINY_BOX = BoundingBox(200, 150, 230, 185)

SAMPLING = SamplingSettings(target_fps=3.0)
QUALITY = QualitySettings(min_face_height_px=100, min_blur_variance=10.0)


def test_reports_source_properties_and_counts(synthetic_video: Path):
    report = inspect_source(
        source=str(synthetic_video),
        backend=StubBackend(boxes=[FACE_BOX]),
        sampling=SAMPLING,
        quality=QUALITY,
        max_frames=5,
    )

    assert report.frames_sampled == 5
    assert report.resolution == (480, 640)
    assert report.native_fps == 30.0
    assert report.faces_total == 5
    assert report.faces_passed == 5
    assert report.frames_with_faces == 5


def test_summary_includes_quality_distributions(synthetic_video: Path):
    report = inspect_source(
        source=str(synthetic_video),
        backend=StubBackend(boxes=[FACE_BOX]),
        sampling=SAMPLING,
        quality=QUALITY,
        max_frames=3,
    )
    summary = report.summary()

    assert summary["resolution"] == "640x480"
    for key in ("face_height_px", "detector_score", "blur_variance", "yaw_ratio"):
        assert summary[key] is not None
        assert {"min", "p50", "max"} == summary[key].keys()


def test_gated_faces_are_counted_with_reasons(synthetic_video: Path):
    report = inspect_source(
        source=str(synthetic_video),
        backend=StubBackend(boxes=[TINY_BOX]),
        sampling=SAMPLING,
        quality=QUALITY,
        max_frames=4,
    )

    assert report.faces_total == 4
    assert report.faces_passed == 0
    assert report.faces_gated == 4
    assert "face_height" in report.failure_reasons


def test_spread_samples_across_the_whole_clip(long_synthetic_video: Path):
    """The default must not judge a 12s clip from only its opening seconds."""
    report = inspect_source(
        source=str(long_synthetic_video),
        backend=StubBackend(boxes=[FACE_BOX]),
        sampling=SAMPLING,
        quality=QUALITY,
        max_frames=10,
        spread=True,
    )

    assert report.duration_seconds is not None
    assert report.duration_seconds == pytest.approx(12.0, abs=0.2)
    assert report.frames_sampled == 10
    assert report.covered_seconds is not None
    assert report.covered_seconds > report.duration_seconds * 0.8, (
        f"only covered {report.covered_seconds:.1f}s of {report.duration_seconds:.1f}s"
    )
    assert "of the clip" in report.summary()["examined_span"]


def test_no_spread_concentrates_on_the_opening_seconds(long_synthetic_video: Path):
    report = inspect_source(
        source=str(long_synthetic_video),
        backend=StubBackend(boxes=[FACE_BOX]),
        sampling=SAMPLING,
        quality=QUALITY,
        max_frames=10,
        spread=False,
    )

    assert report.frames_sampled == 10
    assert report.covered_seconds is not None
    assert report.covered_seconds < 4.0, "without spreading, 10 frames at 3 FPS is ~3s"


def test_spread_never_samples_faster_than_the_configured_rate(synthetic_video: Path):
    """On a clip too short to spread over, behaviour is unchanged."""
    report = inspect_source(
        source=str(synthetic_video),
        backend=StubBackend(boxes=[FACE_BOX]),
        sampling=SAMPLING,
        quality=QUALITY,
        max_frames=20,
        spread=True,
    )
    assert report.frames_sampled <= 9, "a 3s clip at 3 FPS yields about 9 frames"


def test_advice_warns_when_most_of_the_clip_was_skipped():
    report = InspectionReport(
        source="clip.mp4",
        duration_seconds=38.0,
        frames_sampled=20,
        frames_with_faces=20,
        faces_total=20,
        faces_passed=20,
        face_heights=[150.0] * 20,
        first_sample_at=0.0,
        last_sample_at=6.33,
    )
    advice = " ".join(report.advice(QUALITY))
    assert "6.3s of this 38.0s clip" in advice
    assert "--max-frames" in advice


def test_advice_flags_footage_with_no_faces():
    report = InspectionReport(source="clip.mp4", frames_sampled=10)
    advice = " ".join(report.advice(QUALITY))
    assert "No faces detected" in advice


def test_advice_recommends_a_lower_gate_for_small_faces():
    report = InspectionReport(
        source="clip.mp4",
        frames_sampled=10,
        frames_with_faces=10,
        faces_total=10,
        faces_passed=0,
        face_heights=[55.0] * 10,
    )
    advice = " ".join(report.advice(QualitySettings(min_face_height_px=100)))

    assert "below the 100px gate" in advice
    assert "ATT_QUALITY__MIN_FACE_HEIGHT_PX=44" in advice


def test_advice_is_positive_for_usable_footage():
    report = InspectionReport(
        source="clip.mp4",
        frames_sampled=10,
        frames_with_faces=10,
        faces_total=10,
        faces_passed=10,
        face_heights=[150.0] * 10,
        blur_variances=[120.0] * 10,
        yaw_ratios=[0.1] * 10,
    )
    assert "usable as-is" in " ".join(report.advice(QUALITY))


def test_saves_annotated_frames_and_crops(synthetic_video: Path, tmp_path: Path):
    frames_dir = tmp_path / "frames"
    crops_dir = tmp_path / "crops"

    report = inspect_source(
        source=str(synthetic_video),
        backend=StubBackend(boxes=[FACE_BOX]),
        sampling=SAMPLING,
        quality=QUALITY,
        max_frames=3,
        save_frames_dir=frames_dir,
        save_crops_dir=crops_dir,
    )

    assert report.frames_written == 3
    assert report.crops_written == 3
    assert len(list(frames_dir.glob("*.jpg"))) == 3
    assert len(list(crops_dir.glob("*.jpg"))) == 3
    assert any("pass" in p.name for p in crops_dir.glob("*.jpg"))


def test_extract_references_collapses_one_track_to_one_person(
    synthetic_video: Path, tmp_path: Path
):
    """Many frames of one continuous track become one directory, not one file per frame."""
    output = tmp_path / "candidates"
    result = extract_reference_candidates(
        report_dir=output,
        source=str(synthetic_video),
        backend=StubBackend(boxes=[FACE_BOX]),
        sampling=SAMPLING,
        quality=QUALITY,
        max_frames=9,
    )

    assert result.tracks_found == 1
    assert result.people_found == 1
    photos = list((output / "person_01").glob("*.jpg"))
    assert len(photos) == 1
    assert (output / "clusters.json").exists()


def test_extract_replaces_stale_track_folders(synthetic_video: Path, tmp_path: Path):
    output = tmp_path / "candidates"
    leftover = output / "person_70"
    leftover.mkdir(parents=True)
    (leftover / "ref.jpg").write_bytes(b"old")

    extract_reference_candidates(
        report_dir=output,
        source=str(synthetic_video),
        backend=StubBackend(boxes=[FACE_BOX]),
        sampling=SAMPLING,
        quality=QUALITY,
        max_frames=3,
    )

    assert not leftover.exists()
    assert (output / "person_01").is_dir()


def test_cluster_chains_fragments_that_only_match_through_a_middle_view():
    """Profile A and profile C may sit below the threshold against each other, but both
    match a 3/4-view B. That must still be one person, which greedy assignment misses."""
    import numpy as np

    from attendance.inspect import TrackCandidate, _cluster_by_identity

    a = _unit([1.0, 0.0, 0.0])
    b = _unit([0.7, 0.3, 0.0])
    c = _unit([0.3, 0.95, 0.0])
    assert float(np.dot(a, c)) < 0.5
    assert float(np.dot(a, b)) >= 0.5
    assert float(np.dot(b, c)) >= 0.5

    blank = np.zeros((8, 8, 3), dtype=np.uint8)
    fragments = [
        TrackCandidate(1, 1.0, 10, blank, blank, a),
        TrackCandidate(2, 4.0, 9, blank, blank, c),
        TrackCandidate(3, 8.0, 8, blank, blank, b),
    ]
    clusters = _cluster_by_identity(fragments, threshold=0.5)

    assert len(clusters) == 1
    assert {m.track_id for m in clusters[0]} == {1, 2, 3}


def test_cluster_does_not_merge_distinct_identities():
    import numpy as np

    from attendance.inspect import TrackCandidate, _cluster_by_identity

    blank = np.zeros((8, 8, 3), dtype=np.uint8)
    fragments = [
        TrackCandidate(1, 1.0, 10, blank, blank, _unit([1, 0, 0])),
        TrackCandidate(2, 2.0, 9, blank, blank, _unit([1, 0, 0])),
        TrackCandidate(3, 3.0, 8, blank, blank, _unit([0, 1, 0])),
    ]
    clusters = _cluster_by_identity(fragments, threshold=0.5)

    assert len(clusters) == 2
    assert sorted(len(c) for c in clusters) == [1, 2]


def test_select_references_prefers_quality_and_time_gap():
    import numpy as np

    from attendance.inspect import TrackCandidate, _select_references

    blank = np.zeros((8, 8, 3), dtype=np.uint8)
    members = [
        TrackCandidate(1, 1.0, 10, blank, blank),
        TrackCandidate(2, 1.2, 9, blank, blank),
        TrackCandidate(3, 5.0, 8, blank, blank),
        TrackCandidate(4, 9.0, 4, blank, blank),
    ]
    chosen = _select_references(members, max_per_person=3, min_gap_seconds=1.0)
    times = [m.offset_seconds for m in chosen]
    assert 1.2 not in times, "1.2s is too close to the sharper 1.0s crop"
    assert times[0] == 1.0


def _unit(values: list[float]) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)
