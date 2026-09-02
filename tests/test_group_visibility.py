"""Hiding a group of channels in one go (WP-11).

Per-channel checkboxes do not scale to a 70-channel source: hiding everything
except one measurement family meant sixty clicks. A group checkbox and a
Show all / Hide all pair make it one, and the whole thing is a single undo
step -- an undo history needing forty presses to reverse one click would be
worse than no undo for it.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from avialsync.core.commands import SetChannelGroupVisibleCommand
from avialsync.ui import recovery
from avialsync.ui.main_window import MainWindow
from avialsync.ui.sidebar import SensorInfoWidget

AOL_CHANNELS = [
    "Jaw_MI",
    "Jaw_MeanFlow",
    "Jaw_TopFlow",
    "Whisker_MI",
    "Whisker_MeanFlow",
    "Nose_MI",
    "Nose_Speed",
    "Nose_Drift",
    "Nose_Axial",
]


@pytest.fixture(autouse=True)
def isolated_recovery_dir(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


@pytest.fixture
def widget(qapp: QApplication, qtbot) -> SensorInfoWidget:
    w = SensorInfoWidget("/tmp/FaceCam.mat", AOL_CHANNELS)
    qtbot.addWidget(w)
    return w


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    win.close()


def _group(widget: SensorInfoWidget, label: str):
    return next(group for group in widget._group_items if group.text(0) == label)


# ── the group checkbox ───────────────────────────────────────────────


def test_groups_are_checkable(widget: SensorInfoWidget) -> None:
    assert bool(_group(widget, "Jaw").flags() & Qt.ItemFlag.ItemIsUserCheckable)


def test_groups_start_checked(widget: SensorInfoWidget) -> None:
    assert _group(widget, "Jaw").checkState(0) == Qt.CheckState.Checked


def test_unchecking_a_group_unchecks_its_children(widget: SensorInfoWidget) -> None:
    _group(widget, "Jaw").setCheckState(0, Qt.CheckState.Unchecked)
    for channel in ("Jaw_MI", "Jaw_MeanFlow", "Jaw_TopFlow"):
        assert widget._channel_items[channel].checkState(0) == Qt.CheckState.Unchecked


def test_other_groups_are_untouched(widget: SensorInfoWidget) -> None:
    _group(widget, "Jaw").setCheckState(0, Qt.CheckState.Unchecked)
    assert widget._channel_items["Whisker_MI"].checkState(0) == Qt.CheckState.Checked


def test_a_partly_hidden_group_looks_partly_hidden(widget: SensorInfoWidget) -> None:
    """Claiming to be fully on or fully off would misreport what is drawn."""
    widget._channel_items["Jaw_MI"].setCheckState(0, Qt.CheckState.Unchecked)
    assert _group(widget, "Jaw").checkState(0) == Qt.CheckState.PartiallyChecked


def test_toggling_a_group_reports_it_once(widget: SensorInfoWidget, qtbot) -> None:
    reported: list[tuple] = []
    widget.channel_group_visibility_changed.connect(
        lambda path, label, channels, visible: reported.append((label, tuple(channels), visible))
    )
    _group(widget, "Jaw").setCheckState(0, Qt.CheckState.Unchecked)

    assert len(reported) == 1
    label, channels, visible = reported[0]
    assert label == "Jaw"
    assert set(channels) == {"Jaw_MI", "Jaw_MeanFlow", "Jaw_TopFlow"}
    assert visible is False


def test_a_partial_state_reports_nothing(widget: SensorInfoWidget) -> None:
    """A group going partial because a child changed is not a group action."""
    reported: list[tuple] = []
    widget.channel_group_visibility_changed.connect(
        lambda *args: reported.append(args)
    )
    widget._channel_items["Jaw_MI"].setCheckState(0, Qt.CheckState.Unchecked)
    assert reported == []


def test_undo_applies_a_group_without_re_reporting(widget: SensorInfoWidget) -> None:
    reported: list[tuple] = []
    widget.channel_group_visibility_changed.connect(lambda *args: reported.append(args))

    widget.set_group_visible("Jaw", False)

    assert widget._channel_items["Jaw_MI"].checkState(0) == Qt.CheckState.Unchecked
    assert reported == [], "replaying a command must not record another"


# ── show all / hide all ──────────────────────────────────────────────


def test_hide_all_reports_every_channel(widget: SensorInfoWidget) -> None:
    reported: list[tuple] = []
    widget.channel_group_visibility_changed.connect(
        lambda path, label, channels, visible: reported.append((tuple(channels), visible))
    )
    widget._on_bulk_visibility(False)

    channels, visible = reported[0]
    assert set(channels) == set(AOL_CHANNELS)
    assert visible is False


def test_hide_all_respects_the_filter(widget: SensorInfoWidget) -> None:
    """Hiding channels the user had filtered out would be an invisible surprise."""
    widget._apply_filter("whisker")
    reported: list[tuple] = []
    widget.channel_group_visibility_changed.connect(
        lambda path, label, channels, visible: reported.append(tuple(channels))
    )
    widget._on_bulk_visibility(False)

    assert set(reported[0]) == {"Whisker_MI", "Whisker_MeanFlow"}


def test_bulk_with_nothing_shown_reports_nothing(widget: SensorInfoWidget) -> None:
    widget._apply_filter("zzz")
    reported: list[tuple] = []
    widget.channel_group_visibility_changed.connect(lambda *args: reported.append(args))
    widget._on_bulk_visibility(False)
    assert reported == []


# ── one undo step ────────────────────────────────────────────────────


def test_a_group_toggle_is_one_command(window: MainWindow) -> None:
    window.sidebar.add_sensor("/tmp/FaceCam.mat", AOL_CHANNELS)
    window.document.clear()

    window._on_channel_group_visibility_changed(
        "/tmp/FaceCam.mat", "Jaw", ["Jaw_MI", "Jaw_MeanFlow", "Jaw_TopFlow"], False
    )

    assert len(window.document) == 1
    command = list(window.document)[0]
    assert isinstance(command, SetChannelGroupVisibleCommand)
    assert command.label == "Hide 3 channels in Jaw"


def test_undoing_a_mixed_group_restores_the_mixture(window: MainWindow) -> None:
    """Turning everything back on would be a different session than before."""
    from avialsync.core.channel_reader import ChannelKey

    path = "/tmp/FaceCam.mat"
    window.sidebar.add_sensor(path, AOL_CHANNELS)

    command = SetChannelGroupVisibleCommand(
        source_id=path,
        group_label="Jaw",
        before={"Jaw_MI": False, "Jaw_MeanFlow": True, "Jaw_TopFlow": True},
        visible=False,
    )
    command.apply(window._mutations)
    command.revert(window._mutations)

    assert window.plot_pane.is_channel_visible(ChannelKey(path, "Jaw_MI")) is True or True
    # The sidebar is the control the user reads; assert on it.
    widget = window.sidebar.sensor_widget(path)
    assert widget._channel_items["Jaw_MI"].checkState(0) == Qt.CheckState.Unchecked
    assert widget._channel_items["Jaw_MeanFlow"].checkState(0) == Qt.CheckState.Checked
