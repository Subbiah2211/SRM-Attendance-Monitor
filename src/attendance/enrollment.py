"""Enrollment (spec section 3.5).

The one thing this must guarantee is that reference photos travel the *same* detection,
alignment and embedding path as runtime frames, including the same quality gate. The
spec is right that this matters more for accuracy than almost anything else, and it is
easy to lose by accident: a separate enrollment script that crops differently or skips
alignment produces vectors that quietly do not compare well.

The same ``EnrolledEmbedding`` records load into Postgres (the default) or a
portable ``.npz`` bundle for offline runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import cv2
import numpy as np
import structlog

from attendance.config import QualitySettings
from attendance.faces.base import FaceBackend
from attendance.faces.quality import QualityGate
from attendance.types import EnrolledEmbedding

log = structlog.get_logger(__name__)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

_STUDENT_NAMESPACE = UUID("6f2a1d5e-9c3b-4f7a-8e21-0b5c7d9a4e13")
"""Fixed namespace so a given university_id always derives the same student_id.

Real student_ids will come from the students table once it exists; deriving them
deterministically here keeps enrollment reproducible in the meantime.
"""


@dataclass
class EnrollmentResult:
    embeddings: list[EnrolledEmbedding]
    skipped: list[tuple[Path, str]]

    @property
    def student_count(self) -> int:
        return len({e.student_id for e in self.embeddings})


def student_id_for(university_id: str) -> UUID:
    return uuid5(_STUDENT_NAMESPACE, university_id)


def resolve_enrollment_names(
    university_ids: set[str],
    roster_names: dict[str, str],
    existing_names: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    """Roster wins over names already in the database. Returns (names, missing)."""
    names = {**existing_names, **roster_names}
    missing = sorted(university_ids - names.keys())
    return names, missing


def enroll_directory(
    photo_dir: Path,
    backend: FaceBackend,
    quality: QualitySettings,
    max_per_student: int = 3,
    enforce_quality: bool = True,
) -> EnrollmentResult:
    """Enroll from a directory laid out either as ``<dir>/<university_id>/*.jpg``
    or as flat files named ``<university_id>.jpg``.
    """
    gate = QualityGate(quality)
    embeddings: list[EnrolledEmbedding] = []
    skipped: list[tuple[Path, str]] = []

    for university_id, paths in _group_photos(photo_dir).items():
        student_id = student_id_for(university_id)
        accepted = 0
        for path in paths:
            if accepted >= max_per_student:
                break
            image = cv2.imread(str(path))
            if image is None:
                skipped.append((path, "unreadable image"))
                continue

            faces = backend.detect(image)
            if not faces:
                skipped.append((path, "no face detected"))
                continue
            if len(faces) > 1:
                # Ambiguous reference photo: enrolling the wrong face here poisons every
                # future match for this student, so refuse rather than guess.
                skipped.append((path, f"{len(faces)} faces detected, expected exactly one"))
                continue

            face = faces[0]
            aligned = backend.align(image, face)
            assessment = gate.assess(face, aligned)
            if enforce_quality and not assessment.passed:
                skipped.append((path, "; ".join(assessment.reasons)))
                continue

            embedding = backend.embed_aligned(aligned)
            embeddings.append(
                EnrolledEmbedding(
                    embedding_id=uuid4(),
                    student_id=student_id,
                    university_id=university_id,
                    vector=embedding.vector,
                    model_version=embedding.model_version,
                )
            )
            accepted += 1

        if accepted == 0:
            log.warning("student_not_enrolled", university_id=university_id, photos=len(paths))

    return EnrollmentResult(embeddings=embeddings, skipped=skipped)


def save_embeddings(result_embeddings: list[EnrolledEmbedding], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        vectors=np.vstack([e.vector for e in result_embeddings]).astype(np.float32),
        embedding_ids=np.array([str(e.embedding_id) for e in result_embeddings]),
        student_ids=np.array([str(e.student_id) for e in result_embeddings]),
        university_ids=np.array([e.university_id for e in result_embeddings]),
        model_versions=np.array([e.model_version for e in result_embeddings]),
    )


def load_embeddings(path: Path) -> list[EnrolledEmbedding]:
    with np.load(path, allow_pickle=False) as data:
        return [
            EnrolledEmbedding(
                embedding_id=UUID(str(data["embedding_ids"][i])),
                student_id=UUID(str(data["student_ids"][i])),
                university_id=str(data["university_ids"][i]),
                vector=data["vectors"][i],
                model_version=str(data["model_versions"][i]),
            )
            for i in range(len(data["embedding_ids"]))
        ]


def _group_photos(photo_dir: Path) -> dict[str, list[Path]]:
    if not photo_dir.is_dir():
        raise NotADirectoryError(f"not a directory: {photo_dir}")

    grouped: dict[str, list[Path]] = {}
    for child in sorted(photo_dir.iterdir()):
        if child.is_dir():
            photos = sorted(p for p in child.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
            if photos:
                grouped[child.name] = photos
        elif child.suffix.lower() in IMAGE_SUFFIXES:
            grouped.setdefault(child.stem, []).append(child)
    return grouped
