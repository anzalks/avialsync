"""Video-pane construction tests."""

from types import SimpleNamespace

from avialview.ui import video_pane


def test_windows_render_widget_has_video_pane_parent(monkeypatch, qapp) -> None:
    """The render API widget owns a native surface below its VideoPane."""

    class FakeMpv:
        def __init__(self, **_options: object) -> None:
            pass

        def property_observer(self, _name: str):
            return lambda callback: callback

    monkeypatch.setattr(video_pane, "probe_libmpv", lambda _parent: True)
    monkeypatch.setattr(video_pane.sys, "platform", "win32")
    monkeypatch.setitem(__import__("sys").modules, "mpv", SimpleNamespace(MPV=FakeMpv))
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)

    pane = video_pane.VideoPane()

    assert pane.gl_widget.parentWidget() is pane
