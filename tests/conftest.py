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

    libmpv used to raise ``0xe24c4a02`` on its own native threads routinely,
    several times per ``mpv.MPV()`` construction. CPython only ignores
    non-error codes and MSC C++ exceptions (``0xe06d7363``), so that one was
    treated as fatal: faulthandler called ``_Py_DumpTracebackThreads`` to walk
    *every* Python thread's frame chain — from a libmpv thread holding no GIL
    and having no thread state, while the owning threads pushed and popped
    those frames. Reading a reused frame faulted the process with
    ``0xC0000005``, charged to whichever test happened to be running.

    **That trigger is gone with libmpv (D-075).** This is retained as cheap
    insurance, not because anything is known to need it: PyAV's FFmpeg does not
    raise SEH exceptions on foreign threads the way libmpv did. It costs only
    the cross-thread walk in a Windows fault report, which is unsafe from a
    foreign thread anyway. See HANDOUT.md trap 30 before removing it — the
    failure it prevented took weeks to attribute.
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
def no_startup_diagnostics(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep the startup diagnostics off the suite's background threads.

    ``MainWindow`` schedules ``_run_diagnostics`` 500 ms after construction, and
    it writes a 32 MB file to measure disk speed on a daemon thread. Which test
    is running when that timer fires is a race, so its cost — and any failure —
    lands on whatever unrelated test is in flight.

    This used to guard something sharper: the probe behind it constructed and
    terminated a real ``mpv.MPV``, and a native fault there was charged to an
    innocent test, which is what made the Windows fault so hard to place. That
    probe is gone with libmpv (D-075); the disk measurement is reason enough to
    keep the fixture.

    ``_STARTUP_DIAGNOSTICS`` is reset per test because it caches for the whole
    session, so whether the work runs at all would otherwise depend on order.
    """
    from avialsync.ui import diagnostics
    from avialsync.ui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "_run_diagnostics", lambda _self: None)
    monkeypatch.setattr(diagnostics, "_STARTUP_DIAGNOSTICS", None)
    yield
