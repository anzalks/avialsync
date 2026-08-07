"""Startup diagnostics lifecycle tests."""

from types import SimpleNamespace

from avialsync.ui import diagnostics


def test_hwdec_probe_reports_what_ffmpeg_was_built_against() -> None:
    """Informational only — software decode already meets every budget (D-075).

    PyAV carries its own FFmpeg, so this can never fail for a missing library
    the way the libmpv probe could; it reports a capability rather than gating
    playback on one.
    """
    result = diagnostics.probe_hwdec()

    assert isinstance(result["available"], bool)
    assert isinstance(result["decoders"], list)
    assert all(isinstance(name, str) for name in result["decoders"])
    assert result["available"] == bool(result["decoders"])


def test_hwdec_probe_survives_a_decoder_that_cannot_be_queried(monkeypatch) -> None:
    """A failed capability query must stay observable rather than raise."""
    import av.codec.hwaccel

    def _boom():
        raise RuntimeError("probe failed")

    monkeypatch.setattr(av.codec.hwaccel, "hwdevices_available", _boom)

    result = diagnostics.probe_hwdec()

    assert result["available"] is False
    assert "probe failed" in result["error"]


def test_diagnostics_report_names_the_decoder_actually_in_use() -> None:
    """A bug report has to say what decoded the video, not what is installed."""
    text = diagnostics.format_diagnostics({"hwdec": {}, "disk_speed_mbps": 120.0})

    assert "PyAV" in text
    assert "libmpv" not in text


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
