"""Per-camera identification pipeline.

Spec section 2 describes five separately deployable stages joined by queues. Stages one
through four all pass whole video frames, and serializing 1080p frames across process
boundaries costs considerably more than the 8-10ms of inference the spec budgets
around. So capture, sampling, detection and embedding run in a single process here, and
the only real process boundary is the event hand-off in section 3.6.

The resilience property section 6.4 asks for is preserved: this is one supervised
process *per camera*, so one camera's decode trouble cannot stall another, and the
matcher and event consumer remain independently restartable behind their interfaces.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import structlog

from attendance.config import CameraSettings, Settings
from attendance.events import EventPublisher
from attendance.faces.base import FaceBackend
from attendance.faces.quality import QualityGate
from attendance.matching.base import Matcher
from attendance.metrics import PipelineMetrics
from attendance.tracking import DebounceAction, EventDebouncer, IouTracker, Track
from attendance.types import (
    BoundingBox,
    DetectedFace,
    Frame,
    IdentificationEvent,
    MatchOutcome,
    UnresolvedDetection,
)
from attendance.video import open_source
from attendance.video.sampler import FrameSampler

log = structlog.get_logger(__name__)


class CameraPipeline:
    def __init__(
        self,
        camera: CameraSettings,
        settings: Settings,
        backend: FaceBackend,
        matcher: Matcher,
        publisher: EventPublisher,
    ) -> None:
        self.camera = camera
        self.settings = settings
        self.backend = backend
        self.matcher = matcher
        self.publisher = publisher
        self.quality_gate = QualityGate(settings.quality)
        self.tracker = IouTracker(settings.tracking)
        self.debouncer = EventDebouncer(settings.tracking.emit_debounce_seconds)
        self.metrics = PipelineMetrics()

    def run(self, max_frames: int | None = None) -> PipelineMetrics:
        source = open_source(
            camera_id=self.camera.camera_id,
            source=self.camera.source,
            **self._source_kwargs(),
        )
        sampler = FrameSampler(source, self.settings.sampling, roi=self.camera.roi)

        log.info(
            "pipeline_starting",
            camera_id=self.camera.camera_id,
            source_mode=source.mode.value,
            provider=self.backend.provider,
            model_version=self.backend.model_version,
            target_fps=self.settings.sampling.target_fps,
            enrolled_embeddings=self.matcher.store.size,
        )

        with source:
            for index, frame in enumerate(sampler):
                if max_frames is not None and index >= max_frames:
                    break
                self._process_frame(frame)

        log.info("pipeline_finished", camera_id=self.camera.camera_id, **self.metrics.as_dict())
        return self.metrics

    def _source_kwargs(self) -> dict:
        lowered = self.camera.source.lower()
        if lowered.startswith(("rtsp://", "rtsps://")) or "!" in self.camera.source:
            return {
                "reconnect_initial_seconds": self.camera.reconnect_initial_seconds,
                "reconnect_max_seconds": self.camera.reconnect_max_seconds,
            }
        return {}

    def _process_frame(self, frame: Frame) -> None:
        processing_started = time.perf_counter()
        self.metrics.frames_sampled += 1

        detect_started = time.perf_counter()
        faces = self.backend.detect(frame.image)
        self.metrics.record("detect_ms", _elapsed_ms(detect_started))

        faces = [f for f in faces if self._within_roi(f, frame)]
        self.metrics.faces_detected += len(faces)
        if not faces:
            return

        for face, track in self.tracker.update(faces, frame.captured_at):
            self._process_face(frame, face, track, processing_started)

    def _process_face(
        self, frame: Frame, face: DetectedFace, track: Track, processing_started: float
    ) -> None:
        if not self.tracker.needs_recognition(track, frame.captured_at):
            self.metrics.recognitions_skipped += 1
            return

        align_started = time.perf_counter()
        aligned = self.backend.align(frame.image, face)
        self.metrics.record("align_ms", _elapsed_ms(align_started))

        assessment = self.quality_gate.assess(face, aligned)
        if not assessment.passed:
            self.metrics.faces_gated += 1
            self.metrics.unresolved_quality += 1
            self.publisher.log_unresolved(
                UnresolvedDetection(
                    camera_id=frame.camera_id,
                    frame_captured_at=frame.captured_at,
                    track_id=track.track_id,
                    stage="quality",
                    reason="; ".join(assessment.reasons),
                    detector_score=face.detector_score,
                    box=face.box,
                    quality_metrics=assessment.metrics,
                )
            )
            return

        embed_started = time.perf_counter()
        embedding = self.backend.embed_aligned(aligned)
        self.metrics.record("embed_ms", _elapsed_ms(embed_started))
        self.metrics.faces_embedded += 1

        match_started = time.perf_counter()
        result = self.matcher.match(embedding)
        self.metrics.record("match_ms", _elapsed_ms(match_started))

        track.last_recognized_at = frame.captured_at

        if result.outcome is not MatchOutcome.MATCHED or result.best is None:
            self.metrics.unresolved_match += 1
            self.publisher.log_unresolved(
                UnresolvedDetection(
                    camera_id=frame.camera_id,
                    frame_captured_at=frame.captured_at,
                    track_id=track.track_id,
                    stage="match",
                    reason=result.reason or result.outcome.value,
                    detector_score=face.detector_score,
                    box=face.box,
                    best_similarity=result.best.similarity if result.best else None,
                    margin=result.margin,
                    quality_metrics=assessment.metrics,
                    embedding=(
                        embedding.vector
                        if self.settings.privacy.persist_unresolved_embeddings
                        else None
                    ),
                )
            )
            return

        candidate = result.best
        previous_student = track.student_id
        identity_changed = (
            previous_student is not None and previous_student != candidate.student_id
        )
        track.student_id = candidate.student_id
        track.university_id = candidate.university_id
        track.best_similarity = candidate.similarity
        track.similarity_history.append(candidate.similarity)

        if identity_changed:
            # Re-confirmation disagreed with the first match. Worth surfacing: it means
            # either a borderline pair of students or a track that swapped subjects.
            log.warning(
                "track_identity_changed",
                camera_id=frame.camera_id,
                track_id=track.track_id,
                previous_student_id=str(previous_student),
                new_university_id=candidate.university_id,
                similarity=round(candidate.similarity, 3),
            )

        already_reported = track.event_emitted and self.settings.tracking.emit_event_once_per_track
        action = self.debouncer.decide(
            candidate.student_id,
            frame.captured_at,
            candidate.similarity,
            identity_changed=identity_changed,
        )

        if action is DebounceAction.REPLACE:
            event = IdentificationEvent(
                event_id=self.debouncer.event_id_for(candidate.student_id),
                student_id=candidate.student_id,
                university_id=candidate.university_id,
                camera_id=frame.camera_id,
                confidence=candidate.similarity,
                frame_captured_at=frame.captured_at,
                model_version=embedding.model_version,
                track_id=track.track_id,
                matched_at=datetime.now(UTC),
            )
            self.publisher.replace(event)
            self.debouncer.mark_replaced(candidate.student_id, candidate.similarity)
            self.metrics.events_updated += 1
            self.metrics.record("processing_latency_ms", _elapsed_ms(processing_started))
            return

        if action is DebounceAction.SUPPRESS:
            self.metrics.events_debounced += 1
            log.info(
                "identification_debounced",
                university_id=candidate.university_id,
                camera_id=frame.camera_id,
                track_id=track.track_id,
                confidence=round(candidate.similarity, 3),
            )
            return

        if already_reported and not identity_changed:
            return

        event = IdentificationEvent(
            student_id=candidate.student_id,
            university_id=candidate.university_id,
            camera_id=frame.camera_id,
            confidence=candidate.similarity,
            frame_captured_at=frame.captured_at,
            model_version=embedding.model_version,
            track_id=track.track_id,
            matched_at=datetime.now(UTC),
        )
        self.publisher.publish(event)
        self.debouncer.mark_emitted(
            event.event_id, candidate.student_id, frame.captured_at, candidate.similarity
        )
        track.event_emitted = True
        self.metrics.events_published += 1
        self.metrics.record("processing_latency_ms", _elapsed_ms(processing_started))

    def _within_roi(self, face: DetectedFace, frame: Frame) -> bool:
        if self.camera.roi is None:
            return True
        height, width = frame.shape
        x1, y1, x2, y2 = self.camera.roi
        region = BoundingBox(x1 * width, y1 * height, x2 * width, y2 * height)
        return face.box.iou(region) > 0 or _contains(region, face.box.center)


def _contains(box: BoundingBox, point: tuple[float, float]) -> bool:
    return box.x1 <= point[0] <= box.x2 and box.y1 <= point[1] <= box.y2


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0
