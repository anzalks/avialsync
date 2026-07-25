"""Tests for the two-row timeline and status transport layout."""

import pytest
from PySide6.QtCore import QPoint, Qt

from kinochronix.ui.transport import Transport


def test_timeline_row_is_above_controls_and_has_reset_zoom(qtbot) -> None:
    """Timeline navigation stays visually separate from playback controls."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1000, 90)
    transport.show()
    qtbot.waitExposed(transport)

    assert transport.slider.geometry().center().y() < transport.play_btn.geometry().center().y()
    assert transport._reset_zoom_btn.geometry().x() > transport.slider.geometry().x()
    assert transport._end_time_label.geometry().x() > transport.slider.geometry().x()


def test_transport_status_and_reset_signal(qtbot) -> None:
    """Status updates do not block controls and reset has one explicit signal."""
    transport = Transport()
    qtbot.addWidget(transport)
    reset_requests: list[bool] = []
    transport.reset_zoom_requested.connect(lambda: reset_requests.append(True))

    transport.set_bounds(0.0, 62.5)
    transport.set_status("Importing sensor data 62%", "busy")
    transport._reset_zoom_btn.click()

    assert transport._end_time_label.text() == "00:01:02.500"
    assert transport._status_label.text() == "Importing sensor data 62%"
    assert "#f0c674" in transport._status_label.styleSheet()
    assert reset_requests == [True]
    assert transport.play_btn.focusPolicy() == Qt.FocusPolicy.NoFocus


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
        pos=QPoint(transport.overview.width() // 2, transport.overview.height() // 2),
    )

    assert len(transport.overview._coverage) == 2
    assert transport.overview._ttl_events == (20.0, 40.0)
    assert transport.overview._gap_events == (50.0,)
    assert len(transport.overview._markers) == 2
    assert seeks[0][0] == pytest.approx(50.0, abs=0.5)
    assert seeks[0][1] is True


def test_overview_can_be_resized_from_its_lower_edge(qtbot) -> None:
    """Dense event evidence can be given more vertical room without a new panel."""
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1000, 160)
    transport.show()
    qtbot.waitExposed(transport)
    original_height = transport.overview.height()
    edge = QPoint(transport.overview.width() // 2, transport.overview.height() - 2)

    qtbot.mousePress(transport.overview, Qt.MouseButton.LeftButton, pos=edge)
    qtbot.mouseMove(transport.overview, QPoint(edge.x(), edge.y() + 40))
    qtbot.mouseRelease(transport.overview, Qt.MouseButton.LeftButton, pos=edge)

    assert transport.overview.height() > original_height
