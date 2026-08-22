"""Bone topology for the 3D view: what to draw, and where it came from.

Two questions the pane itself should not answer inline. Which skeleton is in
force (declared by the session, derived from geometry, or none) is a display
mode; matching a declared body-part name onto the point names the cache
actually holds is string work that has nothing to do with painting.

Deriving topology lives in :mod:`avialsync.core.skeleton`, which is headless.
This module is the adapter: it samples the pane's mmap-backed trajectories into
the array that inference wants, and resolves declared names against real ones.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from typing import Protocol

import numpy as np


class BoneMode(Enum):
    """Which skeleton the 3D view draws.

    ``AUTO`` is the default and the only mode that changes with the data: it
    draws what the session declared, and falls back to geometry when the
    session declared nothing. The other two are user pins, so a scientist who
    distrusts a derived skeleton can turn it off and keep it off.
    """

    AUTO = "auto"
    DETECTED = "detected"
    OFF = "off"


class _PointArrays(Protocol):
    """The shape of one tracked point, as the 3D pane already holds it.

    Read-only members, so the pane's frozen dataclass satisfies it: a Protocol
    declaring plain attributes demands settable ones.
    """

    @property
    def name(self) -> str:
        """Body-part name this point's channels were grouped under."""

    @property
    def values(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Coordinate arrays, one per axis, in XYZ order."""

    @property
    def gaps(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Per-axis masks marking samples the source never recorded."""


def sample_trajectories(
    points: Sequence[_PointArrays], budget: int
) -> tuple[tuple[str, ...], np.ndarray]:
    """Stride *budget* frames out of mmap-backed trajectories into one array.

    Striding rather than slicing keeps the sample representative of the whole
    recording — a pose that only ever bends in its last minute still shows the
    bend — while touching a bounded number of cache pages. Gapped samples
    become NaN, which is what the inference treats as "not observed".
    """
    if not points:
        return (), np.zeros((0, 0, 3), dtype=np.float64)

    frame_count = min(len(point.values[0]) for point in points)
    if frame_count == 0:
        return tuple(point.name for point in points), np.zeros(
            (0, len(points), 3), dtype=np.float64
        )
    step = max(1, int(np.ceil(frame_count / budget)))

    sampled = np.empty((len(range(0, frame_count, step)), len(points), 3), dtype=np.float64)
    for index, point in enumerate(points):
        for axis in range(3):
            column = np.asarray(point.values[axis][:frame_count:step], dtype=np.float64)
            gaps = np.asarray(point.gaps[axis][:frame_count:step], dtype=bool)
            sampled[:, index, axis] = np.where(gaps, np.nan, column)
    return tuple(point.name for point in points), sampled


def resolve_edges(
    declared: Sequence[tuple[str, str]], names: Sequence[str]
) -> list[tuple[str, str]]:
    """Map declared body-part names onto the point names the cache holds.

    A session names body parts; a cache holds channel-derived point names, and
    the two agree only when every loader stripped every prefix the same way.
    An edge whose endpoint is one unambiguous suffix away — ``head_bar`` for
    ``ensemble_head_bar`` — is the same bone, and dropping it silently is how a
    declared skeleton ends up invisible.

    Resolution never invents topology: it only renames endpoints of edges the
    data already declared, and a name matching two points at once is skipped
    rather than guessed at.
    """
    exact = {name: name for name in names}
    lowered: dict[str, list[str]] = {}
    for name in names:
        lowered.setdefault(name.lower(), []).append(name)

    resolved: list[tuple[str, str]] = []
    for first, second in declared:
        start = _resolve_name(first, exact, lowered, names)
        end = _resolve_name(second, exact, lowered, names)
        if start is not None and end is not None and start != end:
            resolved.append((start, end))
    return resolved


def _resolve_name(
    declared: str,
    exact: dict[str, str],
    lowered: dict[str, list[str]],
    names: Sequence[str],
) -> str | None:
    """Find the one point *declared* refers to, or None when it is ambiguous."""
    if declared in exact:
        return exact[declared]
    candidates = lowered.get(declared.lower().strip(), [])
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        return None
    key = declared.lower().strip()
    suffix_matches = [name for name in names if name.lower().endswith(key)]
    return suffix_matches[0] if len(suffix_matches) == 1 else None


def bone_depths(edges: Sequence[tuple[str, str]], roots: Sequence[str]) -> dict[str, int]:
    """Depth of each point below its root, for edges already ordered parent-first.

    The view uses it to taper bones outward, which is how the direction the
    skeleton was rooted in becomes visible without drawing arrowheads on a plot
    that is already dense with markers.
    """
    depths = {root: 0 for root in roots}
    for parent, child in edges:
        depths[child] = depths.get(parent, 0) + 1
    return depths
