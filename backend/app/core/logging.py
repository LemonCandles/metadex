"""JSON logging with recursive redaction of credentials."""

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any, TextIO

from pydantic import SecretStr

from app.core.clock import to_utc_iso, utc_now

LOGGER_NAME = "metadex"
REDACTED = "[REDACTED]"
_SENSITIVE_PARTS = ("api_key", "authorization", "password", "secret", "token")
_STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)


class RedactingJsonFormatter(logging.Formatter):
    """Render one JSON object per line and remove known credentials."""

    def __init__(self, secret_values: Sequence[str] = ()) -> None:
        super().__init__()
        self.secret_values = tuple(value for value in secret_values if value)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": to_utc_iso(utc_now()),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(self._redact(payload), ensure_ascii=False, default=self._json_default)

    def _redact(self, value: Any, *, key: str = "") -> Any:
        normalized_key = key.lower().replace("-", "_")
        if any(part in normalized_key for part in _SENSITIVE_PARTS):
            return REDACTED
        if isinstance(value, SecretStr):
            return REDACTED
        if isinstance(value, Mapping):
            return {
                item_key: self._redact(item, key=str(item_key)) for item_key, item in value.items()
            }
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [self._redact(item) for item in value]
        if isinstance(value, str):
            for secret in self.secret_values:
                value = value.replace(secret, REDACTED)
        return value

    @staticmethod
    def _json_default(value: Any) -> str:
        if isinstance(value, datetime):
            return to_utc_iso(value)
        if isinstance(value, (date, Path)):
            return str(value)
        return repr(value)


def configure_logging(
    *,
    level: int | str = logging.INFO,
    api_key: SecretStr | None = None,
    stream: TextIO | None = None,
) -> logging.Logger:
    """Configure the project logger without exposing the optional API key."""
    secret_values = (api_key.get_secret_value(),) if api_key else ()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingJsonFormatter(secret_values))

    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def get_logger(module_name: str) -> logging.Logger:
    """Return a child logger that follows the shared Metadex configuration."""
    suffix = module_name.removeprefix(f"{LOGGER_NAME}.")
    return logging.getLogger(f"{LOGGER_NAME}.{suffix}")
