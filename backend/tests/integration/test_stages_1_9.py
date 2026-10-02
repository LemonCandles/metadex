"""Exercise the catalog, detail enrichment, daily publication and HTTP integration."""

import json
from contextlib import closing
from copy import deepcopy
from datetime import date

import duckdb
import httpx
import pyarrow.parquet as pq
import pytest

from app.analytics.heroes import HeroFilters, HeroPeriod
from app.analytics.queries import main as query_main
from app.collectors.match_details import collect_match_details
from app.collectors.metadata import collect_metadata
from app.collectors.opendota import OpenDotaClient
from app.core.config import Settings
from app.core.errors import DataError
from app.core.paths import get_data_paths
from app.core.runs import RunStatus
from app.main import create_app
from app.pipeline import run_pipeline
from app.storage.catalog import file_sha256, rebuild_catalog
from app.storage.hero_queries import DuckDBHeroStatsRepository
from app.storage.metadata import load_metadata, persist_metadata
from app.storage.raw import list_run_paths, persist_collection, read_run

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def no_sleep(_seconds):
    pass


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None, data_dir=tmp_path / "data", duckdb_path=tmp_path / "data" / "metadex.duckdb"
    )


@pytest.fixture
def constants(load_opendota_fixture):
    values = load_opendota_fixture("constants.json")
    return {
        "heroes": values["heroes"],
        "items": values["items"],
        "game_mode": values["game_modes"],
        "lobby_type": values["lobby_types"],
    }


async def archive_metadata(settings, constants):
    async with OpenDotaClient(
        settings,
        sleep=no_sleep,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=constants[request.url.path.rsplit("/", 1)[1]])
        ),
    ) as client:
        result = await collect_metadata(client)
    assert result.run.status is RunStatus.SUCCEEDED
    persist_metadata(get_data_paths(settings).raw, result)
    return result


async def test_live_shaped_details_merge_without_losing_public_rank_or_raw_payload(
    settings, constants, load_opendota_fixture
):
    await archive_metadata(settings, constants)
    detail = load_opendota_fixture("match_detail_parsed.json")
    public = {key: value for key, value in detail.items() if key != "players"}
    public.update(avg_rank_tier=75, num_rank_tier=8)
    detail.pop("avg_rank_tier", None)
    detail.pop("num_rank_tier", None)
    requests = []

    def handle(request):
        requests.append(request.url.path)
        return httpx.Response(
            200, json=[public] if request.url.path.endswith("publicMatches") else detail
        )

    async with OpenDotaClient(
        settings, sleep=no_sleep, transport=httpx.MockTransport(handle)
    ) as client:
        result = await run_pipeline(
            settings, collect=True, count=1, max_pages=1, with_details=True, client=client
        )
    assert result.run.status is RunStatus.SUCCEEDED, result.message
    assert requests == ["/api/publicMatches", f"/api/matches/{detail['match_id']}"]
    assert result.counts["raw_matches"] == result.counts["matches"] == 1
    assert result.counts["player_items"] > 0
    paths = get_data_paths(settings)
    sources = list_run_paths(paths.raw)
    assert len(sources) == 2
    archived = [read_run(paths.raw, folder.name)[1][0] for folder in sources]
    assert public in archived and detail in archived
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert connection.execute(
            "SELECT avg_rank_tier, num_rank_tier FROM matches"
        ).fetchone() == (75, 8)
        assert connection.execute("SELECT count(*) FROM hero_daily_stats").fetchone() == (10,)
        assert connection.execute(
            "SELECT sum(picks), sum(wins) FROM hero_daily_stats"
        ).fetchone() == (10, 5)
    again = await run_pipeline(settings)
    for name in ("matches", "match_players", "player_items", "hero_daily_stats"):
        assert file_sha256(
            paths.processed / "versions" / result.version_id / f"{name}.parquet"
        ) == (file_sha256(paths.processed / "versions" / again.version_id / f"{name}.parquet"))


async def test_named_cohort_uses_pinned_catalog_and_matches_denominator(
    settings, constants, load_opendota_fixture
):
    await archive_metadata(settings, constants)
    sample = [
        deepcopy(load_opendota_fixture("public_matches_high_skill.json")[0]) for _ in range(5)
    ]
    for index, match in enumerate(sample):
        match.update(
            match_id=1000 + index, avg_rank_tier=75, num_rank_tier=5, game_mode=22, lobby_type=7
        )
    sample[1]["num_rank_tier"] = 4
    sample[2]["avg_rank_tier"] = 69
    sample[3]["game_mode"] = 23
    sample[4]["lobby_type"] = 2
    async with OpenDotaClient(
        settings,
        sleep=no_sleep,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=sample)),
    ) as client:
        result = await run_pipeline(settings, collect=True, count=5, max_pages=1, client=client)
    assert result.run.status is RunStatus.SUCCEEDED
    params = {
        "period_start": "2026-09-18",
        "period_end": "2026-09-19",
        "cohort": "high_skill_public_v1",
        "include_below_min": "true",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as api:
        response = await api.get("/api/v1/meta/heroes", params=params)
    assert response.status_code == 200
    assert response.json()["sample"]["matches"] == 1
    assert response.json()["filters"]["cohort"] == "high_skill_public_v1"
    assert all(hero["pick_rate"] == 1 for hero in response.json()["heroes"])
    # A newly captured catalog affects the next publication, never an existing snapshot.
    constants["game_mode"]["22"]["balanced"] = False
    await archive_metadata(settings, constants)
    repo = DuckDBHeroStatsRepository(settings.duckdb_path)
    period = HeroPeriod(date(2026, 9, 18), date(2026, 9, 19))
    assert (
        sum(repo.read(period, HeroFilters(cohort="high_skill_public_v1")).match_counts.values())
        == 1
    )
    await run_pipeline(settings)
    assert not repo.read(period, HeroFilters(cohort="high_skill_public_v1")).match_counts


async def test_details_deduplicate_per_source_and_mismatch_fails(settings):
    def handle(request):
        return httpx.Response(200, json={"match_id": int(request.url.path.rsplit("/", 1)[1])})

    async with OpenDotaClient(
        settings, sleep=no_sleep, transport=httpx.MockTransport(handle)
    ) as client:
        first = await collect_match_details(client, [101])
        second = await collect_match_details(client, [101])
    raw = get_data_paths(settings).raw
    assert persist_collection(raw, first, max_pages=1)["volumes"]["new"] == 1
    assert persist_collection(raw, second, max_pages=1)["volumes"]["new"] == 0
    assert read_run(raw, second.run.run_id)[1] == [{"match_id": 101}]
    async with OpenDotaClient(
        settings,
        sleep=no_sleep,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"match_id": 102})),
    ) as client:
        failed = await collect_match_details(client, [101])
    assert failed.run.status is RunStatus.FAILED
    assert failed.run.attempts == failed.run.failures == 1


async def test_partial_details_do_not_replace_publication(settings, load_opendota_fixture):
    sample = load_opendota_fixture("public_matches_high_skill.json")[:1]
    async with OpenDotaClient(
        settings,
        sleep=no_sleep,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=sample)),
    ) as client:
        previous = await run_pipeline(settings, collect=True, count=1, max_pages=1, client=client)
    async with OpenDotaClient(
        settings,
        sleep=no_sleep,
        transport=httpx.MockTransport(
            lambda request: (
                httpx.Response(200, json=sample)
                if request.url.path.endswith("publicMatches")
                else httpx.Response(404)
            )
        ),
    ) as client:
        failed = await run_pipeline(
            settings, collect=True, count=1, max_pages=1, with_details=True, client=client
        )
    assert failed.run.status is RunStatus.FAILED
    assert failed.version_id is None
    repo = DuckDBHeroStatsRepository(settings.duckdb_path)
    assert repo.read(
        HeroPeriod(date(2026, 9, 18), date(2026, 9, 19)), HeroFilters()
    ).version_id == (previous.version_id)


async def test_corrupt_daily_counts_prevent_rebuild_even_with_updated_checksum(
    settings, load_opendota_fixture
):
    sample = load_opendota_fixture("public_matches_high_skill.json")[:1]
    async with OpenDotaClient(
        settings,
        sleep=no_sleep,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=sample)),
    ) as client:
        result = await run_pipeline(settings, collect=True, count=1, max_pages=1, client=client)
    paths = get_data_paths(settings)
    folder = paths.processed / "versions" / result.version_id
    path = folder / "hero_daily_stats.parquet"
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows[0]["wins"] += 1
    import pyarrow as pa

    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    manifest = json.loads((folder / "version.json").read_text())
    manifest["files"][path.name] = file_sha256(path)
    (folder / "version.json").write_text(json.dumps(manifest))
    with pytest.raises(DataError, match="hero_daily_stats"):
        rebuild_catalog(paths)


async def test_legacy_snapshot_remains_readable_and_can_be_rebuilt(settings, load_opendota_fixture):
    sample = load_opendota_fixture("public_matches_high_skill.json")[:1]
    async with OpenDotaClient(
        settings,
        sleep=no_sleep,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=sample)),
    ) as client:
        result = await run_pipeline(settings, collect=True, count=1, max_pages=1, client=client)
    paths = get_data_paths(settings)
    manifest_path = paths.processed / "versions" / result.version_id / "version.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["aggregator_version"] = 1
    for name in ("hero_daily_stats.parquet", "metadata.json", "recommendation_stats.parquet"):
        del manifest["files"][name]
    manifest.pop("metadata")
    manifest_path.write_text(json.dumps(manifest))
    assert rebuild_catalog(paths)["version_id"] == result.version_id
    repo = DuckDBHeroStatsRepository(settings.duckdb_path)
    data = repo.read(HeroPeriod(date(2026, 9, 18), date(2026, 9, 19)), HeroFilters())
    assert len(data.heroes) == 10


async def test_metadata_archive_integrity_and_partial_catalog(settings, constants):
    result = await archive_metadata(settings, constants)
    raw = get_data_paths(settings).raw
    metadata = load_metadata(raw)
    assert metadata["summary"]["source_run_id"] == result.run.run_id
    path = raw / metadata["summary"]["raw_path"]
    path.write_text("{}")
    with pytest.raises(DataError, match="checksum"):
        load_metadata(raw)
    async with OpenDotaClient(
        settings,
        sleep=no_sleep,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json=constants["heroes"], headers={"X-Rate-Limit-Remaining-Minute": "0"}
            )
        ),
    ) as client:
        partial = await collect_metadata(client)
    assert partial.run.status is RunStatus.PARTIAL
    assert partial.run.attempts == 1


async def test_api_cors_health_and_missing_cohort_catalog(settings):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as api:
        response = await api.options(
            "/api/v1/meta/heroes",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
        rejected = await api.options(
            "/health",
            headers={"Origin": "https://unlisted.example", "Access-Control-Request-Method": "GET"},
        )
        assert rejected.status_code == 400
        assert (await api.get("/health")).json() == {"status": "ok"}
        assert (
            await api.get("/api/v1/meta/heroes", params={"cohort": "high_skill_public_v1"})
        ).status_code == 503


async def test_query_cli_reads_publication_and_rejects_invalid_ranges(
    settings, load_opendota_fixture, monkeypatch, capsys
):
    sample = load_opendota_fixture("public_matches_high_skill.json")[:1]
    async with OpenDotaClient(
        settings,
        sleep=no_sleep,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=sample)),
    ) as client:
        await run_pipeline(settings, collect=True, count=1, max_pages=1, client=client)
    monkeypatch.setattr("app.analytics.queries.get_settings", lambda: settings)
    assert (
        query_main(
            [
                "ranking",
                "--period-start",
                "2026-09-18",
                "--period-end",
                "2026-09-19",
                "--include-below-min",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["sample"]["matches"] == 1
    with pytest.raises(SystemExit) as exc:
        query_main(["detail", "1", "--period-start", "2026-09-18"])
    assert exc.value.code == 2
