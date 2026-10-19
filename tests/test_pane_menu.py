"""The video pane's right-click menu routes each choice to the window.

WINDOW_COMPOSITION_PLAN A5 moved it out of MainWindow; nothing tested it before.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from avialsync.ui.menus import pane_menu
from avialsync.ui.overlay_registry import OVERLAY_LAYERS, OverlayState


class _Grid:
    point_edit_mode = False

    def __init__(self) -> None:
        self.fullscreen: list[str] = []

    def custom_marker_at(self, _path: str, _pos: Any) -> None:
        return None

    def toggle_fullscreen(self, path: str) -> None:
        self.fullscreen.append(path)

    def frame_records_at(self, _t: float) -> list[dict[str, Any]]:
        return [
            {"path": "/cam1.mp4", "frame_index": 12, "media_timestamp": 0.4},
            {"path": "/cam2.mp4", "frame_index": 99, "media_timestamp": 3.3},
        ]


class _Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.video_grid = _Grid()
        self.overlay_state = OverlayState()
        self.clock = SimpleNamespace(state=SimpleNamespace(t=0.4))
        self.calls: list[tuple[Any, ...]] = []

    def _on_overlay_toggled(self, overlay_id: str, visible: bool, camera: str | None) -> None:
        self.calls.append(("overlay", overlay_id, visible, camera))

    def _apply_overlay_state(self) -> None:
        self.calls.append(("apply",))

    def _export_snapshot_for_pane(self, path: str) -> None:
        self.calls.append(("snapshot", path))

    def _show_video_properties(self, path: str) -> None:
        self.calls.append(("properties", path))


def _choose(monkeypatch: pytest.MonkeyPatch, label: str) -> None:
    """Make the menu return the action named *label* instead of blocking."""

    class _ScriptedMenu(QMenu):
        # A Python subclass: patching QMenu.exec itself does not reach a call
        # Shiboken dispatches, so the real menu would open and wait.
        def exec(self, *_args: Any) -> Any:
            menus = [self, *(a.menu() for a in self.actions() if a.menu())]
            return next(a for m in menus for a in m.actions() if a.text() == label)

    monkeypatch.setattr(pane_menu, "QMenu", _ScriptedMenu)


@pytest.fixture
def window(qapp: QApplication, qtbot) -> _Window:
    win = _Window()
    qtbot.addWidget(win)
    return win


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Snapshot this camera", ("snapshot", "/cam1.mp4")),
        ("Properties…", ("properties", "/cam1.mp4")),
    ],
)
def test_a_command_reaches_the_window_for_that_camera(
    window: _Window, monkeypatch: pytest.MonkeyPatch, label: str, expected: tuple
) -> None:
    _choose(monkeypatch, label)
    pane_menu.show_pane_menu(window, "/cam1.mp4", QPoint())
    assert window.calls == [expected]


def test_fullscreen_enlarges_the_clicked_camera(window: _Window, monkeypatch) -> None:
    _choose(monkeypatch, "Fullscreen this camera")
    pane_menu.show_pane_menu(window, "/cam2.mp4", QPoint())
    assert window.video_grid.fullscreen == ["/cam2.mp4"]


def test_a_camera_overlay_override_names_the_camera(window: _Window, monkeypatch) -> None:
    layer = next(item for item in OVERLAY_LAYERS if item.per_camera and not item.locked)
    _choose(monkeypatch, layer.label)
    pane_menu.show_pane_menu(window, "/cam1.mp4", QPoint())
    shown = window.overlay_state.is_visible(layer.overlay_id)
    assert window.calls == [("overlay", layer.overlay_id, shown, "/cam1.mp4")]


def test_follow_the_view_menu_clears_overrides_and_reapplies(window: _Window, monkeypatch) -> None:
    layer = next(item for item in OVERLAY_LAYERS if item.per_camera and not item.locked)
    window.overlay_state.set_visible(layer.overlay_id, False, "/cam1.mp4")
    _choose(monkeypatch, "Follow the View menu")
    pane_menu.show_pane_menu(window, "/cam1.mp4", QPoint())
    assert window.calls == [("apply",)]
    assert window.overlay_state.is_visible(layer.overlay_id, "/cam1.mp4") == (
        window.overlay_state.is_visible(layer.overlay_id)
    )


def test_copy_frame_info_copies_only_the_clicked_camera(
    window: _Window, monkeypatch, qapp: QApplication
) -> None:
    _choose(monkeypatch, "Copy frame info")
    pane_menu.show_pane_menu(window, "/cam2.mp4", QPoint())
    assert qapp.clipboard().text() == "path=/cam2.mp4\nframe=99\nmedia_t=3.300000"
