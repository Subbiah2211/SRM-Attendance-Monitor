"""PostgreSQL + pgvector implementations of the storage and publishing seams.

Two conversions happen here and nowhere else:

  * pgvector's ``<=>`` operator returns cosine *distance*. The spec's prose talks about
    similarity thresholds while its DDL uses ``vector_cosine_ops``, which is the
    inversion hazard flagged during review. Distance becomes ``1 - distance`` at the
    boundary of this module, so nothing above it deals in distance.
  * Vectors are written L2-normalized, which is what makes that identity hold.

The polling consumer uses ``FOR UPDATE SKIP LOCKED`` so more than one Phase 2 worker
can drain the queue without processing the same event twice. The spec's ``consumed``
boolean alone would not give that.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib import resources
from pathlib import Path
from uuid import UUID

import numpy as np
import psycopg
import structlog
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from attendance.events import EventPublisher
from attendance.matching.base import EmbeddingStore
from attendance.types import (
    Candidate,
    EnrolledEmbedding,
    FaceEmbedding,
    IdentificationEvent,
    UnresolvedDetection,
)

log = structlog.get_logger(__name__)

SCHEMA_FILE = "schema.sql"
HNSW_FILE = "002_hnsw_index.sql"


def connect(dsn: str) -> psycopg.Connection:
    connection = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)
    register_vector(connection)
    connection.execute("SET search_path TO identity, attendance, public")
    return connection


def check_capabilities(dsn: str) -> dict[str, object]:
    """Report whether this server can host the Phase 1 schema at all.

    Written to answer the open question about the existing university instance without
    needing schema privileges: pgvector is a server-side extension, and if it is not
    available the data model in spec section 4 cannot be used as written.
    """
    with psycopg.connect(dsn, row_factory=dict_row, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('server_version') AS version")
            server_version = cursor.fetchone()["version"]

            cursor.execute(
                "SELECT default_version, installed_version "
                "FROM pg_available_extensions WHERE name = 'vector'"
            )
            extension = cursor.fetchone()

            cursor.execute("SELECT current_user AS user, current_database() AS database")
            identity = cursor.fetchone()

            installed = bool(extension and extension["installed_version"])
            hnsw_available = False
            if installed:
                cursor.execute("SELECT 1 FROM pg_am WHERE amname = 'hnsw'")
                hnsw_available = cursor.fetchone() is not None

    return {
        "server_version": server_version,
        "database": identity["database"],
        "user": identity["user"],
        "pgvector_available": bool(extension),
        "pgvector_default_version": extension["default_version"] if extension else None,
        "pgvector_installed_version": extension["installed_version"] if extension else None,
        "hnsw_index_available": hnsw_available,
        "verdict": (
            "ready"
            if installed
            else "pgvector available but not yet installed; run 'attendance db migrate'"
            if extension
            else "pgvector NOT available on this server -- spec section 4 cannot be used as written"
        ),
    }


def apply_schema(dsn: str, include_hnsw: bool = False) -> list[str]:
    applied = [SCHEMA_FILE]
    statements = _read_sql(SCHEMA_FILE)
    if include_hnsw:
        statements += "\n" + _read_sql(HNSW_FILE)
        applied.append(HNSW_FILE)

    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(statements)
    return applied


def _read_sql(name: str) -> str:
    package_files = resources.files("attendance.storage")
    return (package_files / name).read_text(encoding="utf-8")


class PgVectorEmbeddingStore(EmbeddingStore):
    def __init__(
        self,
        connection: psycopg.Connection,
        model_version: str,
        exclude_inactive_students: bool = True,
        ef_search: int | None = None,
    ) -> None:
        self.connection = connection
        self.model_version = model_version
        self.exclude_inactive_students = exclude_inactive_students
        if ef_search is not None:
            # Only meaningful once the HNSW index exists; harmless otherwise. Left
            # unset by default because exact search needs no recall tuning.
            self.connection.execute("SET hnsw.ef_search = %s", (ef_search,))

    @property
    def size(self) -> int:
        row = self.connection.execute(
            "SELECT count(*) AS n FROM face_embeddings WHERE model_version = %s",
            (self.model_version,),
        ).fetchone()
        return int(row["n"])

    def search(self, embedding: FaceEmbedding, limit: int) -> Sequence[Candidate]:
        query = """
            SELECT fe.student_id,
                   s.university_id,
                   1 - (fe.embedding <=> %(query)s) AS similarity
            FROM face_embeddings fe
            JOIN students s ON s.student_id = fe.student_id
            WHERE fe.model_version = %(model_version)s
              {student_filter}
            ORDER BY fe.embedding <=> %(query)s
            LIMIT %(limit)s
        """.format(
            student_filter=(
                "AND s.enrollment_status = 'active'" if self.exclude_inactive_students else ""
            )
        )
        rows = self.connection.execute(
            query,
            {
                "query": np.asarray(embedding.vector, dtype=np.float32),
                "model_version": embedding.model_version,
                "limit": limit,
            },
        ).fetchall()

        return [
            Candidate(
                student_id=row["student_id"],
                university_id=row["university_id"],
                similarity=float(row["similarity"]),
            )
            for row in rows
        ]

    def add_enrolled(self, records: Sequence[EnrolledEmbedding], source: str = "enrollment") -> int:
        with self.connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO face_embeddings
                    (embedding_id, student_id, embedding, model_version, source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (embedding_id) DO NOTHING
                """,
                [
                    (
                        record.embedding_id,
                        record.student_id,
                        _normalized(record.vector),
                        record.model_version,
                        source,
                    )
                    for record in records
                ],
            )
            student_ids = list({record.student_id for record in records})
            if student_ids:
                cursor.execute(
                    "UPDATE students SET face_registered = true WHERE student_id = ANY(%s)",
                    (student_ids,),
                )
        return len(records)


def fetch_student_names(
    connection: psycopg.Connection, university_ids: Sequence[str]
) -> dict[str, str]:
    if not university_ids:
        return {}
    rows = connection.execute(
        "SELECT university_id, full_name FROM students WHERE university_id = ANY(%s)",
        (list(university_ids),),
    ).fetchall()
    return {row["university_id"]: row["full_name"] for row in rows}


class PostgresEventPublisher(EventPublisher):
    """Durable, ordered hand-off point (spec section 3.6).

    A table with a polling consumer, as the spec suggests for pilot scale. Swapping in
    Redis Streams later replaces this class and nothing else.
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        model_version: str,
        persist_unresolved_embeddings: bool = False,
    ) -> None:
        self.connection = connection
        self.model_version = model_version
        self.persist_unresolved_embeddings = persist_unresolved_embeddings
        self.published_count = 0
        self.unresolved_count = 0

    def publish(self, event: IdentificationEvent) -> None:
        self.connection.execute(
            """
            INSERT INTO identification_events
                (event_id, student_id, camera_id, confidence,
                 frame_captured_at, matched_at, model_version, track_id)
            VALUES (%s, %s, %s, %s, %s, coalesce(%s, now()), %s, %s)
            ON CONFLICT (event_id) DO NOTHING
            """,
            (
                event.event_id,
                event.student_id,
                event.camera_id,
                event.confidence,
                event.frame_captured_at,
                event.matched_at,
                event.model_version,
                event.track_id,
            ),
        )
        self.published_count += 1

    def replace(self, event: IdentificationEvent) -> None:
        self.connection.execute(
            """
            UPDATE identification_events
               SET confidence = %s,
                   frame_captured_at = %s,
                   matched_at = coalesce(%s, now()),
                   track_id = %s,
                   model_version = %s
             WHERE event_id = %s
               AND confidence < %s
            """,
            (
                event.confidence,
                event.frame_captured_at,
                event.matched_at,
                event.track_id,
                event.model_version,
                event.event_id,
                event.confidence,
            ),
        )

    def log_unresolved(self, detection: UnresolvedDetection) -> None:
        self.connection.execute(
            """
            INSERT INTO unresolved_detections
                (detection_id, camera_id, frame_captured_at, track_id, stage, reason,
                 detector_score, box, best_similarity, margin, quality_metrics,
                 model_version, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (detection_id) DO NOTHING
            """,
            (
                detection.detection_id,
                detection.camera_id,
                detection.frame_captured_at,
                detection.track_id,
                detection.stage,
                detection.reason,
                detection.detector_score,
                [detection.box.x1, detection.box.y1, detection.box.x2, detection.box.y2],
                detection.best_similarity,
                detection.margin,
                json.dumps(detection.quality_metrics),
                self.model_version,
                (
                    _normalized(detection.embedding)
                    if self.persist_unresolved_embeddings and detection.embedding is not None
                    else None
                ),
            ),
        )
        self.unresolved_count += 1


def claim_events(connection: psycopg.Connection, batch_size: int = 100) -> list[dict]:
    """Reference consumer for Phase 2, and the thing that proves the contract works.

    SKIP LOCKED is what makes the queue safe for more than one worker: each claims a
    disjoint batch instead of two workers racing on the same rows. Events are returned
    oldest-first by capture time, since that is the order a student actually walked past.
    """
    with connection.transaction():
        rows = connection.execute(
            """
            SELECT e.event_id, e.student_id, s.university_id, e.camera_id, e.confidence,
                   e.frame_captured_at, e.matched_at, e.model_version, e.track_id
            FROM identification_events e
            JOIN students s ON s.student_id = e.student_id
            WHERE NOT e.consumed
            ORDER BY e.frame_captured_at
            LIMIT %s
            FOR UPDATE OF e SKIP LOCKED
            """,
            (batch_size,),
        ).fetchall()

        if rows:
            connection.execute(
                "UPDATE identification_events "
                "SET consumed = true, consumed_at = now() "
                "WHERE event_id = ANY(%s)",
                ([row["event_id"] for row in rows],),
            )
    return rows


def upsert_camera(
    connection: psycopg.Connection,
    camera_id: str,
    location_label: str,
    source_ref: str,
    roi: tuple[float, float, float, float] | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO cameras (camera_id, location_label, source_ref, roi)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (camera_id) DO UPDATE
            SET location_label = excluded.location_label,
                source_ref = excluded.source_ref,
                roi = excluded.roi
        """,
        (camera_id, location_label, source_ref, list(roi) if roi else None),
    )


def upsert_student(
    connection: psycopg.Connection,
    student_id: UUID,
    university_id: str,
    full_name: str,
) -> UUID:
    row = connection.execute(
        """
        INSERT INTO students (student_id, university_id, full_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (university_id) DO UPDATE SET full_name = excluded.full_name
        RETURNING student_id
        """,
        (student_id, university_id, full_name),
    ).fetchone()
    return row["student_id"]


def _normalized(vector: np.ndarray) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(array))
    if norm == 0.0:
        raise ValueError("refusing to store a zero vector")
    return array / norm


def schema_path() -> Path:
    return Path(str(resources.files("attendance.storage") / SCHEMA_FILE))
