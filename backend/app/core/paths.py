"""Canonical paths for local data artifacts."""

from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class DataPaths:
    """Locations used by storage modules without repeating path logic."""

    root: Path
    raw: Path
    processed: Path
    duckdb: Path


def get_data_paths(settings: Settings) -> DataPaths:
    """Derive the complete local data layout from validated settings."""
    return DataPaths(
        root=settings.data_dir,
        raw=settings.data_dir / "raw",
        processed=settings.data_dir / "processed",
        duckdb=settings.duckdb_path,
    )


def ensure_data_directories(paths: DataPaths) -> None:
    """Create only the directories required by the current data layout."""
    paths.raw.mkdir(parents=True, exist_ok=True)
    paths.processed.mkdir(parents=True, exist_ok=True)
    paths.duckdb.parent.mkdir(parents=True, exist_ok=True)
