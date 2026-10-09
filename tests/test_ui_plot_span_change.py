"""A span change costs one paint, and rows scrolled away cost nothing (D-201).

The channel stack is one tall view inside a scroll area, so Qt considers every
row on screen. Before these, a 48-row span change made two full repaints, made
every row's cursor and coverage lines recompute their bounds, and rewrote 48
hidden axis labels -- 70-140 ms of UI time where 49-57 ms remain.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor

from avialsync.core.pyramid import PyramidBuilder
from avialsync.ui.plot_pane import PlotPane
from avialsync.ui.snapshot_capture import capture_plot_image

ROWS = 24


@pytest.fixture(scope="module")
def cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("span") / "cache"
    root.mkdir()
    times = np.linspace(0.0, 120.0, 24_000)
    for index in range(ROWS):
        PyramidBuilder(root, f"ch{index}").build_and_save(times, np.sin(times * (index + 1)))
    return root


@pytest.fixture
def pane(qtbot, cache: Path) -> PlotPane:
    widget = PlotPane()
    qtbot.addWidget(widget)
    widget.resize(900, 420)
    widget.show()
    qtbot.waitExposed(widget)
    widget.load_channels(cache, [f"ch{index}" for index in range(ROWS)])
    widget.wait_for_pending_rows()
    widget.set_timeline_bounds(0.0, 120.0)
    qtbot.waitUntil(
        lambda: (
            widget._page_worker is None
            and widget._last_installed_generation == widget._page_generation
        ),
        timeout=10_000,
    )
    qtbot.wait(50)
    return widget


def _drawn(pane: PlotPane) -> list[bool]:
    return [channel.plot_item.getViewBox().childGroup.isVisible() for channel in pane.channels]


class _Paints(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def eventFilter(self, _obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Paint:
            self.count += 1
        return False


def test_a_span_change_repaints_once(qtbot, pane: PlotPane, monkeypatch) -> None:
    # The page that follows is a second, legitimate paint; this is about the
    # span change itself, so the page worker is held back.
    monkeypatch.setattr(PlotPane, "_start_page_job", lambda self: None)
    paints = _Paints()
    pane.graphics_layout.viewport().installEventFilter(paints)

    pane.set_window_duration(20.0)
    qtbot.wait(150)

    assert paints.count == 1


def test_rows_scrolled_away_are_not_drawn_until_they_come_back(qtbot, pane: PlotPane) -> None:
    drawn = _drawn(pane)
    assert drawn[0], "the first row is on screen"
    assert not drawn[-1], "the last row is several viewports below the fold"
    # The user's own row visibility is a different state and is untouched.
    assert all(channel.plot_item.isVisible() for channel in pane.channels)

    scroll = pane._plot_scroll.verticalScrollBar()
    scroll.setValue(scroll.maximum())
    drawn = _drawn(pane)

    assert drawn[-1], "scrolling re-culls before the next paint"
    assert not drawn[0]


def test_a_snapshot_still_draws_every_row(pane: PlotPane) -> None:
    """The figure carries rows below the fold, culled on screen or not."""
    assert not _drawn(pane)[-1]

    image = capture_plot_image(pane, 900)

    assert image is not None
    # The last row's own trace colour, not grid or axis ink, which is never
    # culled and would pass this on its own.
    trace = pane.channels[-1].curve.opts["pen"].color()
    band = range(int(image.height() * (1 - 1.0 / ROWS)), image.height() - 4)
    traced = 0
    for y in band:
        for x in range(image.width() // 4, image.width() - 20, 3):
            pixel = QColor(image.pixel(x, y))
            if (
                abs(pixel.red() - trace.red())
                + abs(pixel.green() - trace.green())
                + abs(pixel.blue() - trace.blue())
                < 60
            ):
                traced += 1
    assert traced > 10, "the last row's trace is missing from the figure"
    assert not _drawn(pane)[-1], "culling resumes after the capture"


def test_rows_draw_two_grid_levels_and_no_hidden_si_labels(pane: PlotPane) -> None:
    item = pane.channels[0].plot_item
    assert item.getAxis("bottom").style["maxTickLevel"] == 1
    assert not item.getAxis("top").autoSIPrefix
    assert not item.getAxis("right").autoSIPrefix
