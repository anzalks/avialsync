"""A theme switch must reach the custom-painted surfaces, not stop at Qt's.

Qt repaints its own widgets when the application palette changes. Three kinds of
surface in this application do not get that for free, and each one had gone
stale in a different way:

*pyqtgraph canvases.* pyqtgraph paints its own scene and takes its colours from
module-level config options read once, at construction. Setting them on a
palette change — which is what the plot pane used to do — moves nothing that
already exists, so the graph background, the tick numbers and the axis titles
all stayed on whichever theme was current when the rows were built.

*Graphics items.* A pen handed to an ``InfiniteLine`` or a curve is a literal
from that moment on. The playhead was a hardcoded yellow, legible on the dark
canvas it was chosen against and washed out on a white one.

*Self-painting widgets.* A ``paintEvent`` that names a colour keeps naming it.
The 3D pose view filled its canvas with ``Qt.GlobalColor.white`` whatever the
theme said, and drew grey structure on top tuned for that one surface.

Every assertion here is a property — contrast against the surface, a change
across a switch, or a relationship between two marks. A test that pinned a hex
would need editing every time the palette moved and would prove nothing about
legibility, which is the thing actually at stake.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from avialsync.core.pyramid import PyramidBuilder
from avialsync.ui.plot_pane import PlotPane
from avialsync.ui.theme import (
    THEME_DARK,
    THEME_LIGHT,
    apply_theme,
    coverage_color,
    neutral_on_canvas,
    playhead_color,
    plot_colors,
    trace_color,
)

#: Lightness gap below which a one- or two-pixel line stops being visible.
_MIN_CONTRAST = 0.2

#: Saturation above which a mark reads as carrying a hue rather than as neutral.
_CHROMATIC = 0.15


def _surfaces() -> tuple[QPalette, QPalette]:
    """A dark and a light palette differing in the roles a plot canvas reads."""
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Base, QColor("#282828"))
    dark.setColor(QPalette.ColorRole.AlternateBase, QColor("#333333"))
    dark.setColor(QPalette.ColorRole.Window, QColor("#1e1e1e"))
    dark.setColor(QPalette.ColorRole.Text, QColor("#f0f0f0"))
    dark.setColor(QPalette.ColorRole.WindowText, QColor("#f0f0f0"))
    dark.setColor(QPalette.ColorRole.Highlight, QColor("#0a84ff"))
    dark.setColor(QPalette.ColorRole.Link, QColor("#0a84ff"))

    light = QPalette()
    light.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    light.setColor(QPalette.ColorRole.AlternateBase, QColor("#eeeeee"))
    light.setColor(QPalette.ColorRole.Window, QColor("#f5f5f5"))
    light.setColor(QPalette.ColorRole.Text, QColor("#1b1b1b"))
    light.setColor(QPalette.ColorRole.WindowText, QColor("#1b1b1b"))
    light.setColor(QPalette.ColorRole.Highlight, QColor("#0a84ff"))
    light.setColor(QPalette.ColorRole.Link, QColor("#0a84ff"))
    return dark, light


DARK, LIGHT = _surfaces()


def _contrast(color: QColor, palette: QPalette) -> float:
    """Lightness distance between a mark and the canvas it is drawn on."""
    canvas = palette.color(QPalette.ColorRole.Base)
    return abs(color.lightnessF() - canvas.lightnessF())


# ── The colours themselves ───────────────────────────────────────────────


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_the_playhead_is_visible_against_its_canvas(palette: QPalette) -> None:
    """The bug: a yellow playhead chosen on dark, near-invisible on white."""
    assert _contrast(playhead_color(palette), palette) > _MIN_CONTRAST


def test_the_playhead_moves_with_the_theme() -> None:
    """A hardcoded colour is exactly the one that does not."""
    assert playhead_color(DARK) != playhead_color(LIGHT)


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_the_playhead_is_achromatic(palette: QPalette) -> None:
    """It must never be mistaken for a channel.

    Every colour this application gives a trace, a lane or a marker carries a
    hue, so neutral is the one choice that cannot collide with a data colour
    however many channels are loaded.
    """
    assert playhead_color(palette).saturationF() < _CHROMATIC


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_the_playhead_is_tellable_from_every_trace(palette: QPalette) -> None:
    """Whatever the channel count, the playhead stays the odd one out."""
    playhead = playhead_color(palette)
    for index in range(16):
        trace = trace_color(palette, index)
        assert playhead.name() != trace.name(), f"trace {index} paints as the playhead"


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_traces_are_visible_against_the_canvas(palette: QPalette) -> None:
    """The four-colour literal this replaced was tuned for a light canvas."""
    for index in range(8):
        assert _contrast(trace_color(palette, index), palette) > _MIN_CONTRAST, f"trace {index}"


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_the_coverage_wash_changes_the_surface_it_covers(palette: QPalette) -> None:
    """A white wash lightens a dark canvas and vanishes into a white one.

    The wash is translucent, so what matters is the composite: whether a reader
    can see where the source has data. Comparing the raw colour would pass on a
    wash that is invisible once blended.
    """
    canvas = palette.color(QPalette.ColorRole.Base)
    wash = coverage_color(palette)
    alpha = wash.alphaF()
    blended = QColor.fromRgbF(
        *(
            wash_part * alpha + canvas_part * (1.0 - alpha)
            for wash_part, canvas_part in (
                (wash.redF(), canvas.redF()),
                (wash.greenF(), canvas.greenF()),
                (wash.blueF(), canvas.blueF()),
            )
        )
    )
    assert abs(blended.lightnessF() - canvas.lightnessF()) > 0.02, (
        "the coverage wash blends away into its own canvas"
    )


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_neutral_weight_means_the_same_thing_on_both_surfaces(palette: QPalette) -> None:
    """The point of a weight: one constant, correct against either canvas.

    A literal grey is a fixed distance from white and an arbitrary one from
    anything else, which is how a faint grid rule became the brightest mark in
    the 3D view once its canvas stopped being forced to white.
    """
    faint = neutral_on_canvas(palette, 0.25)
    strong = neutral_on_canvas(palette, 0.9)
    assert _contrast(faint, palette) < _contrast(strong, palette)
    assert faint.saturationF() < _CHROMATIC


def test_neutral_marks_run_opposite_ways_on_opposite_canvases() -> None:
    """Same weight, opposite surfaces, opposite direction of travel."""
    assert neutral_on_canvas(DARK, 0.8).lightnessF() > neutral_on_canvas(LIGHT, 0.8).lightnessF()


def test_the_canvas_and_axis_come_from_palette_roles() -> None:
    """Not from a second, quietly diverging set of colours."""
    colors = plot_colors(DARK)
    assert colors.canvas == DARK.color(QPalette.ColorRole.Base)
    assert colors.axis == DARK.color(QPalette.ColorRole.Text)


# ── The live canvas ──────────────────────────────────────────────────────


def _pane_with_a_channel(qtbot, tmp_path: Path) -> PlotPane:
    cache = tmp_path / "theme.avialcache"
    cache.mkdir(parents=True, exist_ok=True)
    times = np.arange(2_000, dtype=np.float64) / 1000.0
    PyramidBuilder(cache, "ch0").build_and_save(times, np.sin(times))

    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(800, 400)
    pane.show()
    qtbot.waitExposed(pane)
    pane.set_timeline_bounds(0.0, 2.0)
    pane.load_channels(cache, ["ch0"])
    pane.wait_for_pending_rows()
    return pane


def _switch(pane: PlotPane, palette: QPalette) -> None:
    """Deliver a palette change the way the application's theme menu does."""
    pane.setPalette(palette)
    pane.changeEvent(QEvent(QEvent.Type.PaletteChange))


def test_the_plot_canvas_repaints_for_a_new_palette(qtbot, tmp_path: Path) -> None:
    """The headline bug.

    ``setConfigOption`` is read when an item is constructed and never again, so
    the pane could set both options on every palette change and the view kept
    the background it was born with. Measured before the fix: a live view stayed
    on ``#ffffff`` through a flip to a dark palette.
    """
    pane = _pane_with_a_channel(qtbot, tmp_path)

    _switch(pane, DARK)
    dark_background = pane.graphics_layout.backgroundBrush().color()
    _switch(pane, LIGHT)
    light_background = pane.graphics_layout.backgroundBrush().color()

    assert dark_background != light_background, "the graph kept the outgoing theme's background"
    assert dark_background == DARK.color(QPalette.ColorRole.Base)
    assert light_background == LIGHT.color(QPalette.ColorRole.Base)


def test_axis_lines_and_tick_numbers_repaint(qtbot, tmp_path: Path) -> None:
    """Three separately coloured things per axis, none of which used to move.

    The axis line and ticks take the axis pen, the tick numbers take the text
    pen, and the axis title keeps its own style — which pyqtgraph defaults to a
    literal mid-grey.
    """
    pane = _pane_with_a_channel(qtbot, tmp_path)
    axis = pane.channels[0].plot_item.getAxis("left")

    _switch(pane, DARK)
    dark_pen = axis.pen().color()
    dark_text = axis.textPen().color()
    dark_label = axis.labelStyle.get("color")

    _switch(pane, LIGHT)

    assert axis.pen().color() != dark_pen, "axis lines and ticks kept the old theme"
    assert axis.textPen().color() != dark_text, "tick numbers kept the old theme"
    assert axis.labelStyle.get("color") != dark_label, "the axis title kept the old theme"


def test_the_playhead_and_trace_repaint_with_the_pane(qtbot, tmp_path: Path) -> None:
    """A pen given to a graphics item is a literal until something re-pens it."""
    pane = _pane_with_a_channel(qtbot, tmp_path)
    channel = pane.channels[0]

    _switch(pane, DARK)
    dark_cursor = channel.cursor_line.pen.color()
    dark_trace = channel.curve.opts["pen"].color()

    _switch(pane, LIGHT)

    assert channel.cursor_line.pen.color() != dark_cursor
    assert channel.curve.opts["pen"].color() != dark_trace


def test_a_row_built_after_a_switch_matches_the_rows_already_there(qtbot, tmp_path: Path) -> None:
    """Construction reads the live palette, not a global left over from earlier."""
    pane = _pane_with_a_channel(qtbot, tmp_path)
    _switch(pane, DARK)
    existing = pane.channels[0].cursor_line.pen.color()

    cache = tmp_path / "later.avialcache"
    cache.mkdir(parents=True, exist_ok=True)
    times = np.arange(2_000, dtype=np.float64) / 1000.0
    PyramidBuilder(cache, "ch1").build_and_save(times, np.cos(times))
    pane.load_channels(cache, ["ch1"])
    pane.wait_for_pending_rows()

    assert pane.channels[-1].cursor_line.pen.color() == existing


def test_a_theme_switch_leaves_the_view_where_it_was(qtbot, tmp_path: Path) -> None:
    """Appearance only.

    AGENTS.md is explicit that a theme may move palette roles and nothing else:
    not view state, not playback state, not interaction. This is the guard on
    the repaint added above, which touches items the view's ranges depend on.
    """
    pane = _pane_with_a_channel(qtbot, tmp_path)
    before_x = pane.channels[0].plot_item.viewRange()[0]
    before_window = pane.window_duration

    _switch(pane, DARK)

    assert pane.channels[0].plot_item.viewRange()[0] == pytest.approx(before_x)
    assert pane.window_duration == pytest.approx(before_window)


# ── The self-painting 3D view ────────────────────────────────────────────


def test_the_3d_view_asks_for_a_repaint_when_the_appearance_changes(qtbot) -> None:
    """Qt repaints its own widgets; one that paints itself has to ask.

    Without this the pose kept the outgoing theme's canvas until something else
    invalidated it — a resize, a rotate, or the next tracking sample.
    """
    from avialsync.ui.tracking_3d_pane import Tracking3DCanvas

    view = Tracking3DCanvas()
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)

    repaints: list[bool] = []
    original = view.update
    view.update = lambda *args: (repaints.append(True), original(*args))[1]  # type: ignore[method-assign]
    view.changeEvent(QEvent(QEvent.Type.PaletteChange))

    assert repaints, "the pose would keep the previous theme's canvas"


def test_the_3d_view_does_not_force_a_white_canvas(qtbot) -> None:
    """It filled with ``Qt.GlobalColor.white`` whatever the theme said.

    Asserted by rendering the widget and reading the corner pixel, because the
    fill is a statement inside ``paintEvent`` — the only honest way to ask what
    it drew is to look at what it drew.
    """
    from PySide6.QtGui import QImage

    from avialsync.ui.tracking_3d_pane import Tracking3DCanvas

    view = Tracking3DCanvas()
    qtbot.addWidget(view)
    view.resize(200, 150)

    def corner(palette: QPalette) -> QColor:
        view.setPalette(palette)
        image = QImage(view.size(), QImage.Format.Format_ARGB32)
        view.render(image)
        return QColor(image.pixelColor(2, 2))

    assert corner(DARK) == DARK.color(QPalette.ColorRole.Base)
    assert corner(LIGHT) == LIGHT.color(QPalette.ColorRole.Base)


# ── Reading the platform's own appearance ────────────────────────────────


def test_system_appearance_prefers_the_platform_hint_over_the_palette() -> None:
    """``colorScheme`` is authoritative; palette lightness is the fallback.

    A style whose palette does not track the desktop — Fusion on a dark Linux
    session — paints light whatever the session's preference is, so inferring
    the appearance from ``Window`` lightness reports "light" on a dark desktop
    and the System preference silently follows nothing.
    """
    from avialsync.ui import theme

    app = QApplication.instance()
    assert app is not None

    light_palette = QPalette()
    light_palette.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
    theme._system_palettes[id(app)] = light_palette

    for scheme, expected in ((Qt.ColorScheme.Dark, True), (Qt.ColorScheme.Light, False)):
        theme._color_scheme_hint = lambda _app, _s=scheme: _s  # type: ignore[assignment]
        assert theme.system_is_dark(app) is expected

    # Unknown is what the offscreen plugin reports, and what every platform
    # reports before Qt 6.5 — the palette has to answer for it.
    theme._color_scheme_hint = lambda _app: Qt.ColorScheme.Unknown  # type: ignore[assignment]
    assert theme.system_is_dark(app) is False
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor("#1e1e1e"))
    theme._system_palettes[id(app)] = dark_palette
    assert theme.system_is_dark(app) is True


def test_an_explicit_theme_reports_itself_before_the_palette_lands(qtbot) -> None:
    """``is_dark`` must answer with the appearance being repainted *into*.

    A widget repainting from the palette change asks what theme it is now, and
    the property used to be set after ``setPalette`` — so for the length of one
    repaint it answered with the outgoing theme.
    """
    from avialsync.ui import theme

    app = QApplication.instance()
    assert app is not None

    seen: list[bool] = []
    app.paletteChanged.connect(lambda _p: seen.append(theme.is_dark()))

    apply_theme(app, THEME_DARK)
    assert theme.is_dark() is True
    apply_theme(app, THEME_LIGHT)
    assert theme.is_dark() is False

    assert seen, "no palette change was delivered, so nothing was proved"
    assert seen[0] is True, "a widget repainting into Dark was told it was Light"


# ── Emphasis that does not cost the palette ──────────────────────────────


def test_bold_text_still_follows_the_palette(qtbot) -> None:
    """The quiet half of "the fonts don't change with the theme".

    Applying any stylesheet hands a widget to Qt's stylesheet style, which
    resolves everything the sheet does not mention from the style's defaults
    instead of from the application palette. A sheet setting only a font weight
    therefore also pinned the text colour: measured, such a label resolved
    ``WindowText`` to black and rendered black ink under a dark palette, while
    the plain label beside it followed. Every bold heading in the sidebar and
    the readout panel was built that way.
    """
    from PySide6.QtWidgets import QLabel

    from avialsync.ui.theme import set_bold

    app = QApplication.instance()
    assert app is not None

    plain = QLabel("Hg")
    emphasised = QLabel("Hg")
    qtbot.addWidget(plain)
    qtbot.addWidget(emphasised)
    set_bold(emphasised)

    assert emphasised.font().bold(), "set_bold must actually embolden"
    assert not plain.font().bold()

    for palette in (DARK, LIGHT):
        plain.setPalette(palette)
        emphasised.setPalette(palette)
        expected = palette.color(QPalette.ColorRole.WindowText)
        assert emphasised.palette().color(QPalette.ColorRole.WindowText) == expected, (
            "emphasised text stopped following the palette"
        )
        assert plain.palette().color(QPalette.ColorRole.WindowText) == expected


def test_emphasis_survives_a_font_size_change(qtbot) -> None:
    """The font-size preference rebuilds each widget's font from a captured base.

    Anything not re-applied during that walk is lost the first time the user
    changes text size — which is why ``set_bold`` records a property rather than
    only setting the font, exactly as ``set_font_family`` does.
    """
    from PySide6.QtWidgets import QLabel

    from avialsync.ui.theme import FONT_LARGE, FONT_SYSTEM, apply_font_size, set_bold

    app = QApplication.instance()
    assert app is not None

    label = QLabel("Hg")
    qtbot.addWidget(label)
    set_bold(label)
    try:
        apply_font_size(app, FONT_LARGE)
        assert label.font().bold(), "a text-size change dropped the emphasis"
    finally:
        apply_font_size(app, FONT_SYSTEM)
