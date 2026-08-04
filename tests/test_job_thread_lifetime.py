"""A running QThread must outlive whatever started it.

Qt aborts the process outright — "QThread: Destroyed while thread is still
running", SIGABRT, no traceback — if a running QThread is destroyed. `JobManager`
used to parent each thread to itself, so a manager destroyed *without*
`shutdown()` took its running threads down with it and killed the process
instead of closing. Every test harness reaches that path: a window discarded at
teardown never runs `closeEvent`.

It showed up as an intermittent CI abort with only PySide6 in the loaded
extension modules, which is why it read as unrelated to any test's assertions.

These run in a subprocess on purpose. An abort cannot be caught, so an
in-process check would take the whole pytest session with it rather than fail.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

_PREAMBLE = """
import gc, sys, threading
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QApplication
from avialsync.ui.job_manager import JobManager, drain_abandoned

app = QApplication.instance() or QApplication(sys.argv)
release = threading.Event()

class Wedged(QObject):
    finished = Signal()
    error = Signal(str)
    def cancel(self):
        pass
    @Slot()
    def run(self):
        release.wait(timeout=30.0)
        self.finished.emit()

def settle(rounds=200):
    for _ in range(rounds):
        app.processEvents()
"""


def _run(body: str) -> subprocess.CompletedProcess:
    script = textwrap.dedent(_PREAMBLE) + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        env={"QT_QPA_PLATFORM": "offscreen", "PATH": "/usr/bin:/bin"},
    )


def _assert_no_abort(result: subprocess.CompletedProcess) -> None:
    assert "Destroyed while thread" not in result.stderr, result.stderr[-600:]
    assert result.returncode == 0, (
        f"exit {result.returncode} (SIGABRT is 134 or -6)\n{result.stderr[-600:]}"
    )


@pytest.mark.timeout(180)
def test_dropping_a_manager_with_a_running_job_does_not_abort() -> None:
    """The crash: a manager discarded without shutdown, while a job still runs."""
    result = _run(
        """
        def make_and_drop():
            manager = JobManager()
            manager.start("wedged", Wedged())
            settle()
            del manager

        make_and_drop()
        gc.collect()
        settle()
        release.set()
        drain_abandoned()
        print("ok")
        """
    )
    _assert_no_abort(result)
    assert "ok" in result.stdout


@pytest.mark.timeout(180)
def test_a_wedged_job_survives_shutdown_and_drains_cleanly() -> None:
    """The documented path still works: shutdown abandons, drain reclaims."""
    result = _run(
        """
        manager = JobManager()
        manager.start("wedged", Wedged())
        settle()
        abandoned = manager.shutdown(grace_s=0.1)
        assert abandoned == ["wedged"], abandoned
        release.set()
        drain_abandoned()
        from avialsync.ui.job_manager import _ABANDONED
        assert not _ABANDONED, _ABANDONED
        print("ok")
        """
    )
    _assert_no_abort(result)
    assert "ok" in result.stdout


@pytest.mark.timeout(180)
def test_a_finished_job_leaves_nothing_retained() -> None:
    """A job that ends normally must not accumulate in the module registry."""
    result = _run(
        """
        class Quick(QObject):
            finished = Signal()
            error = Signal(str)
            @Slot()
            def run(self):
                self.finished.emit()

        manager = JobManager()
        manager.start("quick", Quick())
        settle()
        drain_abandoned()
        from avialsync.ui.job_manager import _ABANDONED
        assert not _ABANDONED, _ABANDONED
        print("ok")
        """
    )
    _assert_no_abort(result)
    assert "ok" in result.stdout
