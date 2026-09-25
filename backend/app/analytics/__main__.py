"""Normalize one committed raw run without making network requests."""

import argparse
import json

from app.core.config import get_settings
from app.core.paths import get_data_paths
from app.storage.processed import process_raw_run


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize a local OpenDota raw run")
    parser.add_argument("run_id", help="committed raw run ID")
    args = parser.parse_args()
    paths = get_data_paths(get_settings())
    print(json.dumps(process_raw_run(paths.raw, paths.processed, args.run_id), ensure_ascii=False))


if __name__ == "__main__":
    main()
