"""Derived colours: legible on both surfaces, distinct, and following the accent.

These assert *properties*, never hex values. A test that pins a literal is the
same bug this module exists to remove — it would have to be edited every time
the palette moves, and it proves nothing about legibility.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QPalette

from avialsync.ui.theme import (
    MARKER_COLOR_COUNT,
    accent_hue,
    evidence_color,
    loop_pin_color,
    marker_color,
    on_surface,
    status_color,
)

#: Lightness gap below which a one-pixel tick stops being visible.
_MIN_CONTRAST = 0.2

#: Colour distance below which two lanes are not tellable apart.
_MIN_DISTANCE = 0.15


def _palette(surface: str, accent: str = "#0a84ff") -> QPalette:
    """A palette with an explicit surface and accent, standing in for a theme."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(surface))
    palette.setColor(QPalette.ColorRole.Window, QColor(surface))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(accent))
    palette.setColor(QPalette.ColorRole.Link, QColor(accent))
    return palette


DARK = _palette("#1e1e1e")
LIGHT = _palette("#f5f5f5")

#: Every lane that derives its colour rather than taking a palette role.
DERIVED_LANES = ["gap", "message"]


def _contrast(color: QColor, palette: QPalette) -> float:
    surface = palette.color(QPalette.ColorRole.AlternateBase)
    return abs(color.lightnessF() - surface.lightnessF())


def _distance(a: QColor, b: QColor) -> float:
    """Normalised RGB distance — a blunt but honest 'can I tell these apart'."""
    return max(
        abs(a.redF() - b.redF()),
        abs(a.greenF() - b.greenF()),
        abs(a.blueF() - b.blueF()),
    )


@pytest.mark.parametrize("kind", DERIVED_LANES)
@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_a_derived_lane_contrasts_with_the_surface_it_sits_on(kind: str, palette: QPalette) -> None:
    """The failure this prevents: a tick tuned on dark, invisible on light."""
    assert _contrast(evidence_color(palette, kind), palette) > _MIN_CONTRAST


@pytest.mark.parametrize("kind", DERIVED_LANES)
def test_a_derived_lane_changes_with_the_theme(kind: str) -> None:
    """A hardcoded colour is exactly the one that does not."""
    assert evidence_color(DARK, kind) != evidence_color(LIGHT, kind)


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_messages_are_tellable_apart_from_defects_and_from_sync(palette: QPalette) -> None:
    """Three lanes that mean different things must not paint the same."""
    message = evidence_color(palette, "message")
    gap = evidence_color(palette, "gap")
    sync = evidence_color(palette, "ttl")

    assert _distance(message, gap) > _MIN_DISTANCE
    assert _distance(message, sync) > _MIN_DISTANCE
    assert _distance(gap, sync) > _MIN_DISTANCE


@pytest.mark.parametrize("accent", ["#0a84ff", "#ff453a", "#30d158", "#bf5af2", "#ffd60a"])
def test_message_and_defect_stay_apart_under_every_platform_accent(accent: str) -> None:
    """A cyan accent rotates its derived hue straight onto the defect red.

    Without the separation guard, the Messages lane and the Data-gaps lane paint
    identically for one specific accent and nobody notices until a user picks it.
    """
    palette = _palette("#1e1e1e", accent)
    assert (
        _distance(evidence_color(palette, "message"), evidence_color(palette, "gap"))
        > _MIN_DISTANCE
    )


def test_the_message_lane_follows_the_users_accent() -> None:
    """Derived means derived — change the accent and the lane moves with it."""
    blue = evidence_color(_palette("#1e1e1e", "#0a84ff"), "message")
    green = evidence_color(_palette("#1e1e1e", "#30d158"), "message")
    assert blue != green


def test_a_grey_accent_still_yields_distinguishable_lanes() -> None:
    """macOS Graphite is achromatic; ``hueF`` answers -1 for it.

    Deriving from -1 collapses every accent-relative colour onto one hue, which
    is how a whole set of lanes would quietly become the same colour.
    """
    graphite = _palette("#1e1e1e", "#8e8e93")
    assert accent_hue(graphite) >= 0.0
    assert (
        _distance(evidence_color(graphite, "message"), evidence_color(graphite, "gap"))
        > _MIN_DISTANCE
    )


@pytest.mark.parametrize("severity", ["busy", "warning", "error"])
@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_status_severities_stay_readable_in_both_themes(severity: str, palette: QPalette) -> None:
    assert _contrast(status_color(palette, severity), palette) > _MIN_CONTRAST


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_the_two_loop_pins_never_look_alike(palette: QPalette) -> None:
    """A and B mark opposite ends; one colour for both makes the control useless."""
    assert _distance(loop_pin_color(palette, "in"), loop_pin_color(palette, "out")) > _MIN_DISTANCE


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_consecutive_markers_are_distinguishable(palette: QPalette) -> None:
    """The categorical sequence exists to tell one marker from the next."""
    for index in range(MARKER_COLOR_COUNT):
        first = marker_color(palette, index)
        second = marker_color(palette, index + 1)
        assert _distance(first, second) > _MIN_DISTANCE, f"markers {index} and {index + 1}"


def test_marker_colors_repeat_only_after_the_full_cycle() -> None:
    seen = {marker_color(DARK, index).name() for index in range(MARKER_COLOR_COUNT)}
    assert len(seen) == MARKER_COLOR_COUNT
    assert marker_color(DARK, MARKER_COLOR_COUNT) == marker_color(DARK, 0)


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_markers_stay_readable_on_both_surfaces(palette: QPalette) -> None:
    """The literal list this replaced was tuned for light and washed out on dark."""
    for index in range(MARKER_COLOR_COUNT):
        assert _contrast(marker_color(palette, index), palette) > _MIN_CONTRAST


def test_on_surface_is_the_only_thing_that_needs_the_surface() -> None:
    """Same requested hue, opposite surfaces, opposite lightness."""
    hue = 0.33
    assert on_surface(DARK, hue).lightnessF() > on_surface(LIGHT, hue).lightnessF()


# ── Following a live appearance change ───────────────────────────────────


def test_a_stylesheet_widget_re_derives_its_colour_on_a_palette_change(qtbot) -> None:
    """The whole point of ``follow_palette``.

    Qt re-resolves palette *roles* by itself, but a stylesheet is a literal from
    the moment it is set — nothing re-runs the f-string that built it. Every
    hardcoded ``setStyleSheet("color: #...")`` in this application froze at
    whichever theme was current when its widget was built.
    """
    from PySide6.QtWidgets import QLabel

    from avialsync.ui.theme import follow_palette

    label = QLabel()
    qtbot.addWidget(label)
    follow_palette(label, lambda palette: f"color: {status_color(palette, 'error').name()};")
    before = label.styleSheet()

    label.setPalette(
        LIGHT
        if label.palette().color(QPalette.ColorRole.AlternateBase).lightnessF() < 0.5
        else DARK
    )

    assert label.styleSheet() != before, "a theme switch must re-derive the colour"


def test_the_timeline_lanes_repaint_when_the_appearance_changes(qtbot) -> None:
    """A self-painting widget must ask for the repaint; Qt only does it for its own."""
    from PySide6.QtCore import QEvent

    from avialsync.ui.transport import TimelineOverview

    overview = TimelineOverview()
    qtbot.addWidget(overview)
    overview.set_bounds(0.0, 100.0)
    overview.set_message_events([10.0])
    overview.show()
    qtbot.waitExposed(overview)

    repaints: list[bool] = []
    original = overview.update

    def counting_update(*args: object) -> None:
        repaints.append(True)
        original(*args)

    overview.update = counting_update  # type: ignore[method-assign]
    overview.changeEvent(QEvent(QEvent.Type.PaletteChange))

    assert repaints, "the lanes would keep the previous theme's colours"
