from datetime import UTC, datetime

import pytest

from app.core.identifiers import new_run_id

pytestmark = pytest.mark.unit


def test_run_id_can_be_created_deterministically() -> None:
    run_id = new_run_id(
        now=datetime(2026, 9, 18, 12, 34, 56, tzinfo=UTC),
        suffix="abcd1234",
    )

    assert run_id == "run_20260918T123456Z_abcd1234"
