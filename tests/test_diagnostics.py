"""Startup diagnostics lifecycle tests."""

import sys
from types import SimpleNamespace

from avialsync.ui import diagnostics


def test_hwdec_probe_reports_failure_and_terminates_player(monkeypatch) -> None:
    """A failed capability query must remain observable and release libmpv."""
    terminated: list[bool] = []

    class _Player:
        @property
        def hwdec(self):
            raise RuntimeError("probe failed")

        def terminate(self) -> None:
            terminated.append(True)

    fake_mpv = SimpleNamespace(MPV=lambda **_kwargs: _Player())
    monkeypatch.setitem(sys.modules, "mpv", fake_mpv)
    monkeypatch.setattr(diagnostics, "_LIBMPV_AVAILABLE", True)

    result = diagnostics.probe_hwdec()

    assert result["available"] is False
    assert "probe failed" in result["error"]
    assert terminated == [True]


def test_disk_probe_uses_unique_file_and_cleans_it(tmp_path) -> None:
    """Concurrent app instances must not contend for one fixed probe filename."""
    speed = diagnostics.probe_disk_speed(str(tmp_path))

    assert speed >= 0.0
    assert list(tmp_path.iterdir()) == []


def test_startup_diagnostics_starts_one_background_probe(monkeypatch) -> None:
    """Repeated windows share one diagnostics probe instead of spawning threads."""
    started: list[object] = []

    class _Thread:
        def __init__(self, *, target, daemon, name) -> None:
            self.target = target
            self.daemon = daemon
            self.name = name

        def start(self) -> None:
            started.append(self)

    monkeypatch.setattr(diagnostics, "_STARTUP_DIAGNOSTICS", None)
    monkeypatch.setattr(diagnostics, "threading", SimpleNamespace(Thread=_Thread))

    first = diagnostics.run_startup_diagnostics()
    second = diagnostics.run_startup_diagnostics()

    assert first is second
    assert len(started) == 1
