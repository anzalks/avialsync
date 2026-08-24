"""Tests for the two-row timeline and status transport layout."""

import pytest
from PySide6.QtCore import QPoint, Qt

from avialsync.ui.theme import status_color
from avialsync.ui.transport import Transport


def test_seek_row_orders_playhead_ab_end_time_and_rate_controls(qtbot) -> None:
    """Seek-row controls follow the compact visual-inspection workflow."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1000, 220)
    transport.show()
    qtbot.waitExposed(transport)

    assert transport._jump_fwd_btn.geometry().x() < transport._time_edit.geometry().x()
    assert transport._time_edit.geometry().right() < transport.slider.geometry().x()
    assert transport.slider.geometry().right() < transport._end_time_label.geometry().x()
    assert transport._end_time_label.geometry().right() < transport._ab_in_btn.geometry().x()
    assert transport._ab_clear_btn.geometry().x() < transport._speed_label.geometry().x()
    assert transport._speed_label.geometry().right() < transport.rate_combo.geometry().x()
    assert transport.evidence.reset_zoom_button.geometry().x() > transport.slider.geometry().x()


def test_transport_status_and_reset_signal(qtbot) -> None:
    """Status updates do not block controls and reset has one explicit signal."""
    transport = Transport()
    qtbot.addWidget(transport)
    reset_requests: list[bool] = []
    transport.reset_zoom_requested.connect(lambda: reset_requests.append(True))

    transport.set_bounds(0.0, 62.5)
    transport.set_status("Importing sensor data 62%", "busy")
    transport.evidence.reset_zoom_button.click()

    assert transport._end_time_label.text() == "00:01:02.500"
    assert transport.evidence._status_label.text() == "Status: Importing sensor data 62%"
    # Asserted as the derived colour, not as a hex literal. Pinning the literal
    # is what let the hardcoded amber sit here unnoticed: it read as dark grey
    # on a light theme, and the test agreed with it either way.
    label = transport.evidence._status_label
    assert status_color(label.palette(), "busy").name() in label.styleSheet()
    assert status_color(label.palette(), "busy") != status_color(label.palette(), "error")
    assert reset_requests == [True]
    assert transport.play_btn.focusPolicy() == Qt.FocusPolicy.TabFocus


def test_status_timer_is_owned_by_data_streams(qtbot) -> None:
    """A pending status clear cannot outlive and call a deleted label."""
    transport = Transport()
    transport.set_status("Ready")

    timer = transport.evidence._status_clear_timer
    assert timer.parent() is transport.evidence
    timer.start(1)
    transport.deleteLater()
    qtbot.wait(10)


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
    """Flag lives in the Data Streams header and retains the annotation action."""
    transport = Transport()
    qtbot.addWidget(transport)
    requests: list[bool] = []
    transport.annotate_requested.connect(lambda: requests.append(True))

    transport.evidence.flag_button.click()

    assert transport.evidence.flag_button.text() == "Flag Frame"
    assert requests == [True]


def test_data_streams_header_buttons_have_explanatory_tooltips(qtbot) -> None:
    """Header actions explain their user-visible purpose without relying on icons."""
    transport = Transport()
    qtbot.addWidget(transport)

    for button in (
        transport.evidence.collapse_button,
        transport.evidence.flag_button,
        transport.evidence.snapshot_button,
        transport.evidence.fullscreen_button,
        transport.evidence.reset_zoom_button,
    ):
        assert button.toolTip()


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
    assert "40.000000 s" in detail
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
