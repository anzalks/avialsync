"""Pytest configuration."""

from collections.abc import Iterator

import pytest


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
