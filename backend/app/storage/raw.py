"""Atomic Parquet archives with independent deduplication for summaries and details."""

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import UTC
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.collectors.public_matches import CollectionResult
from app.core.clock import to_utc_iso
from app.core.runs import RunStatus
from app.storage.locking import writer_lock

COLLECTOR_VERSION = "0.1.0"
DATASET = "public_matches"
RUN_ID_PATTERN = re.compile(r"^run_[A-Za-z0-9_]+$")
SCHEMA = pa.schema(
    [
        ("match_id", pa.int64()),
        ("source", pa.string()),
        ("endpoint", pa.string()),
        ("parameters_json", pa.string()),
        ("requested_at", pa.string()),
        ("status_code", pa.int16()),
        ("collected_at", pa.string()),
        ("payload_json", pa.string()),
        ("payload_sha256", pa.string()),
        ("collector_version", pa.string()),
    ]
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def list_run_paths(raw_root: Path) -> list[Path]:
    """List only atomically committed raw runs, never staging directories."""
    return sorted(
        path
        for dataset in (DATASET, "match_details")
        for path in (raw_root / dataset).glob("collected_date=*/run_*")
        if path.is_dir() and (path / "manifest.json").is_file()
    )


def list_partitions(raw_root: Path) -> list[str]:
    """List committed collection dates; staging directories are invisible."""
    return sorted(
        {path.parent.name.removeprefix("collected_date=") for path in list_run_paths(raw_root)}
    )


def list_runs(raw_root: Path) -> list[dict[str, Any]]:
    """Return committed manifests in deterministic path order."""
    return [
        json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        for path in list_run_paths(raw_root)
    ]


def _stored_ids(raw_root: Path, dataset: str) -> set[int]:
    ids: set[int] = set()
    for path in list_run_paths(raw_root):
        if path.parent.parent.name != dataset:
            continue
        table = pq.read_table(path / "matches.parquet", columns=["match_id"])
        ids.update(table.column("match_id").to_pylist())
    return ids


def persist_collection(
    raw_root: Path, result: CollectionResult, *, max_pages: int
) -> dict[str, Any]:
    """Commit atomically; the first payload wins per dataset and match ID."""
    with writer_lock(raw_root / ".writer.lock"):
        return _persist_collection(raw_root, result, max_pages=max_pages)


def _persist_collection(
    raw_root: Path, result: CollectionResult, *, max_pages: int
) -> dict[str, Any]:
    if result.run.status is RunStatus.RUNNING:
        raise ValueError("cannot persist an unfinished collection")
    if not RUN_ID_PATTERN.fullmatch(result.run.run_id):
        raise ValueError("invalid run_id")
    if result.dataset not in (DATASET, "match_details"):
        raise ValueError("unsupported raw dataset")
    collected_at = to_utc_iso(result.run.started_at)
    date = result.run.started_at.astimezone(UTC).date().isoformat()
    partition = raw_root / result.dataset / f"collected_date={date}"
    destination = partition / result.run.run_id
    if destination.exists():
        raise FileExistsError(f"run already committed: {result.run.run_id}")
    seen = _stored_ids(raw_root, result.dataset)
    rows: list[dict[str, Any]] = []
    match_ids: list[int] = []
    for match in result.matches:
        match_id = match["match_id"]
        if type(match_id) is not int or match_id < 1 or match_id in match_ids:
            raise ValueError("collection contains an invalid or repeated match_id")
        match_ids.append(match_id)
        if match_id in seen:
            continue
        page = result.source_pages[result.match_pages[match_id]]
        payload = _json(match)
        rows.append(
            {
                "match_id": match_id,
                "source": "opendota",
                "endpoint": page.get("endpoint", "/publicMatches"),
                "parameters_json": _json(page["parameters"]),
                "requested_at": page["requested_at"],
                "status_code": page["status_code"],
                "collected_at": collected_at,
                "payload_json": payload,
                "payload_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                "collector_version": COLLECTOR_VERSION,
            }
        )
    manifest = {
        "schema_version": 1,
        "run": result.run.as_log_context(),
        "collector_version": COLLECTOR_VERSION,
        "source": "opendota",
        "dataset": result.dataset,
        "endpoint": "/publicMatches" if result.dataset == DATASET else "/matches/{match_id}",
        "parameters": (
            {"min_rank": 70, "count": result.run.requested_count, "max_pages": max_pages}
            if result.dataset == DATASET
            else {"count": result.run.requested_count}
        ),
        "volumes": {
            "received": result.run.received_count,
            "selected": len(match_ids),
            "discarded": result.discarded_count,
            "new": len(rows),
            "existing": len(match_ids) - len(rows),
        },
        "pages": result.source_pages,
        "match_ids": match_ids,
        "message": result.message,
        "errors": [result.message] if result.run.status is not RunStatus.SUCCEEDED else [],
    }
    partition.mkdir(parents=True, exist_ok=True)
    staging = partition / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), staging / "matches.parquet")
        (staging / "manifest.json").write_text(_json(manifest) + "\n", encoding="utf-8")
        if destination.exists():
            raise FileExistsError(f"run already committed: {result.run.run_id}")
        os.replace(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return manifest


def read_run(raw_root: Path, run_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Rebuild the selected sample from local Parquet, with no network access."""
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("invalid run_id")
    paths = [path for path in list_run_paths(raw_root) if path.name == run_id]
    if len(paths) != 1:
        raise FileNotFoundError(f"committed run not found: {run_id}")
    manifest = json.loads((paths[0] / "manifest.json").read_text(encoding="utf-8"))
    wanted = set(manifest["match_ids"])
    payloads: dict[int, dict[str, Any]] = {}
    for path in list_run_paths(raw_root):
        if path.parent.parent.name != paths[0].parent.parent.name:
            continue
        for row in pq.read_table(path / "matches.parquet").to_pylist():
            if row["match_id"] in wanted:
                if (
                    hashlib.sha256(row["payload_json"].encode("utf-8")).hexdigest()
                    != row["payload_sha256"]
                ):
                    raise ValueError(f"payload hash mismatch: {row['match_id']}")
                payload = json.loads(row["payload_json"])
                if (
                    not isinstance(payload, dict)
                    or type(payload.get("match_id")) is not int
                    or payload["match_id"] != row["match_id"]
                ):
                    raise ValueError("persisted payload does not match its row match_id")
                payloads.setdefault(row["match_id"], payload)
    missing = wanted - payloads.keys()
    if missing:
        raise ValueError(f"missing persisted match IDs: {sorted(missing)}")
    return manifest, [payloads[match_id] for match_id in manifest["match_ids"]]
