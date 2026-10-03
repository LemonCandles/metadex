"""Offline evidence for the daily job, quality gate and recovery tooling."""

from contextlib import closing
from datetime import timedelta
from pathlib import Path

import duckdb
import httpx
import pytest

from app.collectors.opendota import OpenDotaClient
from app.core.clock import utc_now
from app.core.config import Settings
from app.core.paths import get_data_paths
from app.operations.daily import run_daily
from app.operations.maintenance import backup_catalog, prune_versions
from app.operations.monitor import check_status
from app.pipeline.runner import run_pipeline
from app.storage.catalog import current_version, rebuild_catalog
from app.storage.locking import WriterBusyError
from app.storage.raw import list_run_paths

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        duckdb_path=tmp_path / "data" / "metadex.duckdb",
        opendota_base_url="https://offline.example.test/api",
    )


async def _daily(settings, sample):
    async with OpenDotaClient(
        settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=sample)),
    ) as client:
        return await run_daily(settings, count=len(sample), max_pages=1, client=client)


async def test_two_daily_updates_deduplicate_and_report_stale_source(
    settings, load_opendota_fixture
):
    sample = load_opendota_fixture("public_matches_high_skill.json")[:2]
    first = await _daily(settings, sample)
    second = await _daily(settings, sample)
    assert first["status"] == second["status"] == "succeeded"
    assert first["version_id"] != second["version_id"]
    assert second["counts"]["raw_matches"] == 2
    assert [item["code"] for item in second["alerts"]] == ["no_new_matches"]
    paths = get_data_paths(settings)
    assert len(list_run_paths(paths.raw)) == 2
    assert "no_new_matches" in [item["code"] for item in check_status(settings)["alerts"]]
    stale = check_status(settings, now=utc_now() + timedelta(days=2))
    assert "publication_stale" in [item["code"] for item in stale["alerts"]]


async def test_quality_failure_preserves_previous_publication_and_alerts(
    settings, load_opendota_fixture
):
    sample = load_opendota_fixture("public_matches_high_skill.json")[:1]
    first = await _daily(settings, sample)
    bad = {"match_id": 999_999_999, "start_time": 1, "radiant_win": True}
    async with OpenDotaClient(
        settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[bad])),
    ) as client:
        second = await run_daily(settings, count=1, max_pages=1, client=client)
    assert second["status"] == "failed"
    assert second["stage"] == "aggregate"
    assert second["alerts"][0]["code"] == "daily_pipeline_failed"
    assert check_status(settings)["status"] == "alert"
    with closing(duckdb.connect(str(settings.duckdb_path), read_only=True)) as connection:
        assert current_version(connection) == first["version_id"]
        assert connection.execute("SELECT count(*) FROM matches").fetchone() == (1,)


async def test_daily_retries_transient_writer_contention(
    settings, load_opendota_fixture, monkeypatch
):
    import app.operations.daily as daily

    original = daily.run_pipeline
    attempts = 0

    async def flaky_pipeline(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise WriterBusyError("another data writer is active")
        return await original(*args, **kwargs)

    async def no_sleep(_delay):
        pass

    monkeypatch.setattr(daily, "run_pipeline", flaky_pipeline)
    monkeypatch.setattr(daily.asyncio, "sleep", no_sleep)
    sample = load_opendota_fixture("public_matches_high_skill.json")[:1]
    status = await _daily(settings, sample)
    assert status["status"] == "succeeded"
    assert status["scheduler_attempts"] == 2


async def test_backup_and_retention_keep_raw_and_rebuild(settings, load_opendota_fixture, tmp_path):
    sample = load_opendota_fixture("public_matches_high_skill.json")[:1]
    await _daily(settings, sample)
    await run_pipeline(settings)
    await run_pipeline(settings)
    paths = get_data_paths(settings)
    raw_before = len(list_run_paths(paths.raw))
    backup = backup_catalog(settings, tmp_path / "backup.duckdb")
    assert backup["version_id"] is not None
    assert Path(backup["catalog_backup"]).is_file()
    future = utc_now() + timedelta(days=40)
    preview = prune_versions(settings, now=future)
    assert len(preview["candidates"]) == 1
    assert Path(paths.processed / "versions" / preview["candidates"][0]).is_dir()
    applied = prune_versions(settings, now=future, apply=True)
    assert applied["candidates"] == preview["candidates"]
    assert len(list_run_paths(paths.raw)) == raw_before
    rebuilt = rebuild_catalog(paths)
    assert rebuilt["restored_versions"] == 2
    assert rebuilt["version_id"] == backup["version_id"]
