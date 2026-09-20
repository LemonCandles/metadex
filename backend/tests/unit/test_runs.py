from datetime import UTC, datetime, timedelta

import pytest

from app.core.runs import RunRecord, RunStatus

pytestmark = pytest.mark.unit


def test_finished_run_exposes_structured_operational_context() -> None:
    started_at = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    run = RunRecord(operation="collect_public_matches", run_id="run_test", started_at=started_at)
    run.requested_count = 100
    run.received_count = 80
    run.processed_count = 75
    run.attempts = 2
    run.failures = 1

    run.finish(RunStatus.PARTIAL, finished_at=started_at + timedelta(milliseconds=1250))

    assert run.as_log_context() == {
        "run_id": "run_test",
        "operation": "collect_public_matches",
        "status": "partial",
        "started_at": "2026-09-18T12:00:00Z",
        "finished_at": "2026-09-18T12:00:01.250000Z",
        "duration_ms": 1250,
        "requested_count": 100,
        "received_count": 80,
        "processed_count": 75,
        "attempts": 2,
        "failures": 1,
    }


def test_run_rejects_invalid_lifecycle_values() -> None:
    started_at = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="operation"):
        RunRecord(operation=" ", started_at=started_at)

    run = RunRecord(operation="collect", started_at=started_at)
    with pytest.raises(ValueError, match="remain running"):
        run.finish(RunStatus.RUNNING)
    with pytest.raises(ValueError, match="earlier"):
        run.finish(RunStatus.FAILED, finished_at=started_at - timedelta(seconds=1))


def test_run_rejects_negative_counters_when_finished() -> None:
    run = RunRecord(operation="collect")
    run.failures = -1

    with pytest.raises(ValueError, match="negative"):
        run.finish(RunStatus.FAILED)
