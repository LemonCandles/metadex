"""Run or rebuild the local pipeline with python -m app.pipeline."""

import argparse
import asyncio
import json
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.paths import get_data_paths
from app.core.runs import RunStatus
from app.pipeline.runner import run_pipeline
from app.storage.catalog import rebuild_catalog


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect, validate, normalize, aggregate and publish"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    complete = sub.add_parser("run", help="collect a bounded sample and process all archived data")
    complete.add_argument("--count", type=int, default=20, help="1 to 200 matches (default: 20)")
    complete.add_argument("--max-pages", type=int, default=2, help="1 to 5 pages (default: 2)")
    complete.add_argument(
        "--with-details", action="store_true", help="archive details too (max 20 matches)"
    )
    sub.add_parser("reprocess", help="process all committed raw runs without accessing OpenDota")
    sub.add_parser("rebuild", help="restore the catalog from complete published versions")
    args = parser.parse_args()
    if args.command == "run" and (not 1 <= args.count <= 200 or not 1 <= args.max_pages <= 5):
        parser.error("--count must be 1..200 and --max-pages must be 1..5")
    if args.command == "run" and args.with_details and args.count > 20:
        parser.error("--with-details supports at most 20 matches")
    settings = get_settings()
    configure_logging(api_key=settings.opendota_api_key, stream=sys.stderr)
    try:
        if args.command == "rebuild":
            output = rebuild_catalog(get_data_paths(settings))
            code = 0
        else:
            result = await run_pipeline(
                settings,
                collect=args.command == "run",
                count=getattr(args, "count", 20),
                max_pages=getattr(args, "max_pages", 2),
                with_details=getattr(args, "with_details", False),
            )
            output = result.as_dict()
            code = {RunStatus.SUCCEEDED: 0, RunStatus.PARTIAL: 2, RunStatus.FAILED: 1}[
                result.run.status
            ]
    except Exception as exc:
        output = {"status": "failed", "message": str(exc)}
        get_logger(__name__).error(
            "pipeline_command_failed",
            extra={
                "event": "pipeline_command_failed",
                "detail": str(exc),
            },
        )
        code = 1
    print(json.dumps(output, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
