"""Deterministic backend with no model weights, for tests and CI.

It detects nothing useful, but it satisfies the FaceBackend contract exactly, so every
stage downstream of detection can be exercised without pulling licensed weights onto a
build machine. Embeddings are a stable hash of pixel content: the same crop always
yields the same vector, and different crops yield near-orthogonal ones.
"""

from __future__ import annotations

import hashlib

import cv2
import numpy as np

from attendance.faces.base import FaceBackend
from attendance.types import BoundingBox, DetectedFace, FaceEmbedding


class MockFaceBackend(FaceBackend):
    def __init__(self, embedding_dim: int = 512, boxes: list[BoundingBox] | None = None) -> None:
        self._embedding_dim = embedding_dim
        self._boxes = boxes

    @property
    def model_version(self) -> str:
        return "mock-v1"

    @property
    def embedding_dim(self) -> int:
        return self._embedding_dim

    @property
    def provider(self) -> str:
        return "MockProvider"

    def detect(self, image: np.ndarray) -> list[DetectedFace]:
        if self._boxes is None:
            return []
        height, width = image.shape[:2]
        return [
            DetectedFace(
                box=box.clipped_to(width, height),
                detector_score=0.99,
                landmarks=_synthetic_landmarks(box),
            )
            for box in self._boxes
        ]

    def align(self, image: np.ndarray, face: DetectedFace) -> np.ndarray:
        x1, y1 = int(max(0, face.box.x1)), int(max(0, face.box.y1))
        x2, y2 = int(min(image.shape[1], face.box.x2)), int(min(image.shape[0], face.box.y2))
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            crop = np.zeros((112, 112, 3), dtype=np.uint8)
        return cv2.resize(crop, (112, 112))

    def embed(self, image: np.ndarray, face: DetectedFace) -> FaceEmbedding:
        return self.embed_aligned(self.align(image, face))

    def embed_aligned(self, aligned: np.ndarray) -> FaceEmbedding:
        digest = hashlib.sha256(np.ascontiguousarray(aligned).tobytes()).digest()
        seed = int.from_bytes(digest[:8], "big")
        vector = np.random.default_rng(seed).normal(size=self._embedding_dim).astype(np.float32)
        return FaceEmbedding(
            vector=vector / float(np.linalg.norm(vector)), model_version=self.model_version
        )


def _synthetic_landmarks(box: BoundingBox) -> np.ndarray:
    cx, cy = box.center
    w, h = box.width, box.height
    return np.array(
        [
            [cx - 0.2 * w, cy - 0.1 * h],
            [cx + 0.2 * w, cy - 0.1 * h],
            [cx, cy + 0.05 * h],
            [cx - 0.15 * w, cy + 0.25 * h],
            [cx + 0.15 * w, cy + 0.25 * h],
        ],
        dtype=np.float32,
    )
