"""One palette, one name-to-colour rule, shared by the 2D overlay and 3D view.

The video overlay (per-camera 2D pose) and the 3D pose view draw the same
anatomical points from different sources: a camera's own 2D CSV lists whatever
body parts that model tracked, in whatever column order its export happened to
use, while the fused 3D EKS CSV lists its own triangulated set, in its own
column order. Assigning colour by *position* in either list — "the Nth point in
this file gets colour N" — only makes the two views agree by accident, when
both files happen to enumerate the same names in the same order. In general
they do not, so the same body part (e.g. ``nose``) could render cyan in the 2D
overlay and orange in the 3D view.

``color_for_point`` instead maps a point's *name* to a colour, independent of
what other points are present or in what order. The same name always resolves
to the same colour, in both views, on every launch.
"""

from __future__ import annotations

import hashlib

#: Canonical palette. Six distinct, readable hues; this is the single
#: definition both views import rather than each keeping its own copy.
POINT_COLORS: tuple[tuple[int, int, int], ...] = (
    (0, 188, 212),
    (255, 152, 0),
    (156, 39, 176),
    (76, 175, 80),
    (233, 30, 99),
    (63, 81, 181),
)


def color_for_point(
    name: str, palette: tuple[tuple[int, int, int], ...] = POINT_COLORS
) -> tuple[int, int, int]:
    """Return a stable colour for *name*, independent of ordering or siblings.

    Built on a content hash rather than Python's built-in ``hash()``, which is
    salted per process (the same class of trap already fixed elsewhere in this
    codebase for plugin module names, RECOVERY_PLAN V-18): with ``hash()`` the
    same body part could get a different colour on every restart. A stable
    digest keeps the mapping identical across launches and across the two
    independent readers (2D overlay, 3D view) that never see each other's data.
    """
    if not palette:
        raise ValueError("palette must not be empty")
    digest = hashlib.sha1(name.encode("utf-8"), usedforsecurity=False).digest()
    index = int.from_bytes(digest[:4], "big") % len(palette)
    return palette[index]
