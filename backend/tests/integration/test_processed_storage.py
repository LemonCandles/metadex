"""Raw-to-processed local replay without OpenDota or a DuckDB catalog."""

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from app.analytics.normalize import normalize
from app.collectors.public_matches import CollectionResult
from app.core.runs import RunRecord, RunStatus
from app.storage.processed import persist_normalized, process_raw_run
from app.storage.raw import persist_collection

pytestmark = pytest.mark.integration


def test_process_raw_run_writes_joinable_parquet_and_repeat_is_identical(
    tmp_path: Path, load_opendota_fixture
):
    sample = load_opendota_fixture("public_matches_high_skill.json")[:2]
    run = RunRecord(operation="collect_public_matches", requested_count=2)
    run.received_count = 2
    run.processed_count = 2
    run.finish(RunStatus.SUCCEEDED)
    result = CollectionResult(
        run=run,
        matches=sample,
        discarded_count=0,
        pages=1,
        message="requested sample collected",
        source_pages=[
            {
                "requested_at": "2026-09-25T00:00:00Z",
                "status_code": 200,
                "parameters": {"min_rank": 70},
                "received_count": 2,
            }
        ],
        match_pages={match["match_id"]: 0 for match in sample},
    )
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    persist_collection(raw, result, max_pages=1)
    report = process_raw_run(raw, processed, run.run_id)
    folder = processed / "public_matches" / run.run_id
    assert report["accepted_matches"] == 2
    assert report["accepted_match_players"] == 20
    assert report["accepted_player_items"] == 0
    assert json.loads((folder / "quality.json").read_text()) == report
    matches = pq.read_table(folder / "matches.parquet").to_pylist()
    players = pq.read_table(folder / "match_players.parquet").to_pylist()
    items = pq.read_table(folder / "player_items.parquet").to_pylist()
    assert {row["match_id"] for row in players} == {row["match_id"] for row in matches}
    winner_by_match = {row["match_id"]: row["radiant_win"] for row in matches}
    assert all(
        row["won"] == (winner_by_match[row["match_id"]] == (row["team"] == "radiant"))
        for row in players
    )
    assert items == []
    before = {path.name: path.read_bytes() for path in folder.iterdir()}
    assert process_raw_run(raw, processed, run.run_id) == report
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == before


def test_detail_rows_can_be_persisted_with_item_times(tmp_path: Path, load_opendota_fixture):
    detail = load_opendota_fixture("match_detail_parsed.json")
    report = persist_normalized(tmp_path, "run_detail_fixture", normalize([detail]))
    folder = tmp_path / "public_matches" / "run_detail_fixture"
    players = pq.read_table(folder / "match_players.parquet").to_pylist()
    items = pq.read_table(folder / "player_items.parquet").to_pylist()
    assert report["accepted_matches"] == 1
    assert len(players) == 10
    assert {row["player_slot"] for row in players} == {*range(5), *range(128, 133)}
    assert all(
        (row["match_id"], row["player_slot"])
        in {(player["match_id"], player["player_slot"]) for player in players}
        for row in items
    )
    assert any(row["purchase_time_seconds"] == -50 for row in items)
