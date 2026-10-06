"""Compact source cards (D-175, INTERFACE_DESIGN_PLAN DS-7)."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from avialsync.ui.elided_label import ElidedLabel
from avialsync.ui.sidebar import SensorInfoWidget, SidebarPane, VideoInfoWidget
from avialsync.ui.source_card import short_path

_META = {"fps": 30.0, "codec": "h264", "duration": 4.0, "file_size_bytes": 2_000_000}


def test_timing_sits_behind_a_disclosure_over_the_same_spin_boxes(qtbot) -> None:
    card = VideoInfoWidget("/rec/camera_1.mp4", _META)
    qtbot.addWidget(card)
    card.show()
    assert not card.timing.is_open()
    assert not card.offset_spin.isVisible()
    card.offset_spin.setValue(0.25)
    assert card.timing.summary() == "+0.250000 s · 0 ms/h"
    card.drift_spin.setValue(54.0)
    assert card.timing.summary() == "+0.250000 s · +54.0 ms/h"
    assert "frames/h" in card.drift_spin.toolTip(), "the drift in frames, at this camera's rate"
    card.timing.set_open(True)
    assert card.offset_spin.isVisible() and card.drift_spin.isVisible()
    assert card.timing.body.isAncestorOf(card.offset_spin), "the one authority, not a copy"


def test_remove_is_in_the_overflow_last_and_marked(qtbot) -> None:
    card = VideoInfoWidget("/rec/camera_1.mp4", _META)
    qtbot.addWidget(card)
    removed: list[str] = []
    card.remove_requested.connect(removed.append)
    actions = [a for a in card.more_button.menu().actions() if not a.isSeparator()]
    assert [a.text() for a in actions] == ["Properties", "Copy details", "Remove video source"]
    assert actions[-1].property("av_role") == "destructive"
    assert not actions[-1].icon().isNull(), "marked by glyph, not by colour alone"
    actions[-1].trigger()
    assert removed == ["/rec/camera_1.mp4"]
    actions[1].trigger()
    assert "camera_1.mp4" in QApplication.clipboard().text()


def test_every_way_in_is_one_visible_button_and_reset_stands_apart(qtbot) -> None:
    """D-181: one full-width button per way to open, none behind a menu.

    D-175's split button showed only Open Videos; Sensor/Ephys Data, Session and
    Synchronize hid behind its arrow. Each is visible again, and each is its
    menu's own QAction (rule 15). Reset Session is last, after a gap, marked
    destructive by glyph as well as place.
    """
    from avialsync.ui.design_tokens import ControlRole, role_of

    pane = SidebarPane()
    qtbot.addWidget(pane)
    open_video = QAction("Open Videos…", pane)
    open_sensor = QAction("Open Sensor/Ephys Data…", pane)
    open_imaging = QAction("Open 2P Imaging…", pane)
    open_session = QAction("Open Session…", pane)
    sync = QAction("Synchronize TTL / events…", pane)
    reset = QAction("Reset Session", pane)
    pane.install_open_actions(open_video, open_sensor, reset)
    pane.install_open_imaging_action(open_imaging)
    pane.install_open_session_action(open_session)
    pane.install_align_action(sync)
    pane.resize(280, 600)
    pane.show()
    buttons = [
        pane.btn_open_video,
        pane.btn_open_sensor,
        pane.btn_open_imaging,
        pane.btn_open_session,
        pane.btn_align,
        pane.btn_reset_session,
    ]
    assert [b.action for b in buttons] == [
        open_video,
        open_sensor,
        open_imaging,
        open_session,
        sync,
        reset,
    ]
    assert all(b.isVisible() and b.text() == b.action.text() for b in buttons)
    tops = [b.geometry().top() for b in buttons]
    assert tops == sorted(tops), "stacked in the order a session is built"
    assert role_of(pane.btn_open_video) is ControlRole.PRIMARY
    assert role_of(pane.btn_reset_session) is ControlRole.DESTRUCTIVE
    assert pane._scroll_area.horizontalScrollBar().maximum() == 0


def test_paths_show_their_folder_not_the_whole_tree(qtbot) -> None:
    raw = "/var/folders/sc/abc123/T/tmpxyz/session_7/force.csv"
    assert short_path(raw) == "…/session_7/force.csv"
    assert short_path(raw, "/var/folders/sc/abc123/T/tmpxyz") == "session_7/force.csv"
    card = SensorInfoWidget(raw, ["a", "b"])
    qtbot.addWidget(card)
    shown = [label.fullText() for label in card.findChildren(ElidedLabel)]
    assert "…/session_7/force.csv" in shown and raw not in shown


def test_four_cameras_and_twelve_files_show_every_name_and_badge(qtbot, qapp) -> None:
    """DS-7 acceptance at the 280 px default inspector width, compact density."""
    pane = SidebarPane()
    qtbot.addWidget(pane)
    pane.resize(280, 800)
    for index in range(4):
        pane.add_video(f"/rec/camera_{index}.mp4", _META)
    for index in range(12):
        pane.add_sensor(f"/rec/data/signal_{index}.csv", ["ch0", "ch1"])
    pane.show()
    qapp.processEvents()
    viewport = pane._scroll_area.viewport()
    assert pane._scroll_area.horizontalScrollBar().maximum() == 0
    cards = pane.findChildren(VideoInfoWidget) + pane.findChildren(SensorInfoWidget)
    assert len(cards) == 16
    for card in cards:
        card._badge_btn.setVisible(True)
    qapp.processEvents()
    for card in cards:
        right = card._badge_btn.mapTo(viewport, card._badge_btn.rect().topRight()).x()
        assert right <= viewport.width(), f"{card.path}: badge is off the edge"
        names = [w for w in card.findChildren(ElidedLabel) if w.toolTip() == card.path]
        assert names and names[0].width() > 0


def test_align_has_a_one_click_entry_beside_open_and_no_toolbar(qtbot) -> None:
    """D-178: no main toolbar; Align → Synchronize sits with the open buttons (D-181)."""
    from PySide6.QtWidgets import QToolBar

    from avialsync.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.findChildren(QToolBar) == []
    button = window.sidebar.btn_align
    assert button.action is window._act_synchronize
    assert button.text() == window._act_synchronize.text()
    window.close()
