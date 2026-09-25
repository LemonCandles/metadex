"""Write normalized Parquet datasets and their quality report as one local run."""

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.analytics.normalize import Normalized, normalize
from app.storage.raw import DATASET, RUN_ID_PATTERN, read_run

NORMALIZER_VERSION = 1
MATCHES_SCHEMA = pa.schema(
    [
        ("match_id", pa.int64()),
        ("started_at_utc", pa.timestamp("s", tz="UTC")),
        ("duration_seconds", pa.int32()),
        ("radiant_win", pa.bool_()),
        ("game_mode", pa.int32()),
        ("lobby_type", pa.int32()),
        ("avg_rank_tier", pa.float64()),
        ("num_rank_tier", pa.int8()),
        ("cluster", pa.int32()),
        ("source_kind", pa.string()),
    ]
)
MATCH_PLAYERS_SCHEMA = pa.schema(
    [
        ("match_id", pa.int64()),
        ("player_slot", pa.int16()),
        ("team_index", pa.int8()),
        ("hero_id", pa.int32()),
        ("team", pa.string()),
        ("won", pa.bool_()),
        ("position", pa.int8()),
        ("lane_role", pa.int8()),
    ]
)
PLAYER_ITEMS_SCHEMA = pa.schema(
    [
        ("match_id", pa.int64()),
        ("player_slot", pa.int16()),
        ("item_id", pa.int32()),
        ("item_key", pa.string()),
        ("source_kind", pa.string()),
        ("slot", pa.string()),
        ("purchase_index", pa.int32()),
        ("purchase_time_seconds", pa.int32()),
    ]
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def persist_normalized(processed_root: Path, run_id: str, result: Normalized) -> dict[str, Any]:
    """Commit one deterministic version; refuse a changed result under the same run ID."""
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("invalid run_id")
    base = processed_root / DATASET
    destination = base / run_id
    base.mkdir(parents=True, exist_ok=True)
    staging = base / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    report = {
        "schema_version": 1,
        "normalizer_version": NORMALIZER_VERSION,
        "source_run_id": run_id,
        **result.quality,
    }
    try:
        for filename, rows, schema in (
            ("matches.parquet", result.matches, MATCHES_SCHEMA),
            ("match_players.parquet", result.match_players, MATCH_PLAYERS_SCHEMA),
            ("player_items.parquet", result.player_items, PLAYER_ITEMS_SCHEMA),
        ):
            pq.write_table(pa.Table.from_pylist(rows, schema=schema), staging / filename)
        (staging / "quality.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        if destination.exists():
            filenames = (
                "matches.parquet",
                "match_players.parquet",
                "player_items.parquet",
                "quality.json",
            )
            if any(
                not (destination / name).is_file()
                or _sha256(staging / name) != _sha256(destination / name)
                for name in filenames
            ):
                raise ValueError(f"processed run differs from existing output: {run_id}")
            return report
        os.replace(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return report


def process_raw_run(raw_root: Path, processed_root: Path, run_id: str) -> dict[str, Any]:
    """Rebuild a committed raw sample locally and write its normalized entities."""
    _manifest, payloads = read_run(raw_root, run_id)
    return persist_normalized(processed_root, run_id, normalize(payloads))
