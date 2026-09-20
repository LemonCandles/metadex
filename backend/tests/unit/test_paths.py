from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.paths import ensure_data_directories, get_data_paths

pytestmark = pytest.mark.unit


def test_data_paths_are_derived_from_settings(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        duckdb_path=tmp_path / "catalog" / "metadex.duckdb",
    )

    paths = get_data_paths(settings)
    ensure_data_directories(paths)

    assert paths.raw == tmp_path / "data/raw"
    assert paths.processed == tmp_path / "data/processed"
    assert paths.duckdb == tmp_path / "catalog/metadex.duckdb"
    assert paths.raw.is_dir()
    assert paths.processed.is_dir()
    assert paths.duckdb.parent.is_dir()
