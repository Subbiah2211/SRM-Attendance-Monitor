"""Command line entry points."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from attendance import enrollment
from attendance.config import CameraSettings, Settings
from attendance.events import JsonlEventPublisher
from attendance.faces import build_backend
from attendance.logging import configure_logging
from attendance.matching import InMemoryEmbeddingStore, Matcher
from attendance.pipeline import CameraPipeline

app = typer.Typer(add_completion=False, help="Phase 1 attendance identification pipeline.")
models_app = typer.Typer(help="Model weight management.")
db_app = typer.Typer(help="Database inspection and schema management.")
app.add_typer(models_app, name="models")
app.add_typer(db_app, name="db")

LICENCE_NOTICE = """
Licence notice (spec section 3.3)
---------------------------------
InsightFace's code is MIT licensed, but its pretrained model packs -- including
buffalo_l -- are published for NON-COMMERCIAL RESEARCH USE. Commercial use requires
separate licensing from InsightFace.

Whether a university deployment falls inside those terms is a question for
procurement/legal, not engineering. These weights are fine for benchmarking and for
deciding whether the accuracy is good enough to proceed; they are not yet cleared for
production. The FaceBackend interface exists so the production model can be swapped
without touching the pipeline.
"""


@models_app.command("download")
def download_models(
    pack: Annotated[str, typer.Option(help="InsightFace model pack name.")] = "buffalo_l",
    accept_licence: Annotated[
        bool, typer.Option("--accept-licence", help="Acknowledge the notice and proceed.")
    ] = False,
) -> None:
    """Download detector and embedder weights. Deliberately explicit, never implicit."""
    typer.echo(LICENCE_NOTICE)
    if not accept_licence:
        typer.echo("Re-run with --accept-licence to download for evaluation purposes.")
        raise typer.Exit(code=1)

    from insightface.utils import storage

    settings = Settings()
    target = settings.inference.model_dir
    target.mkdir(parents=True, exist_ok=True)
    typer.echo(f"Downloading '{pack}' into {target} ...")
    storage.ensure_available("models", pack, root=str(target.parent))
    typer.echo("Done.")


@models_app.command("info")
def models_info(
    backend: Annotated[str, typer.Option(help="Backend to inspect.")] = "insightface",
) -> None:
    """Report the resolved execution provider and model version."""
    configure_logging()
    settings = Settings()
    face_backend = build_backend(settings, backend)
    typer.echo(
        json.dumps(
            {
                "backend": backend,
                "model_version": face_backend.model_version,
                "embedding_dim": face_backend.embedding_dim,
                "provider": face_backend.provider,
            },
            indent=2,
        )
    )


def _require_dsn(dsn: str | None) -> str:
    resolved = dsn or Settings().database.dsn
    if not resolved:
        typer.echo(
            "No database DSN. Pass --dsn or set ATT_DATABASE__DSN "
            "(e.g. postgresql://user:pass@host:5432/attendance).",
            err=True,
        )
        raise typer.Exit(code=2)
    return resolved


@db_app.command("check")
def db_check(
    dsn: Annotated[str | None, typer.Option(help="Postgres DSN.")] = None,
) -> None:
    """Report whether this server can host the Phase 1 schema.

    Needs only read access, so it can be run against the existing university instance
    before anyone grants schema privileges. If pgvector is unavailable, the data model
    in spec section 4 cannot be used as written and that decision has to be revisited.
    """
    from attendance.storage import check_capabilities

    report = check_capabilities(_require_dsn(dsn))
    typer.echo(json.dumps(report, indent=2))
    if not report["pgvector_available"]:
        raise typer.Exit(code=1)


@db_app.command("migrate")
def db_migrate(
    dsn: Annotated[str | None, typer.Option(help="Postgres DSN.")] = None,
    with_hnsw: Annotated[
        bool, typer.Option(help="Also create the approximate HNSW index.")
    ] = False,
) -> None:
    """Apply the Phase 1 schema. Idempotent."""
    from attendance.storage import apply_schema

    applied = apply_schema(_require_dsn(dsn), include_hnsw=with_hnsw)
    typer.echo(f"Applied: {', '.join(applied)}")
    if not with_hnsw:
        typer.echo(
            "Vector matching will use an exact scan (perfect recall). "
            "Add --with-hnsw once the enrolled population makes that too slow."
        )


@db_app.command("load-enrollment")
def db_load_enrollment(
    bundle: Annotated[Path, typer.Argument(help="Embedding bundle from 'enroll'.")],
    roster: Annotated[
        Path | None,
        typer.Option(help="CSV of university_id,full_name. Required to create students."),
    ] = None,
    dsn: Annotated[str | None, typer.Option(help="Postgres DSN.")] = None,
) -> None:
    """Load an embedding bundle into Postgres, creating student rows as needed."""
    import csv

    from attendance.storage import PgVectorEmbeddingStore, connect, upsert_student

    records = enrollment.load_embeddings(bundle)
    if not records:
        typer.echo("Bundle is empty.", err=True)
        raise typer.Exit(code=1)

    names: dict[str, str] = {}
    if roster is not None:
        with roster.open() as handle:
            for row in csv.DictReader(handle):
                names[row["university_id"].strip()] = row["full_name"].strip()

    missing = sorted({r.university_id for r in records} - names.keys())
    if missing:
        typer.echo(
            f"No full_name for {len(missing)} student(s): {', '.join(missing[:5])}"
            f"{' ...' if len(missing) > 5 else ''}\n"
            "Provide --roster so student records carry real names rather than invented ones.",
            err=True,
        )
        raise typer.Exit(code=2)

    connection = connect(_require_dsn(dsn))
    try:
        for university_id in {r.university_id for r in records}:
            upsert_student(
                connection,
                student_id=enrollment.student_id_for(university_id),
                university_id=university_id,
                full_name=names[university_id],
            )
        store = PgVectorEmbeddingStore(connection, model_version=records[0].model_version)
        count = store.add_enrolled(records)
    finally:
        connection.close()

    typer.echo(
        f"Loaded {count} embedding(s) for {len({r.university_id for r in records})} student(s)."
    )


@db_app.command("consume")
def db_consume(
    dsn: Annotated[str | None, typer.Option(help="Postgres DSN.")] = None,
    batch_size: Annotated[int, typer.Option(help="Events to claim.")] = 100,
) -> None:
    """Claim a batch of unconsumed events, as Phase 2 would.

    Exists to prove the hand-off contract from the consumer's side; Phase 1 does not
    otherwise care who reads the queue.
    """
    from attendance.storage import claim_events, connect

    connection = connect(_require_dsn(dsn))
    try:
        rows = claim_events(connection, batch_size=batch_size)
    finally:
        connection.close()

    typer.echo(json.dumps(rows, indent=2, default=str))
    typer.echo(f"Claimed {len(rows)} event(s).", err=True)


@app.command("inspect")
def inspect_command(
    source: Annotated[str, typer.Argument(help="Video file or RTSP URL to probe.")],
    backend: Annotated[str, typer.Option(help="Face backend to use.")] = "insightface",
    max_frames: Annotated[int, typer.Option(help="Sampled frames to examine.")] = 20,
    spread: Annotated[
        bool,
        typer.Option(
            "--spread/--no-spread",
            help="Spread the frame budget across the whole clip instead of the first few seconds.",
        ),
    ] = True,
    target_fps: Annotated[float | None, typer.Option(help="Override sampling rate.")] = None,
    save_frames: Annotated[
        Path | None, typer.Option(help="Write annotated frames here for visual checking.")
    ] = None,
    save_crops: Annotated[
        Path | None, typer.Option(help="Write the aligned face crops here.")
    ] = None,
) -> None:
    """Check whether a clip is usable before enrolling or matching against it.

    Runs detection and the quality gate and reports what it found. Nothing is matched,
    stored or published, so this is safe to point at any footage.
    """
    configure_logging()
    from attendance.inspect import inspect_source

    settings = Settings()
    if target_fps is not None:
        settings.sampling.target_fps = target_fps

    report = inspect_source(
        source=source,
        backend=build_backend(settings, backend),
        sampling=settings.sampling,
        quality=settings.quality,
        max_frames=max_frames,
        spread=spread,
        save_frames_dir=save_frames,
        save_crops_dir=save_crops,
    )

    typer.echo(json.dumps(report.summary(), indent=2))
    typer.echo("")
    for note in report.advice(settings.quality):
        typer.echo(f"* {note}")
    if report.frames_written:
        typer.echo(f"\nWrote {report.frames_written} annotated frame(s) to {save_frames}")
    if report.crops_written:
        typer.echo(f"Wrote {report.crops_written} face crop(s) to {save_crops}")


@app.command("extract-references")
def extract_references(
    source: Annotated[str, typer.Argument(help="Video file or RTSP URL.")],
    output: Annotated[Path, typer.Option(help="Directory to fill with candidates.")] = Path(
        "var/candidates"
    ),
    backend: Annotated[str, typer.Option(help="Face backend to use.")] = "insightface",
    max_frames: Annotated[
        int | None, typer.Option(help="Sampled frames to scan. Default scans the whole clip.")
    ] = None,
    similarity: Annotated[
        float,
        typer.Option(
            help="Cosine similarity at which two track fragments are treated as one person."
        ),
    ] = 0.5,
    max_per_person: Annotated[int, typer.Option(help="Reference photos to keep per person.")] = 3,
) -> None:
    """Pull reference photos out of a clip, one directory per person.

    For when the clip is the only material available. Track fragments are grouped by face
    similarity, so a person the tracker split across many tracks still produces a single
    'person_NN' directory. Rename each to that student's university_id before enrolling.

    Reference photos taken from the same camera as runtime frames also avoid the domain
    gap that hurts accuracy when enrollment photos come from elsewhere.
    """
    configure_logging()
    from attendance.inspect import extract_reference_candidates

    settings = Settings()
    result = extract_reference_candidates(
        report_dir=output,
        source=source,
        backend=build_backend(settings, backend),
        sampling=settings.sampling,
        quality=settings.quality,
        max_frames=max_frames,
        similarity_threshold=similarity,
        max_per_person=max_per_person,
    )
    if result.people_found == 0:
        typer.echo(
            "No usable faces found. Run 'attendance inspect' on the same clip to see why.",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo(
        f"Scanned {result.frames_scanned} frame(s): {result.tracks_found} track fragment(s) "
        f"grouped into {result.people_found} person(s)."
    )
    if result.fragmentation and result.fragmentation > 1.5:
        typer.echo(
            f"  Tracker produced {result.fragmentation:.1f} fragments per person, which is "
            "normal at a low sampling rate; grouping by face similarity absorbed it."
        )
    typer.echo(f"Wrote {result.references_written} reference photo(s) to {output}/person_NN/")
    typer.echo(f"Cluster map: {output}/clusters.json")
    typer.echo(
        "\nRename each person_NN directory to that student's university_id, then:\n"
        f"  attendance enroll {output} --output var/enrolled.npz"
    )
    typer.echo(
        "If one person still appears twice, lower --similarity; if two people were merged, "
        "raise it. Previous person_* folders in the output directory are replaced each run."
    )


@app.command("enroll")
def enroll(
    photo_dir: Annotated[Path, typer.Argument(help="Reference photos, grouped by university_id.")],
    output: Annotated[Path, typer.Option(help="Where to write the embedding bundle.")] = Path(
        "var/enrolled.npz"
    ),
    backend: Annotated[str, typer.Option(help="Face backend to use.")] = "insightface",
    max_per_student: Annotated[int, typer.Option(help="Reference photos per student.")] = 3,
    enforce_quality: Annotated[
        bool, typer.Option(help="Apply the runtime quality gate to reference photos too.")
    ] = True,
) -> None:
    """Build embeddings from reference photos using the runtime detection path."""
    configure_logging()
    settings = Settings()
    face_backend = build_backend(settings, backend)

    result = enrollment.enroll_directory(
        photo_dir=photo_dir,
        backend=face_backend,
        quality=settings.quality,
        max_per_student=max_per_student,
        enforce_quality=enforce_quality,
    )
    if not result.embeddings:
        typer.echo("No embeddings produced. Nothing written.", err=True)
        raise typer.Exit(code=1)

    enrollment.save_embeddings(result.embeddings, output)
    typer.echo(
        f"Enrolled {result.student_count} student(s), "
        f"{len(result.embeddings)} embedding(s) -> {output}"
    )
    for path, reason in result.skipped:
        typer.echo(f"  skipped {path.name}: {reason}")


@app.command("run")
def run(
    source: Annotated[str, typer.Argument(help="RTSP URL, GStreamer pipeline, or video file.")],
    camera_id: Annotated[str, typer.Option(help="Identifier carried on every event.")] = "CAM-1",
    enrolled: Annotated[Path, typer.Option(help="Embedding bundle from 'enroll'.")] = Path(
        "var/enrolled.npz"
    ),
    backend: Annotated[str, typer.Option(help="Face backend to use.")] = "insightface",
    store_kind: Annotated[
        str, typer.Option("--store", help="Where embeddings and events live: memory or postgres.")
    ] = "memory",
    dsn: Annotated[str | None, typer.Option(help="Postgres DSN when --store postgres.")] = None,
    target_fps: Annotated[float | None, typer.Option(help="Override sampling rate.")] = None,
    threshold: Annotated[float | None, typer.Option(help="Override similarity threshold.")] = None,
    max_frames: Annotated[int | None, typer.Option(help="Stop after N sampled frames.")] = None,
    output_dir: Annotated[Path | None, typer.Option(help="Where events are written.")] = None,
    json_logs: Annotated[bool, typer.Option(help="Emit JSON logs.")] = False,
) -> None:
    """Run the identification pipeline for one camera."""
    configure_logging(json_output=json_logs)
    settings = Settings()
    if target_fps is not None:
        settings.sampling.target_fps = target_fps
    if threshold is not None:
        settings.matching.similarity_threshold = threshold
    if output_dir is not None:
        settings.output_dir = output_dir

    face_backend = build_backend(settings, backend)
    camera = CameraSettings(camera_id=camera_id, source=source)

    connection = None
    try:
        if store_kind == "postgres":
            from attendance.storage import (
                PgVectorEmbeddingStore,
                PostgresEventPublisher,
                upsert_camera,
            )
            from attendance.storage import connect as pg_connect

            connection = pg_connect(_require_dsn(dsn))
            upsert_camera(
                connection,
                camera_id=camera_id,
                location_label=camera_id,
                source_ref=source,
            )
            store = PgVectorEmbeddingStore(
                connection,
                model_version=face_backend.model_version,
                exclude_inactive_students=settings.matching.exclude_inactive_students,
                ef_search=settings.database.ef_search,
            )
            publisher = PostgresEventPublisher(
                connection,
                model_version=face_backend.model_version,
                persist_unresolved_embeddings=settings.privacy.persist_unresolved_embeddings,
            )
        elif store_kind == "memory":
            store = _load_memory_store(enrolled, face_backend)
            publisher = JsonlEventPublisher(
                settings.output_dir,
                persist_unresolved_embeddings=settings.privacy.persist_unresolved_embeddings,
            )
        else:
            typer.echo(f"Unknown --store value: {store_kind}", err=True)
            raise typer.Exit(code=2)

        if store.size == 0:
            typer.echo(
                "No enrolled embeddings available. Running detection only; "
                "every face will be logged as unresolved.",
                err=True,
            )

        with publisher:
            pipeline = CameraPipeline(
                camera=camera,
                settings=settings,
                backend=face_backend,
                matcher=Matcher(store, settings.matching),
                publisher=publisher,
            )
            metrics = pipeline.run(max_frames=max_frames)
    finally:
        if connection is not None:
            connection.close()

    typer.echo(json.dumps(metrics.as_dict(), indent=2))


def _load_memory_store(enrolled: Path, face_backend) -> InMemoryEmbeddingStore:
    store = InMemoryEmbeddingStore()
    if not enrolled.exists():
        return store

    records = enrollment.load_embeddings(enrolled)
    store.add_many(records)
    mismatched = {r.model_version for r in records} - {face_backend.model_version}
    if mismatched:
        typer.echo(
            f"Warning: enrolled vectors were built by {sorted(mismatched)} but this run uses "
            f"{face_backend.model_version}. Those students cannot be matched and need "
            "re-enrollment against the current model.",
            err=True,
        )
    return store


if __name__ == "__main__":
    app()
