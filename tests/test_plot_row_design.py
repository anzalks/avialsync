"""Plot rows: identity beyond colour, row tools, lighter rules (D-177, DS-9)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent, QPalette
from PySide6.QtWidgets import QApplication

from avialsync.ui.plot_row import reveal_row_tools
from avialsync.ui.theme import plot_colors
from tests.test_ui_plot_row_geometry import _pane_with_channels


def test_every_visible_trace_carries_a_non_colour_identifier(qtbot, tmp_path: Path) -> None:
    """D-094/D-177: one trace per row, named in its own gutter, so hue is never alone."""
    pane = _pane_with_channels(qtbot, tmp_path, 6, 1000, 700)
    for channel in pane.channels:
        if not channel.visible:
            continue
        items = [item for item in channel.plot_item.listDataItems() if item is channel.curve]
        assert items == [channel.curve], "a row draws exactly one trace"
        assert channel.name in channel.plot_item.getAxis("left").labelText


def test_row_tools_show_on_hover_and_focus_and_in_the_menu(qtbot, tmp_path: Path) -> None:
    pane = _pane_with_channels(qtbot, tmp_path, 3, 1000, 700)
    first, second = pane.channels[0], pane.channels[1]
    assert first.close_proxy.opacity() == 0.0, "quiet until asked for"
    reveal_row_tools(pane.channels, first.plot_item.sceneBoundingRect().center().y())
    assert first.close_proxy.opacity() == 1.0 and second.close_proxy.opacity() == 0.0
    # Delivered directly: an embedded widget gets no real focus in a headless run.
    QApplication.sendEvent(
        second.close_button, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason)
    )
    assert second.close_proxy.opacity() == 1.0
    assert second.close_button.focusPolicy() & Qt.FocusPolicy.TabFocus, "Tab still reaches it"

    hidden: list[tuple[str, str]] = []
    pane.channel_close_requested.connect(lambda s, c: hidden.append((s, c)))
    pane.hide_channel_row(second.name)
    assert not second.visible and hidden and hidden[0][1] == second.name


def test_rules_are_lighter_than_the_tick_numbers(qapp) -> None:
    palette = qapp.palette()
    colors = plot_colors(palette)
    text = palette.color(QPalette.ColorRole.Text)
    canvas = palette.color(QPalette.ColorRole.Base)

    def distance(a, b) -> float:
        return abs(a.lightnessF() - b.lightnessF())

    assert colors.axis == text, "tick numbers keep full contrast"
    assert distance(colors.rule, canvas) < distance(text, canvas), "strokes recede"
    assert colors.grid_alpha <= 0.12
