"""Video-pane construction tests."""

import threading
from types import SimpleNamespace

from avialview.ui import video_pane


def test_windows_render_widget_has_video_pane_parent(monkeypatch, qapp) -> None:
    """The render API widget owns a native surface below its VideoPane."""

    class FakeMpv:
        def __init__(self, **_options: object) -> None:
            self.seek_calls: list[tuple[float, dict[str, object]]] = []

        def property_observer(self, _name: str):
            return lambda callback: callback

        def event_callback(self, _name: str):
            return lambda callback: callback

        def command_async(self, name: str, *args: object, **kwargs: object) -> None:
            if name == "seek":
                target = args[0]
                self.seek_calls.append((target, args[1:]))

    monkeypatch.setattr(video_pane, "probe_libmpv", lambda _parent: True)
    monkeypatch.setattr(video_pane.sys, "platform", "win32")
    monkeypatch.setitem(__import__("sys").modules, "mpv", SimpleNamespace(MPV=FakeMpv))
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)

    pane = video_pane.VideoPane()

    assert pane.gl_widget.parentWidget() is pane
    pane.seek(2.5, exact=True)
    assert pane.mpv.seek_calls == []

    pane._on_file_loaded()
    assert pane.mpv.seek_calls == [(2.5, ("absolute", "exact"))]
    assert pane.is_seeking

    pane._observe_seeking(False)
    pane._observe_time(2.5)
    assert not pane.is_seeking


def test_video_osd_queue_keeps_only_latest_frame() -> None:
    """A delayed UI thread must not accumulate one OSD event per decoded frame."""

    class _Signal:
        def __init__(self) -> None:
            self.emissions = 0

        def emit(self) -> None:
            self.emissions += 1

    signal = _Signal()
    pane = SimpleNamespace(
        _osd_lock=threading.Lock(),
        _pending_osd=(0.0, 0.0),
        _osd_event_pending=False,
        _osd_update=signal,
    )

    for frame in range(10_000):
        video_pane.VideoPane._queue_osd_update(pane, frame / 30.0, 30.0)

    assert pane._pending_osd == (9999 / 30.0, 30.0)
    assert pane._osd_event_pending is True
    assert signal.emissions == 1
