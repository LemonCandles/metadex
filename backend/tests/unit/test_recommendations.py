"""Synthetic evidence checks for conjunctions, uniform fallback and deterministic ties."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.analytics.heroes import HeroFilters, HeroPeriod, RepositoryUnavailable
from app.analytics.recommendations import (
    ItemTiming,
    PublishedRecommendationData,
    RecommendationContext,
    RecommendationCount,
    RecommendationService,
)
from app.api.recommendation_models import RecommendationResponse
from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.unit
DAY = date(2026, 9, 18)
PERIOD = HeroPeriod(DAY, date(2026, 9, 19))
PARAMS = {"period_start": "2026-09-18", "period_end": "2026-09-19"}


def row(hero=1, size=3, wins=2, **values):
    return replace(
        RecommendationCount(
            DAY,
            hero,
            None,
            (2, 3, 4, 5),
            (6, 7, 8, 9, 10),
            1800,
            "hero",
            None,
            None,
            None,
            size,
            wins,
        ),
        **values,
    )


class Repository:
    def __init__(self, rows=(), positions=False):
        self.data = PublishedRecommendationData(
            "test_publication",
            datetime(2026, 9, 30, tzinfo=UTC),
            tuple(rows),
            positions,
        )
        self.calls = []
        self.failure = None

    def read(self, period, filters, *, context, timing):
        self.calls.append((period, filters, context, timing))
        if self.failure:
            raise self.failure
        return self.data


def service(rows, positions=False):
    return RecommendationService(Repository(rows, positions), window_days=7, min_sample_size=3)


def recommend(rows, context=None, **kwargs):
    return service(rows).recommend(
        "hero", PERIOD, HeroFilters(), context or RecommendationContext(), **kwargs
    )


def test_aggregate_counts_before_rates_and_tie_by_sample_then_id():
    result = recommend(
        [
            row(1, 1, 1),
            row(1, 2, 1),
            row(20, 6, 4),
            row(21, 6, 4),
            row(22, 1, 1),
        ]
    )
    assert [item["hero_id"] for item in result["recommendations"]] == [20, 21, 1]
    last = result["recommendations"][-1]
    assert (last["sample_size"], last["wins"], last["losses"], last["win_rate"]) == (3, 2, 1, 2 / 3)


def test_all_context_ids_must_match_correct_sides_and_draft_is_excluded():
    context = RecommendationContext(ally_ids=(2, 3), opponent_ids=(6, 7))
    result = recommend(
        [
            row(1),
            row(20, ally_ids=(2, 30, 4, 5)),
            row(21, opponent_ids=(6, 70, 8, 9, 10)),
            row(2),
            row(6),
        ],
        context,
        allow_fallback=False,
    )
    assert [item["hero_id"] for item in result["recommendations"]] == [1]
    assert result["fallback"]["attempts"][0]["eligible_count"] == 1


def test_fallback_preserves_opponents_and_uses_one_level_for_all_suggestions():
    context = RecommendationContext(ally_ids=(99,), opponent_ids=(6,))
    result = recommend([row(1, 1, 1, ally_ids=(99, 2, 3, 4)), row(1, 2, 1), row(20)], context)
    assert result["fallback"]["removed_filters"] == ["ally_ids"]
    assert result["used_context"]["opponent_ids"] == (6,)
    assert [attempt["level"] for attempt in result["fallback"]["attempts"]] == [
        "exact",
        "without_allies",
    ]
    assert all(item["context"] == result["used_context"] for item in result["recommendations"])
    assert result["recommendations"][0]["sample_size"] == 3


def test_fallback_never_recommends_draft_heroes_or_duplicates_observations():
    result = recommend(
        [row(1), row(99), row(100)],
        RecommendationContext(
            ally_ids=(99,),
            opponent_ids=(100,),
        ),
    )
    assert result["fallback"]["removed_filters"] == ["ally_ids", "opponent_ids"]
    assert [item["hero_id"] for item in result["recommendations"]] == [1]
    assert result["recommendations"][0]["sample_size"] == 3


def test_sparse_evidence_never_produces_a_ranking():
    result = recommend([row(1, 1, 1)])
    assert result["status"] == "insufficient_evidence"
    assert result["recommendations"] == []
    assert not result["fallback"]["applied"]
    assert result["fallback"]["attempts"][0]["candidate_count"] == 1


def test_disabled_fallback_does_not_broaden_and_no_data_retains_metadata():
    result = recommend([row(1)], RecommendationContext(ally_ids=(99,)), allow_fallback=False)
    assert result["recommendations"] == []
    assert len(result["fallback"]["attempts"]) == 1
    result = recommend([])
    assert result["status"] == "no_data"
    assert result["version_id"] == "test_publication"


def test_unknown_position_is_explicit_and_known_position_never_relaxed():
    context = RecommendationContext(position=1, ally_ids=(99,))
    result = recommend([row()], context)
    assert result["status"] == "unsupported_context"
    assert result["fallback"]["attempts"] == []
    known = service([row(position=2)], positions=True).recommend(
        "hero",
        PERIOD,
        HeroFilters(),
        context,
    )
    assert known["recommendations"] == []
    assert all(attempt["context"]["position"] == 1 for attempt in known["fallback"]["attempts"])


def test_items_keep_hero_and_purchase_bounds_through_fallback_and_sort_keys():
    rows = [row(1, 10, 5)]
    for key, hero, index, time in (
        ("boots", 1, 1, 200),
        ("blink", 1, 1, 200),
        ("late", 1, 1, 1800),
        ("wrong_hero", 20, 1, 200),
        ("wrong_order", 1, 4, 200),
    ):
        rows.append(
            row(hero, kind="item", item_key=key, purchase_index=index, purchase_time_seconds=time)
        )
    context = RecommendationContext(hero_id=1, ally_ids=(99,))
    result = service(rows).recommend(
        "item", PERIOD, HeroFilters(), context, timing=ItemTiming(purchase_index_max=2)
    )
    assert [item["item_key"] for item in result["recommendations"]] == ["blink", "boots"]
    assert all(item["hero_id"] == 1 for item in result["recommendations"])
    assert result["recommendations"][0]["mean_purchase_time_seconds"] == 200
    assert result["fallback"]["removed_filters"] == ["ally_ids"]


@pytest.fixture
def api(tmp_path):
    repository = Repository([row(1, 100, 50)])
    settings = Settings(_env_file=None, data_dir=tmp_path, duckdb_path=tmp_path / "data.duckdb")
    with TestClient(
        create_app(settings, recommendation_repository=repository), raise_server_exceptions=False
    ) as client:
        yield client, repository


@pytest.mark.parametrize(
    ("route", "params"),
    [
        ("heroes", {}),
        ("items", {"hero_id": 1}),
    ],
)
def test_http_contract_uses_replaceable_repository(api, route, params):
    client, repository = api
    response = client.get(f"/api/v1/recommendations/{route}", params={**PARAMS, **params})
    assert response.status_code == 200
    RecommendationResponse.model_validate(response.json())
    assert repository.calls[0][0] == PERIOD


@pytest.mark.parametrize(
    ("route", "params"),
    [
        ("heroes", {"ally_ids": [1, 1]}),
        ("heroes", {"ally_ids": [1, 2, 3, 4, 5]}),
        ("heroes", {"ally_ids": [1], "opponent_ids": [1]}),
        ("heroes", {"ally_ids": [0]}),
        ("heroes", {"position": 0}),
        ("heroes", {"position": 6}),
        ("heroes", {"limit": 0}),
        ("heroes", {"allow_fallback": "invalid"}),
        ("heroes", {"hero_id": 1}),
        ("heroes", {"unknown": "never-echo-input"}),
        ("heroes", {"period_end": "2026-09-18"}),
        ("heroes", {"skill_min": "NaN"}),
        ("items", {}),
        ("items", {"hero_id": -1}),
        ("items", {"hero_id": 1, "ally_ids": [1]}),
        ("items", {"hero_id": 1, "duration_min_seconds": 2000, "duration_max_seconds": 1000}),
        ("items", {"hero_id": 1, "purchase_time_min_seconds": 1300}),
        ("items", {"hero_id": 1, "purchase_index_min": 3, "purchase_index_max": 2}),
    ],
)
def test_invalid_inputs_never_read_repository_or_echo_values(api, route, params):
    client, repository = api
    response = client.get(f"/api/v1/recommendations/{route}", params={**PARAMS, **params})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_parameters"
    assert not repository.calls
    assert "never-echo-input" not in response.text


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (RepositoryUnavailable("private/path"), 503),
        (RuntimeError("private-secret"), 500),
    ],
)
def test_repository_failures_are_sanitized(api, failure, status):
    client, repository = api
    repository.failure = failure
    response = client.get("/api/v1/recommendations/heroes", params=PARAMS)
    assert response.status_code == status
    assert "private" not in response.text


def test_unknown_item_hero_and_openapi_contract(api):
    client, repository = api
    repository.data = replace(repository.data, hero_exists=False)
    assert (
        client.get("/api/v1/recommendations/items", params={**PARAMS, "hero_id": 999}).status_code
        == 404
    )
    document = client.get("/openapi.json").json()
    for route in ("heroes", "items"):
        operation = document["paths"][f"/api/v1/recommendations/{route}"]["get"]
        assert {"200", "422", "503", "500"} <= operation["responses"].keys()
        assert {"ally_ids", "opponent_ids", "position", "allow_fallback"} <= {
            parameter["name"] for parameter in operation["parameters"]
        }
