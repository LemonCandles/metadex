"""UTC clock helpers shared by the pipeline and API."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return a timezone-aware current instant in UTC."""
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Convert an aware datetime to UTC without guessing a missing timezone."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include timezone information")
    return value.astimezone(UTC)


def to_utc_iso(value: datetime) -> str:
    """Serialize an aware datetime with the explicit UTC suffix."""
    return as_utc(value).isoformat().replace("+00:00", "Z")
