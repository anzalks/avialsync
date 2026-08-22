"""Skeleton topology derived from the geometry of 3D pose points.

Point *names* never imply connectivity (D-041): calling a channel ``head_bar``
says nothing about what it is attached to, and guessing from the lexicon
invents scientific semantics the recording never claimed. The trajectories do
carry that evidence, though -- two markers on one rigid segment hold a constant
separation however the animal moves, and two that are not do not. This module
reads only that: pairwise distance over time, a minimum spanning tree over how
rigid each pair is, and a root chosen from the anatomical vertical so the tree
has a direction to flow in.

The result is an *estimate*, never a declaration. A session that ships explicit
topology always wins, and the view marks a derived skeleton as derived (D-082).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

#: Above this many points the O(P^2) pass stops being a UI-thread callback.
#: Real pose rigs are far below it -- the AOL reference session emits 27.
MAX_POINTS = 64

#: Elements per pairwise pass, which sets how many frames are sampled for a
#: given point count. Sampling spans the whole recording by striding, so a
#: longer session is described no worse than a short one, only more coarsely.
_PAIR_WORK_BUDGET = 400_000
_MIN_FRAMES = 24
_MAX_FRAMES = 256

#: Frames in which both endpoints are present, below which a pair has no
#: evidence either way and is not linked.
DEFAULT_MIN_OVERLAP = 12

#: Length coefficient of variation above which a pair is not a credible rigid
#: segment. A triangulated bone measures 0.0-0.05 once reconstruction noise is
#: included, so 0.15 leaves room for a noisy short segment while still rejecting
#: a pair whose separation merely happens to stay in the same range -- two
#: animals drifting around one arena reach ~0.33 by coincidence alone, and a
#: threshold loose enough to admit that draws bones between them.
DEFAULT_MAX_VARIATION = 0.15

#: Weight on normalised segment length in the spanning-tree cost. Rigidity
#: decides connectivity; this only breaks ties toward the shorter of two
#: equally rigid candidates, which is the one an anatomy would call a bone.
_LENGTH_WEIGHT = 0.15


@dataclass(frozen=True)
class SkeletonEstimate:
    """Connectivity derived from pose geometry, with the flow it was rooted in.

    ``edges`` are ordered parent to child, breadth-first from each root, so a
    consumer that draws them in order draws outward from the roots. Disjoint
    groups of points stay disjoint: a forest is the honest answer when the data
    shows no rigid link between two clusters, and inventing one to force a
    single tree would be exactly the guess this module exists to avoid.
    """

    edges: tuple[tuple[str, str], ...] = ()
    roots: tuple[str, ...] = ()
    parents: dict[str, str] = field(default_factory=dict)
    #: Length coefficient of variation per edge -- 0.0 is perfectly rigid.
    variation: dict[tuple[str, str], float] = field(default_factory=dict)
    #: Frames actually examined, for status text and tests.
    frames_used: int = 0

    def __bool__(self) -> bool:
        """True when any connectivity was found."""
        return bool(self.edges)


def frame_budget(point_count: int) -> int:
    """Frames to sample for *point_count* points, bounded by the pairwise budget."""
    if point_count <= 1:
        return _MIN_FRAMES
    per_frame = point_count * point_count
    return int(np.clip(_PAIR_WORK_BUDGET // per_frame, _MIN_FRAMES, _MAX_FRAMES))


def _strided(samples: np.ndarray, budget: int) -> np.ndarray:
    """Take at most *budget* frames spread across the whole recording."""
    frame_count = samples.shape[0]
    if frame_count <= budget:
        return samples
    step = int(np.ceil(frame_count / budget))
    return samples[::step]


def _pair_statistics(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return per-pair (overlap count, mean distance, distance std).

    NaN-aware without ``nanstd``: a masked sum of squares costs one pass where
    the nan-functions cost several over the same (frames x points x points)
    buffer, and this runs on the UI thread when a session finishes importing.
    """
    squared = np.zeros((samples.shape[0], samples.shape[1], samples.shape[1]), dtype=np.float64)
    for axis in range(3):
        column = samples[:, :, axis]
        delta = column[:, :, None] - column[:, None, :]
        squared += delta * delta
    distance = np.sqrt(squared)

    present = np.isfinite(distance)
    finite = np.where(present, distance, 0.0)
    counts = present.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = finite.sum(axis=0) / counts
        variance = (finite * finite).sum(axis=0) / counts - mean * mean
    return counts, mean, np.sqrt(np.maximum(variance, 0.0))


def _rigidity_cost(
    samples: np.ndarray, min_overlap: int, max_variation: float
) -> tuple[np.ndarray, np.ndarray]:
    """Return (cost, variation) matrices; ``inf`` marks a pair that cannot link."""
    counts, mean, deviation = _pair_statistics(samples)
    with np.errstate(invalid="ignore", divide="ignore"):
        variation = deviation / mean

    usable = (counts >= min_overlap) & np.isfinite(mean) & (mean > 0.0)
    usable &= np.isfinite(variation) & (variation <= max_variation)
    np.fill_diagonal(usable, False)

    lengths = mean[usable]
    scale = float(np.median(lengths)) if lengths.size else 1.0
    if not np.isfinite(scale) or scale <= 0.0:
        scale = 1.0

    cost = np.full(mean.shape, np.inf, dtype=np.float64)
    cost[usable] = variation[usable] + _LENGTH_WEIGHT * (mean[usable] / scale)
    return cost, np.where(usable, variation, np.inf)


def _spanning_forest(cost: np.ndarray) -> list[tuple[int, int]]:
    """Prim's algorithm, restarted per component, over a dense cost matrix.

    Restarting is what turns the tree into a forest: when nothing reachable is
    finite, the remaining points start their own component instead of being
    joined by the least-bad link available.
    """
    point_count = cost.shape[0]
    in_tree = np.zeros(point_count, dtype=bool)
    best_cost = np.full(point_count, np.inf, dtype=np.float64)
    best_from = np.full(point_count, -1, dtype=np.int64)
    edges: list[tuple[int, int]] = []

    for _ in range(point_count):
        candidate = np.where(in_tree, np.inf, best_cost)
        index = int(np.argmin(candidate))
        if not np.isfinite(candidate[index]):
            # No finite link into the rest: seed the next component at the
            # lowest remaining index, which keeps the result deterministic.
            remaining = np.flatnonzero(~in_tree)
            if remaining.size == 0:
                break
            index = int(remaining[0])
        elif best_from[index] >= 0:
            edges.append((int(best_from[index]), index))

        in_tree[index] = True
        improved = (~in_tree) & (cost[index] < best_cost)
        best_cost[improved] = cost[index][improved]
        best_from[improved] = index

    return edges


def _finite_height(height: np.ndarray, index: int) -> float:
    """Treat a missing height as the lowest possible, never as a winner."""
    value = float(height[index])
    return value if np.isfinite(value) else -np.inf


def _root_of(component: list[int], height: np.ndarray | None, degree: np.ndarray) -> int:
    """Pick the point a component's flow starts from.

    The anatomical vertical, when the view has one, makes that the topmost
    point -- a head, on any animal that holds one up. Without it, the most
    connected point is the closest thing to a trunk the geometry offers.
    """
    if height is not None and np.any(np.isfinite(height[component])):
        return sorted(component, key=lambda index: (-_finite_height(height, index), index))[0]
    return sorted(component, key=lambda index: (-int(degree[index]), index))[0]


def _component(start: int, neighbours: dict[int, list[int]]) -> list[int]:
    """Collect every point reachable from *start*."""
    stack = [start]
    found = {start}
    while stack:
        current = stack.pop()
        for neighbour in neighbours[current]:
            if neighbour not in found:
                found.add(neighbour)
                stack.append(neighbour)
    return sorted(found)


def _rooted_edges(
    names: Sequence[str],
    neighbours: dict[int, list[int]],
    degree: np.ndarray,
    height: np.ndarray | None,
) -> tuple[list[tuple[str, str]], dict[str, str], list[str]]:
    """Walk each component outward from its root, parent-first."""
    ordered: list[tuple[str, str]] = []
    parents: dict[str, str] = {}
    roots: list[str] = []
    seen: set[int] = set()

    for start in range(len(names)):
        if start in seen or degree[start] == 0:
            continue
        component = _component(start, neighbours)
        seen.update(component)
        root = _root_of(component, height, degree)
        roots.append(names[root])
        queue = [root]
        visited = {root}
        while queue:
            current = queue.pop(0)
            for neighbour in sorted(neighbours[current]):
                if neighbour in visited:
                    continue
                visited.add(neighbour)
                ordered.append((names[current], names[neighbour]))
                parents[names[neighbour]] = names[current]
                queue.append(neighbour)
    return ordered, parents, roots


def infer_skeleton(
    names: Sequence[str],
    samples: np.ndarray,
    *,
    up: np.ndarray | None = None,
    min_overlap: int = DEFAULT_MIN_OVERLAP,
    max_variation: float = DEFAULT_MAX_VARIATION,
) -> SkeletonEstimate:
    """Derive skeleton connectivity from how rigidly point pairs hold together.

    Args:
        names: One name per point, in the order of ``samples``' second axis.
        samples: ``(frames, points, 3)`` coordinates; NaN marks a missing
            sample, which is excluded pair by pair rather than frame by frame.
        up: Optional world-space vertical, used only to root each component so
            its edges flow from the anatomically highest point outward.
        min_overlap: Frames both endpoints must be present in to be judged.
        max_variation: Largest length coefficient of variation still counted as
            a rigid segment.

    Returns:
        A :class:`SkeletonEstimate`, empty when the data carries too few points,
        too few frames, or no credibly rigid pair.
    """
    point_count = len(names)
    if point_count < 2 or point_count > MAX_POINTS:
        return SkeletonEstimate()
    coordinates = np.asarray(samples, dtype=np.float64)
    if coordinates.ndim != 3 or coordinates.shape[1] != point_count or coordinates.shape[2] != 3:
        return SkeletonEstimate()

    window = _strided(coordinates, frame_budget(point_count))
    frames_used = int(window.shape[0])
    if frames_used < min_overlap:
        return SkeletonEstimate()

    cost, variation = _rigidity_cost(window, min_overlap, max_variation)
    tree_edges = _spanning_forest(cost)
    if not tree_edges:
        return SkeletonEstimate(frames_used=frames_used)

    neighbours: dict[int, list[int]] = {index: [] for index in range(point_count)}
    for first, second in tree_edges:
        neighbours[first].append(second)
        neighbours[second].append(first)
    degree = np.array([len(neighbours[index]) for index in range(point_count)], dtype=np.int64)

    height: np.ndarray | None = None
    if up is not None:
        direction = np.asarray(up, dtype=np.float64).reshape(3)
        with np.errstate(invalid="ignore"):
            height = np.nanmean(window @ direction, axis=0)

    index_of = {name: index for index, name in enumerate(names)}
    ordered, parents, roots = _rooted_edges(names, neighbours, degree, height)
    scores = {
        (parent, child): float(variation[index_of[parent], index_of[child]])
        for parent, child in ordered
    }
    return SkeletonEstimate(
        edges=tuple(ordered),
        roots=tuple(roots),
        parents=parents,
        variation=scores,
        frames_used=frames_used,
    )
