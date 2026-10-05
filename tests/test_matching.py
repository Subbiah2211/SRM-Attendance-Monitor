from __future__ import annotations

import numpy as np
import pytest

from attendance.config import MatchingSettings
from attendance.matching import InMemoryEmbeddingStore, Matcher
from attendance.types import EnrolledEmbedding, FaceEmbedding, MatchOutcome

MODEL = "test-v1"


def unit(*values: float) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def enrolled(university_id: str, vector: np.ndarray, student_id=None) -> EnrolledEmbedding:
    from uuid import uuid4

    from attendance.enrollment import student_id_for

    return EnrolledEmbedding(
        embedding_id=uuid4(),
        student_id=student_id or student_id_for(university_id),
        university_id=university_id,
        vector=vector,
        model_version=MODEL,
    )


def query(vector: np.ndarray, model_version: str = MODEL) -> FaceEmbedding:
    return FaceEmbedding(vector=vector, model_version=model_version)


def test_embedding_rejects_unnormalized_vector():
    with pytest.raises(ValueError, match="L2-normalized"):
        FaceEmbedding(vector=np.array([3.0, 4.0], dtype=np.float32), model_version=MODEL)


def test_confident_match_is_returned():
    store = InMemoryEmbeddingStore([enrolled("CS21B045", unit(1, 0, 0))])
    matcher = Matcher(store, MatchingSettings(similarity_threshold=0.55, min_margin=0.05))

    result = matcher.match(query(unit(0.98, 0.02, 0)))

    assert result.outcome is MatchOutcome.MATCHED
    assert result.best is not None
    assert result.best.university_id == "CS21B045"
    assert result.best.similarity > 0.9


def test_below_threshold_is_unresolved_not_forced():
    store = InMemoryEmbeddingStore([enrolled("CS21B045", unit(1, 0, 0))])
    matcher = Matcher(store, MatchingSettings(similarity_threshold=0.8))

    result = matcher.match(query(unit(1, 1, 0)))

    assert result.outcome is MatchOutcome.UNRESOLVED
    assert result.best is not None, "the near miss is still reported, for tuning"
    assert "below threshold" in (result.reason or "")


def test_ambiguous_pair_is_unresolved_even_above_threshold():
    """Two students almost equally similar must not be force-matched to the top one."""
    store = InMemoryEmbeddingStore(
        [
            enrolled("CS21B045", unit(1.0, 0.0, 0.0)),
            enrolled("CS21B046", unit(0.999, 0.045, 0.0)),
        ]
    )
    matcher = Matcher(store, MatchingSettings(similarity_threshold=0.5, min_margin=0.05))

    result = matcher.match(query(unit(1.0, 0.02, 0.0)))

    assert result.outcome is MatchOutcome.UNRESOLVED
    assert result.best is not None and result.best.similarity > 0.5
    assert "margin" in (result.reason or "")


def test_multiple_embeddings_per_student_aggregate_by_max():
    """A student's best reference photo should decide their score, not their worst."""
    student = enrolled("CS21B045", unit(1, 0, 0)).student_id
    store = InMemoryEmbeddingStore(
        [
            enrolled("CS21B045", unit(1, 0, 0), student_id=student),
            enrolled("CS21B045", unit(0, 1, 0), student_id=student),
            enrolled("CS21B099", unit(0.5, 0.5, 0.2)),
        ]
    )
    matcher = Matcher(store, MatchingSettings(similarity_threshold=0.5, aggregation="max"))

    result = matcher.match(query(unit(0.95, 0.05, 0)))

    assert result.outcome is MatchOutcome.MATCHED
    assert result.best is not None and result.best.university_id == "CS21B045"
    assert result.runner_up is not None
    assert result.runner_up.university_id == "CS21B099", (
        "runner-up must come from a different student, not the same student's other photo"
    )


def test_vectors_from_a_different_model_are_never_compared():
    store = InMemoryEmbeddingStore([enrolled("CS21B045", unit(1, 0, 0))])
    matcher = Matcher(store, MatchingSettings())

    result = matcher.match(query(unit(1, 0, 0), model_version="insightface-buffalo_l-v2"))

    assert result.outcome is MatchOutcome.NO_CANDIDATES


def test_empty_store_yields_no_candidates():
    matcher = Matcher(InMemoryEmbeddingStore(), MatchingSettings())
    assert matcher.match(query(unit(1, 0, 0))).outcome is MatchOutcome.NO_CANDIDATES


def test_roster_names_win_over_existing_database_names():
    from attendance.enrollment import resolve_enrollment_names

    names, missing = resolve_enrollment_names(
        {"202405CS001", "202405CS002"},
        roster_names={"202405CS001": "Oviya"},
        existing_names={"202405CS001": "Old Name", "202405CS002": "Rithika"},
    )
    assert names == {"202405CS001": "Oviya", "202405CS002": "Rithika"}
    assert missing == []


def test_missing_enrollment_names_are_reported():
    from attendance.enrollment import resolve_enrollment_names

    names, missing = resolve_enrollment_names(
        {"202405CS001", "202405CS002"},
        roster_names={"202405CS001": "Oviya"},
        existing_names={},
    )
    assert names == {"202405CS001": "Oviya"}
    assert missing == ["202405CS002"]
