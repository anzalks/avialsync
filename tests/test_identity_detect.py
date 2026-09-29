"""Finding a flip the tracker made, against data where the truth is known.

Every fixture here is built by taking two clean trajectories and *injecting* the
failure -- exchanging the labels from a known frame -- so the detector is
measured against the frame that was corrupted rather than against its own
output. The reconstruction test closes the loop: accepting what it proposes has
to give back the trajectories the corruption was applied to, exactly.
"""

from __future__ import annotations

import warnings

import numpy as np

from avialsync.core import identity_detect
from avialsync.core.edit_program import build as build_program
from avialsync.core.identity_detect import Trajectory
from avialsync.core.identity_groups import ANIMALS, groups_for_schema
from avialsync.core.identity_swaps import SwapEvent, SwapStore
from avialsync.core.point_edits import PointEditStore
from avialsync.core.pose import PosePoint, PoseSchema

FRAMES = 200
CROSSING = 100
SPEED = 5.0

SOURCE = "/data/twomice.csv"
SCHEMA = PoseSchema(
    points=tuple(
        PosePoint(individual=individual, bodypart="snout", axes=("x", "y"))
        for individual in ("testMouse", "conSpecific")
    ),
    frame_indexed=True,
)


def _truth() -> tuple[Trajectory, Trajectory]:
    """Two animals crossing: one left to right, one right to left, 12 apart."""
    frames = np.arange(FRAMES, dtype=float)
    a = Trajectory(SPEED * frames, np.full(FRAMES, 50.0))
    b = Trajectory(2 * SPEED * CROSSING - SPEED * frames, np.full(FRAMES, 62.0))
    return a, b


def _flip(a: Trajectory, b: Trajectory, at: int) -> tuple[Trajectory, Trajectory]:
    """What the estimator wrote after losing track at *at*: the labels exchanged."""
    seen_a = Trajectory(a.x.copy(), a.y.copy())
    seen_b = Trajectory(b.x.copy(), b.y.copy())
    seen_a.x[at:], seen_b.x[at:] = b.x[at:], a.x[at:].copy()
    seen_a.y[at:], seen_b.y[at:] = b.y[at:], a.y[at:].copy()
    return seen_a, seen_b


def _lanes(a: Trajectory, b: Trajectory) -> dict[str, Trajectory]:
    return {"testMouse": a, "conSpecific": b}


# ── what it proposes ─────────────────────────────────────────────────


def test_an_injected_flip_is_proposed_at_the_frame_it_was_injected() -> None:
    seen = _flip(*_truth(), at=CROSSING)
    candidates = identity_detect.detect(_lanes(*seen))

    assert [candidate.index for candidate in candidates] == [CROSSING]
    assert candidates[0].lanes == ("testMouse", "conSpecific")
    assert candidates[0].cost_ratio < 1.0


def test_a_clean_crossing_proposes_nothing() -> None:
    assert identity_detect.detect(_lanes(*_truth())) == ()


def test_two_animals_that_never_meet_propose_nothing() -> None:
    frames = np.arange(FRAMES, dtype=float)
    a = Trajectory(SPEED * frames, np.full(FRAMES, 50.0))
    b = Trajectory(SPEED * frames, np.full(FRAMES, 5_000.0))
    seen = _flip(a, b, at=CROSSING)
    # Cheaper to swap, and yet not a flip: they were never near each other, so
    # there was nothing for the estimator to confuse.
    assert identity_detect.detect(_lanes(*seen)) == ()


def test_a_flip_across_an_occlusion_reports_the_frames_it_spans() -> None:
    seen_a, seen_b = _flip(*_truth(), at=CROSSING)
    for lane in (seen_a, seen_b):
        lane.x[CROSSING - 4 : CROSSING] = np.nan
        lane.y[CROSSING - 4 : CROSSING] = np.nan

    candidates = identity_detect.detect(_lanes(seen_a, seen_b))

    assert [candidate.index for candidate in candidates] == [CROSSING]
    assert candidates[0].gap == 4


def test_a_burst_around_one_crossing_is_reported_once() -> None:
    seen_a, seen_b = _flip(*_truth(), at=CROSSING)
    # The estimator dithering: three frames of exchange either side of the real
    # one. A reviewer wants the event, not the dither.
    for extra in (CROSSING + 2, CROSSING + 5):
        seen_a, seen_b = _flip(seen_a, seen_b, at=extra)

    candidates = identity_detect.detect(_lanes(seen_a, seen_b))

    assert len(candidates) == 1


def test_a_resting_animal_is_not_a_crossing() -> None:
    rng = np.random.default_rng(0)
    still = Trajectory(
        np.full(FRAMES, 100.0) + rng.normal(0.0, 0.01, FRAMES),
        np.full(FRAMES, 100.0) + rng.normal(0.0, 0.01, FRAMES),
    )
    other = Trajectory(
        np.full(FRAMES, 101.0) + rng.normal(0.0, 0.01, FRAMES),
        np.full(FRAMES, 101.0) + rng.normal(0.0, 0.01, FRAMES),
    )

    assert identity_detect.detect(_lanes(still, other)) == ()


def test_the_centroid_ignores_a_part_the_model_lost() -> None:
    present = Trajectory(np.array([1.0, 2.0]), np.array([3.0, 4.0]))
    missing = Trajectory(np.array([np.nan, 6.0]), np.array([np.nan, 8.0]))

    middle = identity_detect.centroid([present, missing])

    assert middle.x[0] == 1.0
    assert middle.x[1] == 4.0


def test_a_wholly_missing_frame_remains_nan_without_a_warning() -> None:
    missing = Trajectory(np.array([np.nan, 4.0]), np.array([np.nan, 8.0]))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        middle = identity_detect.centroid([missing, missing])
        assert not [warning for warning in caught if issubclass(warning.category, RuntimeWarning)]

    assert np.isnan(middle.x[0]) and np.isnan(middle.y[0])
    assert middle.x[1] == 4.0


# ── accepting one puts the recording back ────────────────────────────


def test_accepting_the_proposal_reconstructs_the_true_trajectories() -> None:
    truth_a, truth_b = _truth()
    seen = dict(
        zip(
            ("testMouse_snout", "conSpecific_snout"),
            _flip(truth_a, truth_b, at=CROSSING),
            strict=True,
        )
    )
    candidates = identity_detect.detect(_lanes(seen["testMouse_snout"], seen["conSpecific_snout"]))

    swaps = SwapStore()
    swaps.set_groups(SOURCE, groups_for_schema(SCHEMA))
    swaps.add(
        SOURCE,
        SwapEvent(
            index=candidates[0].index,
            group=ANIMALS,
            lanes=candidates[0].lanes,
        ),
    )
    program = build_program(SOURCE, swaps, PointEditStore())

    shown_x = np.array(
        [seen[program.source_of("testMouse_snout", index)].x[index] for index in range(FRAMES)]
    )
    assert np.array_equal(shown_x, truth_a.x)
