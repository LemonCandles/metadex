"""Collect a small sample without writing to storage or serving API requests."""

from dataclasses import dataclass
from typing import Any

from app.collectors.opendota import OpenDotaClient
from app.core.clock import to_utc_iso
from app.core.errors import MetadexError
from app.core.logging import get_logger
from app.core.runs import RunRecord, RunStatus


@dataclass(slots=True)
class CollectionResult:
    run: RunRecord
    matches: list[dict[str, Any]]
    discarded_count: int
    pages: int
    message: str
    source_pages: list[dict[str, Any]]
    match_pages: dict[int, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run": self.run.as_log_context(),
            "discarded_count": self.discarded_count,
            "pages": self.pages,
            "message": self.message,
            "matches": self.matches,
            "source_pages": self.source_pages,
        }


async def collect_public_matches(
    client: OpenDotaClient, *, count: int = 20, max_pages: int = 2
) -> CollectionResult:
    """Page backwards by match ID, deduplicate and stop at the request budget."""
    if not 1 <= count <= 200 or not 1 <= max_pages <= 5:
        raise ValueError("count must be 1..200 and max_pages must be 1..5")
    run = RunRecord(operation="collect_public_matches", requested_count=count)
    logger = get_logger(__name__)
    matches: list[dict[str, Any]] = []
    seen: set[int] = set()
    cursor: int | None = None
    discarded = 0
    pages = 0
    source_pages: list[dict[str, Any]] = []
    match_pages: dict[int, int] = {}
    message = "requested sample collected"
    before_attempts = client.attempts
    before_failures = client.failures
    try:
        for page_number in range(max_pages):
            if page_number:
                await client.sleep(client.policy.page_interval_seconds)
            before_attempts = client.attempts
            before_failures = client.failures
            page = await client.public_matches(cursor=cursor)
            pages += 1
            source_pages.append(
                {
                    "requested_at": to_utc_iso(page.requested_at),
                    "status_code": page.status_code,
                    "parameters": page.parameters,
                    "received_count": len(page.matches),
                }
            )
            run.attempts += client.attempts - before_attempts
            run.failures += client.failures - before_failures
            before_attempts = client.attempts
            before_failures = client.failures
            run.received_count += len(page.matches)
            if not page.matches:
                message = "OpenDota returned no more matches"
                break
            next_cursor = min(item["match_id"] for item in page.matches)
            if cursor is not None and next_cursor >= cursor:
                raise ValueError("OpenDota cursor did not move backwards")
            for item in page.matches:
                match_id = item["match_id"]
                if match_id in seen or (cursor is not None and match_id >= cursor):
                    discarded += 1
                    continue
                seen.add(match_id)
                if len(matches) < count:
                    matches.append(item)
                    match_pages[match_id] = pages - 1
                else:
                    discarded += 1
            cursor = next_cursor
            if len(matches) >= count:
                break
            if page.remaining_day == 0 or page.remaining_minute == 0:
                message = "OpenDota rate limit budget exhausted"
                break
        else:
            message = "page budget reached before requested sample"
        if len(matches) < count and message == "requested sample collected":
            message = "requested sample incomplete"
        run.processed_count = len(matches)
        run.finish(RunStatus.SUCCEEDED if len(matches) == count else RunStatus.PARTIAL)
    except (MetadexError, ValueError) as exc:
        run.attempts += client.attempts - before_attempts
        run.failures += client.failures - before_failures
        if client.failures == before_failures:
            run.failures += 1
        run.processed_count = len(matches)
        run.finish(RunStatus.PARTIAL if matches else RunStatus.FAILED)
        message = str(exc)
    result = CollectionResult(run, matches, discarded, pages, message, source_pages, match_pages)
    logger.info(
        "collection_finished",
        extra={
            "event": "collection_finished",
            **run.as_log_context(),
            "discarded_count": discarded,
            "pages": pages,
            "detail": message,
        },
    )
    return result
