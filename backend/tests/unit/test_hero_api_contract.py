"""HTTP contract tests replace storage with an in-memory repository."""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.analytics.heroes import (
    HeroDailyCount,
    HeroPeriod,
    PublishedHeroData,
    RepositoryUnavailable,
)
from app.api.models import DetailResponse, RankingResponse, TrendResponse
from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.unit
PERIOD = {"period_start": "2026-09-18", "period_end": "2026-09-19"}


class StubRepository:
    def __init__(self):
        self.calls = []
        self.failure = None

    def read(self, period, filters, *, hero_id=None, compare=False):
        self.calls.append((period, filters, hero_id, compare))
        if self.failure:
            raise self.failure
        return PublishedHeroData(
            "test_publication",
            datetime(2026, 9, 30, tzinfo=UTC),
            {date(2026, 9, 18): 2},
            (HeroDailyCount(date(2026, 9, 18), 1, 1, 1),),
            hero_exists=hero_id in (None, 1),
        )


@pytest.fixture
def api(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        duckdb_path=tmp_path / "meta.duckdb",
        opendota_api_key="never-expose-this-secret",
    )
    repository = StubRepository()
    with TestClient(
        create_app(settings, hero_repository=repository), raise_server_exceptions=False
    ) as client:
        yield client, repository


def test_health_does_not_access_repository_or_expose_settings(api):
    client, repository = api
    repository.failure = RuntimeError("sensitive/path")
    assert client.get("/health").json() == {"status": "ok"}
    assert not repository.calls


@pytest.mark.parametrize(
    ("path", "model"),
    [
        ("/api/v1/meta/heroes", RankingResponse),
        ("/api/v1/meta/heroes/1", DetailResponse),
        ("/api/v1/meta/heroes/1/trend", TrendResponse),
    ],
)
def test_endpoints_use_replaceable_repository_and_validate_responses(api, path, model):
    client, repository = api
    response = client.get(path, params=PERIOD)
    assert response.status_code == 200
    result = model.model_validate(response.json())
    assert result.sample.matches == 2
    assert result.updated_at == datetime(2026, 9, 30, tzinfo=UTC)
    assert repository.calls[0][0] == HeroPeriod(date(2026, 9, 18), date(2026, 9, 19))


@pytest.mark.parametrize(
    "params",
    [
        {"period_start": "2026-09-18"},
        {"period_end": "2026-09-19"},
        {"period_start": "invalid-date", "period_end": "2026-09-19"},
        {"period_start": "2026-09-19", "period_end": "2026-09-18"},
        {"period_start": "2026-09-18", "period_end": "2026-09-18"},
        {"period_start": "2025-01-01", "period_end": "2026-09-18"},
        {"period_start": "0001-01-01", "period_end": "0001-01-02"},
        {"skill_min": "80", "skill_max": "70"},
        {"skill_min": "NaN"},
        {"skill_max": "inf"},
        {"skill_min": "-1"},
        {"rank_coverage_min": "11"},
        {"rank_coverage_min": "0"},
        {"game_mode": "-1"},
        {"lobby_type": "no-number"},
        {"order_by": "unsupported"},
        {"order": "random"},
        {"include_below_min": "invalid"},
        {"position": "1"},
        {"opendota_api_key": "never-echo-input"},
    ],
)
def test_invalid_parameters_have_documented_error_and_never_query_storage(api, params):
    client, repository = api
    response = client.get("/api/v1/meta/heroes", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_parameters"
    assert response.json()["error"]["details"]
    assert "never-echo-input" not in response.text
    assert not repository.calls


@pytest.mark.parametrize("hero_id", ["0", "-1", "text", "2147483648"])
@pytest.mark.parametrize("suffix", ["", "/trend"])
def test_invalid_hero_ids_are_rejected_before_querying(api, hero_id, suffix):
    client, repository = api
    response = client.get(f"/api/v1/meta/heroes/{hero_id}{suffix}", params=PERIOD)
    assert response.status_code == 422
    assert not repository.calls


@pytest.mark.parametrize("suffix", ["", "/trend"])
def test_unknown_hero_has_consistent_404(api, suffix):
    client, _repository = api
    response = client.get(f"/api/v1/meta/heroes/999{suffix}", params=PERIOD)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "hero_not_found"


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (RepositoryUnavailable("secret-catalog-path"), 503, "data_unavailable"),
        (RuntimeError("secret-internal-detail"), 500, "internal_error"),
    ],
)
def test_internal_failures_never_leak_storage_details(api, failure, status, code):
    client, repository = api
    repository.failure = failure
    response = client.get("/api/v1/meta/heroes", params=PERIOD)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "secret" not in response.text


def test_openapi_documents_actual_parameters_models_and_examples(api):
    client, _repository = api
    document = client.get("/openapi.json").json()
    assert document["info"]["version"] == "1.0.0"
    for path, model in [
        ("/api/v1/meta/heroes", RankingResponse),
        ("/api/v1/meta/heroes/{hero_id}", DetailResponse),
        ("/api/v1/meta/heroes/{hero_id}/trend", TrendResponse),
    ]:
        operation = document["paths"][path]["get"]
        assert {"200", "422", "503", "500"} <= operation["responses"].keys()
        assert operation["responses"]["422"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("ErrorResponse")
        example = operation["responses"]["200"]["content"]["application/json"]["example"]
        model.model_validate(example)
        names = {parameter["name"] for parameter in operation["parameters"]}
        assert {
            "period_start",
            "period_end",
            "game_mode",
            "lobby_type",
            "skill_min",
            "skill_max",
            "rank_coverage_min",
        } <= names
    assert client.get("/docs").status_code == 200
    assert client.get("/missing").json()["error"]["code"] == "http_error"
