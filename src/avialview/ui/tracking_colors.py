"""One palette, one name-to-colour rule, shared by the 2D overlay and 3D view.

The video overlay (per-camera 2D pose) and the 3D pose view draw the same
anatomical points from different sources: a camera's own 2D CSV lists whatever
body parts that model tracked, in whatever column order its export happened to
use, while the fused 3D EKS CSV lists its own triangulated set, in its own
column order. Assigning colour by *position* in either list — "the Nth point in
this file gets colour N" — only makes the two views agree by accident, when
both files happen to enumerate the same names in the same order. In general
they do not, so the same body part (e.g. ``nose``) could render one colour in
the 2D overlay and another in the 3D view.

The colour is therefore keyed on a point's *name*, and both views read it from
one shared registry. ``nose`` is the same colour in the overlay and in the 3D
view because there is a single dict holding that answer, not because two
independent rules happened to agree.

Assignment happens when data loads: :meth:`PointColorRegistry.register` walks
the names it has not seen before in sorted order and hands each the next
palette entry. Two consequences worth knowing:

* Points get *distinct* colours while the palette lasts. The earlier rule
  hashed each name into the palette independently, which — as hashes do —
  collided freely: a real ten-point pose set drew from only three of the six
  available colours, so body parts shared colours for no reason.
* A name already assigned never changes colour, so loading a second source
  mid-session cannot recolour the points already on screen. The cost is that
  assignment follows load order: registering ``{nose, tail}`` and then ``{ear}``
  gives ``ear`` the third colour, whereas loading all three at once would give
  it the first. Reloading the same session the same way is stable; two sessions
  that load the same parts in a different order need not match.
"""

from __future__ import annotations

from collections.abc import Iterable

#: Canonical palette, shared by both views rather than each keeping a copy.
#:
#: Muted rather than saturated (Material 300 rather than 500): these markers sit
#: on top of the footage being examined, and fully saturated dots read as the
#: subject of the image instead of an annotation of it.
#:
#: Ten entries, chosen to maximise the smallest perceptual gap between any two
#: (CIE76 ΔE 20.9 at the closest pair, purple/plum) over the muted range. Every
#: entry keeps enough chroma to stay distinct from the browns and greys of fur
#: and rig hardware; low-chroma colours separate well numerically but camouflage
#: against real footage, which is the thing that actually matters here.
POINT_COLORS: tuple[tuple[int, int, int], ...] = (
    (77, 208, 225),
    (255, 183, 77),
    (186, 104, 200),
    (129, 199, 132),
    (240, 98, 146),
    (121, 134, 203),
    (229, 115, 115),
    (100, 181, 246),
    (220, 231, 117),
    (206, 147, 216),
)


class PointColorRegistry:
    """Hand out one stable colour per body-part name, decided at load time."""

    def __init__(self, palette: tuple[tuple[int, int, int], ...] = POINT_COLORS) -> None:
        if not palette:
            raise ValueError("palette must not be empty")
        self._palette = palette
        self._assigned: dict[str, tuple[int, int, int]] = {}

    def register(self, names: Iterable[str]) -> None:
        """Assign a colour to every name not seen before, in sorted order.

        Idempotent, so a view may call it on every refresh: names already
        assigned keep the colour they were given.
        """
        for name in sorted({n for n in names if n and n not in self._assigned}):
            self._assigned[name] = self._palette[len(self._assigned) % len(self._palette)]

    def color(self, name: str) -> tuple[int, int, int]:
        """Return *name*'s colour, assigning one now if it was never registered.

        Painting must never fail on an unregistered name — a loose ``*_x``/
        ``*_y`` reader pair reaches the overlay without passing through any
        load-time registration — so this is deliberately total.
        """
        assigned = self._assigned.get(name)
        if assigned is None:
            self.register([name])
            assigned = self._assigned[name]
        return assigned

    def reset(self) -> None:
        """Forget every assignment. For tests that need a known starting point."""
        self._assigned.clear()


#: The one registry both views share. Two instances would reintroduce exactly
#: the 2D/3D disagreement this module exists to prevent.
REGISTRY = PointColorRegistry()


def register_points(names: Iterable[str]) -> None:
    """Decide colours for *names* now, before anything paints them."""
    REGISTRY.register(names)


def color_for_point(name: str) -> tuple[int, int, int]:
    """Return the shared colour for the body part called *name*."""
    return REGISTRY.color(name)
