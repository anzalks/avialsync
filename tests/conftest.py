"""Pytest configuration."""

import faulthandler
import sys
from collections.abc import Iterator
from typing import TextIO

import pytest


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    """Re-arm faulthandler without its all-threads walk on Windows.

    pytest enables faulthandler with ``all_threads=True``. On Windows that
    installs a *vectored* exception handler, which the OS runs on first chance
    for every SEH exception in the process, on whatever thread raised it.

    libmpv raises ``0xe24c4a02`` on its own native threads routinely — several
    times per ``mpv.MPV()`` construction. CPython only ignores non-error codes
    and MSC C++ exceptions (``0xe06d7363``), so this one is treated as fatal:
    faulthandler prints "Windows fatal exception: code 0xe24c4a02" and then
    calls ``_Py_DumpTracebackThreads`` to walk *every* Python thread's frame
    chain — from a libmpv thread that holds no GIL and has no thread state,
    while the owning threads are pushing and popping those frames. Reading a
    frame whose memory has already been reused faults the process with
    ``0xC0000005``, charged to whichever test happened to be running.

    That benign-looking exception is therefore not the crash, but it is the
    trigger: the fault is inside the diagnostic, not inside anything AvialSync
    or libmpv does with the video panes.

    ``all_threads=False`` keeps faulthandler reporting real faults that happen
    on a Python thread, and drops only the cross-thread walk that is unsafe
    from a foreign thread. Every other platform keeps pytest's default.
    """
    if sys.platform != "win32":
        return

    # pytest dups stderr so its handler keeps working under capture; reuse that
    # fd rather than a second one. The stash key is private API, so fall back to
    # the real stderr rather than losing the fault report if it ever moves.
    stream: int | TextIO | None = sys.__stderr__
    try:
        from _pytest.faulthandler import fault_handler_stderr_fd_key
    except ImportError:
        pass
    else:
        if fault_handler_stderr_fd_key in config.stash:
            stream = config.stash[fault_handler_stderr_fd_key]

    if stream is not None:
        faulthandler.enable(file=stream, all_threads=False)


@pytest.fixture(autouse=True)
def no_startup_libmpv_probe(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep the startup probe from building a real libmpv client mid-suite.

    ``MainWindow`` schedules ``_run_diagnostics`` 500 ms after construction, and
    the probe behind it constructs and terminates a real ``mpv.MPV`` on a daemon
    thread. Which test is running when that timer fires is a race, so a native
    fault in the probe is charged to whatever unrelated test is in flight — the
    symptom that made the Windows fault so hard to place (HANDOUT.md "Pending").
    Only the tests that build a pane on purpose should own a client.

    The two module globals are reset per test for the same reason: both cache
    across the whole session, so whether a probe runs at all otherwise depends
    on test order.
    """
    from avialsync.ui import diagnostics
    from avialsync.ui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "_run_diagnostics", lambda _self: None)
    monkeypatch.setattr(diagnostics, "_STARTUP_DIAGNOSTICS", None)
    monkeypatch.setattr(diagnostics, "_LIBMPV_AVAILABLE", None)
    yield
