"""Run a guarded daily publication and persist a small actionable status record."""

import asyncio
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from app.core.clock import to_utc_iso, utc_now
from app.core.config import Settings
from app.core.errors import DataError
from app.core.paths import get_data_paths
from app.core.runs import RunStatus
from app.pipeline.runner import PipelineResult, run_pipeline
from app.storage.catalog import write_json_atomic
from app.storage.locking import WriterBusyError


@dataclass(frozen=True)
class DailyPolicy:
    """Conservative limits for accepting a cumulative dataset."""

    max_rejected_fraction: float = 0.05

    def __post_init__(self) -> None:
        if not 0 <= self.max_rejected_fraction < 1:
            raise ValueError("max_rejected_fraction must be in [0, 1)")

    def validate(self, quality: dict[str, Any], counts: dict[str, int]) -> None:
        total = quality["input_matches"]
        rejected = quality["rejected_matches"]
        if not total or not counts["matches"]:
            raise DataError("daily quality gate: no accepted matches")
        if rejected / total > self.max_rejected_fraction:
            raise DataError("daily quality gate: rejected match fraction exceeds limit")


def status_path(settings: Settings) -> Path:
    return get_data_paths(settings).root / "operations" / "daily-status.json"


def save_status(settings: Settings, value: dict[str, Any]) -> None:
    path = status_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, value)


async def run_daily(
    settings: Settings,
    *,
    count: int = 20,
    max_pages: int = 2,
    with_details: bool = False,
    policy: DailyPolicy | None = None,
    client: Any = None,
) -> dict[str, Any]:
    """Persist state before and after the pipeline so interruptions become visible."""
    if not 1 <= count <= 200 or not 1 <= max_pages <= 5:
        raise ValueError("count must be 1..200 and max_pages must be 1..5")
    if with_details and count > 20:
        raise ValueError("with_details supports at most 20 matches")
    started_at = utc_now()
    previous_count = None
    if settings.duckdb_path.is_file():
        try:
            with closing(duckdb.connect(str(settings.duckdb_path), read_only=True)) as connection:
                previous_count = connection.execute("SELECT count(*) FROM raw_matches").fetchone()[
                    0
                ]
        except duckdb.Error:
            pass
    save_status(settings, {"status": "running", "started_at": to_utc_iso(started_at)})
    result: PipelineResult | None = None
    try:
        for scheduler_attempts in range(1, 4):
            try:
                result = await run_pipeline(
                    settings,
                    collect=True,
                    count=count,
                    max_pages=max_pages,
                    with_details=with_details,
                    client=client,
                    quality_gate=(policy or DailyPolicy()).validate,
                )
                break
            except (WriterBusyError, duckdb.IOException) as exc:
                if (
                    scheduler_attempts == 3
                    or isinstance(exc, duckdb.IOException)
                    and "lock" not in str(exc).lower()
                ):
                    raise
                await asyncio.sleep(2**scheduler_attempts)
        alerts = []
        if result.run.status is not RunStatus.SUCCEEDED:
            alerts.append(
                {
                    "code": "daily_pipeline_failed",
                    "action": "Inspect pipeline_runs and stderr; fix the cause, then retry.",
                }
            )
        elif result.counts and result.counts["raw_matches"] == 0:
            # This cannot occur after validation, but keep the operational contract explicit.
            alerts.append({"code": "empty_publication", "action": "Inspect the raw archive."})
        if result.run.status is RunStatus.SUCCEEDED and result.counts is not None:
            if previous_count is not None and result.counts["raw_matches"] == previous_count:
                alerts.append(
                    {
                        "code": "no_new_matches",
                        "action": "Check whether OpenDota returned the same recent matches.",
                    }
                )
            if result.run.failures:
                alerts.append(
                    {
                        "code": "source_retries",
                        "action": "Inspect collection logs and OpenDota rate-limit headers.",
                    }
                )
        status = {
            "status": result.run.status.value,
            "started_at": to_utc_iso(started_at),
            "finished_at": to_utc_iso(utc_now()),
            "run_id": result.run.run_id,
            "version_id": result.version_id,
            "stage": result.stage.value,
            "requested_count": result.run.requested_count,
            "received_count": result.run.received_count,
            "processed_count": result.run.processed_count,
            "attempts": result.run.attempts,
            "scheduler_attempts": scheduler_attempts,
            "failures": result.run.failures,
            "counts": result.counts,
            "alerts": alerts,
        }
    except Exception:
        status = {
            "status": "failed",
            "started_at": to_utc_iso(started_at),
            "finished_at": to_utc_iso(utc_now()),
            "alerts": [
                {
                    "code": "daily_command_failed",
                    "action": "Inspect service logs, writer lock and configuration; then retry.",
                }
            ],
        }
        save_status(settings, status)
        raise
    save_status(settings, status)
    return status
