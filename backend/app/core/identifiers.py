"""Identifiers for observable pipeline executions."""

from datetime import datetime
from secrets import token_hex

from app.core.clock import to_utc_iso, utc_now


def new_run_id(*, now: datetime | None = None, suffix: str | None = None) -> str:
    """Create a sortable identifier without embedding user or secret data."""
    instant = now or utc_now()
    timestamp = to_utc_iso(instant).replace("-", "").replace(":", "").replace(".", "")
    return f"run_{timestamp}_{suffix or token_hex(4)}"
