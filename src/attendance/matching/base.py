"""The vector-match seam (spec section 3.4).

Two rules live above whatever store backs this, because they are accuracy policy
rather than storage detail:

  1. Per-student aggregation. A nearest-neighbour search returns *embeddings*, and a
     student has one to three of them, so the scores have to be collapsed per student.
     The spec does not say how; this defines it explicitly.
  2. A margin rule. Accepting requires not just clearing a similarity threshold but
     beating the best candidate from a *different* student by a margin. The gap is
     usually a stronger signal than the absolute score, and it makes the spec's
     "ties are logged as unresolved" a decidable condition instead of a sentiment.

Implementations must speak cosine *similarity*, never distance. pgvector's ``<=>``
returns distance (1 - similarity), so a pgvector-backed implementation converts at
its boundary and nothing above it has to remember the inversion.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from attendance.config import MatchingSettings
from attendance.types import Candidate, FaceEmbedding, MatchOutcome, MatchResult


class EmbeddingStore(ABC):
    """Nearest-neighbour search over enrolled embeddings."""

    @abstractmethod
    def search(self, embedding: FaceEmbedding, limit: int) -> Sequence[Candidate]:
        """Return up to ``limit`` nearest enrolled embeddings, descending by similarity.

        Results are per *embedding*, so the same student may appear more than once.
        Implementations must filter to the same ``model_version`` as the query, since
        vectors from different models are not comparable.
        """

    @property
    @abstractmethod
    def size(self) -> int:
        """Number of enrolled embeddings available for matching."""


class Matcher:
    def __init__(self, store: EmbeddingStore, settings: MatchingSettings) -> None:
        self.store = store
        self.settings = settings

    def match(self, embedding: FaceEmbedding, candidate_limit: int = 10) -> MatchResult:
        raw = self.store.search(embedding, limit=candidate_limit)
        if not raw:
            return MatchResult(outcome=MatchOutcome.NO_CANDIDATES, reason="no enrolled embeddings")

        per_student = self._aggregate(raw)
        best = per_student[0]
        runner_up = next((c for c in per_student[1:] if c.student_id != best.student_id), None)

        if best.similarity < self.settings.similarity_threshold:
            return MatchResult(
                outcome=MatchOutcome.UNRESOLVED,
                best=best,
                runner_up=runner_up,
                reason=(
                    f"similarity {best.similarity:.3f} below threshold "
                    f"{self.settings.similarity_threshold:.3f}"
                ),
            )

        if runner_up is not None:
            margin = best.similarity - runner_up.similarity
            if margin < self.settings.min_margin:
                return MatchResult(
                    outcome=MatchOutcome.UNRESOLVED,
                    best=best,
                    runner_up=runner_up,
                    reason=(
                        f"margin {margin:.3f} below minimum {self.settings.min_margin:.3f} "
                        f"(ambiguous between {best.university_id} and {runner_up.university_id})"
                    ),
                )

        return MatchResult(outcome=MatchOutcome.MATCHED, best=best, runner_up=runner_up)

    def _aggregate(self, raw: Sequence[Candidate]) -> list[Candidate]:
        grouped: dict[object, list[Candidate]] = {}
        for candidate in raw:
            grouped.setdefault(candidate.student_id, []).append(candidate)

        aggregated: list[Candidate] = []
        for candidates in grouped.values():
            if self.settings.aggregation == "max":
                aggregated.append(max(candidates, key=lambda c: c.similarity))
            else:
                mean = sum(c.similarity for c in candidates) / len(candidates)
                aggregated.append(
                    Candidate(
                        student_id=candidates[0].student_id,
                        university_id=candidates[0].university_id,
                        similarity=mean,
                    )
                )
        aggregated.sort(key=lambda c: c.similarity, reverse=True)
        return aggregated
