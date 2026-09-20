"""In-memory execution record shared by future pipeline commands."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.core.clock import as_utc, to_utc_iso, utc_now
from app.core.identifiers import new_run_id


class RunStatus(StrEnum):
    """Lifecycle states for one pipeline execution."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(slots=True)
class RunRecord:
    """Operational counters and timing for one execution."""

    operation: str
    run_id: str = field(default_factory=new_run_id)
    started_at: datetime = field(default_factory=utc_now)
    status: RunStatus = RunStatus.RUNNING
    finished_at: datetime | None = None
    requested_count: int = 0
    received_count: int = 0
    processed_count: int = 0
    attempts: int = 0
    failures: int = 0

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("operation must not be empty")
        self.started_at = as_utc(self.started_at)
        self._validate_counters()

    @property
    def duration_ms(self) -> int | None:
        """Return elapsed milliseconds once the execution has finished."""
        if self.finished_at is None:
            return None
        return round((self.finished_at - self.started_at).total_seconds() * 1000)

    def finish(
        self,
        status: RunStatus,
        *,
        finished_at: datetime | None = None,
    ) -> None:
        """Close an execution with an explicit terminal state."""
        if status is RunStatus.RUNNING:
            raise ValueError("a finished run cannot remain running")
        end = as_utc(finished_at or utc_now())
        if end < self.started_at:
            raise ValueError("finished_at cannot be earlier than started_at")
        self.finished_at = end
        self.status = status
        self._validate_counters()

    def as_log_context(self) -> dict[str, str | int | None]:
        """Expose the required structured log fields with stable names."""
        return {
            "run_id": self.run_id,
            "operation": self.operation,
            "status": self.status.value,
            "started_at": to_utc_iso(self.started_at),
            "finished_at": to_utc_iso(self.finished_at) if self.finished_at else None,
            "duration_ms": self.duration_ms,
            "requested_count": self.requested_count,
            "received_count": self.received_count,
            "processed_count": self.processed_count,
            "attempts": self.attempts,
            "failures": self.failures,
        }

    def _validate_counters(self) -> None:
        counters = (
            self.requested_count,
            self.received_count,
            self.processed_count,
            self.attempts,
            self.failures,
        )
        if any(value < 0 for value in counters):
            raise ValueError("run counters cannot be negative")
