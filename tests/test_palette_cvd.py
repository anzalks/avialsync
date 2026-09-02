"""The categorical palette must survive colour blindness (WP-12, D-094).

The point of these tests is that the palette's *reputation* is not evidence.
Okabe-Ito is well regarded, and it would still be wrong to adopt it here without
measuring it at the size actually used, on the surfaces actually drawn on, and
against the palette it replaces.

They also pin two findings that are easy to get backwards and were, in my first
draft: the wheel's failure is under **protanopia**, not deuteranopia, and it is a
blue/purple pair rather than a red/green one.
"""

from __future__ import annotations

import colorsys

import pytest

from avialsync.ui.cvd import (
    DEFICIENCIES,
    OKABE_ITO,
    lifted,
    minimum_separation,
    palette_for_surface,
    perceptual_distance,
    simulate,
)
from avialsync.ui.theme import MARKER_COLOR_COUNT

#: Below this, two colours are the same colour. The wheel's worst pair sits at
#: 0.025; anything near that is a failure whatever else the palette does well.
INDISTINGUISHABLE = 0.04

#: The floor a shipped palette must clear under every deficiency.
REQUIRED_SEPARATION = 0.05


def _even_hue_wheel(count: int, saturation: float = 0.8, lightness: float = 0.55):
    """The palette this replaces, reconstructed for comparison."""
    colours = []
    for index in range(count):
        hue = (index + 0.5) / count
        red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
        colours.append((int(red * 255), int(green * 255), int(blue * 255)))
    return tuple(colours)


# ── the palette in use clears the floor ──────────────────────────────


@pytest.mark.parametrize("deficiency", DEFICIENCIES)
@pytest.mark.parametrize("dark", [False, True], ids=["light-surface", "dark-surface"])
def test_the_shipped_palette_stays_distinguishable(deficiency: str, dark: bool) -> None:
    palette = palette_for_surface(dark)[:MARKER_COLOR_COUNT]
    separation = minimum_separation(palette, deficiency)
    assert separation >= REQUIRED_SEPARATION, (
        f"under {deficiency} on a {'dark' if dark else 'light'} surface the closest "
        f"pair is {separation:.3f}"
    )


@pytest.mark.parametrize("dark", [False, True], ids=["light-surface", "dark-surface"])
def test_no_pair_is_indistinguishable(dark: bool) -> None:
    """The specific failure being fixed, not just an average."""
    palette = palette_for_surface(dark)[:MARKER_COLOR_COUNT]
    for deficiency in DEFICIENCIES:
        assert minimum_separation(palette, deficiency) > INDISTINGUISHABLE


# ── it is better than what it replaces, where it matters ─────────────


def test_the_wheel_has_an_indistinguishable_pair() -> None:
    """The evidence for the change, measured rather than asserted."""
    wheel = _even_hue_wheel(MARKER_COLOR_COUNT)
    assert minimum_separation(wheel, "protanopia") < INDISTINGUISHABLE


def test_the_wheels_failure_is_protanopia_not_deuteranopia() -> None:
    """The obvious guess is wrong, and this pins the correction."""
    wheel = _even_hue_wheel(MARKER_COLOR_COUNT)
    assert minimum_separation(wheel, "protanopia") < minimum_separation(wheel, "deuteranopia")


def test_the_wheels_worst_pair_is_blue_and_purple() -> None:
    """Not the red/green pair the hue wheel makes you expect."""
    wheel = _even_hue_wheel(MARKER_COLOR_COUNT)
    worst = min(
        ((i, j) for i in range(len(wheel)) for j in range(i + 1, len(wheel))),
        key=lambda pair: perceptual_distance(
            simulate(wheel[pair[0]], "protanopia"), simulate(wheel[pair[1]], "protanopia")
        ),
    )
    for index in worst:
        red, green, blue = wheel[index]
        assert blue > red and blue > green, "both members of the worst pair are blue-dominant"


def test_okabe_ito_beats_the_wheel_under_protanopia() -> None:
    wheel = _even_hue_wheel(MARKER_COLOR_COUNT)
    ours = OKABE_ITO[:MARKER_COLOR_COUNT]
    assert minimum_separation(ours, "protanopia") > 3 * minimum_separation(wheel, "protanopia")


def test_the_tritanopia_trade_is_acknowledged() -> None:
    """It is slightly worse there, and that is the deliberate trade."""
    wheel = _even_hue_wheel(MARKER_COLOR_COUNT)
    ours = OKABE_ITO[:MARKER_COLOR_COUNT]
    assert minimum_separation(ours, "tritanopia") < minimum_separation(wheel, "tritanopia")
    # But still far above indistinguishable, which is the standard that matters.
    assert minimum_separation(ours, "tritanopia") > INDISTINGUISHABLE


# ── the dark-surface adjustment must not undo it ─────────────────────


def test_lifting_preserves_separation() -> None:
    """A uniform shift keeps the lightness differences the palette relies on."""
    original = minimum_separation(OKABE_ITO[:MARKER_COLOR_COUNT], "deuteranopia")
    shifted = minimum_separation(palette_for_surface(True)[:MARKER_COLOR_COUNT], "deuteranopia")
    assert shifted > 0.7 * original


def _rebuilt(lightness: float, saturation: float | None) -> tuple[tuple[int, int, int], ...]:
    """Okabe-Ito with its lightness -- and optionally saturation -- normalised."""
    out = []
    for red, green, blue in OKABE_ITO[:MARKER_COLOR_COUNT]:
        hue, _l, own_saturation = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
        r, g, b = colorsys.hls_to_rgb(
            hue, lightness, own_saturation if saturation is None else saturation
        )
        out.append((int(r * 255), int(g * 255), int(b * 255)))
    return tuple(out)


def test_flattening_lightness_drops_it_below_the_floor() -> None:
    """Why the palette is used as designed rather than re-solved per colour.

    ``theme.on_surface`` solves one lightness for every mark. Applying that here
    takes the worst pair from 0.094 to 0.040 -- below the floor a shipped
    palette has to clear, and at the edge of indistinguishable.
    """
    flattened = _rebuilt(lightness=0.55, saturation=None)
    assert minimum_separation(flattened, "deuteranopia") < REQUIRED_SEPARATION


def test_normalising_saturation_too_destroys_it_outright() -> None:
    """The full `on_surface` treatment, which fixes saturation as well.

    An order of magnitude worse again: 0.094 to 0.004, which is one colour.
    """
    flattened = _rebuilt(lightness=0.55, saturation=0.8)
    designed = minimum_separation(OKABE_ITO[:MARKER_COLOR_COUNT], "deuteranopia")
    assert minimum_separation(flattened, "deuteranopia") < designed / 10


def test_a_lift_stays_in_range() -> None:
    assert lifted((255, 255, 255), 0.5) == (255, 255, 255)
    assert all(0 <= channel <= 255 for channel in lifted((0, 0, 0), -0.5))


# ── the simulation itself ────────────────────────────────────────────


def test_grey_is_unchanged_by_any_deficiency() -> None:
    """A sanity check on the matrices: they alter hue, not luminance."""
    for deficiency in DEFICIENCIES:
        simulated = simulate((128, 128, 128), deficiency)
        assert all(abs(channel - 128) < 20 for channel in simulated)


def test_an_unknown_deficiency_is_a_no_op() -> None:
    assert simulate((10, 20, 30), "not-a-deficiency") == (10, 20, 30)


def test_distance_to_self_is_zero() -> None:
    assert perceptual_distance((10, 20, 30), (10, 20, 30)) == 0.0


def test_a_single_colour_palette_has_no_worst_pair() -> None:
    assert minimum_separation(((1, 2, 3),)) == 1.0


def test_the_palette_is_exactly_the_cycle_length() -> None:
    """No spare colours: an eighth dropped protanopia below the floor."""
    assert len(OKABE_ITO) == MARKER_COLOR_COUNT


def test_adding_an_eighth_colour_would_break_the_floor() -> None:
    """Pins why the palette is this size, so nobody extends it casually."""
    stretched = (*OKABE_ITO, (117, 112, 179))
    assert minimum_separation(stretched, "protanopia") < REQUIRED_SEPARATION
