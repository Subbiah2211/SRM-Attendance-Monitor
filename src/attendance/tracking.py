"""Lightweight IOU tracker (spec section 3.2), with one deliberate deviation.

The spec skips recognition entirely for any face already being tracked. That is a real
saving, but at a 2-3 FPS sampling rate a face moves a long way between observations,
and when two people cross in a doorway an IOU tracker will sometimes hand track A's
box to person B. If recognition is skipped on the strength of the track alone, person B
silently inherits student A's identity and nothing downstream can detect it. That is
precisely the false-accept case spec section 6.3 says to keep rarest.

So tracks here associate detections across nearby frames and carry a running identity
that is re-verified on a short interval. Duplicate events are suppressed once per
track and again by a short per-student debounce. Recognition still runs regularly,
which the GPU headroom in section 7 allows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import UUID

from attendance.config import TrackingSettings
from attendance.types import BoundingBox, DetectedFace


@dataclass
class Track:
    track_id: int
    box: BoundingBox
    first_seen_at: datetime
    last_seen_at: datetime
    frames_since_update: int = 0
    observations: int = 1
    last_recognized_at: datetime | None = None
    student_id: UUID | None = None
    university_id: str | None = None
    best_similarity: float | None = None
    event_emitted: bool = False
    similarity_history: list[float] = field(default_factory=list)

    @property
    def is_identified(self) -> bool:
        return self.student_id is not None


class IouTracker:
    def __init__(self, settings: TrackingSettings) -> None:
        self.settings = settings
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    @property
    def active_tracks(self) -> list[Track]:
        return list(self._tracks.values())

    def update(
        self, faces: list[DetectedFace], timestamp: datetime
    ) -> list[tuple[DetectedFace, Track]]:
        """Associate detections with tracks, greedily by descending IOU.

        Returns one (detection, track) pair per detection, creating tracks for
        detections that match nothing.
        """
        for track in self._tracks.values():
            track.frames_since_update += 1

        pairs: list[tuple[float, int, int]] = []
        for detection_index, face in enumerate(faces):
            for track_id, track in self._tracks.items():
                iou = face.box.iou(track.box)
                if iou >= self.settings.min_iou:
                    pairs.append((iou, detection_index, track_id))
        pairs.sort(reverse=True)

        claimed_detections: set[int] = set()
        claimed_tracks: set[int] = set()
        assignments: dict[int, Track] = {}
        for _, detection_index, track_id in pairs:
            if detection_index in claimed_detections or track_id in claimed_tracks:
                continue
            claimed_detections.add(detection_index)
            claimed_tracks.add(track_id)
            track = self._tracks[track_id]
            track.box = faces[detection_index].box
            track.last_seen_at = timestamp
            track.frames_since_update = 0
            track.observations += 1
            assignments[detection_index] = track

        results: list[tuple[DetectedFace, Track]] = []
        for detection_index, face in enumerate(faces):
            track = assignments.get(detection_index)
            if track is None:
                track = self._create_track(face, timestamp)
            results.append((face, track))

        self._evict_stale()
        return results

    def needs_recognition(self, track: Track, timestamp: datetime) -> bool:
        if track.last_recognized_at is None:
            return True
        elapsed = (timestamp - track.last_recognized_at).total_seconds()
        return elapsed >= self.settings.reconfirm_interval_seconds

    def _create_track(self, face: DetectedFace, timestamp: datetime) -> Track:
        track = Track(
            track_id=self._next_id,
            box=face.box,
            first_seen_at=timestamp,
            last_seen_at=timestamp,
        )
        self._tracks[track.track_id] = track
        self._next_id += 1
        return track

    def _evict_stale(self) -> None:
        stale = [
            track_id
            for track_id, track in self._tracks.items()
            if track.frames_since_update > self.settings.max_age_frames
        ]
        for track_id in stale:
            del self._tracks[track_id]


class DebounceAction(Enum):
    EMIT = "emit"
    SUPPRESS = "suppress"
    REPLACE = "replace"


@dataclass
class DebounceState:
    event_id: UUID
    emitted_at: datetime
    confidence: float


class EventDebouncer:
    """Camera-local publish gate: one event per student per window.

    One pipeline process is one camera, so the key is only ``student_id``.
    The window is measured from the first published event, not each update.
    A later sighting with a higher score replaces that event in place.
    """

    def __init__(self, window_seconds: float) -> None:
        self.window_seconds = window_seconds
        self._state: dict[UUID, DebounceState] = {}

    def decide(
        self,
        student_id: UUID,
        at: datetime,
        confidence: float,
        *,
        identity_changed: bool = False,
    ) -> DebounceAction:
        if identity_changed or self.window_seconds <= 0:
            return DebounceAction.EMIT
        current = self._state.get(student_id)
        if current is None:
            return DebounceAction.EMIT
        if (at - current.emitted_at).total_seconds() >= self.window_seconds:
            return DebounceAction.EMIT
        if confidence > current.confidence:
            return DebounceAction.REPLACE
        return DebounceAction.SUPPRESS

    def event_id_for(self, student_id: UUID) -> UUID:
        return self._state[student_id].event_id

    def mark_emitted(
        self, event_id: UUID, student_id: UUID, at: datetime, confidence: float
    ) -> None:
        self._state[student_id] = DebounceState(
            event_id=event_id, emitted_at=at, confidence=confidence
        )

    def mark_replaced(self, student_id: UUID, confidence: float) -> None:
        current = self._state[student_id]
        self._state[student_id] = DebounceState(
            event_id=current.event_id,
            emitted_at=current.emitted_at,
            confidence=confidence,
        )
