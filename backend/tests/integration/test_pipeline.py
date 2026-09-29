"""Offline pipeline publication, recovery and failure invariants."""

import json
from contextlib import closing
from pathlib import Path

import duckdb
import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.collectors.opendota import OpenDotaClient
from app.collectors.public_matches import collect_public_matches
from app.core.config import Settings
from app.core.errors import DataError
from app.core.paths import get_data_paths
from app.core.runs import RunStatus
from app.pipeline import PipelineStage, run_pipeline
from app.storage.catalog import current_version, initialize_catalog, rebuild_catalog
from app.storage.locking import WriterBusyError, pipeline_writer_lock
from app.storage.raw import list_runs, persist_collection

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def no_sleep(_seconds: float) -> None:
    pass


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # SQL path escaping and independently configured catalog paths are part of the contract.
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data d'example",
        duckdb_path=tmp_path / "catalog folder" / "metadex.duckdb",
        opendota_base_url="https://offline.example.test/api",
    )


async def archive(settings: Settings, matches: list[dict]) -> str:
    async with OpenDotaClient(
        settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=matches)),
        sleep=no_sleep,
    ) as client:
        result = await collect_public_matches(client, count=len(matches), max_pages=1)
    persist_collection(get_data_paths(settings).raw, result, max_pages=1)
    return result.run.run_id


async def test_full_pipeline_publishes_stable_joinable_parquet_views(
    settings, load_opendota_fixture
):
    sample = load_opendota_fixture("public_matches_high_skill.json")[:2]
    async with OpenDotaClient(
        settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=sample)),
        sleep=no_sleep,
    ) as client:
        result = await run_pipeline(settings, collect=True, count=2, max_pages=1, client=client)
    assert result.run.status is RunStatus.SUCCEEDED, result.message
    assert result.stage is PipelineStage.PUBLISH
    assert result.counts == {"raw_matches": 2, "matches": 2, "match_players": 20, "player_items": 0}
    paths = get_data_paths(settings)
    folder = paths.processed / "versions" / result.version_id
    assert (folder / "published.json").is_file()
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert current_version(connection) == result.version_id
        for name, count in result.counts.items():
            assert connection.execute(f"SELECT count(*) FROM {name}").fetchone() == (count,)
            if name != "raw_matches":
                assert pq.read_table(folder / f"{name}.parquet").num_rows == count
        assert connection.execute("SELECT count(*) FROM collection_runs").fetchone() == (1,)
        assert connection.execute(
            "SELECT status, stage, version_id FROM pipeline_runs"
        ).fetchone() == (
            "succeeded",
            "publish",
            result.version_id,
        )
        assert connection.execute(
            "SELECT count(*) FROM match_players p LEFT JOIN matches m USING (match_id) "
            "WHERE m.match_id IS NULL"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM match_players WHERE player_slot IS NULL"
        ).fetchone() == (20,)
        assert [row[0] for row in connection.execute("DESCRIBE raw_matches").fetchall()] == [
            "match_id",
            "source",
            "endpoint",
            "parameters_json",
            "requested_at",
            "status_code",
            "collected_at",
            "payload_json",
            "payload_sha256",
            "collector_version",
        ]


async def test_reprocess_deduplicates_runs_and_is_reproducible(settings, load_opendota_fixture):
    sample = load_opendota_fixture("public_matches_high_skill.json")[:2]
    first_source = await archive(settings, sample)
    second_source = await archive(settings, sample)
    first = await run_pipeline(settings)
    second = await run_pipeline(settings)
    assert first.run.status is second.run.status is RunStatus.SUCCEEDED
    assert first.version_id != second.version_id
    assert first.source_run_ids == second.source_run_ids == [first_source, second_source]
    assert (
        first.counts
        == second.counts
        == {
            "raw_matches": 2,
            "matches": 2,
            "match_players": 20,
            "player_items": 0,
        }
    )
    paths = get_data_paths(settings)
    for name in ("matches", "match_players", "player_items", "dataset_counts"):
        before = pq.read_table(paths.processed / "versions" / first.version_id / f"{name}.parquet")
        after = pq.read_table(paths.processed / "versions" / second.version_id / f"{name}.parquet")
        assert before.equals(after)
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert connection.execute(
            "SELECT version_id, status FROM dataset_versions ORDER BY created_at"
        ).fetchall() == [(first.version_id, "superseded"), (second.version_id, "published")]


async def test_detail_items_are_published_with_valid_participant_references(
    settings,
    load_opendota_fixture,
):
    detail = load_opendota_fixture("match_detail_parsed.json")
    await archive(settings, [detail])
    result = await run_pipeline(settings)
    assert result.run.status is RunStatus.SUCCEEDED, result.message
    assert result.counts["player_items"] > 0
    paths = get_data_paths(settings)
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM player_items i LEFT JOIN match_players p "
            "USING (match_id, player_slot) WHERE p.match_id IS NULL"
        ).fetchone() == (0,)
        expected_times = sorted(
            purchase["time"]
            for player in detail["players"]
            for purchase in player.get("purchase_log", [])
        )
        observed_times = [
            row[0]
            for row in connection.execute(
                "SELECT purchase_time_seconds FROM player_items WHERE source_kind='purchase_log' "
                "ORDER BY purchase_time_seconds"
            ).fetchall()
        ]
        assert observed_times == expected_times


async def test_rejections_are_reported_and_only_valid_matches_are_published(
    settings,
    load_opendota_fixture,
):
    valid = load_opendota_fixture("public_matches_high_skill.json")[:1]
    await archive(settings, [*valid, {"match_id": 123}])
    result = await run_pipeline(settings)
    assert result.run.status is RunStatus.SUCCEEDED, result.message
    assert result.quality["rejected_matches"] == 1
    assert result.counts == {"raw_matches": 2, "matches": 1, "match_players": 10, "player_items": 0}


async def test_broken_participant_integrity_prevents_publication(
    settings,
    load_opendota_fixture,
    monkeypatch,
):
    import app.pipeline.runner as runner

    await archive(settings, load_opendota_fixture("public_matches_high_skill.json")[:1])
    previous = await run_pipeline(settings)
    original = runner.write_normalized_tables

    def omit_participant(folder, normalized):
        original(folder, normalized)
        path = folder / "match_players.parquet"
        table = pq.read_table(path)
        pq.write_table(table.slice(1), path)

    monkeypatch.setattr(runner, "write_normalized_tables", omit_participant)
    failed = await run_pipeline(settings)
    assert failed.run.status is RunStatus.FAILED
    assert failed.stage is PipelineStage.AGGREGATE
    assert "ten distinct participants" in failed.message
    paths = get_data_paths(settings)
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert current_version(connection) == previous.version_id
        assert connection.execute("SELECT count(*) FROM match_players").fetchone() == (10,)


async def test_partial_sample_can_be_explicitly_reprocessed(settings, load_opendota_fixture):
    sample = load_opendota_fixture("public_matches_high_skill.json")[:1]
    async with OpenDotaClient(
        settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=sample)),
        sleep=no_sleep,
    ) as client:
        partial = await run_pipeline(settings, collect=True, count=2, max_pages=1, client=client)
    assert partial.run.status is RunStatus.PARTIAL
    assert partial.version_id is None
    result = await run_pipeline(settings)
    assert result.run.status is RunStatus.SUCCEEDED, result.message
    assert result.counts["matches"] == 1


async def test_aggregation_failure_keeps_current_version_and_cleans_staging(
    settings,
    load_opendota_fixture,
    monkeypatch,
):
    import app.pipeline.runner as runner

    sample = load_opendota_fixture("public_matches_high_skill.json")
    await archive(settings, sample[:1])
    first = await run_pipeline(settings)
    await archive(settings, sample[1:2])

    def fail(*_args):
        raise OSError("aggregation disk failure")

    monkeypatch.setattr(runner, "aggregate_dataset", fail)
    failed = await run_pipeline(settings)
    assert failed.run.status is RunStatus.FAILED
    assert failed.stage is PipelineStage.AGGREGATE
    assert failed.version_id is None
    paths = get_data_paths(settings)
    assert list((paths.processed / "versions").glob(".staging-*")) == []
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert current_version(connection) == first.version_id
        assert connection.execute("SELECT count(*) FROM raw_matches").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM matches").fetchone() == (1,)
        assert connection.execute(
            "SELECT status, stage, error FROM pipeline_runs WHERE run_id=?",
            [failed.run.run_id],
        ).fetchone() == ("failed", "aggregate", "aggregation disk failure")


async def test_publication_failure_rolls_back_all_views_and_receipt(
    settings,
    load_opendota_fixture,
    monkeypatch,
):
    import app.storage.catalog as catalog

    sample = load_opendota_fixture("public_matches_high_skill.json")
    await archive(settings, sample[:1])
    first = await run_pipeline(settings)
    await archive(settings, sample[1:2])
    original = catalog.write_json_atomic

    def fail_after_receipt(path, value):
        original(path, value)
        raise OSError("publication interrupted")

    monkeypatch.setattr(catalog, "write_json_atomic", fail_after_receipt)
    failed = await run_pipeline(settings)
    assert failed.run.status is RunStatus.FAILED
    assert failed.stage is PipelineStage.PUBLISH
    paths = get_data_paths(settings)
    assert not (paths.processed / "versions" / failed.run.run_id / "published.json").exists()
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert current_version(connection) == first.version_id
        assert dict(connection.execute("SELECT * FROM dataset_counts").fetchall()) == first.counts
        assert connection.execute("SELECT count(*) FROM dataset_versions").fetchone() == (1,)
    monkeypatch.setattr(catalog, "write_json_atomic", original)
    assert rebuild_catalog(paths)["version_id"] == first.version_id


async def test_catalog_rebuild_recovers_latest_publication_and_ignores_unfinished_output(
    settings,
    load_opendota_fixture,
):
    sample = load_opendota_fixture("public_matches_high_skill.json")[:2]
    await archive(settings, sample[:1])
    first = await run_pipeline(settings)
    await archive(settings, sample[1:])
    latest = await run_pipeline(settings)
    assert latest.run.status is RunStatus.SUCCEEDED
    paths = get_data_paths(settings)
    (paths.processed / "versions" / ".staging-unfinished").mkdir()
    (paths.processed / "versions" / "run_unpublished").mkdir()
    # A missing catalog can be recreated without a collection or normalization pass.
    paths.duckdb.unlink()
    restored = rebuild_catalog(paths)
    assert restored["version_id"] == latest.version_id
    assert restored["restored_versions"] == 2
    assert restored["counts"] == latest.counts
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert connection.execute("SELECT count(*) FROM pipeline_runs").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM collection_runs").fetchone() == (2,)
        assert connection.execute(
            "SELECT status FROM dataset_versions WHERE version_id=?",
            [first.version_id],
        ).fetchone() == ("superseded",)


@pytest.mark.parametrize("response", [httpx.Response(200, json=[]), httpx.Response(400)])
async def test_incomplete_collection_is_archived_without_publishing(
    settings,
    load_opendota_fixture,
    response,
):
    await archive(settings, load_opendota_fixture("public_matches_high_skill.json")[:1])
    previous = await run_pipeline(settings)
    async with OpenDotaClient(
        settings,
        transport=httpx.MockTransport(lambda _: response),
        sleep=no_sleep,
    ) as client:
        result = await run_pipeline(settings, collect=True, count=2, max_pages=1, client=client)
    assert result.run.status in (RunStatus.PARTIAL, RunStatus.FAILED)
    assert result.stage is PipelineStage.COLLECT
    assert result.version_id is None
    paths = get_data_paths(settings)
    assert len(list_runs(paths.raw)) == 2
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert current_version(connection) == previous.version_id
        assert connection.execute("SELECT count(*) FROM matches").fetchone() == (1,)


async def test_empty_or_invalid_input_is_recorded_without_publishing(settings):
    empty = await run_pipeline(settings)
    assert empty.run.status is RunStatus.FAILED
    assert empty.stage is PipelineStage.VALIDATE
    await archive(settings, [{"match_id": 123}])
    invalid = await run_pipeline(settings)
    assert invalid.run.status is RunStatus.FAILED
    assert invalid.stage is PipelineStage.NORMALIZE
    assert invalid.quality["rejected_matches"] == 1
    paths = get_data_paths(settings)
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert current_version(connection) is None
        assert connection.execute("SELECT count(*) FROM matches").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM pipeline_runs WHERE status='failed'"
        ).fetchone() == (2,)


async def test_corrupt_raw_input_does_not_replace_publication(settings, load_opendota_fixture):
    await archive(settings, load_opendota_fixture("public_matches_high_skill.json")[:1])
    previous = await run_pipeline(settings)
    paths = get_data_paths(settings)
    path = next(paths.raw.rglob("matches.parquet"))
    table = pq.ParquetFile(path).read()
    row = table.to_pylist()[0]
    row["payload_json"] = "{}"
    pq.write_table(pa.Table.from_pylist([row], schema=table.schema), path)
    failed = await run_pipeline(settings)
    assert failed.run.status is RunStatus.FAILED
    assert failed.stage is PipelineStage.VALIDATE
    assert "hash mismatch" in failed.message
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert current_version(connection) == previous.version_id
        assert connection.execute("SELECT count(*) FROM matches").fetchone() == (1,)


async def test_rebuild_checks_snapshot_integrity_before_changing_current_views(
    settings,
    load_opendota_fixture,
):
    await archive(settings, load_opendota_fixture("public_matches_high_skill.json")[:1])
    previous = await run_pipeline(settings)
    paths = get_data_paths(settings)
    manifest_path = paths.processed / "versions" / previous.version_id / "version.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["counts"]["matches"] = 99
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(DataError, match="counts"):
        rebuild_catalog(paths)
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert current_version(connection) == previous.version_id
        assert connection.execute("SELECT count(*) FROM matches").fetchone() == (1,)


async def test_typed_empty_catalog_and_raw_only_rebuild(settings, load_opendota_fixture):
    paths = get_data_paths(settings)
    initial = rebuild_catalog(paths)
    assert initial["version_id"] is None
    assert initial["counts"] == {}
    await archive(settings, load_opendota_fixture("public_matches_high_skill.json")[:1])
    restored = rebuild_catalog(paths)
    assert restored["version_id"] is None
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert connection.execute("SELECT count(*) FROM raw_matches").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM matches").fetchone() == (0,)
        assert connection.execute("DESCRIBE player_items").fetchall()[0][:2] == (
            "match_id",
            "BIGINT",
        )


async def test_another_async_writer_cannot_inherit_parent_lock(settings):
    import asyncio

    paths = get_data_paths(settings)
    with pipeline_writer_lock(paths), pytest.raises(WriterBusyError):
        await asyncio.create_task(run_pipeline(settings))
    assert (await run_pipeline(settings)).run.status is RunStatus.FAILED


async def test_stale_running_record_is_closed_when_next_writer_starts(settings):
    paths = get_data_paths(settings)
    paths.duckdb.parent.mkdir(parents=True)
    with closing(duckdb.connect(str(paths.duckdb))) as connection:
        initialize_catalog(connection)
        connection.execute(
            """INSERT INTO pipeline_runs VALUES (
            'run_interrupted', 'pipeline_reprocess', 'normalize', 'running', now(), NULL, NULL,
            0, 0, 0, 0, 0, '[]', NULL, NULL)""",
        )
    await run_pipeline(settings)
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert connection.execute(
            "SELECT status, error FROM pipeline_runs WHERE run_id='run_interrupted'"
        ).fetchone() == ("failed", "previous writer was interrupted")
