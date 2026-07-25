"""Startup diagnostics lifecycle tests."""

from types import SimpleNamespace

from kinochronix.ui import diagnostics


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
