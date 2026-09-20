"""The detector/embedder seam.

Detection and embedding are separate calls rather than one fused ``get()`` so the
quality gate can reject a face *before* paying for the embedding, and so alternative
detectors and embedders can be mixed when benchmarking.

Any backend added here must satisfy two contracts that the rest of the pipeline
depends on:
  1. ``embed`` returns an L2-normalized vector (FaceEmbedding enforces this).
  2. ``model_version`` changes whenever the weights change, because embeddings from
     different models are not comparable and stored vectors are tagged with it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from attendance.types import DetectedFace, FaceEmbedding


class FaceBackend(ABC):
    @property
    @abstractmethod
    def model_version(self) -> str: ...

    @property
    @abstractmethod
    def embedding_dim(self) -> int: ...

    @property
    @abstractmethod
    def provider(self) -> str:
        """The execution provider actually in use, which may differ from the one requested."""

    @abstractmethod
    def detect(self, image: np.ndarray) -> list[DetectedFace]:
        """Detect faces in a BGR image."""

    @abstractmethod
    def align(self, image: np.ndarray, face: DetectedFace) -> np.ndarray:
        """Return the aligned crop that ``embed`` would use, for quality assessment."""

    @abstractmethod
    def embed(self, image: np.ndarray, face: DetectedFace) -> FaceEmbedding:
        """Produce an L2-normalized embedding for one detected face."""

    def embed_aligned(self, aligned: np.ndarray) -> FaceEmbedding:
        """Embed a pre-aligned crop, avoiding a second alignment pass."""
        raise NotImplementedError
