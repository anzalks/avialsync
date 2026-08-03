"""A source offset must survive the round trip through its control.

An AOL recording is timed as seconds since midnight, so a mid-morning session
needs an offset near -34500 s. The offset spin boxes were limited to +/-1 hour,
so such a value was clamped on the way in and ``mapping()`` then reported the
clamp as fact.

Nothing warned. The value is applied with signals blocked, so the live view
stayed correct and only the saved session was wrong -- reopening it put pose
data hours away from its video. D-026: never silently substitute a mapping the
user did not accept.
"""

from __future__ import annotations

import pytest

from avialsync.ui.sidebar import SensorInfoWidget, SidebarPane, VideoInfoWidget

#: A real AOL session start, 09:35:26 expressed as seconds since midnight.
_SESSION_OFFSET_S = -34526.312

#: The widest time base a session realistically uses, either direction.
_FULL_DAY_S = 86_400.0


def test_a_sensor_widget_keeps_a_wall_clock_offset(qtbot) -> None:
    widget = SensorInfoWidget("/tmp/pose.csv", ["head_bar_x", "head_bar_y"])
    qtbot.addWidget(widget)

    widget.set_mapping(_SESSION_OFFSET_S, 0.0)

    offset, _drift = widget.mapping()
    assert offset == pytest.approx(_SESSION_OFFSET_S), (
        "the control clamped a legitimate session offset; the saved session "
        "would carry the clamp and this source would open desynchronised"
    )


def test_a_video_widget_keeps_a_wall_clock_offset(qtbot) -> None:
    widget = VideoInfoWidget("/tmp/cam.mp4", {})
    qtbot.addWidget(widget)

    widget.offset_spin.setValue(_SESSION_OFFSET_S)

    assert widget.offset_spin.value() == pytest.approx(_SESSION_OFFSET_S)


@pytest.mark.parametrize("value", [-_FULL_DAY_S, _FULL_DAY_S])
def test_a_full_day_either_way_is_representable(qtbot, value: float) -> None:
    widget = SensorInfoWidget("/tmp/edge.csv", ["ch"])
    qtbot.addWidget(widget)

    widget.set_mapping(value, 0.0)

    assert widget.mapping()[0] == pytest.approx(value)


def test_the_saved_session_carries_the_offset_the_source_was_given(qtbot) -> None:
    """The corruption path end to end: what the sidebar reports is what is saved."""
    pane = SidebarPane()
    qtbot.addWidget(pane)
    pane.add_sensor("/tmp/pose.csv", ["head_bar_x"])

    pane.set_sensor_mapping("/tmp/pose.csv", _SESSION_OFFSET_S, 12.5)

    assert pane.sensor_mapping("/tmp/pose.csv") == (
        pytest.approx(_SESSION_OFFSET_S),
        pytest.approx(12.5),
    )
