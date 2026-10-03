"""Operator CLI: daily, monitor, backup and processed-version retention."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.operations.daily import DailyPolicy, run_daily
from app.operations.maintenance import backup_catalog, prune_versions
from app.operations.monitor import check_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Operate the Metadex daily MVP")
    commands = parser.add_subparsers(dest="command", required=True)
    daily = commands.add_parser("daily", help="collect and publish with a quality gate")
    daily.add_argument("--count", type=int, default=20)
    daily.add_argument("--max-pages", type=int, default=2)
    daily.add_argument("--no-details", action="store_true")
    daily.add_argument("--max-rejected-percent", type=float, default=5.0)
    monitor = commands.add_parser("monitor", help="check daily status and publication age")
    monitor.add_argument("--max-age-hours", type=int, default=36)
    backup = commands.add_parser("backup", help="copy a quiescent DuckDB catalog")
    backup.add_argument("--destination", type=Path, required=True)
    prune = commands.add_parser("prune", help="retire old processed versions; dry run by default")
    prune.add_argument("--keep", type=int, default=2)
    prune.add_argument("--min-age-days", type=int, default=30)
    prune.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(api_key=settings.opendota_api_key, stream=sys.stderr)
    try:
        if args.command == "daily":
            policy = DailyPolicy(args.max_rejected_percent / 100)
            result = asyncio.run(
                run_daily(
                    settings,
                    count=args.count,
                    max_pages=args.max_pages,
                    with_details=not args.no_details,
                    policy=policy,
                )
            )
            code = 0 if result["status"] == "succeeded" else 1
        elif args.command == "monitor":
            result = check_status(settings, max_age_hours=args.max_age_hours)
            code = 0 if result["status"] == "ok" else 2
        elif args.command == "backup":
            result = backup_catalog(settings, args.destination)
            code = 0
        else:
            result = prune_versions(
                settings, keep=args.keep, min_age_days=args.min_age_days, apply=args.apply
            )
            code = 0
    except Exception:
        get_logger(__name__).exception(
            "operations_command_failed", extra={"event": "operations_command_failed"}
        )
        result = {"status": "failed", "action": "Inspect sanitized service logs and retry."}
        code = 1
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
