"""Raw -> normalized -> contextual Parquet -> HTTP, using offline source responses."""

import hashlib
import json
from contextlib import closing
from copy import deepcopy

import duckdb
import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.collectors.metadata import collect_metadata
from app.collectors.opendota import OpenDotaClient
from app.core.config import Settings
from app.core.paths import get_data_paths
from app.core.runs import RunStatus
from app.main import create_app
from app.pipeline import run_pipeline
from app.storage.catalog import current_version, rebuild_catalog
from app.storage.metadata import persist_metadata

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
PERIOD = {"period_start": "2026-09-18", "period_end": "2026-09-19"}


async def no_sleep(_seconds):
    pass


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data d'example",
        duckdb_path=tmp_path / "catalog" / "meta.duckdb",
        min_sample_size=2,
    )


async def publish(settings, details):
    public = []
    for detail in details:
        match = {key: value for key, value in detail.items() if key != "players"}
        for team, radiant in (("radiant", True), ("dire", False)):
            match[f"{team}_team"] = [
                player["hero_id"]
                for player in detail["players"]
                if (player["player_slot"] < 128) == radiant
            ]
        public.append(match)
    by_id = {detail["match_id"]: detail for detail in details}

    def source(request):
        if request.url.path.endswith("/publicMatches"):
            return httpx.Response(200, json=public)
        return httpx.Response(200, json=by_id[int(request.url.path.rsplit("/", 1)[1])])

    async with OpenDotaClient(
        settings, transport=httpx.MockTransport(source), sleep=no_sleep
    ) as client:
        result = await run_pipeline(
            settings, collect=True, count=len(public), max_pages=1, with_details=True, client=client
        )
    assert result.run.status is RunStatus.SUCCEEDED, result.message
    return result


@pytest.fixture
def synthetic_details(load_opendota_fixture):
    template = load_opendota_fixture("match_detail_parsed.json")
    details = []
    for index, (duration, won, rank) in enumerate(
        [
            (1500, True, 72),
            (1800, False, 72),
            (2700, True, 80),
            (2800, True, 80),
        ]
    ):
        detail = deepcopy(template)
        detail.update(
            match_id=30_000 + index,
            duration=duration,
            radiant_win=won,
            avg_rank_tier=rank,
            num_rank_tier=8,
        )
        for player in detail["players"]:
            player["win"] = int(won == (player["player_slot"] < 128))
            player["purchase_log"] = []
        detail["players"][0]["purchase_log"] = [
            {"key": "branches", "time": -40},
            {"key": "branches", "time": -30},
            {"key": "boots", "time": 100},
            {"key": "boots", "time": 200},
            {"key": "blink", "time": 1000},
            {"key": "recipe_boots", "time": 10},
            {"key": "late_item", "time": 2400},
            {"key": "after_match", "time": 99999},
        ]
        details.append(detail)
    return details


async def request(settings, route, **params):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as api:
        return await api.get(f"/api/v1/recommendations/{route}", params={**PERIOD, **params})


async def test_purchase_stats_match_http_and_exclude_duplicates_inventory_recipes_and_late(
    settings,
    synthetic_details,
):
    result = await publish(settings, synthetic_details)
    response = await request(settings, "items", hero_id=93)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version_id"] == result.version_id
    assert body["sample"]["matches"] == 4
    assert [item["item_key"] for item in body["recommendations"]] == ["blink", "boots", "branches"]
    for item in body["recommendations"]:
        assert (item["sample_size"], item["wins"], item["losses"], item["win_rate"]) == (
            4,
            3,
            1,
            0.75,
        )
        assert item["context_sample_size"] == 4
    boots = body["recommendations"][1]
    assert boots["mean_purchase_time_seconds"] == 100
    assert boots["mean_purchase_index"] == 2
    paths = get_data_paths(settings)
    with closing(duckdb.connect(str(paths.duckdb), read_only=True)) as connection:
        assert connection.execute(
            "SELECT sum(sample_size), sum(wins) FROM recommendation_stats "
            "WHERE kind='item' AND item_key='boots'"
        ).fetchone() == (4, 3)
        assert connection.execute(
            "SELECT sum(sample_size) FROM recommendation_stats WHERE kind='hero'"
        ).fetchone() == (40,)
        assert connection.execute(
            "SELECT count(*) FROM recommendation_stats "
            "WHERE item_key IN ('recipe_boots', 'after_match')"
        ).fetchone() == (0,)
    assert (
        pq.read_table(
            paths.processed / "versions" / result.version_id / "recommendation_stats.parquet"
        ).num_rows
        > 0
    )


@pytest.mark.parametrize(
    ("params", "keys", "size", "wins"),
    [
        ({"duration_min_seconds": 2000}, ["blink", "boots", "branches"], 2, 2),
        ({"duration_max_seconds": 1800}, ["blink", "boots", "branches"], 2, 1),
        ({"purchase_index_max": 1}, ["branches"], 4, 3),
        ({"purchase_time_min_seconds": 500}, ["blink"], 4, 3),
        ({"purchase_time_max_seconds": 3000}, ["late_item", "blink", "boots", "branches"], 2, 2),
        ({"skill_min": 75}, ["blink", "boots", "branches"], 2, 2),
    ],
)
async def test_duration_skill_time_and_source_order_filters(
    settings, synthetic_details, params, keys, size, wins
):
    await publish(settings, synthetic_details)
    response = await request(settings, "items", hero_id=93, **params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["item_key"] for item in body["recommendations"]] == keys
    assert body["recommendations"][0]["sample_size"] == size
    assert body["recommendations"][0]["wins"] == wins


async def test_synthetic_draft_recuo_and_exact_context(settings, synthetic_details):
    await publish(settings, synthetic_details)
    ally = synthetic_details[0]["players"][1]["hero_id"]
    opponent = synthetic_details[0]["players"][5]["hero_id"]
    exact = (await request(settings, "heroes", ally_ids=ally, opponent_ids=opponent)).json()
    assert exact["status"] == "ok"
    assert not exact["fallback"]["applied"]
    assert 93 in [item["hero_id"] for item in exact["recommendations"]]
    assert not ({ally, opponent} & {item["hero_id"] for item in exact["recommendations"]})
    fallback = (await request(settings, "items", hero_id=93, ally_ids=999)).json()
    assert fallback["fallback"]["removed_filters"] == ["ally_ids"]
    assert fallback["requested_context"]["ally_ids"] == [999]
    assert fallback["used_context"]["hero_id"] == 93
    strict = (
        await request(settings, "items", hero_id=93, ally_ids=999, allow_fallback=False)
    ).json()
    assert strict["recommendations"] == []


async def test_small_real_fixture_has_no_misleading_ranking_and_position_is_unknown(
    settings,
    load_opendota_fixture,
):
    await publish(settings, [load_opendota_fixture("match_detail_parsed.json")])
    for route, params in (("heroes", {}), ("items", {"hero_id": 93})):
        response = await request(settings, route, **params)
        assert response.status_code == 200
        assert response.json()["status"] == "insufficient_evidence"
        assert response.json()["recommendations"] == []
    response = await request(settings, "heroes", position=1)
    assert response.json()["status"] == "unsupported_context"
    assert not response.json()["supported_contexts"]["position"]
    assert (await request(settings, "items", hero_id=999)).status_code == 404


async def test_final_inventory_without_purchase_log_does_not_recommend_items(
    settings,
    load_opendota_fixture,
):
    detail = load_opendota_fixture("match_detail_unparsed.json")
    other = deepcopy(detail)
    other["match_id"] += 1
    await publish(settings, [detail, other])
    body = (await request(settings, "items", hero_id=detail["players"][0]["hero_id"])).json()
    assert body["recommendations"] == []
    assert body["status"] == "insufficient_evidence"


async def test_first_purchase_is_chronological_and_later_rebuy_cannot_enter_window(
    settings,
    synthetic_details,
):
    for detail in synthetic_details:
        detail["players"][0]["purchase_log"] = [
            {"key": "boots", "time": 500},
            {"key": "boots", "time": 100},
        ]
    await publish(settings, synthetic_details)
    body = (await request(settings, "items", hero_id=93)).json()
    assert body["recommendations"][0]["mean_purchase_time_seconds"] == 100
    assert body["recommendations"][0]["mean_purchase_index"] == 1
    later = (await request(settings, "items", hero_id=93, purchase_time_min_seconds=200)).json()
    assert later["recommendations"] == []


async def test_empty_filters_exclusive_end_and_missing_cohort_metadata(settings, synthetic_details):
    await publish(settings, synthetic_details)
    for params in (
        {"game_mode": 999},
        {"skill_min": 85},
        {"rank_coverage_min": 10},
        {"period_start": "2026-09-17", "period_end": "2026-09-18"},
    ):
        body = (await request(settings, "heroes", **params)).json()
        assert body["status"] == "no_data"
        assert body["sample"]["matches"] == 0
        assert body["recommendations"] == []
    assert (await request(settings, "heroes", cohort="high_skill_public_v1")).status_code == 503


async def test_reprocess_and_catalog_rebuild_keep_contextual_counts(settings, synthetic_details):
    first = await publish(settings, synthetic_details)
    before = (await request(settings, "items", hero_id=93)).json()
    second = await run_pipeline(settings)
    assert second.run.status is RunStatus.SUCCEEDED
    paths = get_data_paths(settings)
    first_table = pq.read_table(
        paths.processed / "versions" / first.version_id / "recommendation_stats.parquet"
    )
    second_table = pq.read_table(
        paths.processed / "versions" / second.version_id / "recommendation_stats.parquet"
    )
    assert first_table.equals(second_table)
    paths.duckdb.unlink()
    assert rebuild_catalog(paths)["version_id"] == second.version_id
    after = (await request(settings, "items", hero_id=93)).json()
    assert before["recommendations"] == after["recommendations"]


async def test_api_is_read_only_never_collects_and_missing_catalog_is_not_created(
    settings,
    synthetic_details,
    monkeypatch,
):
    assert (await request(settings, "heroes")).status_code == 503
    assert not settings.duckdb_path.exists()
    assert not settings.data_dir.exists()
    await publish(settings, synthetic_details)
    before = hashlib.sha256(settings.duckdb_path.read_bytes()).hexdigest()

    def forbidden(*_args, **_kwargs):
        pytest.fail("Recommendation requests must not create an OpenDota client")

    monkeypatch.setattr(OpenDotaClient, "__init__", forbidden)
    for route, params in (("heroes", {}), ("items", {"hero_id": 93})):
        assert (await request(settings, route, **params)).status_code == 200
    assert hashlib.sha256(settings.duckdb_path.read_bytes()).hexdigest() == before
    with closing(duckdb.connect(str(settings.duckdb_path))):
        assert (await request(settings, "heroes")).status_code == 503


async def test_corrupt_contextual_stats_cannot_replace_current_publication(
    settings,
    synthetic_details,
    monkeypatch,
):
    import app.pipeline.runner as runner

    previous = await publish(settings, synthetic_details)
    original = runner.write_recommendation_stats

    def corrupt(connection, destination):
        original(connection, destination)
        path = destination / "recommendation_stats.parquet"
        table = pq.read_table(path)
        rows = table.to_pylist()
        rows[0]["wins"] += 1
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)

    monkeypatch.setattr(runner, "write_recommendation_stats", corrupt)
    failed = await run_pipeline(settings)
    assert failed.run.status is RunStatus.FAILED
    assert "recommendation_stats" in failed.message
    with closing(duckdb.connect(str(settings.duckdb_path), read_only=True)) as connection:
        assert current_version(connection) == previous.version_id


async def test_v2_snapshot_is_rebuildable_but_requires_reprocess_for_recommendations(
    settings,
    synthetic_details,
):
    previous = await publish(settings, synthetic_details)
    paths = get_data_paths(settings)
    folder = paths.processed / "versions" / previous.version_id
    manifest_path = folder / "version.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["aggregator_version"] = 2
    del manifest["files"]["recommendation_stats.parquet"]
    manifest_path.write_text(json.dumps(manifest))
    paths.duckdb.unlink()
    rebuild_catalog(paths)
    assert (await request(settings, "heroes")).status_code == 503
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as api:
        assert (await api.get("/api/v1/meta/heroes", params=PERIOD)).status_code == 200
    assert (await run_pipeline(settings)).run.status is RunStatus.SUCCEEDED
    assert (await request(settings, "heroes")).status_code == 200


async def test_cohort_uses_archived_constants_and_excludes_low_rank(
    settings, synthetic_details, load_opendota_fixture
):
    constants = load_opendota_fixture("constants.json")
    constants["game_mode"] = constants.pop("game_modes")
    constants["lobby_type"] = constants.pop("lobby_types")
    async with OpenDotaClient(
        settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=constants[request.url.path.rsplit("/", 1)[1]])
        ),
        sleep=no_sleep,
    ) as client:
        metadata = await collect_metadata(client)
    persist_metadata(get_data_paths(settings).raw, metadata)
    synthetic_details[0]["avg_rank_tier"] = 60
    synthetic_details[1]["avg_rank_tier"] = 60
    for detail in synthetic_details:
        detail.update(game_mode=22, lobby_type=7)
    await publish(settings, synthetic_details)
    body = (await request(settings, "items", hero_id=93, cohort="high_skill_public_v1")).json()
    assert body["sample"]["matches"] == 2
    assert all(item["sample_size"] == 2 and item["wins"] == 2 for item in body["recommendations"])
