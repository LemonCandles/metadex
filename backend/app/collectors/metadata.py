"""Collect the four constant catalogs as one bounded, traceable batch."""

from dataclasses import dataclass
from typing import Any

from app.collectors.opendota import OpenDotaClient
from app.core.clock import to_utc_iso
from app.core.errors import MetadexError, RecoverableError
from app.core.logging import get_logger
from app.core.runs import RunRecord, RunStatus

RESOURCES = ("heroes", "items", "game_mode", "lobby_type")


@dataclass
class MetadataResult:
    run: RunRecord
    payloads: dict[str, dict[str, Any]]
    requests: list[dict[str, Any]]
    message: str


async def collect_metadata(client: OpenDotaClient) -> MetadataResult:
    run = RunRecord(operation="collect_metadata", requested_count=len(RESOURCES))
    payloads, requests = {}, []
    attempts, failures = client.attempts, client.failures
    message = "requested metadata collected"
    try:
        for name in RESOURCES:
            if client.remaining_minute == 0 or client.remaining_day == 0:
                raise RecoverableError("OpenDota rate limit budget exhausted")
            if client.attempts:
                await client.sleep(client.policy.page_interval_seconds)
            result = await client.constants(name)
            payloads[name] = result.payload
            requests.append(
                {
                    "endpoint": result.endpoint,
                    "requested_at": to_utc_iso(result.requested_at),
                    "status_code": result.status_code,
                }
            )
        run.finish(RunStatus.SUCCEEDED)
    except (MetadexError, ValueError) as exc:
        message = str(exc)
        run.finish(RunStatus.PARTIAL if payloads else RunStatus.FAILED)
        run.failures = 1
    run.received_count = run.processed_count = len(payloads)
    run.attempts = client.attempts - attempts
    run.failures = max(run.failures, client.failures - failures)
    get_logger(__name__).info(
        "metadata_finished",
        extra={
            "event": "metadata_finished",
            **run.as_log_context(),
            "detail": message,
        },
    )
    return MetadataResult(run, payloads, requests, message)
