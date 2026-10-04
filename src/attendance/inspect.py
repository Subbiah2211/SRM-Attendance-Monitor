"""Probe a video source for suitability before enrolling or matching against it.

Answers the questions that otherwise turn into a confusing zero-match run: are faces
being detected at all, are they big enough, sharp enough and frontal enough to clear the
quality gate, and what settings suit this footage. Runs detection and the gate but never
matches or publishes anything, so it is safe to point at anything.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from attendance.config import QualitySettings, SamplingSettings
from attendance.faces.base import FaceBackend
from attendance.faces.quality import QualityGate
from attendance.types import DetectedFace, Frame
from attendance.video import open_source
from attendance.video.sampler import FrameSampler

PASS_COLOUR = (80, 220, 80)
FAIL_COLOUR = (60, 60, 230)


@dataclass
class InspectionReport:
    source: str
    resolution: tuple[int, int] | None = None
    native_fps: float | None = None
    duration_seconds: float | None = None
    frames_decoded: int = 0
    first_sample_at: float | None = None
    last_sample_at: float | None = None
    """Seconds into the clip, so the report always states which part was examined."""
    frames_sampled: int = 0
    frames_with_faces: int = 0
    faces_total: int = 0
    faces_passed: int = 0
    face_heights: list[float] = field(default_factory=list)
    detector_scores: list[float] = field(default_factory=list)
    blur_variances: list[float] = field(default_factory=list)
    yaw_ratios: list[float] = field(default_factory=list)
    failure_reasons: dict[str, int] = field(default_factory=dict)
    crops_written: int = 0
    frames_written: int = 0

    @property
    def faces_gated(self) -> int:
        return self.faces_total - self.faces_passed

    @property
    def covered_seconds(self) -> float | None:
        if self.first_sample_at is None or self.last_sample_at is None:
            return None
        return self.last_sample_at - self.first_sample_at

    def summary(self) -> dict[str, object]:
        return {
            "source": self.source,
            "resolution": (
                f"{self.resolution[1]}x{self.resolution[0]}" if self.resolution else None
            ),
            "native_fps": self.native_fps,
            "duration_seconds": (
                round(self.duration_seconds, 2) if self.duration_seconds else None
            ),
            "examined_span": self._span_text(),
            "frames_decoded": self.frames_decoded,
            "frames_sampled": self.frames_sampled,
            "frames_with_faces": self.frames_with_faces,
            "faces_detected": self.faces_total,
            "faces_passed_quality": self.faces_passed,
            "faces_gated": self.faces_gated,
            "face_height_px": _describe(self.face_heights),
            "detector_score": _describe(self.detector_scores),
            "blur_variance": _describe(self.blur_variances),
            "yaw_ratio": _describe(self.yaw_ratios),
            "gate_failures": dict(sorted(self.failure_reasons.items(), key=lambda kv: -kv[1])),
        }

    def _span_text(self) -> str | None:
        if self.first_sample_at is None or self.last_sample_at is None:
            return None
        text = f"{self.first_sample_at:.2f}s - {self.last_sample_at:.2f}s"
        if self.duration_seconds:
            fraction = (self.covered_seconds or 0.0) / self.duration_seconds
            text += f" ({fraction:.0%} of the clip)"
        return text

    def advice(self, quality: QualitySettings) -> list[str]:
        """Plain-language next steps, which is the point of running this at all."""
        notes: list[str] = []

        if self.frames_sampled == 0:
            return ["No frames decoded. Check the path, container and codec."]

        if self.faces_total == 0:
            notes.append(
                "No faces detected in any sampled frame. Either there are no faces in "
                "shot, or they are far too small for the detector. Check a frame by eye "
                "with --save-frames before changing any threshold."
            )
            return notes

        if self.faces_passed == 0:
            notes.append(
                "Faces were detected but every one was rejected by the quality gate. "
                "The gate_failures counts above say which rule fired."
            )

        if self.face_heights:
            median_height = float(np.median(self.face_heights))
            if median_height < quality.min_face_height_px:
                notes.append(
                    f"Median face height is {median_height:.0f}px, below the "
                    f"{quality.min_face_height_px}px gate. Either reframe the camera "
                    f"closer, or lower the gate for this footage with "
                    f"ATT_QUALITY__MIN_FACE_HEIGHT_PX={max(40, int(median_height * 0.8))}."
                )
            elif median_height < quality.min_face_height_px * 1.3:
                notes.append(
                    f"Median face height is {median_height:.0f}px, only just above the "
                    f"{quality.min_face_height_px}px gate. Expect intermittent rejections."
                )

        if self.blur_variances:
            median_blur = float(np.median(self.blur_variances))
            if median_blur < quality.min_blur_variance:
                notes.append(
                    f"Median sharpness is {median_blur:.0f}, below the "
                    f"{quality.min_blur_variance:.0f} gate. Usually motion blur; a faster "
                    "shutter or better lighting helps more than lowering the threshold, "
                    "since blurred faces produce unreliable embeddings."
                )

        if self.yaw_ratios:
            median_yaw = float(np.median(self.yaw_ratios))
            if median_yaw > quality.max_yaw_ratio:
                notes.append(
                    f"Median head yaw is {median_yaw:.2f}, above the "
                    f"{quality.max_yaw_ratio:.2f} gate: faces are mostly in profile. "
                    "Aim the camera along the direction of travel rather than across it."
                )

        if (
            self.duration_seconds
            and self.covered_seconds is not None
            and self.covered_seconds < self.duration_seconds * 0.9
        ):
            notes.append(
                f"Only {self.covered_seconds:.1f}s of this {self.duration_seconds:.1f}s clip "
                f"was examined. Raise --max-frames to spread the sample further, or pass "
                "--no-spread to concentrate it at the start."
            )

        if self.frames_with_faces < self.frames_sampled * 0.5:
            notes.append(
                f"Faces appear in only {self.frames_with_faces} of "
                f"{self.frames_sampled} sampled frames. If people cross quickly, raise "
                "--target-fps so they are not missed between samples."
            )

        if not notes:
            notes.append(
                "Footage looks usable as-is. Faces are detected at a workable size and "
                "clear the quality gate."
            )
        return notes


def inspect_source(
    source: str,
    backend: FaceBackend,
    sampling: SamplingSettings,
    quality: QualitySettings,
    camera_id: str = "INSPECT",
    max_frames: int = 20,
    spread: bool = True,
    save_frames_dir: Path | None = None,
    save_crops_dir: Path | None = None,
) -> InspectionReport:
    """Examine up to ``max_frames`` frames and report what the detector and gate found.

    With ``spread`` (the default), the frame budget is distributed across the entire clip
    rather than taken consecutively from the start. Without it, ``max_frames`` at the
    configured sampling rate only ever covers the opening few seconds, which is
    misleading when judging whether footage is usable -- lighting, crowding and face size
    all vary through a clip.
    """
    report = InspectionReport(source=source)
    gate = QualityGate(quality)

    if save_frames_dir is not None:
        save_frames_dir.mkdir(parents=True, exist_ok=True)
    if save_crops_dir is not None:
        save_crops_dir.mkdir(parents=True, exist_ok=True)

    video = open_source(camera_id=camera_id, source=source)
    with video:
        report.native_fps = video.native_fps
        report.duration_seconds = getattr(video, "duration_seconds", None)

        effective = sampling
        if spread and report.duration_seconds:
            # Choose a rate that places max_frames evenly over the whole duration.
            # Never sample faster than the configured rate, so this only ever widens
            # coverage rather than increasing work.
            spread_fps = max_frames / report.duration_seconds
            if spread_fps < sampling.target_fps:
                effective = sampling.model_copy(update={"target_fps": spread_fps})

        sampler = FrameSampler(video, effective)
        for index, frame in enumerate(sampler):
            if index >= max_frames:
                break
            report.frames_sampled += 1
            offset = _offset_seconds(frame, report.native_fps)
            if report.first_sample_at is None:
                report.first_sample_at = offset
            report.last_sample_at = offset
            if report.resolution is None:
                report.resolution = frame.shape

            faces = backend.detect(frame.image)
            if faces:
                report.frames_with_faces += 1
            report.faces_total += len(faces)

            annotated = frame.image.copy() if save_frames_dir is not None else None
            for face_index, face in enumerate(faces):
                aligned = backend.align(frame.image, face)
                assessment = gate.assess(face, aligned)

                report.face_heights.append(face.box.height)
                report.detector_scores.append(face.detector_score)
                if "blur_variance" in assessment.metrics:
                    report.blur_variances.append(assessment.metrics["blur_variance"])
                if "yaw_ratio" in assessment.metrics:
                    report.yaw_ratios.append(assessment.metrics["yaw_ratio"])

                if assessment.passed:
                    report.faces_passed += 1
                else:
                    for reason in assessment.reasons:
                        key = reason.split(" ")[0]
                        report.failure_reasons[key] = report.failure_reasons.get(key, 0) + 1

                if annotated is not None:
                    _draw(annotated, face, assessment.passed)
                if save_crops_dir is not None:
                    status = "pass" if assessment.passed else "gated"
                    name = f"f{index:03d}_face{face_index}_{status}_h{face.box.height:.0f}.jpg"
                    cv2.imwrite(str(save_crops_dir / name), aligned)
                    report.crops_written += 1

            if annotated is not None:
                # Name by position in the clip, not by loop index, so the files say
                # where in the footage they came from.
                cv2.imwrite(str(save_frames_dir / f"t{offset:07.2f}s.jpg"), annotated)
                report.frames_written += 1

        report.frames_decoded = sampler.frames_seen

    return report


def _offset_seconds(frame: Frame, native_fps: float | None) -> float:
    """Seconds into the clip for a sampled frame."""
    if native_fps:
        return frame.sequence / native_fps
    return float(frame.sequence)


def _draw(image: np.ndarray, face: DetectedFace, passed: bool) -> None:
    colour = PASS_COLOUR if passed else FAIL_COLOUR
    x1, y1 = int(face.box.x1), int(face.box.y1)
    x2, y2 = int(face.box.x2), int(face.box.y2)
    cv2.rectangle(image, (x1, y1), (x2, y2), colour, 2)
    label = f"{face.box.height:.0f}px {face.detector_score:.2f}"
    cv2.putText(image, label, (x1, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1)


def _describe(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    array = np.asarray(values, dtype=np.float64)
    return {
        "min": round(float(array.min()), 3),
        "p50": round(float(np.percentile(array, 50)), 3),
        "max": round(float(array.max()), 3),
    }


@dataclass
class TrackCandidate:
    """The best observation of one track: a crop, and what it cost to pick it."""

    track_id: int
    offset_seconds: float
    quality_score: float
    crop: np.ndarray
    aligned: np.ndarray
    embedding: np.ndarray | None = None


@dataclass
class ExtractionResult:
    frames_scanned: int = 0
    tracks_found: int = 0
    people_found: int = 0
    references_written: int = 0
    cluster_sizes: list[int] = field(default_factory=list)

    @property
    def fragmentation(self) -> float | None:
        """Tracks per person. Above ~1.5 means the tracker is splitting people up."""
        if not self.people_found:
            return None
        return self.tracks_found / self.people_found


def extract_reference_candidates(
    report_dir: Path,
    source: str,
    backend: FaceBackend,
    sampling: SamplingSettings,
    quality: QualitySettings,
    max_frames: int | None = None,
    similarity_threshold: float = 0.5,
    max_per_person: int = 3,
) -> ExtractionResult:
    """Extract enrollment candidates from a clip, one directory per *person*.

    Two stages, and the second is the one that matters. First, the best-quality
    observation of each track is kept. Then those per-track crops are grouped by face
    similarity, because an IOU tracker at a 2-3 FPS sampling rate fragments a single
    person into many tracks: a walking subject moves most of a box width between
    samples, and any occlusion past ``max_age_frames`` starts a fresh track. Grouping on
    embeddings rather than trusting track identity is what turns dozens of fragments back
    into one directory per person.

    Clustering is single-linkage over cosine similarity: if A matches B and B matches C,
    A/B/C become one person even when A and C are a weaker pair (profile vs frontal).
    That is the usual shape of gate footage. Lower ``similarity_threshold`` if one person
    is still split; raise it if two people were merged.

    Each person gets up to ``max_per_person`` reference photos, which suits the 1-3
    reference photos per student the enrollment path expects.
    """
    from attendance.config import TrackingSettings
    from attendance.tracking import IouTracker

    _reset_extract_dir(report_dir)
    gate = QualityGate(quality)
    tracker = IouTracker(TrackingSettings())
    best: dict[int, TrackCandidate] = {}
    result = ExtractionResult()

    video = open_source(camera_id="EXTRACT", source=source)
    with video:
        native_fps = video.native_fps
        for index, frame in enumerate(FrameSampler(video, sampling)):
            if max_frames is not None and index >= max_frames:
                break
            result.frames_scanned += 1

            faces = backend.detect(frame.image)
            for face, track in tracker.update(faces, frame.captured_at):
                aligned = backend.align(frame.image, face)
                assessment = gate.assess(face, aligned)
                if not assessment.passed:
                    continue

                # Prefer large and sharp: both raise embedding reliability, and a
                # reference photo is used for every future match of this student.
                score = face.box.height * assessment.metrics.get("blur_variance", 1.0)
                existing = best.get(track.track_id)
                if existing is None or score > existing.quality_score:
                    best[track.track_id] = TrackCandidate(
                        track_id=track.track_id,
                        offset_seconds=_offset_seconds(frame, native_fps),
                        quality_score=score,
                        crop=_reference_crop(frame.image, face, aligned, backend),
                        aligned=aligned,
                    )

    result.tracks_found = len(best)
    if not best:
        return result

    candidates = list(best.values())
    for candidate in candidates:
        candidate.embedding = backend.embed_aligned(candidate.aligned).vector

    clusters = _cluster_by_identity(candidates, similarity_threshold)
    clusters.sort(key=lambda members: (-len(members), -max(m.quality_score for m in members)))
    result.people_found = len(clusters)
    result.cluster_sizes = [len(c) for c in clusters]

    summary: list[dict] = []
    for person_index, members in enumerate(clusters, start=1):
        target = report_dir / f"person_{person_index:02d}"
        target.mkdir(exist_ok=True)
        chosen = _select_references(members, max_per_person)
        for rank, member in enumerate(chosen, start=1):
            name = f"ref{rank}_t{member.offset_seconds:07.2f}s.jpg"
            cv2.imwrite(str(target / name), member.crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
            result.references_written += 1
        summary.append(
            {
                "directory": target.name,
                "fragments": len(members),
                "photos_kept": len(chosen),
                "track_ids": [m.track_id for m in members],
                "times_seconds": [round(m.offset_seconds, 2) for m in chosen],
            }
        )

    (report_dir / "clusters.json").write_text(
        json.dumps(
            {
                "source": source,
                "similarity_threshold": similarity_threshold,
                "tracks_found": result.tracks_found,
                "people_found": result.people_found,
                "people": summary,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def _reset_extract_dir(report_dir: Path) -> None:
    """Drop previous extract output so old track-based folders cannot mix with new ones."""
    report_dir.mkdir(parents=True, exist_ok=True)
    for child in report_dir.iterdir():
        if child.is_dir() and child.name.startswith("person_"):
            shutil.rmtree(child)
        elif child.name == "clusters.json":
            child.unlink()


def _cluster_by_identity(
    candidates: list[TrackCandidate], threshold: float
) -> list[list[TrackCandidate]]:
    """Group track fragments of the same face.

    Single-linkage over cosine similarity, via union-find: any pair at or above the
    threshold is the same person, and equality is transitive. Greedy nearest-centroid
    assignment misses the common case where fragment A is a weak match to C but both
    match a better 3/4-view fragment B.
    """
    usable = [c for c in candidates if c.embedding is not None]
    if not usable:
        return []
    if len(usable) == 1:
        return [usable]

    vectors = np.vstack([c.embedding for c in usable])
    similarity = vectors @ vectors.T
    parent = list(range(len(usable)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            if float(similarity[i, j]) >= threshold:
                root_i, root_j = find(i), find(j)
                if root_i != root_j:
                    parent[root_j] = root_i

    grouped: dict[int, list[TrackCandidate]] = {}
    for index, candidate in enumerate(usable):
        grouped.setdefault(find(index), []).append(candidate)
    return list(grouped.values())


def _select_references(
    members: list[TrackCandidate], max_per_person: int, min_gap_seconds: float = 1.0
) -> list[TrackCandidate]:
    """Keep the sharpest crops, preferring ones spaced apart in time."""
    ranked = sorted(members, key=lambda m: -m.quality_score)
    chosen: list[TrackCandidate] = []
    for member in ranked:
        if len(chosen) >= max_per_person:
            break
        if any(
            abs(member.offset_seconds - other.offset_seconds) < min_gap_seconds for other in chosen
        ):
            continue
        chosen.append(member)
    if len(chosen) < max_per_person:
        for member in ranked:
            if member in chosen:
                continue
            chosen.append(member)
            if len(chosen) >= max_per_person:
                break
    return chosen


def _reference_crop(
    image: np.ndarray,
    face: DetectedFace,
    aligned: np.ndarray,
    backend: FaceBackend,
    margin: float = 0.25,
) -> np.ndarray:
    """A crop that enrollment can re-detect as exactly one face.

    A generous margin often pulls in a neighbour, and enroll refuses those photos. Fall
    back to the aligned 112px face if the padded crop is ambiguous.
    """
    crop = _crop_with_margin(image, face, margin=margin)
    detected = backend.detect(crop)
    if len(detected) == 1:
        return crop
    return aligned


def _crop_with_margin(image: np.ndarray, face: DetectedFace, margin: float = 0.5) -> np.ndarray:
    box = face.box
    pad_x, pad_y = box.width * margin, box.height * margin
    x1 = int(max(0, box.x1 - pad_x))
    y1 = int(max(0, box.y1 - pad_y))
    x2 = int(min(image.shape[1], box.x2 + pad_x))
    y2 = int(min(image.shape[0], box.y2 + pad_y))
    return image[y1:y2, x1:x2].copy()
