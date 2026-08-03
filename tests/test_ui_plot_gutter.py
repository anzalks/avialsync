"""The per-row gutter must stack its parts, not run them together.

pyqtgraph wraps an axis label in a ``<span>`` and hands it to ``setHtml``, so a
newline is whitespace there. Joining the name, unit, and Y range with ``\\n``
produced one long rotated line that overlapped the tick numbers.
"""

from __future__ import annotations

import html
from pathlib import Path

import numpy as np
import pytest

from avialview.core.pyramid import PyramidBuilder
from avialview.ui.plot_pane import PlotPane


@pytest.fixture
def pane_with_channel(qtbot, tmp_path: Path) -> PlotPane:
    cache = tmp_path / "gutter.avialcache"
    cache.mkdir(parents=True, exist_ok=True)
    times = np.linspace(0.0, 1.0, 200)
    PyramidBuilder(cache, "Electrode_1").build_and_save(times, np.sin(times) * 37_000)
    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(900, 600)
    pane.load_channels(cache, ["Electrode_1"])
    pane.wait_for_pending_rows()
    return pane


def _gutter_html(pane: PlotPane) -> str:
    return pane.channels[0].plot_item.getAxis("left").labelText


def test_the_gutter_separates_its_parts_with_a_line_break(pane_with_channel: PlotPane) -> None:
    """Name, unit, and range must occupy their own lines."""
    from avialview.ui.plot_row import fit_channel_y, set_channel_unit

    channel = pane_with_channel.channels[0]
    set_channel_unit(channel, "mV")
    fit_channel_y(channel)

    label = _gutter_html(pane_with_channel)

    assert "<br/>" in label
    assert "\n" not in label, "a newline is whitespace in an HTML axis label"
    assert label.count("<br/>") == 2, "name, unit, and range are three lines"


def test_the_gutter_still_carries_every_part(pane_with_channel: PlotPane) -> None:
    from avialview.ui.plot_row import fit_channel_y, set_channel_unit

    channel = pane_with_channel.channels[0]
    set_channel_unit(channel, "mV")
    fit_channel_y(channel)

    label = _gutter_html(pane_with_channel)

    assert "Electrode_1" in label
    assert "mV" in label
    assert "…" in label, "the stable Y range belongs in the gutter"


def test_a_channel_name_with_markup_characters_survives(qtbot, tmp_path: Path) -> None:
    """An HTML label would otherwise eat part of a name like "I<V"."""
    cache = tmp_path / "markup.avialcache"
    cache.mkdir(parents=True, exist_ok=True)
    times = np.linspace(0.0, 1.0, 50)
    name = "I<V & Q"
    PyramidBuilder(cache, name).build_and_save(times, np.sin(times))
    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.load_channels(cache, [name])
    pane.wait_for_pending_rows()

    label = _gutter_html(pane)

    assert html.escape(name) in label
    assert "<V" not in label, "an unescaped '<' opens a tag and swallows the rest"
