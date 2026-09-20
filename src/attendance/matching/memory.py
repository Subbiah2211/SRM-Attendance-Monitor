"""In-memory exact-search embedding store.

This is the development stand-in while the Postgres/pgvector schema is on hold, but it
is also a defensible pilot choice. At a few hundred to a few thousand enrolled
students, an exact scan over 512-d unit vectors is a single matrix multiply taking well
under a millisecond, and it has perfect recall. HNSW is approximate: it can miss the
true nearest neighbour, which is an awkward property during the exact phase where the
pilot is trying to measure real accuracy. Worth running exact until the enrolled
population makes the index necessary.

Because embeddings are L2-normalized, the dot product *is* cosine similarity.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np

from attendance.matching.base import EmbeddingStore
from attendance.types import Candidate, EnrolledEmbedding, FaceEmbedding


class InMemoryEmbeddingStore(EmbeddingStore):
    def __init__(self, embeddings: Iterable[EnrolledEmbedding] = ()) -> None:
        self._records: list[EnrolledEmbedding] = []
        self._matrix: np.ndarray | None = None
        self.add_many(embeddings)

    @property
    def size(self) -> int:
        return len(self._records)

    def add_many(self, embeddings: Iterable[EnrolledEmbedding]) -> None:
        added = list(embeddings)
        if not added:
            return
        for record in added:
            norm = float(np.linalg.norm(record.vector))
            if norm == 0.0:
                raise ValueError(f"enrolled embedding {record.embedding_id} is a zero vector")
            self._records.append(
                EnrolledEmbedding(
                    embedding_id=record.embedding_id,
                    student_id=record.student_id,
                    university_id=record.university_id,
                    vector=(record.vector / norm).astype(np.float32),
                    model_version=record.model_version,
                )
            )
        self._matrix = None

    def search(self, embedding: FaceEmbedding, limit: int) -> Sequence[Candidate]:
        comparable = [
            index
            for index, record in enumerate(self._records)
            if record.model_version == embedding.model_version
        ]
        if not comparable:
            return []

        matrix = self._ensure_matrix()[comparable]
        similarities = matrix @ embedding.vector

        take = min(limit, len(comparable))
        top = np.argpartition(-similarities, take - 1)[:take]
        top = top[np.argsort(-similarities[top])]

        return [
            Candidate(
                student_id=self._records[comparable[i]].student_id,
                university_id=self._records[comparable[i]].university_id,
                similarity=float(similarities[i]),
            )
            for i in top
        ]

    def _ensure_matrix(self) -> np.ndarray:
        if self._matrix is None:
            self._matrix = (
                np.vstack([r.vector for r in self._records])
                if self._records
                else np.empty((0, 0), dtype=np.float32)
            )
        return self._matrix
