"""Fetch a bounded, sequential batch of details for explicitly selected matches."""

from app.collectors.opendota import OpenDotaClient
from app.collectors.public_matches import CollectionResult
from app.core.clock import to_utc_iso
from app.core.errors import MetadexError
from app.core.logging import get_logger
from app.core.runs import RunRecord, RunStatus


async def collect_match_details(client: OpenDotaClient, match_ids: list[int]) -> CollectionResult:
    if not 1 <= len(match_ids) <= 20 or len(set(match_ids)) != len(match_ids):
        raise ValueError("details require 1..20 distinct match IDs")
    if any(
        type(value) is not int or not 1 <= value <= 9_223_372_036_854_775_807 for value in match_ids
    ):
        raise ValueError("match IDs must be positive 64-bit integers")
    run = RunRecord(operation="collect_match_details", requested_count=len(match_ids))
    matches, pages, match_pages = [], [], {}
    attempts, failures = client.attempts, client.failures
    message = "requested details collected"
    try:
        for match_id in match_ids:
            if client.remaining_minute == 0 or client.remaining_day == 0:
                message = "OpenDota rate limit budget exhausted"
                break
            if client.attempts:
                await client.sleep(client.policy.page_interval_seconds)
            page = await client.match_detail(match_id)
            match_pages[match_id] = len(pages)
            pages.append(
                {
                    "endpoint": page.endpoint,
                    "requested_at": to_utc_iso(page.requested_at),
                    "status_code": page.status_code,
                    "parameters": page.parameters,
                    "received_count": 1,
                }
            )
            matches.extend(page.matches)
        run.finish(RunStatus.SUCCEEDED if len(matches) == len(match_ids) else RunStatus.PARTIAL)
    except (MetadexError, ValueError) as exc:
        message = str(exc)
        run.finish(RunStatus.PARTIAL if matches else RunStatus.FAILED)
        run.failures = 1
    run.received_count = run.processed_count = len(matches)
    run.attempts = client.attempts - attempts
    run.failures = max(run.failures, client.failures - failures)
    result = CollectionResult(
        run, matches, 0, len(pages), message, pages, match_pages, dataset="match_details"
    )
    get_logger(__name__).info(
        "collection_finished",
        extra={
            "event": "collection_finished",
            **run.as_log_context(),
            "message_detail": message,
        },
    )
    return result
