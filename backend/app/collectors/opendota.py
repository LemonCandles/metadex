"""Bounded asynchronous access to OpenDota public matches."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.core.clock import utc_now
from app.core.config import Settings
from app.core.errors import DataError, PermanentError, RecoverableError

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RequestPolicy:
    """Small, predictable request budget for one collection run."""

    timeout_seconds: float = 10.0
    max_attempts: int = 3
    backoff_seconds: float = 1.0
    max_backoff_seconds: float = 30.0
    page_interval_seconds: float = 1.1

    def __post_init__(self) -> None:
        if (
            min(
                self.timeout_seconds,
                self.backoff_seconds,
                self.max_backoff_seconds,
                self.page_interval_seconds,
            )
            <= 0
            or self.max_attempts < 1
        ):
            raise ValueError("request policy values must be positive")


@dataclass(frozen=True, slots=True)
class MatchPage:
    matches: list[dict[str, Any]]
    attempts: int
    failures: int
    remaining_minute: int | None
    remaining_day: int | None
    requested_at: datetime
    status_code: int
    parameters: dict[str, int]


def _remaining(headers: httpx.Headers, suffix: str) -> int | None:
    value = headers.get(f"x-rate-limit-remaining-{suffix}")
    try:
        return max(0, int(value)) if value is not None else None
    except ValueError:
        return None


class OpenDotaClient:
    """HTTP transport only; collection rules live in the collector."""

    def __init__(
        self,
        settings: Settings,
        *,
        policy: RequestPolicy | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.policy = policy or RequestPolicy()
        self.sleep = sleep
        self.attempts = 0
        self.failures = 0
        headers = {"Accept": "application/json", "User-Agent": "Metadex/0.1"}
        if settings.opendota_api_key:
            headers["Authorization"] = f"Bearer {settings.opendota_api_key.get_secret_value()}"
        self._client = httpx.AsyncClient(
            base_url=str(settings.opendota_base_url).rstrip("/") + "/",
            headers=headers,
            timeout=self.policy.timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> "OpenDotaClient":
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._client.__aexit__(*args)

    async def public_matches(self, *, cursor: int | None = None) -> MatchPage:
        if cursor is not None and cursor < 1:
            raise ValueError("cursor must be a positive match_id")
        params = {"min_rank": 70}
        if cursor is not None:
            params["less_than_match_id"] = cursor
        failures = 0
        for attempt in range(1, self.policy.max_attempts + 1):
            self.attempts += 1
            requested_at = utc_now()
            try:
                response = await self._client.get("publicMatches", params=params)
            except httpx.RequestError as exc:
                failures += 1
                self.failures += 1
                if attempt == self.policy.max_attempts:
                    raise RecoverableError("OpenDota network failure after retry limit") from exc
            else:
                if response.status_code == 429 or 500 <= response.status_code <= 599:
                    failures += 1
                    self.failures += 1
                    if attempt == self.policy.max_attempts:
                        raise RecoverableError(
                            f"OpenDota returned HTTP {response.status_code} after retry limit"
                        )
                    delay = min(
                        self.policy.backoff_seconds * 2 ** (attempt - 1),
                        self.policy.max_backoff_seconds,
                    )
                    if response.status_code == 429:
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            with suppress(ValueError):
                                delay = max(delay, float(retry_after))
                        if delay > self.policy.max_backoff_seconds:
                            raise RecoverableError("OpenDota retry delay exceeds wait budget")
                    await self.sleep(delay)
                    continue
                if response.status_code >= 400:
                    raise PermanentError(f"OpenDota returned HTTP {response.status_code}")
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise DataError("OpenDota returned invalid JSON") from exc
                if not isinstance(payload, list) or len(payload) > 100:
                    raise DataError("OpenDota publicMatches returned an invalid page")
                if any(
                    not isinstance(item, dict)
                    or type(item.get("match_id")) is not int
                    or item["match_id"] < 1
                    for item in payload
                ):
                    raise DataError("OpenDota publicMatches contains an invalid match_id")
                return MatchPage(
                    payload,
                    attempt,
                    failures,
                    _remaining(response.headers, "minute"),
                    _remaining(response.headers, "day"),
                    requested_at,
                    response.status_code,
                    params.copy(),
                )
            delay = min(
                self.policy.backoff_seconds * 2 ** (attempt - 1),
                self.policy.max_backoff_seconds,
            )
            await self.sleep(delay)
        raise AssertionError("unreachable retry state")
