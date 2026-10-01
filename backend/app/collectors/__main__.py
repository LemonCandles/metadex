"""Run an explicit, bounded collection with python -m app.collectors."""

import argparse
import asyncio
import json
import sys

from app.collectors.match_details import collect_match_details
from app.collectors.metadata import collect_metadata
from app.collectors.opendota import OpenDotaClient
from app.collectors.public_matches import collect_public_matches
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.paths import get_data_paths
from app.core.runs import RunStatus
from app.storage.metadata import persist_metadata
from app.storage.raw import persist_collection


async def main() -> int:
    parser = argparse.ArgumentParser(description="Collect a small OpenDota public match sample")
    parser.add_argument("--count", type=int, default=20, help="1 to 200 matches (default: 20)")
    parser.add_argument("--max-pages", type=int, default=2, help="1 to 5 pages (default: 2)")
    parser.add_argument("--save", action="store_true", help="archive the sample in raw Parquet")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--details", nargs="+", type=int, help="fetch 1..20 explicit match IDs")
    mode.add_argument(
        "--metadata", action="store_true", help="fetch heroes, items, modes and lobbies"
    )
    args = parser.parse_args()
    if not 1 <= args.count <= 200 or not 1 <= args.max_pages <= 5:
        parser.error("--count must be 1..200 and --max-pages must be 1..5")
    settings = get_settings()
    configure_logging(api_key=settings.opendota_api_key, stream=sys.stderr)
    async with OpenDotaClient(settings) as client:
        if args.metadata:
            metadata = await collect_metadata(client)
            output = {
                "run": metadata.run.as_log_context(),
                "message": metadata.message,
                "resources": list(metadata.payloads),
            }
            if args.save:
                output["manifest"] = persist_metadata(get_data_paths(settings).raw, metadata)
            print(json.dumps(output, ensure_ascii=False))
            return {RunStatus.SUCCEEDED: 0, RunStatus.PARTIAL: 2, RunStatus.FAILED: 1}[
                metadata.run.status
            ]
        if args.details:
            if (
                not 1 <= len(args.details) <= 20
                or len(set(args.details)) != len(args.details)
                or any(not 1 <= value <= 9_223_372_036_854_775_807 for value in args.details)
            ):
                parser.error("--details requires 1..20 distinct positive 64-bit match IDs")
            result = await collect_match_details(client, args.details)
        else:
            result = await collect_public_matches(
                client, count=args.count, max_pages=args.max_pages
            )
    output = result.as_dict()
    if args.save:
        output["manifest"] = persist_collection(
            get_data_paths(settings).raw, result, max_pages=args.max_pages
        )
    print(json.dumps(output, ensure_ascii=False))
    return {RunStatus.SUCCEEDED: 0, RunStatus.PARTIAL: 2, RunStatus.FAILED: 1}[result.run.status]


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
