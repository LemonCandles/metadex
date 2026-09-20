from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.clock import as_utc, to_utc_iso, utc_now

pytestmark = pytest.mark.unit


def test_utc_now_is_timezone_aware() -> None:
    assert utc_now().tzinfo is UTC


def test_datetime_is_converted_to_utc() -> None:
    local_time = datetime(2026, 9, 18, 10, 0, tzinfo=timezone(timedelta(hours=-3)))

    assert as_utc(local_time) == datetime(2026, 9, 18, 13, 0, tzinfo=UTC)
    assert to_utc_iso(local_time) == "2026-09-18T13:00:00Z"


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        as_utc(datetime(2026, 9, 18, 10, 0))
