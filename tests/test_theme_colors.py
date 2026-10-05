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
#: Every lane colour derived from the live palette rather than stored.
#: "identity" joins them so an accepted-swap mark is held to the same
#: two promises as the rest: readable on both surfaces, and different on
#: each (D-141).
DERIVED_LANES = ["gap", "message", "identity"]


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

    Driven by an application palette change, because that is what a theme
    switch is. This test used to set the palette on the label itself — the one
    path Qt still delivers to a styled widget — and so passed while every real
    switch left followed widgets on the launch theme. The full switch is covered
    in ``test_theme_followers.py``.
    """
    from PySide6.QtWidgets import QApplication, QLabel

    from avialsync.ui.theme import follow_palette

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    label = QLabel()
    qtbot.addWidget(label)
    follow_palette(label, lambda palette: f"color: {status_color(palette, 'error').name()};")
    before = label.styleSheet()

    entry = QPalette(app.palette())
    try:
        app.setPalette(
            LIGHT
            if label.palette().color(QPalette.ColorRole.AlternateBase).lightnessF() < 0.5
            else DARK
        )
        assert label.styleSheet() != before, "a theme switch must re-derive the colour"
    finally:
        app.setPalette(entry)


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


# ── a proposal is not a fault (D-141) ────────────────────────────────


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_a_proposed_crossing_wears_the_identity_colour_not_the_caution_one(
    palette: QPalette,
) -> None:
    """Reserved colours are reserved.

    A candidate crossing borrowed the caution colour, which says *fault* about
    something nobody has acted on, and spends a status colour on a series. Both
    kinds of crossing are the same kind of thing: same hue, and fill and weight
    say which is which.
    """
    from avialsync.ui.identity_braid import _node_color

    accepted = _node_color(palette, accepted=True)
    proposed = _node_color(palette, accepted=False)

    assert proposed == accepted, "one hue; the fill says which kind it is"
    assert proposed.alpha() == 255, (
        "a faded proposal disappears into the lane it sits on, which is the one "
        "mark a person is hunting for"
    )
    assert _distance(proposed, status_color(palette, "warning")) > 0.05


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_a_proposed_crossing_stays_readable_on_both_surfaces(palette: QPalette) -> None:
    """Lighter, but never so light that the proposal cannot be seen."""
    from avialsync.ui.identity_braid import _node_color

    assert _contrast(_node_color(palette, accepted=False), palette) > _MIN_CONTRAST


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_the_identity_lane_is_a_stated_colour_not_a_rotation(palette: QPalette) -> None:
    """It is chosen, not computed from whatever accent the machine reports.

    Rotating from the accent sent this mark wherever the accent happened to
    point -- magenta one way, a status-like mint green the other. The pair is
    stated instead, and this pins it so a later edit does not quietly go back
    to arithmetic.
    """
    identity = evidence_color(palette, "identity")
    red, green, blue = identity.red(), identity.green(), identity.blue()

    assert blue > green, f"expected the muted violet, got {identity.name()}"
    assert red < blue, f"expected the muted violet, got {identity.name()}"


def test_the_identity_lane_does_not_follow_the_accent(qapp) -> None:
    """Two very different accents, one identity colour."""
    from PySide6.QtGui import QColor

    from avialsync.ui.theme import _palette_with_surfaces

    blue = _palette_with_surfaces(True, QColor("#0a84ff"))
    red = _palette_with_surfaces(True, QColor("#ff3b30"))

    assert evidence_color(blue, "identity") == evidence_color(red, "identity")


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_the_identity_lane_is_tellable_from_every_status_colour(palette: QPalette) -> None:
    identity = evidence_color(palette, "identity")

    for severity in ("busy", "warning", "error"):
        assert _distance(identity, status_color(palette, severity)) > 0.15, severity


# ── The surface evidence is drawn on ─────────────────────────────────────


def test_a_contradictory_platform_surface_is_not_taken_at_its_word() -> None:
    """macOS's dark palette reports an opaque light-grey ``AlternateBase``.

    Measured ``#989898`` inside a ``#323232`` window. The timeline filled its
    lanes with it under the System appearance on a dark desktop, and every mark
    solved against it chose ink for a light surface.
    """
    from avialsync.ui.theme import surface_color

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#323232"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#171717"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#989898"))

    assert surface_color(palette).lightnessF() < 0.5
    assert on_surface(palette, 0.33).lightnessF() > 0.5, "marks chose light-surface ink"


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_a_consistent_surface_is_used_as_given(palette: QPalette) -> None:
    from avialsync.ui.theme import surface_color

    assert surface_color(palette) == palette.color(QPalette.ColorRole.AlternateBase)


# ── Data coverage is its own colour ──────────────────────────────────────


def _hue_distance(first: QColor, second: QColor) -> float:
    return abs((first.hslHueF() - second.hslHueF() + 0.5) % 1.0 - 0.5)


@pytest.mark.parametrize(
    "accent", ["#0a84ff", "#ff9f0a", "#30d158", "#bf5af2", "#ff375f", "#8e8e93"]
)
@pytest.mark.parametrize("surface", ["#1e1e1e", "#f5f5f5"], ids=["dark", "light"])
def test_data_coverage_is_tellable_from_every_other_timeline_meaning(
    accent: str, surface: str
) -> None:
    """Data coverage took ``Link`` -- the accent at another lightness -- so the
    two coverage rows differed only in how light one blue was."""
    palette = _palette(surface, accent)
    data = evidence_color(palette, "data")
    others = {
        "video": on_surface(palette, accent_hue(palette)),
        "gap": evidence_color(palette, "gap"),
        "message": evidence_color(palette, "message"),
        "loop in": loop_pin_color(palette, "in"),
        "loop out": loop_pin_color(palette, "out"),
    }
    for name, colour in others.items():
        assert _hue_distance(data, colour) >= 0.07, f"data coverage looks like {name}"
    assert _contrast(data, palette) > _MIN_CONTRAST
