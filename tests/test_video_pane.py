"""Video-pane construction tests."""

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

        def seek(self, target: float, **kwargs: object) -> None:
            self.seek_calls.append((target, kwargs))

    monkeypatch.setattr(video_pane, "probe_libmpv", lambda _parent: True)
    monkeypatch.setattr(video_pane.sys, "platform", "win32")
    monkeypatch.setitem(__import__("sys").modules, "mpv", SimpleNamespace(MPV=FakeMpv))
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)

    pane = video_pane.VideoPane()

    assert pane.gl_widget.parentWidget() is pane
    pane.seek(2.5, exact=True)
    assert pane.mpv.seek_calls == []

    pane._on_file_loaded()
    assert pane.mpv.seek_calls == [(2.5, {"reference": "absolute", "precision": "exact"})]
    assert pane.is_seeking

    pane._observe_seeking(False)
    pane._observe_time(2.5)
    assert not pane.is_seeking
