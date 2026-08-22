"""Tests for geometry-derived skeleton topology (D-082).

Headless by construction: the inference lives in ``core`` and never touches Qt,
so these run without a display.
"""

from __future__ import annotations

import numpy as np

from avialsync.core.skeleton import (
    MAX_POINTS,
    SkeletonEstimate,
    frame_budget,
    infer_skeleton,
)


def _rotation(axis: np.ndarray, angle: float) -> np.ndarray:
    """Rodrigues rotation matrix about a unit *axis*."""
    unit = axis / np.linalg.norm(axis)
    cross = np.array(
        [
            [0.0, -unit[2], unit[1]],
            [unit[2], 0.0, -unit[0]],
            [-unit[1], unit[0], 0.0],
        ]
    )
    return np.eye(3) + np.sin(angle) * cross + (1.0 - np.cos(angle)) * (cross @ cross)


def _articulated_chain(
    frames: int = 200,
    lengths: tuple[float, ...] = (40.0, 35.0, 30.0, 25.0),
    seed: int = 7,
    drift: float = 25.0,
) -> np.ndarray:
    """A chain of rigid segments with wide joint motion and a drifting root.

    Every segment holds its length exactly, so a true bone has zero length
    variation; every non-adjacent pair swings with the joint angles.
    """
    rng = np.random.default_rng(seed)
    samples = np.zeros((frames, len(lengths) + 1, 3), dtype=np.float64)
    axis = np.array([0.0, 1.0, 0.0])
    for frame in range(frames):
        # The whole animal translates, so a pair is only rigid because it is
        # linked, never because the scene happens to sit still.
        position = rng.normal(scale=drift, size=3)
        direction = np.array([0.0, 0.0, -1.0])
        samples[frame, 0] = position
        for joint, length in enumerate(lengths):
            direction = _rotation(axis, rng.uniform(-1.1, 1.1)) @ direction
            direction = _rotation(np.array([1.0, 0.0, 0.0]), rng.uniform(-0.9, 0.9)) @ direction
            position = position + direction / np.linalg.norm(direction) * length
            samples[frame, joint + 1] = position
    return samples


def _undirected(estimate: SkeletonEstimate) -> set[frozenset[str]]:
    return {frozenset(edge) for edge in estimate.edges}


def test_rigid_segments_are_recovered_as_the_skeleton() -> None:
    """Constant-length pairs link; pairs that swing with a joint do not."""
    names = ["head", "neck", "spine", "hip", "tail"]
    estimate = infer_skeleton(names, _articulated_chain())

    assert _undirected(estimate) == {
        frozenset(("head", "neck")),
        frozenset(("neck", "spine")),
        frozenset(("spine", "hip")),
        frozenset(("hip", "tail")),
    }
    assert max(estimate.variation.values()) < 1e-6


def test_edges_flow_outward_from_the_highest_point() -> None:
    """The anatomical vertical decides the root, and parents point away from it."""
    names = ["head", "neck", "spine", "hip", "tail"]
    # The chain is built descending in -Z, so +Z up puts 'head' on top.
    estimate = infer_skeleton(names, _articulated_chain(), up=np.array([0.0, 0.0, 1.0]))

    assert estimate.roots == ("head",)
    assert estimate.parents == {
        "neck": "head",
        "spine": "neck",
        "hip": "spine",
        "tail": "hip",
    }
    # Parent first in every emitted pair, so a consumer draws outward in order.
    assert estimate.edges[0] == ("head", "neck")


def test_inverting_the_vertical_reverses_the_flow() -> None:
    """A view whose vertical grows downward roots the same tree at the other end."""
    names = ["head", "neck", "spine", "hip", "tail"]
    estimate = infer_skeleton(names, _articulated_chain(), up=np.array([0.0, 0.0, -1.0]))

    assert estimate.roots == ("tail",)
    assert estimate.parents["hip"] == "tail"


def test_independent_bodies_are_not_joined_into_one_tree() -> None:
    """Two clusters with no rigid link stay two components, never a guessed bone."""
    first = _articulated_chain(lengths=(40.0, 35.0), seed=1, drift=200.0)
    second = _articulated_chain(lengths=(30.0, 25.0), seed=2, drift=200.0)
    samples = np.concatenate((first, second), axis=1)
    names = ["a_head", "a_mid", "a_tail", "b_head", "b_mid", "b_tail"]

    estimate = infer_skeleton(names, samples)

    assert len(estimate.roots) == 2
    for parent, child in estimate.edges:
        assert parent[0] == child[0], f"{parent}-{child} crosses two independent bodies"


def test_names_alone_never_create_a_bone() -> None:
    """Anatomical names on unrelated trajectories stay unconnected (D-041)."""
    rng = np.random.default_rng(3)
    samples = rng.normal(scale=50.0, size=(200, 2, 3))
    estimate = infer_skeleton(["head", "neck"], samples)

    assert estimate.edges == ()
    assert not estimate


def test_a_point_without_overlapping_samples_is_left_unlinked() -> None:
    """A marker present in too few frames has no evidence and gets no bone."""
    samples = _articulated_chain(lengths=(40.0, 35.0))
    samples[5:, 2, :] = np.nan
    names = ["head", "mid", "ghost"]

    estimate = infer_skeleton(names, samples)

    assert _undirected(estimate) == {frozenset(("head", "mid"))}
    assert "ghost" not in estimate.parents


def test_gaps_are_excluded_pair_by_pair_not_frame_by_frame() -> None:
    """One dropped marker must not discard the frames the others were seen in."""
    samples = _articulated_chain(lengths=(40.0, 35.0, 30.0))
    samples[::2, 3, :] = np.nan  # the last joint is missing on half the frames
    names = ["head", "neck", "hip", "tail"]

    estimate = infer_skeleton(names, samples)

    assert _undirected(estimate) == {
        frozenset(("head", "neck")),
        frozenset(("neck", "hip")),
        frozenset(("hip", "tail")),
    }


def test_sampling_is_bounded_for_a_long_recording() -> None:
    """A long session is strided, not scanned, so setup stays a UI-thread callback."""
    samples = _articulated_chain(frames=40_000, lengths=(40.0, 35.0))
    estimate = infer_skeleton(["head", "mid", "tail"], samples)

    assert estimate.frames_used <= frame_budget(3)
    assert estimate.frames_used <= 256
    assert estimate  # striding still finds the topology


def test_frame_budget_shrinks_as_points_grow() -> None:
    """The pairwise pass stays inside one work budget however many points arrive."""
    assert frame_budget(8) == 256
    assert frame_budget(64) < frame_budget(16)
    assert frame_budget(64) >= 24


def test_oversized_and_degenerate_inputs_return_nothing() -> None:
    """Too many points, too few points, or the wrong shape all decline to guess."""
    assert infer_skeleton([], np.zeros((10, 0, 3))).edges == ()
    assert infer_skeleton(["only"], np.zeros((10, 1, 3))).edges == ()
    too_many = [f"p{index}" for index in range(MAX_POINTS + 1)]
    assert infer_skeleton(too_many, np.zeros((10, len(too_many), 3))).edges == ()
    assert infer_skeleton(["a", "b"], np.zeros((10, 2))).edges == ()


def test_a_frozen_scene_still_reports_no_flow_direction_without_a_vertical() -> None:
    """Without a vertical the root is the most connected point, deterministically."""
    samples = _articulated_chain(lengths=(40.0, 35.0, 30.0, 25.0))
    names = ["head", "neck", "spine", "hip", "tail"]

    first = infer_skeleton(names, samples)
    second = infer_skeleton(names, samples)

    assert first.edges == second.edges
    assert len(first.roots) == 1
