"""Finding a channel in a long list (WP-11).

The reference session loads a 70-channel source whose names are
``Jaw_MI``, ``Jaw_MeanFlow``, ``Jaw_TopFlow``, ``Whisker_MI``… The tree
grouped on ``/`` and ``.``, so every one of those arrived flat, in a scrolling
column with no way to search it. The spec targets 128 channels.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from avialsync.ui.channel_tree import (
    MIN_GROUP_SIZE,
    group_prefixes,
    matches_filter,
    split_channel,
)
from avialsync.ui.sidebar import SensorInfoWidget, SidebarPane

#: The shape that motivated this, trimmed.
AOL_CHANNELS = [
    "Jaw_MI",
    "Jaw_MeanFlow",
    "Jaw_TopFlow",
    "Jaw_DirCoh",
    "Jaw_Brightness",
    "Whisker_MI",
    "Whisker_MeanFlow",
    "Nose_MI",
    "Nose_Speed",
]


# ── grouping ─────────────────────────────────────────────────────────


def test_a_shared_prefix_becomes_a_group() -> None:
    prefixes = group_prefixes(AOL_CHANNELS)
    assert {"Jaw", "Whisker", "Nose"} <= prefixes
    assert split_channel("Jaw_MeanFlow", prefixes) == ["Jaw", "MeanFlow"]


def test_a_lone_underscore_name_is_left_alone() -> None:
    """Grouping every underscore would add indentation for nothing."""
    channels = ["t_sec", "force", "angle"]
    prefixes = group_prefixes(channels)
    assert prefixes == set()
    assert split_channel("t_sec", prefixes) == ["t_sec"]


def test_a_prefix_needs_more_than_one_channel() -> None:
    channels = ["Jaw_MI", "Jaw_Speed", "Solo_Thing"]
    prefixes = group_prefixes(channels)
    assert "Jaw" in prefixes
    assert "Solo" not in prefixes
    assert MIN_GROUP_SIZE == 2


def test_explicit_separators_still_nest() -> None:
    prefixes = group_prefixes(["probe/ch1", "probe/ch2"])
    assert split_channel("probe/ch1", prefixes) == ["probe", "ch1"]
    assert split_channel("probe.ch1", prefixes) == ["probe", "ch1"]


def test_explicit_and_underscore_nesting_combine() -> None:
    channels = ["rig/Jaw_MI", "rig/Jaw_Speed"]
    prefixes = group_prefixes(channels)
    assert split_channel("rig/Jaw_MI", prefixes) == ["rig", "Jaw", "MI"]


def test_a_trailing_underscore_is_not_a_group() -> None:
    prefixes = group_prefixes(["odd_", "odd_"])
    assert split_channel("odd_", prefixes) == ["odd_"]


# ── filtering ────────────────────────────────────────────────────────


def test_an_empty_filter_matches_everything() -> None:
    assert all(matches_filter(channel, "") for channel in AOL_CHANNELS)


def test_the_filter_is_case_insensitive() -> None:
    assert matches_filter("Jaw_MeanFlow", "jaw") is True


def test_the_filter_matches_mid_name() -> None:
    """Someone typing "flow" wants MeanFlow and TopFlow."""
    matched = [c for c in AOL_CHANNELS if matches_filter(c, "flow")]
    assert set(matched) == {"Jaw_MeanFlow", "Jaw_TopFlow", "Whisker_MeanFlow"}


def test_surrounding_space_is_ignored() -> None:
    assert matches_filter("Jaw_MI", "  jaw ") is True


def test_a_filter_matching_nothing_matches_nothing() -> None:
    assert not any(matches_filter(c, "zzz") for c in AOL_CHANNELS)


# ── the widget ───────────────────────────────────────────────────────


@pytest.fixture
def widget(qapp: QApplication, qtbot) -> SensorInfoWidget:
    w = SensorInfoWidget("/tmp/FaceCam.mat", AOL_CHANNELS)
    qtbot.addWidget(w)
    return w


def test_every_channel_is_present(widget: SensorInfoWidget) -> None:
    assert len(widget._channel_items) == len(AOL_CHANNELS)


def test_groups_are_built(widget: SensorInfoWidget) -> None:
    labels = {group.text(0) for group in widget._group_items}
    assert {"Jaw", "Whisker", "Nose"} <= labels


def test_filtering_hides_the_rest(widget: SensorInfoWidget) -> None:
    widget._apply_filter("whisker")
    assert widget.visible_channel_count() == 2


def test_clearing_the_filter_restores_everything(widget: SensorInfoWidget) -> None:
    widget._apply_filter("whisker")
    widget._apply_filter("")
    assert widget.visible_channel_count() == len(AOL_CHANNELS)


def test_a_group_with_no_surviving_child_is_hidden(widget: SensorInfoWidget) -> None:
    widget._apply_filter("whisker")
    hidden = {group.text(0) for group in widget._group_items if group.isHidden()}
    assert "Jaw" in hidden
    assert "Whisker" not in hidden


def test_a_matching_group_is_expanded(widget: SensorInfoWidget) -> None:
    """A match hidden inside a collapsed node has not been found."""
    for group in widget._group_items:
        group.setExpanded(False)
    widget._apply_filter("meanflow")
    surviving = [g for g in widget._group_items if not g.isHidden()]
    assert surviving and all(group.isExpanded() for group in surviving)


def test_a_nested_filter_hides_empty_ancestor_groups(qapp: QApplication, qtbot) -> None:
    widget = SensorInfoWidget("/tmp/nested.csv", ["camera/front/left", "camera/back/right"])
    qtbot.addWidget(widget)

    widget._apply_filter("no matching channel")

    assert widget._group_items
    assert all(group.isHidden() for group in widget._group_items)


def test_filtering_does_not_disturb_check_state(widget: SensorInfoWidget) -> None:
    """Hiding rather than rebuilding is what keeps this true."""
    from PySide6.QtCore import Qt

    widget._channel_items["Jaw_MI"].setCheckState(0, Qt.CheckState.Unchecked)
    widget._apply_filter("whisker")
    widget._apply_filter("")
    assert widget._channel_items["Jaw_MI"].checkState(0) == Qt.CheckState.Unchecked


def test_a_short_list_hides_the_filter(qapp: QApplication, qtbot) -> None:
    """A filter over three channels is furniture."""
    w = SensorInfoWidget("/tmp/small.csv", ["a", "b", "c"])
    qtbot.addWidget(w)
    assert w._filter.isVisible() is False


def test_inspector_filter_finds_one_channel_across_sources(qapp: QApplication, qtbot) -> None:
    sidebar = SidebarPane()
    qtbot.addWidget(sidebar)
    channels = [f"camera/joint_{index:03d}" for index in range(128)]
    sidebar.add_sensor("/tmp/front.csv", channels)
    sidebar.add_sensor("/tmp/side.csv", ["temperature", "pressure"])

    front = sidebar.sensor_widget("/tmp/front.csv")
    side = sidebar.sensor_widget("/tmp/side.csv")
    assert front is not None and side is not None

    front._group_items[0].setExpanded(False)
    sidebar._source_filter.setText("joint_127")

    assert not front.isHidden()
    assert front.visible_channel_count() == 1
    assert not front._group_items[0].isHidden()
    assert front._group_items[0].isExpanded()
    assert side.isHidden()

    front._filter.setText("joint_000")
    assert front.isHidden(), "the global and per-source filters should compose"
    front._filter.clear()
    assert not front.isHidden()
    assert front.visible_channel_count() == 1

    sidebar._source_filter.clear()
    assert front.visible_channel_count() == 128
    assert not side.isHidden()


def test_source_filter_does_not_change_video_visibility(qapp: QApplication, qtbot) -> None:
    sidebar = SidebarPane()
    qtbot.addWidget(sidebar)
    sidebar.add_video("/tmp/FrontCam.mp4", {})
    video = sidebar._video_widgets["/tmp/FrontCam.mp4"]
    video.visibility_cb.setChecked(False)

    sidebar._source_filter.setText("frontcam")
    assert not video.isHidden()
    assert not video.visibility_cb.isChecked()

    sidebar._source_filter.setText("missing")
    assert video.isHidden()
    assert not video.visibility_cb.isChecked()
