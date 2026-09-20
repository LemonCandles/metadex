"""Shared deterministic fixtures for the backend test suite."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

OPENDOTA_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "opendota"


@pytest.fixture
def load_opendota_fixture() -> Callable[[str], Any]:
    """Load one versioned OpenDota response without accessing the internet."""

    def load(filename: str) -> Any:
        with (OPENDOTA_FIXTURE_DIR / filename).open(encoding="utf-8") as fixture_file:
            return json.load(fixture_file)

    return load
