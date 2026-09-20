"""Core data types shared across pipeline stages.

Deliberately free of any dependency on a storage backend, model backend or
transport, so that the stage boundaries described in the Phase 1 spec can be
re-wired without touching these definitions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

import numpy as np


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def iou(self, other: BoundingBox) -> float:
        ix1, iy1 = max(self.x1, other.x1), max(self.y1, other.y1)
        ix2, iy2 = min(self.x2, other.x2), min(self.y2, other.y2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def clipped_to(self, width: int, height: int) -> BoundingBox:
        return BoundingBox(
            x1=max(0.0, min(self.x1, width - 1.0)),
            y1=max(0.0, min(self.y1, height - 1.0)),
            x2=max(0.0, min(self.x2, width - 1.0)),
            y2=max(0.0, min(self.y2, height - 1.0)),
        )


class SourceMode(Enum):
    """How a video source must be consumed.

    SEQUENTIAL sources (files) only advance by decoding every frame in order, so
    downsampling means decode-and-discard. LATEST sources (live RTSP) always hand
    back the freshest available frame and drop any backlog, per the spec's
    ``max-buffers=1 drop=true`` requirement.
    """

    SEQUENTIAL = "sequential"
    LATEST = "latest"


@dataclass(frozen=True, slots=True)
class Frame:
    camera_id: str
    image: np.ndarray
    """BGR uint8, shape (H, W, 3)."""
    captured_at: datetime
    """Frame capture time, not processing time. Phase 2 needs this for late-arrival rules."""
    sequence: int

    @property
    def shape(self) -> tuple[int, int]:
        return self.image.shape[0], self.image.shape[1]


@dataclass(frozen=True, slots=True)
class DetectedFace:
    box: BoundingBox
    detector_score: float
    landmarks: np.ndarray | None = None
    """Five-point landmarks (left eye, right eye, nose, left mouth, right mouth), shape (5, 2)."""


@dataclass(frozen=True, slots=True)
class QualityAssessment:
    passed: bool
    reasons: tuple[str, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FaceEmbedding:
    vector: np.ndarray
    """L2-normalized float32, shape (embedding_dim,). Normalization is enforced on construction."""
    model_version: str

    def __post_init__(self) -> None:
        norm = float(np.linalg.norm(self.vector))
        if not math.isclose(norm, 1.0, abs_tol=1e-3):
            raise ValueError(
                f"embedding must be L2-normalized before use, got norm={norm:.4f}. "
                "Cosine similarity and the stored-vector contract both assume unit norm."
            )

    def cosine_similarity(self, other: FaceEmbedding | np.ndarray) -> float:
        vector = other.vector if isinstance(other, FaceEmbedding) else other
        return float(np.dot(self.vector, vector))


@dataclass(frozen=True, slots=True)
class EnrolledEmbedding:
    """One reference vector for one student. A student may have several."""

    embedding_id: UUID
    student_id: UUID
    university_id: str
    vector: np.ndarray
    model_version: str


@dataclass(frozen=True, slots=True)
class Candidate:
    student_id: UUID
    university_id: str
    similarity: float
    """Cosine similarity in [-1, 1]. Higher is more similar.

    Note the inversion hazard: pgvector's ``<=>`` operator returns cosine *distance*
    (1 - similarity). Everything above the storage layer speaks similarity only.
    """


class MatchOutcome(Enum):
    MATCHED = "matched"
    UNRESOLVED = "unresolved"
    NO_CANDIDATES = "no_candidates"


@dataclass(frozen=True, slots=True)
class MatchResult:
    outcome: MatchOutcome
    best: Candidate | None = None
    runner_up: Candidate | None = None
    """Best candidate belonging to a *different* student than ``best``."""
    reason: str | None = None

    @property
    def margin(self) -> float | None:
        if self.best is None:
            return None
        if self.runner_up is None:
            return self.best.similarity
        return self.best.similarity - self.runner_up.similarity


@dataclass(frozen=True, slots=True)
class IdentificationEvent:
    """The Phase 1 to Phase 2 interface boundary. Keep this stable."""

    student_id: UUID
    university_id: str
    camera_id: str
    confidence: float
    frame_captured_at: datetime
    model_version: str
    track_id: int
    event_id: UUID = field(default_factory=uuid4)
    matched_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "student_id": str(self.student_id),
            "university_id": self.university_id,
            "camera_id": self.camera_id,
            "confidence": round(self.confidence, 4),
            "frame_captured_at": _iso(self.frame_captured_at),
            "matched_at": _iso(self.matched_at) if self.matched_at else None,
            "model_version": self.model_version,
            "track_id": self.track_id,
        }


@dataclass(frozen=True, slots=True)
class UnresolvedDetection:
    """A detection that never became an event.

    The spec requires these are logged rather than dropped, both for pilot tuning
    and so nobody downstream has to reason about maybe-matches. Whether the
    embedding itself may be retained here is a privacy decision (spec section 6.5),
    so it is opt-in via configuration rather than always recorded.
    """

    camera_id: str
    frame_captured_at: datetime
    track_id: int
    stage: str
    """Where it dropped out: 'quality' or 'match'."""
    reason: str
    detector_score: float
    box: BoundingBox
    best_similarity: float | None = None
    margin: float | None = None
    quality_metrics: dict[str, float] = field(default_factory=dict)
    embedding: np.ndarray | None = None
    detection_id: UUID = field(default_factory=uuid4)

    def to_dict(self, include_embedding: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "detection_id": str(self.detection_id),
            "camera_id": self.camera_id,
            "frame_captured_at": _iso(self.frame_captured_at),
            "track_id": self.track_id,
            "stage": self.stage,
            "reason": self.reason,
            "detector_score": round(self.detector_score, 4),
            "box": [round(v, 1) for v in (self.box.x1, self.box.y1, self.box.x2, self.box.y2)],
            "best_similarity": (
                round(self.best_similarity, 4) if self.best_similarity is not None else None
            ),
            "margin": round(self.margin, 4) if self.margin is not None else None,
            "quality_metrics": {k: round(v, 4) for k, v in self.quality_metrics.items()},
        }
        if include_embedding and self.embedding is not None:
            payload["embedding"] = [round(float(v), 6) for v in self.embedding]
        return payload


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
