"""The perspective map between a flat surface and one camera image (D-165).

Four clicked image points of four known points on a plane fix the homography
between them exactly. That lets one uncalibrated view place a planar model --
a ladder's rung lattice, a belt's side profile -- with correct perspective,
while the user's own measurements supply its size.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from avialsync.core.errors import PropModelError

__all__ = ["PlaneView"]

Pair = tuple[float, float]


class PlaneView:
    """Plane coordinates to pixels and back, from four correspondences."""

    def __init__(self, plane: Sequence[Pair], image: Sequence[Pair]) -> None:
        if len(plane) != 4 or len(image) != 4:
            raise PropModelError("A plane view needs exactly four point pairs.")
        rows = []
        for (u, v), (x, y) in zip(plane, image, strict=True):
            rows.append((u, v, 1.0, 0.0, 0.0, 0.0, -x * u, -x * v, -x))
            rows.append((0.0, 0.0, 0.0, u, v, 1.0, -y * u, -y * v, -y))
        system = np.asarray(rows, dtype=np.float64)
        if not np.isfinite(system).all():
            raise PropModelError("Plane view points must be finite.")
        _, singular, vh = np.linalg.svd(system)
        # Three collinear points leave a second null direction: no unique map.
        if singular[-2] < 1e-9 * max(1.0, singular[0]):
            raise PropModelError("Three of the four points are in a line.")
        matrix = vh[-1].reshape(3, 3)
        sides = [float(matrix[2] @ (u, v, 1.0)) for u, v in plane]
        if not (all(side > 0 for side in sides) or all(side < 0 for side in sides)):
            raise PropModelError("The clicked points cannot show one flat surface.")
        self._matrix = matrix / (1.0 if sides[0] > 0 else -1.0)
        self._inverse = np.linalg.inv(self._matrix)

    def pixel(self, u: float, v: float) -> Pair | None:
        """The image of a plane point, or None beyond the view's horizon."""
        x, y, w = self._matrix @ (u, v, 1.0)
        if w <= 1e-12 or not np.isfinite((x, y, w)).all():
            return None
        return (float(x / w), float(y / w))

    def plane(self, x: float, y: float) -> Pair | None:
        """The plane point a pixel shows, or None where it shows no plane point."""
        u, v, w = self._inverse @ (x, y, 1.0)
        if w <= 1e-12 or not np.isfinite((u, v, w)).all():
            return None
        return (float(u / w), float(v / w))
