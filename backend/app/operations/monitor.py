"""Read-only freshness and failure checks for an external scheduler or alert sink."""

import json
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb

from app.core.clock import to_utc_iso, utc_now
from app.core.config import Settings
from app.operations.daily import status_path


def check_status(
    settings: Settings, *, max_age_hours: int = 36, now: datetime | None = None
) -> dict[str, Any]:
    if max_age_hours < 1:
        raise ValueError("max_age_hours must be positive")
    instant = now or utc_now()
    if instant.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    instant = instant.astimezone(UTC)
    alerts: list[dict[str, str]] = []
    last_run = None
    path = status_path(settings)
    if path.is_file():
        try:
            last_run = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(last_run, dict):
                raise ValueError("daily status must be an object")
            for alert in last_run.get("alerts", []):
                if isinstance(alert, dict) and "code" in alert and "action" in alert:
                    alerts.append(alert)
            if last_run.get("status") not in ("succeeded", "running"):
                alerts.append(
                    {
                        "code": "daily_run_failed",
                        "action": "Inspect daily-status.json and service logs; retry after repair.",
                    }
                )
            if last_run.get("status") == "running":
                started = datetime.fromisoformat(last_run["started_at"].replace("Z", "+00:00"))
                if instant - started > timedelta(hours=2):
                    alerts.append(
                        {
                            "code": "daily_run_stuck",
                            "action": "Inspect the service, writer lock and pipeline_runs.",
                        }
                    )
        except (ValueError, KeyError, TypeError):
            alerts.append({"code": "invalid_daily_status", "action": "Inspect daily-status.json."})
    else:
        alerts.append({"code": "daily_never_ran", "action": "Install and start the daily timer."})

    publication = None
    try:
        with closing(duckdb.connect(str(settings.duckdb_path), read_only=True)) as connection:
            row = connection.execute(
                """SELECT v.version_id, CAST(v.published_at AS VARCHAR) FROM current_publication c
                JOIN dataset_versions v USING (version_id) WHERE c.singleton=1"""
            ).fetchone()
            if row is not None:
                published_at = datetime.fromisoformat(row[1])
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=UTC)
                published_at = published_at.astimezone(UTC)
                publication = {
                    "version_id": row[0],
                    "published_at": to_utc_iso(published_at),
                }
                if instant - published_at > timedelta(hours=max_age_hours):
                    alerts.append(
                        {
                            "code": "publication_stale",
                            "action": "Inspect the daily service; rerun it or rebuild the catalog.",
                        }
                    )
            else:
                alerts.append(
                    {"code": "no_publication", "action": "Run the pipeline and inspect its result."}
                )
    except (duckdb.Error, OSError):
        alerts.append(
            {
                "code": "catalog_unavailable",
                "action": "Check the catalog path and active writer; retry when idle.",
            }
        )
    return {
        "status": "ok" if not alerts else "alert",
        "checked_at": to_utc_iso(instant),
        "publication": publication,
        "last_run": last_run,
        "alerts": alerts,
    }
