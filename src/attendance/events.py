"""Identification event publishing (spec section 3.6).

The spec wants a durable, ordered hand-off that Phase 1 can write to without caring who
reads it, and says a Postgres table with a polling consumer is enough for pilot scale.
That table is deliberately not written yet; this interface is the seam it will slot
into, and the JSONL implementation below is what the pilot can run against in the
meantime without losing any data.

Unresolved detections go to a *separate* sink, never into the event stream, so Phase 2
never has to reason about a maybe-match.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

import structlog

from attendance.types import IdentificationEvent, UnresolvedDetection

log = structlog.get_logger(__name__)


class EventPublisher(ABC):
    @abstractmethod
    def publish(self, event: IdentificationEvent) -> None: ...

    @abstractmethod
    def replace(self, event: IdentificationEvent) -> None:
        """Update an already-published event in place, keeping ``event_id``."""

    @abstractmethod
    def log_unresolved(self, detection: UnresolvedDetection) -> None: ...

    def close(self) -> None:
        return None

    def __enter__(self) -> EventPublisher:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class JsonlEventPublisher(EventPublisher):
    """JSONL files, flushed per record so a crash loses nothing.

    New events are appended. A debounce upgrade rewrites the matching line so the
    file still holds one row per event_id.
    """

    def __init__(self, output_dir: Path, persist_unresolved_embeddings: bool = False) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.persist_unresolved_embeddings = persist_unresolved_embeddings
        self._events_path = self.output_dir / "identification_events.jsonl"
        self._events: TextIO = self._events_path.open("a")
        self._unresolved: TextIO = (self.output_dir / "unresolved_detections.jsonl").open("a")
        self.published_count = 0
        self.unresolved_count = 0

    def publish(self, event: IdentificationEvent) -> None:
        stamped = _with_matched_at(event)
        self._write(self._events, stamped.to_dict())
        self.published_count += 1
        log.info(
            "identification_published",
            university_id=stamped.university_id,
            camera_id=stamped.camera_id,
            confidence=round(stamped.confidence, 3),
            track_id=stamped.track_id,
        )

    def replace(self, event: IdentificationEvent) -> None:
        stamped = _with_matched_at(event)
        target = str(stamped.event_id)
        self._events.flush()
        self._events.close()
        rewritten: list[str] = []
        found = False
        if self._events_path.exists():
            for line in self._events_path.read_text().splitlines():
                if not line:
                    continue
                payload = json.loads(line)
                if payload.get("event_id") == target:
                    rewritten.append(json.dumps(stamped.to_dict()))
                    found = True
                else:
                    rewritten.append(line)
        if not found:
            rewritten.append(json.dumps(stamped.to_dict()))
        self._events_path.write_text("\n".join(rewritten) + ("\n" if rewritten else ""))
        self._events = self._events_path.open("a")
        log.info(
            "identification_updated",
            university_id=stamped.university_id,
            camera_id=stamped.camera_id,
            confidence=round(stamped.confidence, 3),
            track_id=stamped.track_id,
        )

    def log_unresolved(self, detection: UnresolvedDetection) -> None:
        self._write(
            self._unresolved,
            detection.to_dict(include_embedding=self.persist_unresolved_embeddings),
        )
        self.unresolved_count += 1

    def close(self) -> None:
        self._events.close()
        self._unresolved.close()

    @staticmethod
    def _write(stream: TextIO, payload: dict) -> None:
        stream.write(json.dumps(payload) + "\n")
        stream.flush()


class InMemoryEventPublisher(EventPublisher):
    """Collects records in lists, for tests and for asserting on pipeline behaviour."""

    def __init__(self) -> None:
        self.events: list[IdentificationEvent] = []
        self.unresolved: list[UnresolvedDetection] = []

    def publish(self, event: IdentificationEvent) -> None:
        self.events.append(event)

    def replace(self, event: IdentificationEvent) -> None:
        for index, existing in enumerate(self.events):
            if existing.event_id == event.event_id:
                self.events[index] = event
                return
        self.events.append(event)

    def log_unresolved(self, detection: UnresolvedDetection) -> None:
        self.unresolved.append(detection)


def _with_matched_at(event: IdentificationEvent) -> IdentificationEvent:
    if event.matched_at is not None:
        return event
    return IdentificationEvent(
        event_id=event.event_id,
        student_id=event.student_id,
        university_id=event.university_id,
        camera_id=event.camera_id,
        confidence=event.confidence,
        frame_captured_at=event.frame_captured_at,
        model_version=event.model_version,
        track_id=event.track_id,
        matched_at=datetime.now(UTC),
    )
