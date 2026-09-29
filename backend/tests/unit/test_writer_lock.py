"""An actual competing process must be refused, and exit must release the lock."""

import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import BACKEND_ROOT
from app.storage.locking import writer_lock

pytestmark = pytest.mark.unit


def test_lock_is_reentrant_and_blocks_another_process(tmp_path: Path) -> None:
    path = tmp_path / ".writer.lock"
    script = """
import sys
from pathlib import Path
from app.storage.locking import WriterBusyError, writer_lock
try:
    with writer_lock(Path(sys.argv[1])):
        pass
except WriterBusyError:
    raise SystemExit(2)
"""
    with writer_lock(path), writer_lock(path):
        child = subprocess.run(
            [sys.executable, "-c", script, str(path)],
            check=False,
            cwd=BACKEND_ROOT,
            timeout=10,
        )
        assert child.returncode == 2
    child = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        check=False,
        cwd=BACKEND_ROOT,
        timeout=10,
    )
    assert child.returncode == 0
    assert path.is_file()
