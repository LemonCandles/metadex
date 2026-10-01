"""Publish preserved real responses, then query their metrics through HTTP."""

import hashlib
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime

import duckdb
import httpx
import pytest
import pytest_asyncio

from app.collectors.opendota import OpenDotaClient
from app.core.config import Settings
from app.core.paths import get_data_paths
from app.core.runs import RunStatus
from app.main import create_app
from app.pipeline import run_pipeline
from app.storage.catalog import rebuild_catalog

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
PERIOD = {"period_start": "2026-09-18", "period_end": "2026-09-19"}


@pytest.fixture
def meta_settings(tmp_path):
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data d'example",
        duckdb_path=tmp_path / "catalog" / "metadex.duckdb",
        opendota_api_key="private-key",
    )


async def no_sleep(_seconds):
    pass


async def publish_sample(settings, sample):
    async with OpenDotaClient(
        settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=sample)),
        sleep=no_sleep,
    ) as source:
        result = await run_pipeline(
            settings, collect=True, count=len(sample), max_pages=1, client=source
        )
    assert result.run.status is RunStatus.SUCCEEDED, result.message
    return result


@pytest_asyncio.fixture
async def published(meta_settings, load_opendota_fixture):
    sample = load_opendota_fixture("public_matches_high_skill.json")[:2]
    return await publish_sample(meta_settings, sample)


@pytest_asyncio.fixture
async def api(meta_settings):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(meta_settings)),
        base_url="http://test",
    ) as client:
        yield client


async def test_real_sample_reaches_detail_ranking_and_trend(api, published):
    detail = (await api.get("/api/v1/meta/heroes/1", params=PERIOD)).json()
    assert detail["version_id"] == published.version_id
    assert detail["sample"] == {
        "matches": 2,
        "participants": 20,
        "observed_days": 1,
        "expected_days": 1,
        "min_sample_size": 100,
    }
    assert detail["hero"] == {
        "hero_id": 1,
        "picks": 1,
        "wins": 1,
        "losses": 0,
        "pick_rate": 0.5,
        "win_rate": 1.0,
        "sample_size": 1,
        "meets_min_sample": False,
    }
    ranking = (await api.get("/api/v1/meta/heroes", params=PERIOD)).json()
    assert ranking["heroes"] == []
    assert ranking["status"] == "below_min_sample"
    audit = (
        await api.get("/api/v1/meta/heroes", params={**PERIOD, "include_below_min": True})
    ).json()
    assert len(audit["heroes"]) == 20
    assert sum(hero["picks"] for hero in audit["heroes"]) == 20
    assert sum(hero["wins"] for hero in audit["heroes"]) == 10
    trend = (await api.get("/api/v1/meta/heroes/1/trend", params=PERIOD)).json()
    assert trend["hero"] == detail["hero"]
    assert trend["comparison"]["status"] == "insufficient_history"
    assert trend["comparison"]["pick_rate_delta"] is None
    assert trend["points"][0]["win_rate"] == 1.0


async def test_openapi_examples_match_processed_real_fixture_counts(api, published):
    document = (await api.get("/openapi.json")).json()
    for path in (
        "/api/v1/meta/heroes",
        "/api/v1/meta/heroes/{hero_id}",
        "/api/v1/meta/heroes/{hero_id}/trend",
    ):
        example = document["paths"][path]["get"]["responses"]["200"]["content"]["application/json"][
            "example"
        ]
        result = (await api.get(path.replace("{hero_id}", "1"), params=PERIOD)).json()
        # IDs and timestamps belong to the publication; example metadata is illustrative.
        result["version_id"] = example["version_id"]
        result["updated_at"] = example["updated_at"]
        assert result == example


@pytest.mark.parametrize(
    ("filters", "matches", "picks", "wins"),
    [
        ({"game_mode": 22}, 2, 1, 1),
        ({"game_mode": 23}, 0, 0, 0),
        ({"lobby_type": 7}, 1, 1, 1),
        ({"lobby_type": 0}, 1, 0, 0),
        ({"skill_min": 74}, 1, 0, 0),
        ({"skill_max": 74}, 1, 1, 1),
        ({"rank_coverage_min": 8}, 1, 1, 1),
        ({"skill_min": 70, "skill_max": 74, "rank_coverage_min": 8, "lobby_type": 7}, 1, 1, 1),
    ],
)
async def test_filters_change_numerator_and_denominator_together(
    api, published, filters, matches, picks, wins
):
    response = await api.get("/api/v1/meta/heroes/1", params={**PERIOD, **filters})
    assert response.status_code == 200
    result = response.json()
    assert result["sample"]["matches"] == matches
    assert result["hero"]["picks"] == picks
    assert result["hero"]["wins"] == wins
    assert result["hero"]["pick_rate"] == (picks / matches if matches else None)
    assert result["hero"]["win_rate"] == (wins / picks if picks else None)
    for name, value in filters.items():
        assert result["filters"][name] == value


async def test_api_never_collects_and_does_not_modify_catalog(
    api, published, meta_settings, monkeypatch
):
    def forbidden(*_args, **_kwargs):
        pytest.fail("API requests must not instantiate an OpenDota client")

    monkeypatch.setattr(OpenDotaClient, "__init__", forbidden)
    path = meta_settings.duckdb_path
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    for route in (
        "/health",
        "/api/v1/meta/heroes",
        "/api/v1/meta/heroes/1",
        "/api/v1/meta/heroes/1/trend",
    ):
        response = await api.get(route, params=PERIOD if route != "/health" else {})
        assert response.status_code == 200
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


async def test_empty_period_keeps_publication_metadata_and_null_rates(api, published):
    period = {"period_start": "2026-09-19", "period_end": "2026-09-21"}
    ranking = (await api.get("/api/v1/meta/heroes", params=period)).json()
    assert ranking["status"] == "no_data"
    assert ranking["version_id"] == published.version_id
    assert ranking["sample"]["matches"] == 0
    detail = (await api.get("/api/v1/meta/heroes/1", params=period)).json()
    assert detail["status"] == "no_data"
    assert detail["hero"]["picks"] == 0
    assert detail["hero"]["pick_rate"] is detail["hero"]["win_rate"] is None
    trend = (await api.get("/api/v1/meta/heroes/1/trend", params=period)).json()
    assert len(trend["points"]) == 2
    assert all(not point["has_data"] for point in trend["points"])
    assert trend["comparison"]["status"] == "no_current_data"


async def test_default_window_does_not_silently_move_to_old_data(api, published, monkeypatch):
    monkeypatch.setattr("app.analytics.heroes.utc_now", lambda: datetime(2026, 9, 30, tzinfo=UTC))
    result = (await api.get("/api/v1/meta/heroes")).json()
    assert result["period"]["start"] == "2026-09-23"
    assert result["period"]["end"] == "2026-09-30"
    assert result["status"] == "no_data"


async def test_missing_catalog_is_not_created_by_requests(api, meta_settings):
    assert (await api.get("/health")).json() == {"status": "ok"}
    for path in ("/api/v1/meta/heroes", "/api/v1/meta/heroes/1", "/api/v1/meta/heroes/1/trend"):
        response = await api.get(path, params=PERIOD)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "data_unavailable"
    assert not meta_settings.duckdb_path.exists()
    assert not meta_settings.data_dir.exists()


async def test_empty_catalog_without_publication_returns_503(api, meta_settings):
    rebuild_catalog(get_data_paths(meta_settings))
    response = await api.get("/api/v1/meta/heroes", params=PERIOD)
    assert response.status_code == 503


async def test_busy_writer_returns_sanitized_503_and_health_remains_available(
    api, published, meta_settings
):
    with closing(duckdb.connect(str(meta_settings.duckdb_path))):
        response = await api.get("/api/v1/meta/heroes", params=PERIOD)
        assert response.status_code == 503
        assert str(meta_settings.duckdb_path) not in response.text
        assert (await api.get("/health")).status_code == 200
    assert (await api.get("/api/v1/meta/heroes", params=PERIOD)).status_code == 200


async def test_corrupt_catalog_does_not_expose_internal_error(api, meta_settings):
    meta_settings.duckdb_path.parent.mkdir(parents=True)
    meta_settings.duckdb_path.write_text("invalid database containing private-key")
    response = await api.get("/api/v1/meta/heroes", params=PERIOD)
    assert response.status_code == 503
    assert "private-key" not in response.text
    assert str(meta_settings.duckdb_path) not in response.text


async def test_sql_daily_grouping_comparison_and_exclusive_end(
    api, meta_settings, load_opendota_fixture
):
    # Synthetic dates/results, derived from the fixture's valid participant layout.
    template = load_opendota_fixture("public_matches_high_skill.json")[0]
    sample = []
    for index, (day, won, present) in enumerate(
        [
            (15, False, True),
            (16, True, True),
            (17, True, True),
            (18, True, True),
            (18, False, True),
            (18, True, False),
            (19, True, True),
        ]
    ):
        match = deepcopy(template)
        match.update(
            match_id=10_000 + index,
            radiant_win=not won,
            start_time=int(datetime(2026, 9, day, tzinfo=UTC).timestamp()),
        )
        if not present:
            match["dire_team"][2] = 11
        sample.append(match)
    publication = await publish_sample(meta_settings, sample)
    response = await api.get(
        "/api/v1/meta/heroes/1/trend",
        params={"period_start": "2026-09-17", "period_end": "2026-09-19"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["version_id"] == publication.version_id
    assert result["sample"]["matches"] == 4  # Includes the match without hero 1; excludes day 19.
    assert result["hero"]["picks"] == 3
    assert result["hero"]["win_rate"] == 2 / 3
    assert result["comparison"]["sample"]["matches"] == 2
    assert result["comparison"]["status"] == "comparable"
    assert result["comparison"]["pick_rate_delta"] == -0.25
    assert result["comparison"]["win_rate_delta"] == pytest.approx(1 / 6)
    assert [point["matches"] for point in result["points"]] == [1, 3]


async def test_skill_filter_excludes_unknown_average_or_rank_coverage(
    api, meta_settings, load_opendota_fixture
):
    sample = [
        deepcopy(load_opendota_fixture("public_matches_high_skill.json")[0]) for _ in range(3)
    ]
    for index, match in enumerate(sample):
        match["match_id"] = 20_000 + index
    sample[0]["avg_rank_tier"] = None
    sample[1]["num_rank_tier"] = None
    await publish_sample(meta_settings, sample)
    unfiltered = (await api.get("/api/v1/meta/heroes/1", params=PERIOD)).json()
    filtered = (await api.get("/api/v1/meta/heroes/1", params={**PERIOD, "skill_min": 70})).json()
    assert unfiltered["sample"]["matches"] == 3
    assert filtered["sample"]["matches"] == filtered["hero"]["picks"] == 1
