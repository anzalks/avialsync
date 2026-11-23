"""Tests for workspace layout, multi-monitor detachment, camera reorder, and toolbar labels."""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.commands import ReorderVideosCommand
from avialsync.core.document import Document
from avialsync.core.session import SessionState, VideoEntry
from avialsync.core.settings_schema import setting_for
from avialsync.ui import recovery, workspaces
from avialsync.ui.app_settings import app_settings
from avialsync.ui.main_window import MainWindow
from avialsync.ui.preferences_dialog import write_setting
from avialsync.ui.sidebar import SidebarPane
from avialsync.ui.video_pane import VideoSurface

_META = {"fps": 30.0, "codec": "h264", "duration": 4.0, "file_size_bytes": 2_000_000}


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = app_settings()
    store.clear()
    store.sync()
    yield
    store.clear()
    store.sync()


@pytest.fixture(autouse=True)
def isolated_recovery_dir(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    if isValid(win):
        win.close()


def _install_fake_pane(window: MainWindow, path: str, width: int = 640, height: int = 480) -> None:
    """Insert a lightweight ``VideoPane`` stand-in without spawning a PyAV decoder."""
    from PySide6.QtWidgets import QLabel, QWidget

    class _StandInPane(QWidget):
        def __init__(self, parent: QWidget) -> None:
            super().__init__(parent)
            self.surface = VideoSurface(self)
            self.surface.set_video_size(width, height)
            self.surface.resize(320, 240)
            self.lbl_name = QLabel("", self)
            from avialsync.core.timeline import TimeMap

            self.time_map = TimeMap()
            self.media_path = path
            self.has_media = False
            self.is_seeking = False

        @property
        def video_size(self) -> tuple[int, int] | None:
            return self.surface.video_size

        def set_label(self, text: str) -> None:
            self.lbl_name.setText(text)
            self.lbl_name.setVisible(bool(text))

        def apply_overlay_visibility(self, _vis: dict[str, bool]) -> None:
            pass

        def frame_record_at(self, t_master: float) -> tuple[int, float]:
            return (0, t_master)

        def has_footage_at_master(self, _t: float) -> bool:
            return True

        def set_has_footage(self, flag: bool) -> None:
            self._master_has_footage = flag

        def seek(self, _t: float) -> None:
            pass

        def play(self) -> None:
            pass

        def pause(self) -> None:
            pass

        def close(self) -> bool:
            return super().close()

    grid = window.video_grid
    pane = _StandInPane(grid)
    pane.installEventFilter(grid)
    pane.surface.installEventFilter(grid)
    grid.panes.append(pane)  # type: ignore[arg-type]
    grid._paths.append(path)
    grid._pane_enabled.append(True)
    grid._relayout()
    grid._update_labels()
    window.sidebar.add_video(path, _META)


def test_open_files_disclosure_toggles_cleanly_and_re_expands_on_clear(qtbot) -> None:
    pane = SidebarPane()
    qtbot.addWidget(pane)
    pane.show()
    assert pane.is_open_files_expanded()

    # Stays open while assembling a multi-source session; user can collapse via Hide.
    pane.add_video("/rec/cam0.mp4", _META)
    assert pane.is_open_files_expanded()
    pane.open_files_toggle.click()
    assert not pane.is_open_files_expanded()
    assert pane.open_files_toggle.text() == "Show"

    # Manual collapse sticks across further source loads, and clearing re-expands.
    pane.add_sensor("/rec/imu.csv", ["ax", "ay"])
    assert not pane.is_open_files_expanded()
    pane.clear_sources()
    assert pane.is_open_files_expanded()


def test_detach_3d_imaging_camera_and_inspector_page_and_bring_back(
    window: MainWindow, qapp: QApplication
) -> None:
    _install_fake_pane(window, "/rec/camA.mp4")
    _install_fake_pane(window, "/rec/camB.mp4")

    # Detach 3D View
    window._act_detach_3d.setChecked(True)
    assert window.panel_detachment.tracking_3d_detached
    assert window.imaging_splitter.indexOf(window.tracking_3d_pane) == -1

    # Detach Imaging programmatically
    window.panel_detachment.set_imaging_detached(True)
    assert window.panel_detachment.imaging_detached
    assert window.imaging_splitter.indexOf(window.imaging_pane) == -1

    # Detach one camera
    window.panel_detachment.set_camera_detached("/rec/camA.mp4", True)
    assert window.panel_detachment.is_camera_detached("/rec/camA.mp4")
    assert window.video_grid.is_pane_detached("/rec/camA.mp4")

    # Pop out Values page alongside Sources
    window.panel_detachment.pop_out_inspector_page(1)
    assert window.panel_detachment.is_inspector_page_popped(1)
    assert window._left_tabs.currentIndex() == 0

    qapp.processEvents()
    window._bring_panels_back()
    qapp.processEvents()

    assert not window.panel_detachment.tracking_3d_detached
    assert not window.panel_detachment.imaging_detached
    assert not window.panel_detachment.is_camera_detached("/rec/camA.mp4")
    assert not window.panel_detachment.is_inspector_page_popped(1)
    assert window._left_tabs.widget(1) is window.readout_panel
    assert window.imaging_splitter.indexOf(window.tracking_3d_pane) >= 0
    assert window.imaging_splitter.indexOf(window.imaging_pane) >= 0


def test_camera_reorder_command_and_undo_redo(window: MainWindow) -> None:
    _install_fake_pane(window, "/rec/camA.mp4")
    _install_fake_pane(window, "/rec/camB.mp4")
    _install_fake_pane(window, "/rec/camC.mp4")

    moved = window.video_grid.move_pane("/rec/camC.mp4", -1)
    assert moved == (
        ("/rec/camA.mp4", "/rec/camB.mp4", "/rec/camC.mp4"),
        ("/rec/camA.mp4", "/rec/camC.mp4", "/rec/camB.mp4"),
    )
    assert window.video_grid.pane_paths() == ["/rec/camA.mp4", "/rec/camC.mp4", "/rec/camB.mp4"]
    assert list(window.sidebar._video_widgets) == [
        "/rec/camA.mp4",
        "/rec/camC.mp4",
        "/rec/camB.mp4",
    ]

    assert window.document.undo(window._mutations)
    assert window.video_grid.pane_paths() == ["/rec/camA.mp4", "/rec/camB.mp4", "/rec/camC.mp4"]
    assert window.document.redo(window._mutations)
    assert window.video_grid.pane_paths() == ["/rec/camA.mp4", "/rec/camC.mp4", "/rec/camB.mp4"]


def test_reorder_videos_command_headless() -> None:
    doc = Document()
    target = MagicMock()
    cmd = ReorderVideosCommand(before=("a.mp4", "b.mp4"), after=("b.mp4", "a.mp4"))
    assert cmd.label == "Reorder camera panes"
    doc.execute(cmd, target)
    target.set_video_order.assert_called_once_with(("b.mp4", "a.mp4"))
    doc.undo(target)
    target.set_video_order.assert_called_with(("a.mp4", "b.mp4"))


def test_camera_zoom_pan_and_3d_orientation_persist_in_workspace_and_session(
    window: MainWindow,
) -> None:
    _install_fake_pane(window, "/rec/camA.mp4")
    _install_fake_pane(window, "/rec/camB.mp4")

    pane_a = window.video_grid.panes[0]
    pane_a.surface.set_view_transform(2.5, 12.0, -8.0)
    window.tracking_3d_pane.set_up_axis(1, True)
    window.tracking_3d_pane.set_view_orientation(
        {
            "up_axis": 1,
            "up_inverted": True,
            "up_auto": False,
            "azimuth": math.radians(110.0),
            "elevation": math.radians(-15.0),
            "zoom": 1.8,
            "pan_x": 14.0,
            "pan_y": -6.0,
        }
    )

    # Named Workspace round-trip
    workspaces.save("ZoomedPose", workspaces.capture(window))
    pane_a.surface.reset_view()
    window.tracking_3d_pane.canvas.reset_view()
    loaded_ws = workspaces.load("ZoomedPose")
    assert loaded_ws is not None
    workspaces.apply(window, loaded_ws)
    zoom, px, py = pane_a.surface.view_transform()
    assert zoom == pytest.approx(2.5)
    assert (px, py) == pytest.approx((12.0, -8.0))
    orient = window.tracking_3d_pane.view_orientation()
    assert orient["up_axis"] == 1 and orient["up_inverted"] is True
    assert orient["zoom"] == pytest.approx(1.8)

    # SessionState (.avv) dict round-trip
    state = window._build_session_state()
    reloaded = SessionState.from_dict(state.to_dict())
    assert reloaded.videos[0].view["zoom"] == pytest.approx(2.5)
    assert reloaded.view_3d["zoom"] == pytest.approx(1.8)

    # Deferred VideoSurface view applies cleanly once dimensions arrive
    deferred = VideoSurface()
    deferred.set_view_transform(3.0, 10.0, -5.0)
    assert deferred.view_transform() == pytest.approx((3.0, 10.0, -5.0))
    deferred.resize(320, 240)
    deferred.set_video_size(640, 480)
    assert deferred.view_transform()[0] == pytest.approx(3.0)

    # VideoEntry default view stays empty for unzoomed cameras
    assert VideoEntry(path="/rec/camB.mp4").view == {}


def test_optional_toolbar_labels_and_status_tips(window: MainWindow) -> None:
    toolbar = window.view_toolbar
    # Default is glyph-only (D-174)
    assert toolbar.flag_button.text() == ""
    assert toolbar.snapshot_button.text() == ""
    assert toolbar.flag_button.statusTip() != ""
    assert toolbar.snapshot_button.statusTip() != ""

    setting = setting_for("interface/toolbar_labels")
    assert setting is not None
    write_setting(setting, True)
    window._help_controller.on_setting_changed("interface/toolbar_labels")
    assert toolbar.flag_button.text() == "Flag"
    assert toolbar.snapshot_button.text() == "Snapshot"
    assert toolbar.fit_videos_button.text() == "Fit All"

    write_setting(setting, False)
    window._help_controller.on_setting_changed("interface/toolbar_labels")
    assert toolbar.flag_button.text() == ""
    assert toolbar.snapshot_button.text() == ""


def test_video_grid_drag_reorders_tiles(window: MainWindow, qtbot) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    window.resize(960, 640)
    _install_fake_pane(window, "/rec/camA.mp4")
    _install_fake_pane(window, "/rec/camB.mp4")
    QApplication.processEvents()

    pane_a, pane_b = window.video_grid.panes
    start_global = pane_a.mapToGlobal(QPoint(20, 20))
    end_global = pane_b.mapToGlobal(QPoint(20, 20))
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(20, 20),
        QPointF(start_global),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.AltModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(pane_a.mapFromGlobal(end_global)),
        QPointF(end_global),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.AltModifier,
    )
    window.video_grid.eventFilter(pane_a, press)
    window.video_grid.eventFilter(pane_a, release)
    assert window.video_grid.pane_paths() == ["/rec/camB.mp4", "/rec/camA.mp4"]
