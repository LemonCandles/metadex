"""Safe catalog backup and bounded processed-version retention."""

import os
import shutil
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from app.core.clock import to_utc_iso, utc_now
from app.core.config import Settings
from app.core.paths import get_data_paths
from app.storage.catalog import current_version, file_sha256, write_json_atomic
from app.storage.locking import pipeline_writer_lock


def backup_catalog(settings: Settings, destination: Path) -> dict[str, Any]:
    """Copy a closed catalog after verifying no writer or WAL is present."""
    paths = get_data_paths(settings)
    destination = destination.resolve()
    if destination == paths.duckdb:
        raise ValueError("backup destination must differ from the live catalog")
    with pipeline_writer_lock(paths):
        if not paths.duckdb.is_file():
            raise FileNotFoundError(paths.duckdb)
        if Path(str(paths.duckdb) + ".wal").exists():
            raise RuntimeError("catalog WAL is present; stop other processes before backup")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}-{uuid.uuid4().hex}.tmp")
        try:
            shutil.copy2(paths.duckdb, temporary)
            with closing(duckdb.connect(str(temporary), read_only=True)) as connection:
                version_id = current_version(connection)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        receipt = {
            "created_at": to_utc_iso(utc_now()),
            "version_id": version_id,
            "sha256": file_sha256(destination),
            "note": "Copy raw and processed data separately; catalog views refer to those files.",
        }
        write_json_atomic(destination.with_suffix(destination.suffix + ".json"), receipt)
        return {"catalog_backup": str(destination), **receipt}


def prune_versions(
    settings: Settings,
    *,
    keep: int = 2,
    min_age_days: int = 30,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Keep the current and newest previous versions; never touch raw archives."""
    if keep < 2 or min_age_days < 1:
        raise ValueError("keep must be >= 2 and min_age_days must be >= 1")
    paths = get_data_paths(settings)
    instant = now or utc_now()
    if instant.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    cutoff = instant.astimezone(UTC) - timedelta(days=min_age_days)
    with pipeline_writer_lock(paths), closing(duckdb.connect(str(paths.duckdb))) as connection:
        current = current_version(connection)
        rows = connection.execute(
            "SELECT version_id, CAST(published_at AS VARCHAR), status FROM dataset_versions "
            "ORDER BY published_at DESC, version_id DESC"
        ).fetchall()
        retained = {row[0] for row in rows[:keep]} | ({current} if current else set())

        def older_than_cutoff(value: str) -> bool:
            published = datetime.fromisoformat(value)
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
            return published.astimezone(UTC) < cutoff

        candidates = [
            row[0]
            for row in rows
            if row[0] not in retained and row[2] == "superseded" and older_than_cutoff(row[1])
        ]
        if apply:
            base = (paths.processed / "versions").resolve()
            for version_id in candidates:
                folder = base / version_id
                if not folder.is_dir() or folder.is_symlink() or folder.parent != base:
                    raise RuntimeError(f"unsafe or missing version directory: {version_id}")
                if not (folder / "published.json").is_file():
                    raise RuntimeError(f"version lacks publication receipt: {version_id}")
            for version_id in candidates:
                shutil.rmtree(base / version_id)
                connection.execute("DELETE FROM dataset_versions WHERE version_id=?", [version_id])
    return {
        "applied": apply,
        "current_version": current,
        "candidates": candidates,
        "raw_archives_preserved": True,
    }
