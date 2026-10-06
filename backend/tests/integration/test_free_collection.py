"""Offline checks for free quotas, pacing, interruption recovery and publication."""

import argparse
import json
from pathlib import Path
from unittest.mock import AsyncMock

import duckdb
import httpx
import pytest

from app.core.config import Settings
from scripts import collect_opendota_free as script

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_total_budget_counts_every_http_attempt(tmp_path, monkeypatch):
    calls = []

    async def respond(_transport, request):
        calls.append(request)
        return httpx.Response(521)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", respond)
    monkeypatch.setattr(script.asyncio, "sleep", AsyncMock())
    state = {"requests": 0}
    transport = script.FreeTransport(state, tmp_path / "state.json", maximum=2, per_minute=60)
    request = httpx.Request("GET", "https://api.opendota.com/api/publicMatches")
    try:
        await transport.handle_async_request(request)
        await transport.handle_async_request(request)
        with pytest.raises(script.QuotaReached):
            await transport.handle_async_request(request)
        assert len(calls) == state["requests"] == 2
    finally:
        await transport.aclose()


async def test_daily_limit_is_read_even_from_error_responses(tmp_path, monkeypatch):
    responder = AsyncMock(
        return_value=httpx.Response(429, headers={"x-rate-limit-remaining-day": "0"})
    )
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", responder)
    state = {"requests": 0}
    transport = script.FreeTransport(state, tmp_path / "state.json", maximum=3000, per_minute=60)
    request = httpx.Request("GET", "https://api.opendota.com/api/publicMatches")
    try:
        await transport.handle_async_request(request)
        with pytest.raises(script.QuotaReached, match="diária"):
            await transport.handle_async_request(request)
        assert responder.await_count == 1
    finally:
        await transport.aclose()


@pytest.mark.parametrize(
    "http_request",
    [
        httpx.Request("GET", "https://api.opendota.com/api/publicMatches?api_key=paid"),
        httpx.Request(
            "GET", "https://api.opendota.com/api/publicMatches", headers={"Authorization": "paid"}
        ),
    ],
)
async def test_paid_credentials_are_rejected_before_network(tmp_path, monkeypatch, http_request):
    responder = AsyncMock()
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", responder)
    transport = script.FreeTransport(
        {"requests": 0}, tmp_path / "state.json", maximum=3000, per_minute=60
    )
    try:
        with pytest.raises(ValueError, match="sem chave paga"):
            await transport.handle_async_request(http_request)
        responder.assert_not_awaited()
    finally:
        await transport.aclose()


async def test_429_obeys_retry_after_and_minute_limit(tmp_path, monkeypatch):
    responses = iter(
        [
            httpx.Response(
                429,
                headers={
                    "Retry-After": "90",
                    "x-rate-limit-remaining-minute": "0",
                    "x-rate-limit-remaining-day": "2999",
                },
            ),
            httpx.Response(200),
        ]
    )

    async def respond(_transport, _request):
        return next(responses)

    sleep = AsyncMock()
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", respond)
    monkeypatch.setattr(script.asyncio, "sleep", sleep)
    monkeypatch.setattr(script.time, "time", lambda: 1000)
    state = {"requests": 0}
    transport = script.FreeTransport(state, tmp_path / "state.json", maximum=3000, per_minute=60)
    request = httpx.Request("GET", "https://api.opendota.com/api/publicMatches")
    try:
        await transport.handle_async_request(request)
        await transport.handle_async_request(request)
        sleep.assert_awaited_once_with(90)
    finally:
        await transport.aclose()


def local_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        duckdb_path=tmp_path / "data" / "metadex.duckdb",
        opendota_api_key="paid-key-that-must-not-be-used",
    )


async def test_real_archive_and_pipeline_receive_summaries_and_details(
    tmp_path, monkeypatch, load_opendota_fixture
):
    settings = local_settings(tmp_path)
    detail = load_opendota_fixture("match_detail_parsed.json")
    public = {
        key: detail[key]
        for key in ("match_id", "start_time", "duration", "radiant_win", "game_mode", "lobby_type")
    }
    public.update(
        radiant_team=[p["hero_id"] for p in detail["players"] if p["player_slot"] < 128],
        dire_team=[p["hero_id"] for p in detail["players"] if p["player_slot"] >= 128],
    )
    calls = []

    async def respond(_transport, request):
        calls.append(request)
        assert "authorization" not in request.headers
        assert "api_key" not in request.url.params
        payload = [public] if request.url.path.endswith("publicMatches") else detail
        return httpx.Response(
            200, json=payload, headers={"x-rate-limit-remaining-day": str(2 - len(calls))}
        )

    monkeypatch.setattr(script, "get_settings", lambda: settings)
    monkeypatch.setattr(script, "MAX_PUBLIC_MATCHES", 1)
    monkeypatch.setattr(script.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", respond)
    code = await script.collect(argparse.Namespace(max_requests=2, requests_per_minute=60))
    assert code == 0
    assert len(calls) == 2
    with duckdb.connect(str(settings.duckdb_path), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM matches").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM match_players").fetchone()[0] == 10
        assert connection.execute("SELECT count(*) FROM player_items").fetchone()[0] > 0
    state = json.loads((settings.data_dir / "operations/opendota-free-collection.json").read_text())
    assert state["status"] == "limit_reached"
    assert state["details_received"] == 1


async def test_resume_publishes_pending_pages_without_another_api_call(
    tmp_path, monkeypatch, load_opendota_fixture
):
    settings = local_settings(tmp_path)
    sample = load_opendota_fixture("public_matches_high_skill.json")[:2]
    operations = settings.data_dir / "operations"
    script.save_json(
        operations / "opendota-free-collection.json",
        {
            "requests": 1,
            "phase": "public_matches",
            "cursor": None,
            "public_received": 2,
            "details_received": 0,
            "skipped_details": [],
        },
    )
    script.save_json(
        operations / "opendota-free-pending/public_matches-000001.json",
        {
            "matches": sample,
            "source": {
                "endpoint": "/publicMatches",
                "requested_at": "2026-09-18T12:00:00Z",
                "status_code": 200,
                "parameters": {"min_rank": 70},
                "received_count": 2,
            },
        },
    )
    responder = AsyncMock()
    monkeypatch.setattr(script, "get_settings", lambda: settings)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", responder)
    assert await script.collect(argparse.Namespace(max_requests=1, requests_per_minute=60)) == 0
    responder.assert_not_awaited()
    with duckdb.connect(str(settings.duckdb_path), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM matches").fetchone()[0] == 2
    state = json.loads((operations / "opendota-free-collection.json").read_text())
    assert state["cursor"] == min(item["match_id"] for item in sample)
