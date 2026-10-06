"""DuckDB contracts and transactional publication of immutable Parquet versions."""

import hashlib
import json
import os
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from app.analytics.hero_daily import HERO_DAILY_SCHEMA, validate_hero_daily_stats
from app.analytics.recommendation_stats import (
    RECOMMENDATION_SCHEMA,
    validate_recommendation_stats,
)
from app.core.clock import to_utc_iso, utc_now
from app.core.errors import DataError
from app.core.paths import DataPaths, ensure_data_directories
from app.core.runs import RunRecord, RunStatus
from app.storage.locking import pipeline_writer_lock
from app.storage.processed import (
    MATCH_PLAYERS_SCHEMA,
    MATCHES_SCHEMA,
    NORMALIZER_VERSION,
    PLAYER_ITEMS_SCHEMA,
)
from app.storage.raw import RUN_ID_PATTERN, SCHEMA, list_run_paths

CATALOG_VERSION = 1
AGGREGATOR_VERSION = 3
DATASET_COUNTS_SCHEMA = pa.schema([("dataset", pa.string()), ("row_count", pa.int64())])
ENTITY_SCHEMAS = {
    "raw_matches": SCHEMA,
    "matches": MATCHES_SCHEMA,
    "match_players": MATCH_PLAYERS_SCHEMA,
    "player_items": PLAYER_ITEMS_SCHEMA,
}
VIEW_SCHEMAS = {
    **ENTITY_SCHEMAS,
    "dataset_counts": DATASET_COUNTS_SCHEMA,
    "hero_daily_stats": HERO_DAILY_SCHEMA,
    "recommendation_stats": RECOMMENDATION_SCHEMA,
}
SNAPSHOT_FILES = {f"{name}.parquet" for name in VIEW_SCHEMAS if name != "raw_matches"} | {
    "quality.json",
    "metadata.json",
}
SNAPSHOT_FILES_V2 = SNAPSHOT_FILES - {"recommendation_stats.parquet"}
LEGACY_SNAPSHOT_FILES = SNAPSHOT_FILES_V2 - {"hero_daily_stats.parquet", "metadata.json"}
VERSION_FILES = {1: LEGACY_SNAPSHOT_FILES, 2: SNAPSHOT_FILES_V2, 3: SNAPSHOT_FILES}


def file_sha256(path: Path) -> str:
    """Hash even large archives without loading the entire file into memory."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    """Publish a complete JSON document without exposing a partially written file."""
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _select(connection: duckdb.DuckDBPyConnection, files: list[Path], schema: pa.Schema) -> str:
    columns = ", ".join(f'"{field.name}"' for field in schema)
    if files:
        literals = ", ".join(_literal(str(path.resolve())) for path in files)
        return f"SELECT {columns} FROM read_parquet([{literals}], hive_partitioning=false)"
    connection.register("_empty_schema", pa.Table.from_pylist([], schema=schema))
    try:
        fields = connection.execute("DESCRIBE SELECT * FROM _empty_schema").fetchall()
    finally:
        connection.unregister("_empty_schema")
    projection = ", ".join(f'CAST(NULL AS {kind}) AS "{name}"' for name, kind, *_ in fields)
    return f"SELECT {projection} WHERE FALSE"


def install_views(
    connection: duckdb.DuckDBPyConnection,
    files: dict[str, list[Path]],
    *,
    temporary: bool = False,
    only_missing: bool = False,
) -> None:
    """Bind explicit file lists, so future or unfinished runs cannot alter a publication."""
    for name, schema in VIEW_SCHEMAS.items():
        select = _select(connection, files.get(name, []), schema)
        if name == "raw_matches" and files.get(name):
            select = f"""SELECT * FROM ({select}) QUALIFY row_number() OVER (
                PARTITION BY match_id ORDER BY
                    CASE WHEN endpoint LIKE '/matches/%' THEN 0 ELSE 1 END,
                    collected_at, payload_sha256
            ) = 1"""
        prefix = "TEMP " if temporary else ""
        clause = "IF NOT EXISTS" if only_missing else "OR REPLACE"
        view = f"candidate_{name}" if temporary else name
        if only_missing:
            connection.execute(f"CREATE {prefix}VIEW {clause} {view} AS {select}")
        else:
            connection.execute(f"CREATE {clause} {prefix}VIEW {view} AS {select}")


def initialize_catalog(connection: duckdb.DuckDBPyConnection) -> None:
    """Initialize operational tables and typed empty views on a fresh catalog."""
    connection.execute("SET TimeZone = 'UTC'")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_schema (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1), version INTEGER NOT NULL
        );
        INSERT INTO catalog_schema VALUES (1, 1) ON CONFLICT DO NOTHING;
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id VARCHAR PRIMARY KEY, operation VARCHAR NOT NULL, stage VARCHAR NOT NULL,
            status VARCHAR NOT NULL, started_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ,
            duration_ms BIGINT, requested_count BIGINT NOT NULL, received_count BIGINT NOT NULL,
            processed_count BIGINT NOT NULL, attempts BIGINT NOT NULL, failures BIGINT NOT NULL,
            source_run_ids JSON NOT NULL, version_id VARCHAR, error VARCHAR
        );
        CREATE TABLE IF NOT EXISTS collection_runs (
            run_id VARCHAR PRIMARY KEY, manifest_path VARCHAR NOT NULL, manifest_json JSON NOT NULL
        );
        CREATE TABLE IF NOT EXISTS dataset_versions (
            version_id VARCHAR PRIMARY KEY, run_id VARCHAR NOT NULL, status VARCHAR NOT NULL,
            created_at TIMESTAMPTZ NOT NULL, published_at TIMESTAMPTZ NOT NULL,
            normalizer_version INTEGER NOT NULL, aggregator_version INTEGER NOT NULL,
            manifest_path VARCHAR NOT NULL, manifest_json JSON NOT NULL
        );
        CREATE TABLE IF NOT EXISTS current_publication (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1), version_id VARCHAR NOT NULL
        );
        """
    )
    if connection.execute("SELECT version FROM catalog_schema").fetchone() != (CATALOG_VERSION,):
        raise DataError("unsupported catalog schema version")
    install_views(connection, {}, only_missing=True)


def record_run(
    connection: duckdb.DuckDBPyConnection,
    run: RunRecord | dict[str, Any],
    stage: str,
    source_run_ids: list[str],
    *,
    version_id: str | None = None,
    error: str | None = None,
) -> None:
    context = run.as_log_context() if isinstance(run, RunRecord) else run
    fields = (
        "run_id",
        "operation",
        "status",
        "started_at",
        "finished_at",
        "duration_ms",
        "requested_count",
        "received_count",
        "processed_count",
        "attempts",
        "failures",
    )
    values = [context[key] for key in fields]
    connection.execute(
        """
        INSERT OR REPLACE INTO pipeline_runs (
            run_id, operation, status, started_at, finished_at, duration_ms,
            requested_count, received_count, processed_count, attempts, failures,
            stage, source_run_ids, version_id, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [*values, stage, json.dumps(source_run_ids), version_id, error],
    )


def sync_collection_runs(connection: duckdb.DuckDBPyConnection, paths: DataPaths) -> None:
    for folder in list_run_paths(paths.raw):
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        connection.execute(
            "INSERT OR REPLACE INTO collection_runs VALUES (?, ?, ?)",
            [manifest["run"]["run_id"], str(folder / "manifest.json"), json.dumps(manifest)],
        )


def current_version(connection: duckdb.DuckDBPyConnection) -> str | None:
    row = connection.execute(
        "SELECT version_id FROM current_publication WHERE singleton=1"
    ).fetchone()
    return row[0] if row else None


def validate_entities(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Verify relational invariants before any aggregate or view becomes current."""
    counts = {
        name: connection.execute(f"SELECT count(*) FROM candidate_{name}").fetchone()[0]
        for name in ENTITY_SCHEMAS
    }
    checks = {
        "duplicate raw match IDs": """
            SELECT match_id FROM candidate_raw_matches GROUP BY match_id HAVING count(*) <> 1
        """,
        "invalid or duplicate matches": """
            SELECT match_id FROM candidate_matches
            GROUP BY match_id HAVING match_id IS NULL OR count(*) <> 1
        """,
        "invalid match attributes": """
            SELECT match_id FROM candidate_matches WHERE match_id <= 0 OR started_at_utc IS NULL
            OR duration_seconds IS NULL OR duration_seconds <= 0 OR radiant_win IS NULL
        """,
        "players without a match": """
            SELECT p.match_id FROM candidate_match_players p
            LEFT JOIN candidate_matches m USING (match_id) WHERE m.match_id IS NULL
        """,
        "invalid teams or match results": """
            SELECT p.match_id FROM candidate_match_players p
            JOIN candidate_matches m USING (match_id)
            WHERE p.team IS NULL OR p.team NOT IN ('radiant', 'dire') OR p.hero_id IS NULL
            OR p.hero_id <= 0 OR p.team_index IS NULL OR p.team_index NOT BETWEEN 0 AND 4
            OR p.won IS DISTINCT FROM (m.radiant_win = (p.team = 'radiant'))
            OR (p.player_slot IS NOT NULL AND p.player_slot <>
                p.team_index + CASE WHEN p.team = 'radiant' THEN 0 ELSE 128 END)
        """,
        "matches without ten distinct participants": """
            SELECT m.match_id FROM candidate_matches m
            LEFT JOIN candidate_match_players p USING (match_id) GROUP BY m.match_id
            HAVING count(p.hero_id) <> 10 OR count(DISTINCT p.hero_id) <> 10
            OR count(DISTINCT (p.team, p.team_index)) <> 10
            OR count(*) FILTER (WHERE p.team = 'radiant') <> 5
            OR count(*) FILTER (WHERE p.team = 'dire') <> 5
        """,
        "items without a participant": """
            SELECT i.match_id FROM candidate_player_items i
            LEFT JOIN candidate_match_players p USING (match_id, player_slot)
            WHERE p.match_id IS NULL
        """,
    }
    for reason, query in checks.items():
        if connection.execute(f"SELECT EXISTS ({query})").fetchone()[0]:
            raise DataError(reason)
    if not counts["matches"]:
        raise DataError("no valid matches available for publication")
    return counts


def _under(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise DataError("snapshot path escapes its data directory")
    return path


def _parquet_schema(schema: pa.Schema) -> pa.Schema:
    # Parquet represents Arrow's second-resolution timestamps in milliseconds.
    return pa.schema(
        [
            pa.field(field.name, pa.timestamp("ms", tz=field.type.tz), nullable=field.nullable)
            if pa.types.is_timestamp(field.type) and field.type.unit == "s"
            else field
            for field in schema
        ]
    )


def validate_snapshot(
    connection: duckdb.DuckDBPyConnection, paths: DataPaths, folder: Path
) -> tuple[dict[str, Any], dict[str, list[Path]]]:
    manifest = json.loads((folder / "version.json").read_text(encoding="utf-8"))
    if (
        manifest["schema_version"] != CATALOG_VERSION
        or manifest["normalizer_version"] not in (1, NORMALIZER_VERSION)
        or manifest["aggregator_version"] not in VERSION_FILES
        or manifest["version_id"] != folder.name
        or not RUN_ID_PATTERN.fullmatch(folder.name)
        or set(manifest["files"]) != VERSION_FILES[manifest["aggregator_version"]]
    ):
        raise DataError("unsupported or invalid dataset version manifest")
    for filename, checksum in manifest["files"].items():
        if file_sha256(folder / filename) != checksum:
            raise DataError(f"snapshot checksum mismatch: {filename}")
    files = {
        name: [folder / f"{name}.parquet"]
        for name in VIEW_SCHEMAS
        if f"{name}.parquet" in manifest["files"]
    }
    raw_files = []
    for raw in manifest["raw_files"]:
        path = _under(paths.raw, raw["path"])
        if file_sha256(path) != raw["sha256"]:
            raise DataError(f"raw archive checksum mismatch: {raw['path']}")
        raw_files.append(path)
    files["raw_matches"] = raw_files
    for name, schema in VIEW_SCHEMAS.items():
        for path in files.get(name, []):
            if not pq.read_schema(path).equals(_parquet_schema(schema)):
                raise DataError(f"unexpected Parquet schema: {path.name}")
    install_views(connection, files, temporary=True)
    counts = validate_entities(connection)
    if manifest["aggregator_version"] >= 3:
        validate_recommendation_stats(connection)
    if manifest["aggregator_version"] >= 2:
        validate_hero_daily_stats(connection)
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        if metadata.get("summary") != manifest.get("metadata"):
            raise DataError("metadata summary does not match the snapshot")
        if metadata["summary"] is not None:
            summary = metadata["summary"]
            source = _under(paths.raw, summary["raw_path"])
            if file_sha256(source) != summary["raw_sha256"]:
                raise DataError("metadata source checksum mismatch")
            if json.loads(source.read_text(encoding="utf-8")) != metadata["payloads"]:
                raise DataError("metadata payload differs from its archived source")
    summary = connection.execute(
        "SELECT dataset, row_count FROM candidate_dataset_counts"
    ).fetchall()
    if counts != manifest["counts"] or sorted(summary) != sorted(counts.items()):
        raise DataError("dataset counts do not match the published Parquet")
    quality = json.loads((folder / "quality.json").read_text(encoding="utf-8"))
    if (
        quality != manifest["quality"]
        or quality["input_matches"] != counts["raw_matches"]
        or quality["accepted_matches"] != counts["matches"]
        or quality["accepted_match_players"] != counts["match_players"]
        or quality["accepted_player_items"] != counts["player_items"]
        or quality["accepted_matches"] + quality["rejected_matches"] != quality["input_matches"]
    ):
        raise DataError("quality report does not match the published Parquet")
    return manifest, files


def _promote(
    connection: duckdb.DuckDBPyConnection,
    folder: Path,
    manifest: dict[str, Any],
    files: dict[str, list[Path]],
    published_at: str,
) -> None:
    version_id = manifest["version_id"]
    install_views(connection, files)
    connection.execute("UPDATE dataset_versions SET status='superseded' WHERE status='published'")
    connection.execute(
        "INSERT OR REPLACE INTO dataset_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            version_id,
            version_id,
            "published",
            manifest["created_at"],
            published_at,
            manifest["normalizer_version"],
            manifest["aggregator_version"],
            str(folder / "version.json"),
            json.dumps(manifest),
        ],
    )
    connection.execute("INSERT OR REPLACE INTO current_publication VALUES (1, ?)", [version_id])


def publish_version(
    connection: duckdb.DuckDBPyConnection, paths: DataPaths, folder: Path, run: RunRecord
) -> None:
    """Switch all views, the current version and the terminal run state in one transaction."""
    manifest, files = validate_snapshot(connection, paths, folder)
    if manifest["version_id"] != run.run_id:
        raise DataError("publication run does not own this dataset version")
    receipt = folder / "published.json"
    if receipt.exists():
        raise DataError("dataset version has already been published")
    published_at = to_utc_iso(utc_now())
    connection.execute("BEGIN TRANSACTION")
    try:
        _promote(connection, folder, manifest, files, published_at)
        run.finish(RunStatus.SUCCEEDED)
        record_run(connection, run, "publish", manifest["source_run_ids"], version_id=run.run_id)
        # Written only after all checks and SQL changes. A normal rollback removes the receipt.
        write_json_atomic(
            receipt,
            {
                "version_id": run.run_id,
                "published_at": published_at,
                "run": run.as_log_context(),
            },
        )
        connection.execute("COMMIT")
    except BaseException:
        try:
            connection.execute("ROLLBACK")
        finally:
            receipt.unlink(missing_ok=True)
        raise


def rebuild_catalog(paths: DataPaths) -> dict[str, Any]:
    """Recover only complete published versions; unfinished staging/output is never promoted."""
    with pipeline_writer_lock(paths):
        ensure_data_directories(paths)
        with closing(duckdb.connect(str(paths.duckdb))) as connection:
            initialize_catalog(connection)
            published = []
            for folder in sorted((paths.processed / "versions").glob("run_*")):
                receipt_path = folder / "published.json"
                if receipt_path.is_file():
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                    manifest, files = validate_snapshot(connection, paths, folder)
                    if (
                        receipt["version_id"] != folder.name
                        or receipt["run"]["run_id"] != folder.name
                        or receipt["run"]["status"] != "succeeded"
                    ):
                        raise DataError("invalid publication receipt")
                    published.append((receipt["published_at"], folder, manifest, files, receipt))
            connection.execute("BEGIN TRANSACTION")
            try:
                sync_collection_runs(connection, paths)
                for timestamp, folder, manifest, files, receipt in sorted(
                    published, key=lambda x: x[0]
                ):
                    _promote(connection, folder, manifest, files, timestamp)
                    record_run(
                        connection,
                        receipt["run"],
                        "publish",
                        manifest["source_run_ids"],
                        version_id=manifest["version_id"],
                    )
                if not published and current_version(connection) is None:
                    files = {
                        "raw_matches": [p / "matches.parquet" for p in list_run_paths(paths.raw)]
                    }
                    install_views(connection, files)
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            return {
                "catalog": str(paths.duckdb),
                "version_id": current_version(connection),
                "restored_versions": len(published),
                "counts": dict(connection.execute("SELECT * FROM dataset_counts").fetchall()),
            }
