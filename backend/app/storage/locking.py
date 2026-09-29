"""Nonblocking, reentrant file locks shared by every local data writer."""

import asyncio
import fcntl
import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from pathlib import Path

from app.core.errors import RecoverableError
from app.core.paths import DataPaths


class WriterBusyError(RecoverableError):
    """Another command already owns one of the data locations."""


_held: ContextVar[tuple[object, frozenset[Path]] | None] = ContextVar("writer_locks", default=None)


@contextmanager
def writer_lock(*lock_files: Path) -> Iterator[None]:
    """Keep stable lock files: unlinking one would let writers lock different inodes."""
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    owner = (threading.get_ident(), task)
    inherited = _held.get()
    held = inherited[1] if inherited is not None and inherited[0] == owner else frozenset()
    requested = frozenset(path.resolve() for path in lock_files)
    with ExitStack() as stack:
        for path in sorted(requested - held):
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = stack.enter_context(path.open("a"))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise WriterBusyError(f"another data writer is active: {path}") from exc
            stack.callback(fcntl.flock, handle, fcntl.LOCK_UN)
        token = _held.set((owner, held | requested))
        try:
            yield
        finally:
            _held.reset(token)


@contextmanager
def pipeline_writer_lock(paths: DataPaths) -> Iterator[None]:
    """Cover raw, processed and catalog writes, including separately configured paths."""
    with writer_lock(
        paths.raw / ".writer.lock",
        paths.processed / ".writer.lock",
        paths.duckdb.with_suffix(".duckdb.writer.lock"),
    ):
        yield
