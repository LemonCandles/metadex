"""Offline contract tests for the HTTP client and bounded collector."""

from typing import Any

import httpx
import pytest

from app.collectors.opendota import OpenDotaClient, RequestPolicy
from app.collectors.public_matches import collect_public_matches
from app.core.config import Settings
from app.core.errors import DataError, RecoverableError
from app.core.runs import RunStatus

pytestmark = pytest.mark.unit


def settings(**changes: Any) -> Settings:
    return Settings(
        _env_file=None,
        opendota_base_url="https://offline.example.test/api",
        **changes,
    )


async def no_sleep(_seconds: float) -> None:
    pass


@pytest.mark.asyncio
async def test_pagination_deduplication_and_run_counts() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json=[{"match_id": 30}, {"match_id": 29}])
        return httpx.Response(200, json=[{"match_id": 28}, {"match_id": 28}])

    async with OpenDotaClient(
        settings(), transport=httpx.MockTransport(respond), sleep=no_sleep
    ) as client:
        result = await collect_public_matches(client, count=3)

    assert [item["match_id"] for item in result.matches] == [30, 29, 28]
    assert requests[0].url.params["min_rank"] == "70"
    assert requests[1].url.params["less_than_match_id"] == "29"
    assert result.run.status is RunStatus.SUCCEEDED
    assert (result.run.requested_count, result.run.received_count, result.discarded_count) == (
        3,
        4,
        1,
    )
    assert result.run.attempts == 2
    assert result.run.duration_ms is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_temporary_responses_retry_with_progressive_wait(status: int) -> None:
    calls = 0
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(status)
        return httpx.Response(200, json=[{"match_id": 42}])

    async with OpenDotaClient(
        settings(), transport=httpx.MockTransport(respond), sleep=sleep
    ) as client:
        result = await collect_public_matches(client, count=1)

    assert result.run.status is RunStatus.SUCCEEDED
    assert (result.run.attempts, result.run.failures) == (3, 2)
    assert waits == [1.0, 2.0]


@pytest.mark.asyncio
async def test_timeout_exhaustion_is_failed_with_bounded_attempts() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    async with OpenDotaClient(
        settings(), transport=httpx.MockTransport(respond), sleep=no_sleep
    ) as client:
        result = await collect_public_matches(client, count=1)

    assert result.run.status is RunStatus.FAILED
    assert (result.run.attempts, result.run.failures) == (3, 3)
    assert "network failure" in result.message


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_permanent_errors_are_not_retried(status: int) -> None:
    calls = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    async with OpenDotaClient(
        settings(), transport=httpx.MockTransport(respond), sleep=no_sleep
    ) as client:
        result = await collect_public_matches(client, count=1)

    assert calls == 1
    assert result.run.status is RunStatus.FAILED
    assert result.message == f"OpenDota returned HTTP {status}"


@pytest.mark.asyncio
async def test_invalid_payload_causes_partial_run_after_first_page() -> None:
    calls = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json=[{"match_id": 10}])
        return httpx.Response(200, json={"unexpected": "object"})

    async with OpenDotaClient(
        settings(), transport=httpx.MockTransport(respond), sleep=no_sleep
    ) as client:
        result = await collect_public_matches(client, count=2)

    assert result.run.status is RunStatus.PARTIAL
    assert result.run.received_count == 1
    assert result.run.processed_count == 1
    assert result.run.failures == 1
    assert "invalid page" in result.message


@pytest.mark.asyncio
async def test_authentication_uses_header_and_never_query_string() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer private-key"
        assert "private-key" not in str(request.url)
        assert "api_key" not in request.url.params
        return httpx.Response(200, json=[{"match_id": 1}])

    async with OpenDotaClient(
        settings(opendota_api_key="private-key"), transport=httpx.MockTransport(respond)
    ) as client:
        page = await client.public_matches()
    assert len(page.matches) == 1


@pytest.mark.asyncio
async def test_client_rejects_invalid_payload_without_retry() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"match_id": "wrong"}])

    async with OpenDotaClient(settings(), transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(DataError):
            await client.public_matches()
    assert client.attempts == 1


@pytest.mark.asyncio
async def test_retry_after_beyond_budget_stops_immediately() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "120"})

    async with OpenDotaClient(settings(), transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(RecoverableError, match="wait budget"):
            await client.public_matches()
    assert client.attempts == 1


@pytest.mark.asyncio
async def test_rate_limit_header_prevents_next_page() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=[{"match_id": 4}], headers={"x-rate-limit-remaining-day": "0"}
        )

    async with OpenDotaClient(settings(), transport=httpx.MockTransport(respond)) as client:
        result = await collect_public_matches(client, count=2)
    assert result.run.status is RunStatus.PARTIAL
    assert result.pages == 1
    assert "rate limit" in result.message


@pytest.mark.asyncio
async def test_rejects_invalid_local_limits_before_request() -> None:
    async with OpenDotaClient(settings()) as client:
        with pytest.raises(ValueError, match="count"):
            await collect_public_matches(client, count=201)
    with pytest.raises(ValueError, match="positive"):
        RequestPolicy(max_attempts=0)
