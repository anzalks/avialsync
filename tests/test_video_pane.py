"""Video-pane construction tests."""

import sys
import threading
from types import SimpleNamespace

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from avialsync.ui import video_pane


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


# ── libmpv missing: guided dialog, then a usable pane (V-11 / D-013) ──


def _pane_without_libmpv(monkeypatch):
    """Construct a VideoPane as if the libmpv probe had failed."""
    import avialsync.ui.video_pane as video_pane_module

    monkeypatch.setattr(video_pane_module, "probe_libmpv", lambda _pane: False)
    return video_pane_module.VideoPane()


def test_pane_without_libmpv_still_builds_its_overlay(qapp, monkeypatch) -> None:
    """__init__ used to abort before the labels existed."""
    pane = _pane_without_libmpv(monkeypatch)

    assert pane.paint_canvas is not None
    assert pane.overlay is not None
    assert pane.lbl_name is not None
    assert pane.lbl_osd is not None
    assert pane.lbl_no_footage is not None


def test_pane_without_libmpv_says_why(qapp, monkeypatch) -> None:
    pane = _pane_without_libmpv(monkeypatch)

    assert pane.lbl_no_footage.isVisible() or pane.lbl_no_footage.text()
    assert "libmpv" in pane.lbl_no_footage.text()


def test_pane_without_libmpv_survives_the_normal_call_sequence(qapp, monkeypatch) -> None:
    """Every one of these raised AttributeError after the guided dialog."""
    pane = _pane_without_libmpv(monkeypatch)

    pane.set_label("Camera 1")
    pane.set_has_footage(False)
    pane.set_has_footage(True)
    pane.set_tracking_readers([])

    assert pane.lbl_name.text() == "Camera 1"


def test_pane_without_libmpv_reports_no_media(qapp, monkeypatch) -> None:
    pane = _pane_without_libmpv(monkeypatch)

    assert pane.mpv is None
    assert pane._video_widget is None


# ── libmpv's event thread must not outlive the pane (Windows fault) ──


class _FakePlayer:
    """Stands in for an mpv client so the check needs no libmpv."""

    def __init__(self, **_options) -> None:
        self.terminated = 0
        self.observers: dict[str, object] = {}

    def property_observer(self, name: str):
        def register(function):
            self.observers[name] = function
            return function

        return register

    def event_callback(self, name: str):
        def register(function):
            self.observers[name] = function
            return function

        return register

    def terminate(self) -> None:
        self.terminated += 1


class _FakeMpvModule:
    """The subset of `import mpv` that constructing a pane touches."""

    def __init__(self) -> None:
        self.players: list[_FakePlayer] = []

    def MPV(self, **options) -> _FakePlayer:  # noqa: N802 - mirrors python-mpv
        player = _FakePlayer(**options)
        self.players.append(player)
        return player


def _pane_with_fake_mpv(monkeypatch) -> tuple[object, _FakePlayer]:
    """Build a pane through its real mpv path, with a stand-in client.

    Goes through `VideoPane.__init__` rather than wiring teardown by hand, so
    the production wiring is what is under test. A test that connects
    `destroyed` itself passes even when the application never does.
    """
    import avialsync.ui.video_pane as video_pane_module

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(video_pane_module, "probe_libmpv", lambda _pane: True)
    fake_module = _FakeMpvModule()
    monkeypatch.setitem(sys.modules, "mpv", fake_module)

    pane = video_pane_module.VideoPane()
    assert fake_module.players, "the pane never created a client"
    return pane, fake_module.players[0]


def test_an_observer_survives_a_destroyed_pane(qapp, monkeypatch) -> None:
    """A callback arriving after teardown must not escape into libmpv's thread.

    python-mpv runs these on its own event thread and only warns about an
    exception; on Windows, touching the freed C++ half faults the process
    instead.
    """
    pane, player = _pane_with_fake_mpv(monkeypatch)
    observers = dict(player.observers)
    assert "time-pos" in observers, sorted(observers)

    pane.deleteLater()
    del pane
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()

    values = {
        "time-pos": 1.0,
        "estimated-vf-fps": 30.0,
        "seeking": True,
        "video-out-params": {"dw": 4, "dh": 2},
    }
    for name, callback in observers.items():
        if name == "file-loaded":
            callback(object())  # an event callback takes the event alone
        else:
            callback(name, values[name])
