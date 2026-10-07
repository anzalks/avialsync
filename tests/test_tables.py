"""Table grid lines follow the theme, not the style's fixed grid colour.

The macOS style answers ``SH_Table_GridLineColor`` with a fixed near-black under
both appearances, which no palette role reaches. These render a real table and
read the grid pixels back, so they hold whatever the style under test answers.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from avialsync.ui import theme
from avialsync.ui.tables import ThemedTable


@pytest.fixture
def switch(qapp: QApplication) -> Iterator[object]:
    entry = QPalette(qapp.palette())
    dark = qapp.property("avialsync_theme_dark")
    native = qapp.property("avialsync_theme_native")

    def apply(pref: str) -> None:
        theme._apply(qapp, pref, persist=False)
        qapp.processEvents()

    try:
        yield apply
    finally:
        qapp.setPalette(entry)
        qapp.setProperty("avialsync_theme_dark", dark)
        qapp.setProperty("avialsync_theme_native", native)


def _pixel(image: QImage, x: int, y: int) -> QColor:
    """Read the device pixel under logical point (x, y), Retina or not."""
    ratio = image.devicePixelRatio()
    return image.pixelColor(int(x * ratio), int(y * ratio))


def _table(qtbot) -> ThemedTable:
    table = ThemedTable(3, 2)
    for row in range(3):
        for column in range(2):
            table.setItem(row, column, QTableWidgetItem(f"{row},{column}"))
    table.resize(320, 200)
    qtbot.addWidget(table)
    table.show()
    qtbot.waitExposed(table)
    return table


@pytest.mark.parametrize("pref", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_grid_lines_are_drawn_in_the_separator_colour(qtbot, switch, pref: str) -> None:
    table = _table(qtbot)
    switch(pref)
    table.viewport().repaint()

    image = table.viewport().grab().toImage()
    expected = theme.separator_color(table.palette())
    x = table.columnViewportPosition(0) + table.columnWidth(0) - 1
    y = table.rowViewportPosition(0) + table.rowHeight(0) - 1

    ratio = image.devicePixelRatio()
    # Every device pixel of the one-pixel line, so on Retina no half of Qt's
    # own black line survives beside ours.
    span = range(max(1, round(ratio)))
    probe_y = int((table.rowViewportPosition(1) + 3) * ratio)
    probe_x = int((table.columnViewportPosition(1) + 3) * ratio)
    samples = [image.pixelColor(int(x * ratio) + step, probe_y) for step in span]
    samples += [image.pixelColor(probe_x, int(y * ratio) + step) for step in span]
    for sample in samples:
        assert abs(sample.lightnessF() - expected.lightnessF()) < 0.03, (
            f"{pref}: grid pixel {sample.name()} is not the separator {expected.name()}"
        )


def test_a_table_without_a_grid_draws_none(qtbot, switch) -> None:
    table = _table(qtbot)
    table.setShowGrid(False)
    switch(theme.THEME_LIGHT)
    table.viewport().repaint()

    image = table.viewport().grab().toImage()
    x = table.columnViewportPosition(0) + table.columnWidth(0) - 1
    sample = _pixel(image, x, table.rowViewportPosition(1) + 3)
    assert sample != theme.separator_color(table.palette())
