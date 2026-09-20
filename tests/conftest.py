from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
import pytest

from attendance.faces.base import FaceBackend
from attendance.types import BoundingBox, DetectedFace, EnrolledEmbedding, FaceEmbedding

FRAME_WIDTH = 640
FRAME_HEIGHT = 480


def checkerboard(height: int, width: int) -> np.ndarray:
    """Textured content so real crops clear the blur gate."""
    grid = (np.indices((height, width)).sum(axis=0) // 2) % 2
    return np.stack([grid * 255] * 3, axis=-1).astype(np.uint8)


@pytest.fixture
def synthetic_video(tmp_path: Path) -> Path:
    """Three seconds at 30 FPS of textured frames."""
    path = tmp_path / "clip.mp4"
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (FRAME_WIDTH, FRAME_HEIGHT)
    )
    assert writer.isOpened(), "OpenCV could not open an mp4 writer"
    base = checkerboard(FRAME_HEIGHT, FRAME_WIDTH)
    for index in range(90):
        frame = base.copy()
        cv2.circle(frame, (50 + index * 6, 240), 40, (20, 180, 250), -1)
        writer.write(frame)
    writer.release()
    return path


class StubBackend(FaceBackend):
    """Detects a fixed set of boxes and returns a fixed vector per box.

    Lets pipeline wiring be asserted exactly -- which faces match, which fall out at
    the gate, how many events a track produces -- without model weights or the
    nondeterminism of real detection.
    """

    def __init__(
        self,
        boxes: list[BoundingBox],
        vectors: list[np.ndarray] | None = None,
        detector_scores: list[float] | None = None,
        model_version: str = "stub-v1",
    ) -> None:
        self.boxes = boxes
        self.vectors = vectors or [_unit_basis(i) for i in range(len(boxes))]
        self.detector_scores = detector_scores or [0.95] * len(boxes)
        self._model_version = model_version
        self.detect_calls = 0
        self.embed_calls = 0

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def embedding_dim(self) -> int:
        return 8

    @property
    def provider(self) -> str:
        return "StubProvider"

    def detect(self, image: np.ndarray) -> list[DetectedFace]:
        self.detect_calls += 1
        return [
            DetectedFace(
                box=box,
                detector_score=self.detector_scores[i],
                landmarks=_frontal_landmarks(box),
            )
            for i, box in enumerate(self.boxes)
        ]

    def align(self, image: np.ndarray, face: DetectedFace) -> np.ndarray:
        x1, y1 = int(max(0, face.box.x1)), int(max(0, face.box.y1))
        x2, y2 = int(min(image.shape[1], face.box.x2)), int(min(image.shape[0], face.box.y2))
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            crop = np.zeros((112, 112, 3), dtype=np.uint8)
        return cv2.resize(crop, (112, 112), interpolation=cv2.INTER_NEAREST)

    def embed(self, image: np.ndarray, face: DetectedFace) -> FaceEmbedding:
        index = next(
            (i for i, box in enumerate(self.boxes) if box.iou(face.box) > 0.99),
            0,
        )
        self.embed_calls += 1
        return FaceEmbedding(vector=self.vectors[index], model_version=self._model_version)

    def embed_aligned(self, aligned: np.ndarray) -> FaceEmbedding:
        self.embed_calls += 1
        return FaceEmbedding(vector=self.vectors[0], model_version=self._model_version)


def _unit_basis(index: int, dim: int = 8) -> np.ndarray:
    vector = np.zeros(dim, dtype=np.float32)
    vector[index % dim] = 1.0
    return vector


def _frontal_landmarks(box: BoundingBox) -> np.ndarray:
    cx, cy = box.center
    w, h = box.width, box.height
    return np.array(
        [
            [cx - 0.18 * w, cy - 0.1 * h],
            [cx + 0.18 * w, cy - 0.1 * h],
            [cx, cy + 0.05 * h],
            [cx - 0.13 * w, cy + 0.25 * h],
            [cx + 0.13 * w, cy + 0.25 * h],
        ],
        dtype=np.float32,
    )


def enrolled_for(university_id: str, vector: np.ndarray, model_version: str) -> EnrolledEmbedding:
    from attendance.enrollment import student_id_for

    return EnrolledEmbedding(
        embedding_id=uuid4(),
        student_id=student_id_for(university_id),
        university_id=university_id,
        vector=vector,
        model_version=model_version,
    )
