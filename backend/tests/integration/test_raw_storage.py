"""Persist and reconstruct collected matches without network access."""

import json
from pathlib import Path

import duckdb
import httpx
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.collectors.opendota import OpenDotaClient
from app.collectors.public_matches import collect_public_matches
from app.core.config import Settings
from app.storage.raw import list_partitions, list_runs, persist_collection, read_run

pytestmark = pytest.mark.integration


async def no_sleep(_seconds: float) -> None:
    pass


@pytest.mark.asyncio
async def test_repeat_collection_is_deduplicated_and_reconstructable(
    tmp_path: Path, load_opendota_fixture
) -> None:
    sample = load_opendota_fixture("public_matches_high_skill.json")[:2]

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sample)

    settings = Settings(_env_file=None, opendota_base_url="https://offline.example.test/api")
    raw = tmp_path / "raw"
    for expected_new in (2, 0):
        async with OpenDotaClient(
            settings, transport=httpx.MockTransport(respond), sleep=no_sleep
        ) as client:
            result = await collect_public_matches(client, count=2, max_pages=1)
        manifest = persist_collection(raw, result, max_pages=1)
        assert manifest["volumes"] == {
            "received": 2,
            "selected": 2,
            "discarded": 0,
            "new": expected_new,
            "existing": 2 - expected_new,
        }
        assert manifest["parameters"] == {"min_rank": 70, "count": 2, "max_pages": 1}
        saved_manifest, restored = read_run(raw, result.run.run_id)
        assert saved_manifest == manifest
        assert restored == sample
    assert len(list_runs(raw)) == 2
    assert len(list_partitions(raw)) == 1
    files = list(raw.rglob("matches.parquet"))
    assert duckdb.sql(
        f"SELECT count(*), count(DISTINCT match_id) FROM read_parquet('{raw}/**/*.parquet')"
    ).fetchone() == (2, 2)
    frames = [pd.read_parquet(path) for path in files]
    assert sum(len(frame) for frame in frames) == 2
    populated = next(frame for frame in frames if not frame.empty)
    assert json.loads(populated.iloc[0]["payload_json"]) == sample[0]
    assert populated["match_id"].dtype.kind == "i"


@pytest.mark.asyncio
async def test_write_failure_leaves_no_committed_run(tmp_path: Path, monkeypatch) -> None:
    import app.storage.raw as storage

    settings = Settings(_env_file=None, opendota_base_url="https://offline.example.test/api")
    async with OpenDotaClient(
        settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[{"match_id": 42}])),
    ) as client:
        result = await collect_public_matches(client, count=1, max_pages=1)

    def fail(*_args, **_kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr(storage.pq, "write_table", fail)
    raw = tmp_path / "raw"
    with pytest.raises(OSError, match="disk failure"):
        persist_collection(raw, result, max_pages=1)
    assert list_runs(raw) == []
    assert list(raw.rglob(".staging-*")) == []


@pytest.mark.asyncio
async def test_read_detects_payload_corruption(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, opendota_base_url="https://offline.example.test/api")
    async with OpenDotaClient(
        settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[{"match_id": 42}])),
    ) as client:
        result = await collect_public_matches(client, count=1, max_pages=1)
    raw = tmp_path / "raw"
    persist_collection(raw, result, max_pages=1)
    path = next(raw.rglob("matches.parquet"))
    table = pq.read_table(path)
    row = table.to_pylist()[0]
    row["payload_json"] = '{"match_id":43}'
    pq.write_table(pa.Table.from_pylist([row], schema=table.schema), path)
    with pytest.raises(ValueError, match="hash mismatch"):
        read_run(raw, result.run.run_id)


@pytest.mark.asyncio
async def test_page_cursor_and_partial_error_are_archived(tmp_path: Path) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json=[{"match_id": 9, "extra": {"kept": None}}])
        assert request.url.params["less_than_match_id"] == "9"
        return httpx.Response(400)

    settings = Settings(_env_file=None, opendota_base_url="https://offline.example.test/api")
    async with OpenDotaClient(
        settings, transport=httpx.MockTransport(respond), sleep=no_sleep
    ) as client:
        result = await collect_public_matches(client, count=2, max_pages=2)
    raw = tmp_path / "raw"
    manifest = persist_collection(raw, result, max_pages=2)
    assert manifest["run"]["status"] == "partial"
    assert manifest["errors"] == ["OpenDota returned HTTP 400"]
    assert manifest["pages"][0]["parameters"] == {"min_rank": 70}
    assert manifest["volumes"] == {
        "received": 1,
        "selected": 1,
        "discarded": 0,
        "new": 1,
        "existing": 0,
    }
    _, matches = read_run(raw, result.run.run_id)
    assert matches == [{"match_id": 9, "extra": {"kept": None}}]


@pytest.mark.asyncio
async def test_success_after_retries_has_no_error_message(tmp_path: Path) -> None:
    calls = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=[{"match_id": 42}])

    settings = Settings(_env_file=None, opendota_base_url="https://offline.example.test/api")
    async with OpenDotaClient(
        settings, transport=httpx.MockTransport(respond), sleep=no_sleep
    ) as client:
        result = await collect_public_matches(client, count=1, max_pages=1)
    manifest = persist_collection(tmp_path / "raw", result, max_pages=1)
    assert manifest["run"]["status"] == "succeeded"
    assert manifest["run"]["failures"] == 2
    assert manifest["errors"] == []
