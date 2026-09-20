import json
import logging
from io import StringIO

import pytest
from pydantic import SecretStr

from app.core.logging import REDACTED, configure_logging, get_logger
from app.core.runs import RunRecord

pytestmark = pytest.mark.unit


def test_log_is_structured_and_contains_run_context() -> None:
    output = StringIO()
    configure_logging(stream=output)
    logger = get_logger(__name__)
    run = RunRecord(operation="collect", run_id="run_test")

    logger.info("execution_started", extra={"event": "execution_started", **run.as_log_context()})

    payload = json.loads(output.getvalue())
    assert payload["level"] == "info"
    assert payload["event"] == "execution_started"
    assert payload["run_id"] == "run_test"
    assert payload["attempts"] == 0
    assert payload["failures"] == 0


def test_secret_is_redacted_from_keys_nested_values_and_messages() -> None:
    secret = "super-secret-key"
    output = StringIO()
    configure_logging(api_key=SecretStr(secret), stream=output)
    logger = get_logger(__name__)

    logger.warning(
        "request failed with %s",
        secret,
        extra={
            "event": "request_failed",
            "api_key": secret,
            "request": {
                "authorization": f"Bearer {secret}",
                "url": f"https://example.test?api_key={secret}",
            },
        },
    )

    rendered = output.getvalue()
    payload = json.loads(rendered)
    assert secret not in rendered
    assert payload["api_key"] == REDACTED
    assert payload["request"]["authorization"] == REDACTED
    assert REDACTED in payload["message"]


def test_logger_does_not_duplicate_handlers_after_reconfiguration() -> None:
    first_output = StringIO()
    second_output = StringIO()
    configure_logging(stream=first_output)
    configure_logging(stream=second_output)

    get_logger(__name__).log(logging.INFO, "one_event")

    assert first_output.getvalue() == ""
    assert len(second_output.getvalue().splitlines()) == 1
