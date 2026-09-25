"""Inspect committed raw runs without contacting OpenDota."""

import argparse
import json

from app.core.config import get_settings
from app.core.paths import get_data_paths
from app.storage.raw import list_partitions, list_runs, read_run


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect local raw OpenDota archives")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("partitions")
    sub.add_parser("runs")
    sub.add_parser("read").add_argument("run_id")
    args = parser.parse_args()
    raw = get_data_paths(get_settings()).raw
    if args.command == "partitions":
        output = list_partitions(raw)
    elif args.command == "runs":
        output = list_runs(raw)
    else:
        manifest, matches = read_run(raw, args.run_id)
        output = {"manifest": manifest, "matches": matches}
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
