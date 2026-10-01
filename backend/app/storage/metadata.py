"""Immutable metadata archives and the exact catalog bound to each publication."""

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.collectors.metadata import RESOURCES, MetadataResult
from app.core.errors import DataError
from app.core.runs import RunStatus
from app.storage.locking import writer_lock
from app.storage.raw import RUN_ID_PATTERN


def persist_metadata(raw_root: Path, result: MetadataResult) -> dict[str, Any]:
    if result.run.status is RunStatus.RUNNING or not RUN_ID_PATTERN.fullmatch(result.run.run_id):
        raise ValueError("metadata run must be finished and have a valid ID")
    with writer_lock(raw_root / ".writer.lock"):
        partition = raw_root / "constants" / f"collected_date={result.run.started_at.date()}"
        partition.mkdir(parents=True, exist_ok=True)
        destination = partition / result.run.run_id
        if destination.exists():
            raise FileExistsError("metadata run already committed")
        staging = partition / f".staging-{uuid.uuid4().hex}"
        staging.mkdir()
        text = (
            json.dumps(result.payloads, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        )
        manifest = {
            "schema_version": 1,
            "run": result.run.as_log_context(),
            "requests": result.requests,
            "payload_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "message": result.message,
        }
        try:
            (staging / "payloads.json").write_text(text, encoding="utf-8")
            (staging / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            os.replace(staging, destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return manifest


def _balanced(values: dict[str, Any]) -> list[int]:
    ids = []
    for key, value in values.items():
        if not isinstance(value, dict) or value.get("balanced") is not True:
            continue
        try:
            identifier = int(key)
        except ValueError as exc:
            raise DataError("invalid balanced mode or lobby ID") from exc
        if identifier < 0:
            raise DataError("invalid balanced mode or lobby ID")
        ids.append(identifier)
    return sorted(ids)


def load_metadata(raw_root: Path) -> dict[str, Any]:
    committed = []
    for folder in (raw_root / "constants").glob("collected_date=*/run_*"):
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["run"]["status"] == "succeeded":
            committed.append((manifest["run"]["finished_at"], folder, manifest))
    if not committed:
        return {"summary": None, "payloads": {}}
    _, folder, manifest = max(committed, key=lambda item: item[0])
    path = folder / "payloads.json"
    payload_bytes = path.read_bytes()
    if hashlib.sha256(payload_bytes).hexdigest() != manifest["payload_sha256"]:
        raise DataError("metadata archive checksum mismatch")
    payloads = json.loads(payload_bytes)
    if (
        manifest["schema_version"] != 1
        or manifest["run"]["run_id"] != folder.name
        or not RUN_ID_PATTERN.fullmatch(folder.name)
        or set(payloads) != set(RESOURCES)
        or any(not isinstance(value, dict) or not value for value in payloads.values())
    ):
        raise DataError("invalid committed metadata archive")
    return {
        "summary": {
            "source_run_id": folder.name,
            "captured_at": manifest["run"]["finished_at"],
            "raw_path": str(path.relative_to(raw_root)),
            "raw_sha256": manifest["payload_sha256"],
            "heroes_count": len(payloads["heroes"]),
            "items_count": len(payloads["items"]),
            "balanced_game_modes": _balanced(payloads["game_mode"]),
            "balanced_lobby_types": _balanced(payloads["lobby_type"]),
        },
        "payloads": payloads,
    }
