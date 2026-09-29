"""Orchestrate one writer and publish only a complete, validated dataset version."""

import asyncio
import os
import shutil
import uuid
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from app.analytics.normalize import normalize
from app.collectors.opendota import OpenDotaClient
from app.collectors.public_matches import collect_public_matches
from app.core.clock import to_utc_iso, utc_now
from app.core.config import Settings
from app.core.errors import DataError
from app.core.logging import get_logger
from app.core.paths import DataPaths, ensure_data_directories, get_data_paths
from app.core.runs import RunRecord, RunStatus
from app.storage.catalog import (
    AGGREGATOR_VERSION,
    CATALOG_VERSION,
    DATASET_COUNTS_SCHEMA,
    SNAPSHOT_FILES,
    file_sha256,
    initialize_catalog,
    install_views,
    publish_version,
    record_run,
    sync_collection_runs,
    validate_entities,
    write_json_atomic,
)
from app.storage.locking import pipeline_writer_lock
from app.storage.processed import NORMALIZER_VERSION, write_normalized_tables
from app.storage.raw import list_run_paths, persist_collection, read_run


class PipelineStage(StrEnum):
    COLLECT = "collect"
    VALIDATE = "validate"
    NORMALIZE = "normalize"
    AGGREGATE = "aggregate"
    PUBLISH = "publish"


@dataclass(slots=True)
class PipelineResult:
    run: RunRecord
    stage: PipelineStage
    source_run_ids: list[str]
    version_id: str | None = None
    counts: dict[str, int] | None = None
    quality: dict[str, Any] | None = None
    message: str = "dataset published"

    def as_dict(self) -> dict[str, Any]:
        return {
            "run": self.run.as_log_context(),
            "stage": self.stage.value,
            "source_run_ids": self.source_run_ids,
            "version_id": self.version_id,
            "counts": self.counts,
            "quality": self.quality,
            "message": self.message,
        }


def _load_inputs(paths: DataPaths) -> tuple[list[str], list[dict[str, Any]], list[Path]]:
    folders = list_run_paths(paths.raw)
    if not folders:
        raise DataError("no committed raw runs available; collect a sample first")
    source_run_ids = []
    matches: dict[int, dict[str, Any]] = {}
    for folder in folders:
        manifest, payloads = read_run(paths.raw, folder.name)
        if (
            manifest["schema_version"] != 1
            or manifest["run"]["run_id"] != folder.name
            or manifest["run"]["status"] not in ("succeeded", "partial", "failed")
        ):
            raise DataError(f"invalid committed raw manifest: {folder.name}")
        source_run_ids.append(folder.name)
        for payload in payloads:
            matches.setdefault(payload["match_id"], payload)
    return source_run_ids, list(matches.values()), [p / "matches.parquet" for p in folders]


def aggregate_dataset(staging: Path, raw_files: list[Path]) -> dict[str, int]:
    """Stage 7 aggregates audit counts; hero metrics belong to stage 8."""
    files = {
        "raw_matches": raw_files,
        **{
            name: [staging / f"{name}.parquet"]
            for name in (
                "matches",
                "match_players",
                "player_items",
            )
        },
    }
    with closing(duckdb.connect()) as connection:
        install_views(connection, files, temporary=True)
        counts = validate_entities(connection)
    pq.write_table(
        pa.Table.from_pylist(
            [{"dataset": name, "row_count": count} for name, count in counts.items()],
            schema=DATASET_COUNTS_SCHEMA,
        ),
        staging / "dataset_counts.parquet",
    )
    return counts


async def run_pipeline(
    settings: Settings,
    *,
    collect: bool = False,
    count: int = 20,
    max_pages: int = 2,
    client: OpenDotaClient | None = None,
) -> PipelineResult:
    """Reprocess all committed raw data, optionally preceded by a bounded collection."""
    if not 1 <= count <= 200 or not 1 <= max_pages <= 5:
        raise ValueError("count must be 1..200 and max_pages must be 1..5")
    paths = get_data_paths(settings)
    run = RunRecord(operation="pipeline_run" if collect else "pipeline_reprocess")
    output = PipelineResult(run, PipelineStage.COLLECT if collect else PipelineStage.VALIDATE, [])
    logger = get_logger(__name__)
    staging: Path | None = None
    with pipeline_writer_lock(paths):
        ensure_data_directories(paths)
        with closing(duckdb.connect(str(paths.duckdb))) as connection:
            initialize_catalog(connection)
            # Holding all writer locks proves these runs no longer have a live owner.
            connection.execute(
                """UPDATE pipeline_runs SET status='failed', finished_at=?,
                duration_ms=date_diff('millisecond', started_at, ?), failures=failures+1,
                error='previous writer was interrupted' WHERE status='running'""",
                [utc_now(), utc_now()],
            )

            def stage(value: PipelineStage) -> None:
                output.stage = value
                record_run(connection, run, value.value, output.source_run_ids)
                logger.info(
                    "pipeline_stage",
                    extra={
                        "event": "pipeline_stage",
                        **run.as_log_context(),
                        "stage": value.value,
                    },
                )

            try:
                if collect:
                    stage(PipelineStage.COLLECT)
                    if client is None:
                        async with OpenDotaClient(settings) as owned_client:
                            collected = await collect_public_matches(
                                owned_client,
                                count=count,
                                max_pages=max_pages,
                            )
                    else:
                        collected = await collect_public_matches(
                            client, count=count, max_pages=max_pages
                        )
                    persist_collection(paths.raw, collected, max_pages=max_pages)
                    sync_collection_runs(connection, paths)
                    run.requested_count = count
                    run.received_count = collected.run.received_count
                    run.attempts = collected.run.attempts
                    run.failures = collected.run.failures
                    if collected.run.status is not RunStatus.SUCCEEDED:
                        output.source_run_ids = [collected.run.run_id]
                        output.message = collected.message
                        run.finish(collected.run.status)
                        record_run(
                            connection,
                            run,
                            output.stage.value,
                            output.source_run_ids,
                            error=output.message,
                        )
                        return output
                stage(PipelineStage.VALIDATE)
                output.source_run_ids, payloads, raw_files = _load_inputs(paths)
                sync_collection_runs(connection, paths)
                if not collect:
                    run.requested_count = run.received_count = len(payloads)
                stage(PipelineStage.NORMALIZE)
                normalized = normalize(payloads)
                output.quality = {
                    "schema_version": CATALOG_VERSION,
                    "normalizer_version": NORMALIZER_VERSION,
                    "source_run_ids": output.source_run_ids,
                    **normalized.quality,
                }
                run.processed_count = len(normalized.matches)
                if not normalized.matches:
                    raise DataError("no valid matches available for publication")
                base = paths.processed / "versions"
                base.mkdir(parents=True, exist_ok=True)
                staging = base / f".staging-{uuid.uuid4().hex}"
                staging.mkdir()
                write_normalized_tables(staging, normalized)
                write_json_atomic(staging / "quality.json", output.quality)
                stage(PipelineStage.AGGREGATE)
                output.counts = aggregate_dataset(staging, raw_files)
                manifest = {
                    "schema_version": CATALOG_VERSION,
                    "version_id": run.run_id,
                    "created_at": to_utc_iso(utc_now()),
                    "normalizer_version": NORMALIZER_VERSION,
                    "aggregator_version": AGGREGATOR_VERSION,
                    "source_run_ids": output.source_run_ids,
                    "quality": output.quality,
                    "counts": output.counts,
                    "files": {name: file_sha256(staging / name) for name in sorted(SNAPSHOT_FILES)},
                    "raw_files": [
                        {"path": str(path.relative_to(paths.raw)), "sha256": file_sha256(path)}
                        for path in raw_files
                    ],
                }
                write_json_atomic(staging / "version.json", manifest)
                destination = base / run.run_id
                if destination.exists():
                    raise FileExistsError(f"dataset version already exists: {run.run_id}")
                os.replace(staging, destination)
                staging = None
                stage(PipelineStage.PUBLISH)
                publish_version(connection, paths, destination, run)
                output.version_id = run.run_id
            except BaseException as exc:
                run.failures += 1
                run.finish(RunStatus.FAILED)
                output.message = str(exc) or type(exc).__name__
                record_run(
                    connection,
                    run,
                    output.stage.value,
                    output.source_run_ids,
                    error=output.message,
                )
                if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                    raise
                if not isinstance(exc, Exception):
                    raise
            finally:
                if staging is not None:
                    shutil.rmtree(staging)
                logger.info(
                    "pipeline_finished",
                    extra={
                        "event": "pipeline_finished",
                        **run.as_log_context(),
                        "stage": output.stage.value,
                        "version_id": output.version_id,
                        "detail": output.message,
                    },
                )
    return output
