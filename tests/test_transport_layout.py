"""Tests for the two-row timeline and status transport layout."""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication

from avialsync.ui.main_window import MainWindow
from avialsync.ui.plot_pane import PlotPane
from avialsync.ui.theme import status_color
from avialsync.ui.transport import Transport, _paint_span
from avialsync.ui.view_toolbar import ViewToolbar


def test_seek_row_orders_playhead_ab_end_time_and_rate_controls(qtbot) -> None:
    """D-170/171: playback is ordered, and the capped lane area follows its header."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1000, 220)
    transport.show()
    qtbot.waitExposed(transport)

    playhead_buttons = (
        transport._jump_back_btn,
        transport._step_back_btn,
        transport.play_btn,
        transport._step_fwd_btn,
        transport._jump_fwd_btn,
    )
    assert [button.geometry().x() for button in playhead_buttons] == sorted(
        button.geometry().x() for button in playhead_buttons
    )
    assert transport._jump_fwd_btn.geometry().right() < transport._time_edit.geometry().x()
    assert transport._time_edit.geometry().right() < transport.slider.geometry().x()
    assert transport.slider.geometry().right() < transport._end_time_label.geometry().x()
    assert transport._ab_in_btn.parentWidget() is transport
    # Same row: compare layout cells, since macOS frames a default button 2 px lower.
    row = transport._timeline_layout
    assert (
        row.itemAt(row.indexOf(transport._ab_in_btn)).geometry().center().y()
        == row.itemAt(row.indexOf(transport.play_btn)).geometry().center().y()
    )
    assert transport._time_edit.geometry().top() > transport.evidence.geometry().bottom()
    assert transport._ab_in_btn.geometry().x() < transport._ab_out_btn.geometry().x()
    assert transport._ab_out_btn.geometry().x() < transport._ab_clear_btn.geometry().x()
    assert transport._ab_clear_btn.geometry().x() < transport.rate_combo.geometry().x()
    tools = (
        transport._jump_back_btn,
        transport._step_back_btn,
        transport._step_fwd_btn,
        transport._jump_fwd_btn,
        transport._ab_in_btn,
        transport._ab_out_btn,
        transport._ab_clear_btn,
    )
    assert all(
        button.text() == "" and button.accessibleName() and button.toolTip() for button in tools
    )
    # D-170: the one Data Streams header sits above its lanes.
    evidence = transport.evidence
    assert evidence.collapse_button.parentWidget() is evidence
    assert evidence.collapse_button.geometry().bottom() <= evidence.lane_scroll.geometry().top()
    assert evidence.lane_scroll.widget() is evidence.overview


def test_descriptive_transport_controls_leave_a_usable_slider_at_narrow_width(qtbot) -> None:
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(640, 220)
    transport.show()
    qtbot.waitExposed(transport)

    assert transport.slider.width() > 0
    assert transport._time_edit.width() >= 110
    assert transport._end_time_label.width() >= 110


def test_plot_header_buttons_name_their_effect(qtbot) -> None:
    """Reset is the pane's own action, which the View menu shows too (rule 15).

    It read "Reset plots" here and "Reset Plot Zoom" in the menu for the same
    Ctrl+0 command, so its text now comes only from that action.
    """
    pane = PlotPane()
    qtbot.addWidget(pane)
    header = pane._plot_header

    assert header.fit_all_button.text() == "Fit Y"
    assert header.fit_all_button.accessibleName() == "Fit Y ranges for visible channels"
    assert header.reset_button.action is pane.reset_action
    assert header.reset_button.text() == pane.reset_action.text() == "Reset Plots"
    assert header.reset_button.accessibleName() == "Reset plot ranges and time span"


def test_transport_status_does_not_block_controls(qtbot) -> None:
    """D-170: forwarding updates the status line and leaves playback enabled."""
    transport = Transport()
    qtbot.addWidget(transport)

    transport.set_bounds(0.0, 62.5)
    transport.set_status("Importing sensor data 62%", "busy")

    assert transport._end_time_label.text() == "00:01:02.500"
    assert transport.status_line.text() == "Working: Importing sensor data 62%"
    assert transport.status_text() == "Importing sensor data 62%"
    line = transport.status_line
    assert line.ink_color() == status_color(line.palette(), "busy")
    assert not line.styleSheet()
    assert transport.play_btn.focusPolicy() == Qt.FocusPolicy.TabFocus


def test_status_timer_is_owned_by_status_line(qtbot) -> None:
    """D-170: a pending clear cannot outlive its status line."""
    transport = Transport()
    transport.set_status("Ready")

    timer = transport.status_line._status_clear_timer
    assert timer.parent() is transport.status_line
    timer.start(1)
    transport.deleteLater()
    qtbot.wait(10)


def test_status_line_sits_beside_activity_in_status_bar(qtbot) -> None:
    """D-170: application status and jobs share the status bar without overlap."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    qtbot.waitExposed(window)
    qtbot.waitUntil(lambda: not window._job_manager.jobs(), timeout=5000)
    window.transport.set_status("Loading", "busy")
    window.activity_bar.show()
    qtbot.wait(10)

    line = window.transport.status_line
    assert line.parentWidget() is window.statusBar()
    assert line.geometry().right() <= window.activity_bar.geometry().left()
    assert line.status_text() == "Loading"
    window.close()


def test_moved_loop_and_rate_controls_keep_their_signals(qtbot) -> None:
    """D-170 changes placement and labels, preserving the playback signals."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.set_bounds(0.0, 10.0)
    transport.set_time(2.0)
    loops: list[tuple[float | None, float | None]] = []
    rates: list[float] = []
    transport.ab_loop_changed.connect(lambda start, end: loops.append((start, end)))
    transport.rate_changed.connect(rates.append)

    transport._ab_in_btn.click()
    transport.set_time(4.0)
    transport._ab_out_btn.click()
    transport._ab_clear_btn.click()
    transport.rate_combo.setCurrentIndex(transport.rate_combo.currentIndex() + 1)

    assert loops == [(2.0, None), (2.0, 4.0), (None, None)]
    assert rates == [transport.rate_combo.currentData()]


def test_end_time_explains_its_difference_from_plot_span(qtbot) -> None:
    """D-170: loaded duration and visible page width have distinct names."""
    transport = Transport()
    qtbot.addWidget(transport)
    assert "Time span" in transport._end_time_label.toolTip()


def test_play_pause_text_never_changes_seek_bar_geometry(qtbot) -> None:
    """The seek bar must not jump or resize when Play becomes Pause."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1000, 220)
    transport.show()
    qtbot.waitExposed(transport)
    before = transport.slider.geometry()

    transport.set_playing(True)

    assert transport.play_btn.text() == "Pause"
    assert transport.slider.geometry() == before


def test_flag_button_emits_annotation_request(qtbot) -> None:
    """Flag lives with the video tools (D-126) and retains the annotation request."""
    toolbar = ViewToolbar()
    qtbot.addWidget(toolbar)
    requests: list[bool] = []
    toolbar.flag_requested.connect(lambda: requests.append(True))

    toolbar.flag_button.click()

    # D-181: a glyph, named by its accessible name and tooltip.
    assert toolbar.flag_button.accessibleName() == "Flag Frame"
    assert toolbar.flag_button.toolTip() == "Flag the current frame (M)"
    assert requests == [True]


def test_data_streams_header_buttons_have_explanatory_tooltips(qtbot) -> None:
    """D-170: the lane header owns only its collapse control.

    D-174: Snapshot and Fullscreen are glyph buttons on their menu actions, so
    they carry a tooltip once those actions are installed, as the window does.
    """
    from PySide6.QtGui import QAction

    transport = Transport()
    qtbot.addWidget(transport)

    toolbar = ViewToolbar()
    qtbot.addWidget(toolbar)
    toolbar.install_snapshot_action(QAction("Export Snapshot…", toolbar))
    toolbar.install_fullscreen_action(QAction("Fullscreen", toolbar))
    for button in (
        transport.evidence.collapse_button,
        toolbar.flag_button,
        toolbar.snapshot_button,
        toolbar.fullscreen_button,
    ):
        assert button.toolTip()
    assert transport.evidence.layout().count() == 2
    assert transport._ab_in_btn.parentWidget() is transport


def test_overview_renders_inspection_evidence_and_seeks(qtbot) -> None:
    """Coverage, TTL, gaps, and annotations share one clickable master-time strip."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1000, 90)
    transport.show()
    qtbot.waitExposed(transport)
    transport.set_bounds(0.0, 100.0)
    transport.set_source_coverage("camera", 0.0, 100.0, "video")
    transport.set_source_coverage("sensor", 10.0, 90.0, "data")
    transport.set_ttl_events([20.0, 40.0])
    transport.set_gap_events([50.0])
    transport.set_annotation_markers([(60.0, None, "#f4a261"), (70.0, 80.0, "#2a9d8f")])
    seeks: list[tuple[float, bool]] = []
    transport.seek_requested.connect(lambda t, exact: seeks.append((t, exact)))

    qtbot.mouseClick(
        transport.overview,
        Qt.MouseButton.LeftButton,
        pos=QPoint(
            transport.overview._LABEL_WIDTH
            + (transport.overview.width() - transport.overview._LABEL_WIDTH) // 2,
            transport.overview.height() // 2,
        ),
    )

    assert len(transport.overview._coverage) == 2
    assert transport.overview._ttl_events == ((20.0, ""), (40.0, ""))
    assert transport.overview._gap_events == ((50.0, ""),)
    assert len(transport.overview._markers) == 2
    assert seeks[0][0] == pytest.approx(50.0, abs=0.5)
    assert seeks[0][1] is True


def test_overview_viewport_drag_preserves_page_phase_and_releases_exactly(qtbot) -> None:
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1000, 180)
    transport.show()
    qtbot.waitExposed(transport)
    transport.set_bounds(0.0, 100.0)
    transport.set_plot_viewport(20.0, 10.0, 2.5)
    seeks: list[tuple[float, bool]] = []
    transport.seek_requested.connect(lambda t, exact: seeks.append((t, exact)))

    overview = transport.overview
    left, right = overview._visible_span_x(20.0, 30.0) or (0, 0)
    start = QPoint((left + right) // 2, overview.height() // 2)
    end = QPoint(start.x() + 100, start.y())
    qtbot.mousePress(overview, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(overview, end)
    qtbot.mouseRelease(overview, Qt.MouseButton.LeftButton, pos=end)

    assert seeks
    assert seeks[-1][1] is True
    assert seeks[-1][0] == pytest.approx(transport.overview._cursor)
    assert transport.overview._viewport_duration == pytest.approx(10.0)


def test_a_click_inside_the_page_window_seeks_to_where_it_landed(qtbot) -> None:
    """A press that never travels is a click: it seeks, as anywhere else on the strip."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1000, 180)
    transport.show()
    qtbot.waitExposed(transport)
    transport.set_bounds(0.0, 100.0)
    transport.set_plot_viewport(20.0, 10.0, 0.0)
    seeks: list[tuple[float, bool]] = []
    transport.seek_requested.connect(lambda t, exact: seeks.append((t, exact)))

    overview = transport.overview
    left, right = overview._visible_span_x(20.0, 30.0) or (0, 0)
    point = QPoint(left + (right - left) * 3 // 4, overview.height() // 2)
    qtbot.mousePress(overview, Qt.MouseButton.LeftButton, pos=point)
    qtbot.mouseRelease(overview, Qt.MouseButton.LeftButton, pos=point)

    assert seeks == [(pytest.approx(overview._time_at_x(point.x())), True)]
    assert overview._viewport_start == pytest.approx(20.0)  # the page did not move


def test_the_trials_lane_names_each_trial_on_hover(qtbot) -> None:
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1000, 180)
    transport.show()
    qtbot.waitExposed(transport)
    transport.set_bounds(0.0, 20.0)
    transport.set_trial_segments([(0.0, 10.0, "12-23-08"), (10.0, 20.0, "12-23-36")])
    overview = transport.overview
    assert overview.lane_labels()[-1] == "Trials"
    lane = overview.lane_labels().index("Trials")
    x = overview._visible_span_x(12.0, 12.0)
    assert x is not None
    detail = overview._event_detail(x[0], lane * overview.lane_height() + 2)
    assert detail is not None and "12-23-36" in detail
    transport.set_trial_segments([])
    assert "Trials" not in overview.lane_labels()


def test_transport_controls_keep_tab_focus_but_space_stays_play_pause(qtbot) -> None:
    transport = Transport()
    qtbot.addWidget(transport)
    toggles: list[bool] = []
    transport.play_toggled.connect(toggles.append)
    transport.rate_combo.setFocus()

    qtbot.keyClick(transport.rate_combo, Qt.Key.Key_Space)

    assert transport.rate_combo.focusPolicy() == Qt.FocusPolicy.TabFocus
    assert toggles == [True]


def test_evidence_lanes_are_named_conditional_and_collapsible(qtbot) -> None:
    """Evidence is understandable in text and does not reserve empty lanes."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.set_bounds(0.0, 100.0)
    transport.set_source_coverage("/data/camera.mp4", 0.0, 100.0, "video")

    assert transport.overview.lane_labels() == ["Video · camera.mp4"]
    assert transport.evidence.title.text() == "Data Streams"
    assert transport.evidence.collapse_button.text() == "Hide"

    transport.evidence.set_collapsed(False, persist=False)
    transport.evidence.collapse_button.click()
    assert transport.overview.isHidden()
    assert transport.evidence.collapse_button.text() == "Show"

    transport.evidence.collapse_button.click()
    assert not transport.overview.isHidden()


def test_grouped_coverage_draws_one_lane_spanning_every_member(qtbot) -> None:
    """Files that cover one span get one lane, positioned at the first member.

    Seven pose and ROI-metric files extracted from three videos start and stop
    with those videos, so seven identical lanes crowd out the sources whose
    coverage actually differs -- which is the only thing the strip is for.
    """
    transport = Transport()
    qtbot.addWidget(transport)
    transport.set_bounds(0.0, 100.0)
    transport.set_source_coverage("/s/FaceCam.mat", 10.0, 70.0, "data", "Video tracking")
    transport.set_source_coverage("/s/encoder_log.txt", 5.0, 95.0, "data")
    transport.set_source_coverage("/s/SideCam.mat", 12.0, 74.0, "data", "Video tracking")

    assert transport.overview.lane_labels() == [
        "Data · Video tracking",
        "Data · encoder_log.txt",
    ]

    label, _kind, payload = transport.overview._lanes()[0]
    assert label == "Data · Video tracking"
    assert (payload.start, payload.end) == (10.0, 74.0)
    assert payload.members == 2


def test_a_removed_group_member_does_not_stretch_its_lane_to_zero(qtbot) -> None:
    """An empty span at the origin is a removal, not coverage from time zero."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.set_bounds(0.0, 100.0)
    transport.set_source_coverage("/s/FaceCam.mat", 10.0, 70.0, "data", "Video tracking")
    transport.set_source_coverage("/s/SideCam.mat", 12.0, 74.0, "data", "Video tracking")

    transport.set_source_coverage("/s/SideCam.mat", 0.0, 0.0, "data")

    _label, _kind, payload = transport.overview._lanes()[0]
    assert (payload.start, payload.end) == (10.0, 70.0)
    assert payload.members == 1

    transport.set_source_coverage("/s/FaceCam.mat", 0.0, 0.0, "data")

    assert transport.overview.lane_labels() == []


def test_evidence_event_detail_identifies_type_source_and_time(qtbot) -> None:
    """Hover details make sync evidence inspectable rather than colour-only."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1000, 180)
    transport.show()
    qtbot.waitExposed(transport)
    transport.set_bounds(0.0, 100.0)
    transport.set_source_coverage("/data/camera.mp4", 0.0, 100.0, "video")
    transport.set_ttl_events([(40.0, "Target: camera.mp4 · residual: 0.250 ms")])

    x = transport.overview._content_x(40.0)
    lane_height = transport.overview.height() // len(transport.overview.lane_labels())
    detail = transport.overview._event_detail(x, lane_height + 5)

    assert "Accepted sync / TTL event" in detail
    assert "40.000 s" in detail  # D-185: ms is the readable unit
    assert "camera.mp4" in detail

    transport.set_gap_events([(50.0, "Source: sensors.csv")])
    lane_height = transport.overview.height() // len(transport.overview.lane_labels())
    detail = transport.overview._event_detail(
        transport.overview._content_x(50.0), lane_height * 2 + 5
    )
    assert "Imported data gap" in detail
    assert "sensors.csv" in detail


def test_messages_get_their_own_named_lane_with_readable_text(qtbot) -> None:
    """A recorded note is neither a sync match nor a defect, and reads as itself."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1000, 180)
    transport.show()
    qtbot.waitExposed(transport)
    transport.set_bounds(0.0, 100.0)
    transport.set_source_coverage("/data/board", 0.0, 100.0, "data")
    transport.set_message_events([(30.0, "board: stimulus on")])

    assert transport.overview.lane_labels() == ["Data · board", "Messages"]

    lane_height = transport.overview.height() // len(transport.overview.lane_labels())
    detail = transport.overview._event_detail(transport.overview._content_x(30.0), lane_height + 5)
    assert "Recorded message" in detail
    assert "stimulus on" in detail


def test_a_lane_never_reports_another_lanes_text(qtbot) -> None:
    """Hover text is looked up per kind; the old ternary answered "gap" for all."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1000, 180)
    transport.show()
    qtbot.waitExposed(transport)
    transport.set_bounds(0.0, 100.0)
    transport.set_gap_events([(10.0, "Source: sensors.csv")])
    transport.set_message_events([(30.0, "board: stimulus on")])

    lane_height = transport.overview.height() // len(transport.overview.lane_labels())
    message_detail = transport.overview._event_detail(
        transport.overview._content_x(30.0), lane_height + 5
    )
    assert "sensors.csv" not in message_detail
    assert "stimulus on" in message_detail


def test_overview_keeps_labels_clear_of_clipped_master_time_coverage(qtbot) -> None:
    """Negative and later streams share one timeline origin outside the label gutter."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1000, 220)
    transport.show()
    qtbot.waitExposed(transport)
    transport.set_bounds(0.0, 10.0)
    transport.overview.set_coverage("negative", -5.0, 4.0, "data")
    transport.overview.set_coverage("later", 3.0, 8.0, "video")

    negative_span = transport.overview._visible_span_x(-5.0, 4.0)
    later_span = transport.overview._visible_span_x(3.0, 8.0)

    assert negative_span is not None
    assert later_span is not None
    assert negative_span[0] == transport.overview._LABEL_WIDTH
    assert later_span[0] > transport.overview._LABEL_WIDTH


def test_ten_compact_sources_fit_before_data_streams_scrolls(qtbot) -> None:
    """D-171: four video and six data lanes use the compact cap without squeezing."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1280, 800)
    transport.show()
    qtbot.waitExposed(transport)
    transport.set_bounds(0.0, 10.0)
    for index in range(10):
        kind = "video" if index < 4 else "data"
        transport.set_source_coverage(f"/recording/source_{index}", 0.0, 10.0, kind)

    overview = transport.overview
    scroll = transport.evidence.lane_scroll
    assert len(overview.lane_labels()) == 10
    assert overview.height() == 10 * overview.lane_height()
    assert scroll.height() == overview.height()
    assert scroll.verticalScrollBar().maximum() == 0

    transport.set_source_coverage("/recording/extra", 0.0, 10.0, "data")
    assert overview.height() == 11 * overview.lane_height()
    assert scroll.height() == 10 * overview.lane_height()
    assert scroll.verticalScrollBar().maximum() > 0


def test_data_streams_cap_and_density_follow_preferences(qtbot) -> None:
    """D-171: the remembered cap and density change the live viewport."""
    from avialsync.ui.app_settings import app_settings

    transport = Transport()
    qtbot.addWidget(transport)
    transport.set_bounds(0.0, 10.0)
    for index in range(5):
        transport.set_source_coverage(f"/recording/source_{index}", 0.0, 10.0, "data")
    compact_height = transport.overview.lane_height()
    settings = app_settings()
    settings.setValue("interface/density", "comfortable")
    settings.setValue("timeline/comfortable_visible_lanes", 3)
    try:
        transport.evidence.reload_preferences()
        assert transport.overview.lane_height() > compact_height
        assert transport.evidence.lane_scroll.height() == 3 * transport.overview.lane_height()
    finally:
        # Shared by every later test in the session; a leftover Comfortable
        # density made the empty-window layout test fail at large fonts.
        settings.remove("interface/density")
        settings.remove("timeline/comfortable_visible_lanes")


def test_data_streams_long_label_elides_but_hover_reveals_it(qtbot) -> None:
    """D-171: a long lane name remains available when its painted text is short."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(800, 200)
    transport.show()
    qtbot.waitExposed(transport)
    transport.set_bounds(0.0, 10.0)
    name = "camera_with_a_very_long_identifier_that_will_not_fit_in_the_lane_label.mp4"
    transport.set_source_coverage(f"/recording/{name}", 0.0, 10.0, "video")
    overview = transport.overview
    label = overview.lane_labels()[0]
    assert "…" in overview.fontMetrics().elidedText(
        label, Qt.TextElideMode.ElideMiddle, overview._LABEL_WIDTH - 14
    )
    # Deliver the hover directly: a synthetic cursor move is not reliable on every platform.
    point = QPointF(20, overview.lane_height() // 2)
    QApplication.sendEvent(
        overview,
        QMouseEvent(
            QEvent.Type.MouseMove,
            point,
            overview.mapToGlobal(point),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert overview.toolTip() == label


def test_coverage_span_keeps_solid_two_pixel_caps(qtbot) -> None:
    """D-159/171: tinted coverage still has opaque edges at both ends."""
    del qtbot
    picture = QImage(40, 20, QImage.Format.Format_ARGB32)
    picture.fill(QColor("white"))
    painter = QPainter(picture)
    _paint_span(painter, 5, 4, 20, 10, QColor("#123456"))
    painter.end()
    assert picture.pixelColor(5, 8) == QColor("#123456")
    assert picture.pixelColor(6, 8) == QColor("#123456")
    assert picture.pixelColor(23, 8) == QColor("#123456")
    assert picture.pixelColor(24, 8) == QColor("#123456")
    assert picture.pixelColor(14, 8) != QColor("#123456")
