"""Colour that survives colour blindness (WP-12, D-094).

``theme.marker_color`` was carefully built: hues spread evenly around the wheel
for maximum separation, offset clear of the defect red, lightness solved against
the live palette so the sequence reads on white and on black. The reasoning is
sound and the palette is still wrong, for a reason that reasoning does not
reach.

**Separation in hue is not separation under colour vision deficiency**, and the
seven-step wheel has one pair that proves it. Simulated at severity 1.0, its
blue ``(48, 74, 232)`` and its purple ``(179, 48, 232)`` both become almost
exactly ``(34, 84, 240)`` under protanopia — a separation of 0.025, which is to
say none. Two traces the wheel presents as clearly different are one colour for
those readers.

The mechanism is worth stating precisely, because the obvious guess is wrong.
It is not the red/green pair, and the worst deficiency here is protanopia rather
than deuteranopia; measured, deuteranopia leaves the wheel at a tolerable 0.080.
Even spacing guarantees *angular* distance and says nothing about where those
angles land once two of the three cone responses are gone.

In a viewer where colour encodes channel identity, an indistinguishable pair is
a correctness problem rather than a matter of taste: two traces that look
identical are two traces a reader will conflate.

Okabe–Ito removes that pair. At seven colours it is 3.3× better under
protanopia and 1.2× better under deuteranopia; it is 1.2× *worse* under
tritanopia, which is the trade being made deliberately. A palette is only as
good as its worst pair, and 0.025 is a failure in a way that 0.091 is not.

The simulation lives here so the claim is *testable* rather than taken on the
palette's reputation: ``tests/test_palette_cvd.py`` asserts a floor under all
three deficiencies, at the palette size actually in use.
"""

from __future__ import annotations

import colorsys
import math

__all__ = [
    "OKABE_ITO",
    "simulate",
    "perceptual_distance",
    "minimum_separation",
    "palette_for_surface",
    "lifted",
    "DEFICIENCIES",
]

#: Okabe & Ito's qualitative palette, as (R, G, B) 0-255.
#:
#: Their set is eight including black. Black is dropped here: it is the text
#: colour on a light surface and invisible on a dark one, and a categorical
#: series must not depend on which theme is active. That leaves the seven
#: below, which is exactly ``MARKER_COLOR_COUNT``.
#:
#: An eighth colour was **not** invented to replace black. A first draft added
#: a violet and it took the worst pair under protanopia from 0.084 to 0.048 --
#: below the floor a shipped palette has to clear. The palette is this size
#: because that is how many colours stay distinguishable, and stretching it
#: costs the property it exists for.
OKABE_ITO: tuple[tuple[int, int, int], ...] = (
    (230, 159, 0),  # orange
    (86, 180, 233),  # sky blue
    (0, 158, 115),  # bluish green
    (240, 228, 66),  # yellow
    (0, 114, 178),  # blue
    (213, 94, 0),  # vermillion
    (204, 121, 167),  # reddish purple
)

#: Linear transforms approximating how each deficiency maps colour. Machado,
#: Oliveira and Fernandes' severity-1.0 matrices, which is the standard
#: approximation for exactly this check.
_SIMULATION_MATRICES = {
    "deuteranopia": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "protanopia": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "tritanopia": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.303900),
    ),
}

#: The deficiencies a palette must survive.
DEFICIENCIES = tuple(_SIMULATION_MATRICES)


def simulate(rgb: tuple[int, int, int], deficiency: str) -> tuple[int, int, int]:
    """Return *rgb* as someone with *deficiency* would distinguish it."""
    matrix = _SIMULATION_MATRICES.get(deficiency)
    if matrix is None:
        return rgb

    red, green, blue = (channel / 255.0 for channel in rgb)
    out = []
    for row in matrix:
        value = row[0] * red + row[1] * green + row[2] * blue
        out.append(int(round(max(0.0, min(1.0, value)) * 255)))
    return (out[0], out[1], out[2])


def perceptual_distance(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    """Approximate perceptual distance between two colours, 0-1.

    Weighted so that green counts most and blue least, which is roughly how
    human luminance sensitivity is distributed. A plain RGB euclidean distance
    over-rates blue differences, which is the direction that would let a
    genuinely confusable pair pass.
    """
    weights = (0.30, 0.59, 0.11)
    total = 0.0
    for weight, a, b in zip(weights, first, second, strict=True):
        total += weight * ((a - b) / 255.0) ** 2
    return math.sqrt(total)


def minimum_separation(
    palette: tuple[tuple[int, int, int], ...], deficiency: str | None = None
) -> float:
    """Smallest distance between any two colours, optionally under *deficiency*."""
    colours = [simulate(c, deficiency) if deficiency else c for c in palette]
    if len(colours) < 2:
        return 1.0
    return min(
        perceptual_distance(colours[i], colours[j])
        for i in range(len(colours))
        for j in range(i + 1, len(colours))
    )


#: How much to lift the palette on a dark surface.
#:
#: Measured, not chosen: at +0.08 the worst pair under any deficiency stays at
#: 0.074, against 0.094 unshifted. Larger lifts cost more -- +0.22 drops
#: deuteranopia to 0.036 -- because compressing everything toward white removes
#: the lightness differences the palette relies on.
_DARK_SURFACE_LIFT = 0.08


def lifted(rgb: tuple[int, int, int], lift: float) -> tuple[int, int, int]:
    """Shift *rgb*'s lightness by *lift*, keeping its hue and saturation.

    A **uniform** shift, deliberately, because the obvious alternative destroys
    the palette. Re-solving each colour against the surface the way
    ``theme.on_surface`` does for a single mark takes the worst pair from 0.094
    to 0.040 if only lightness is normalised, and to 0.004 if saturation is
    normalised too -- one colour. Most of Okabe-Ito's separation lives in the
    *differences* between its lightnesses, so flattening them to one value
    throws away the thing that makes it work.
    """
    red, green, blue = (channel / 255.0 for channel in rgb)
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    shifted = max(0.0, min(1.0, lightness + lift))
    out = colorsys.hls_to_rgb(hue, shifted, saturation)
    return tuple(int(round(channel * 255)) for channel in out)  # type: ignore[return-value]


def palette_for_surface(dark_surface: bool) -> tuple[tuple[int, int, int], ...]:
    """The categorical palette, adjusted for the surface it is drawn on.

    Okabe-Ito is designed against a light background. On a dark one every
    colour is lifted by the same amount, which keeps the relative lightnesses
    -- and therefore the separation -- while making the series readable.
    """
    if not dark_surface:
        return OKABE_ITO
    return tuple(lifted(colour, _DARK_SURFACE_LIFT) for colour in OKABE_ITO)
