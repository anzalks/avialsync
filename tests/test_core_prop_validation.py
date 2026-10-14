"""Reject impossible apparatus records and preserve raw observations during edits."""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import pytest

from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import (
    BallBinding,
    BallProp,
    BallSurface,
    BallVisualFrame,
    BeltBinding,
    BeltProp,
    BeltTrack,
    BeltVisualFrame,
    Ladder,
    LadderLayout,
    LadderPoint,
    LadderStep,
    MotionCheck,
    PropStore,
    RungPattern,
    StepClick,
    UnitQuaternion,
    WheelView,
)

CLICK = StepClick("front", 0, 1.0, 2.0)
SECOND = StepClick("side", 0, 3.0, 4.0)
STEP = LadderStep("first", "First", (LadderPoint(),))
TRACK = BeltTrack(((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)))
BELT = BeltProp("belt", TRACK)
BELT_BINDING = BeltBinding("source", "distance", 0, 0.0, 1.0, 1.0)
BALL = BallProp("ball", BallSurface((0.0, 0.0, 0.0), 1.0))
BALL_BINDING = BallBinding("source", ("w", "x", "y", "z"), 0, UnitQuaternion.identity())


@pytest.mark.parametrize(
    "changes",
    [
        {"clicks": (CLICK, CLICK)},
        {"xyz": (np.nan, 0.0, 0.0)},
        {"error_px": np.nan},
        {"error_px": -1.0},
        {"error_px": 1.0},
        {"xyz": (0.0, 0.0, 1.0), "error_px": 0.0},
        {"xyz": (0.0, 0.0, 1.0), "clicks": (CLICK, SECOND)},
        {
            "xyz": (0.0, 0.0, 1.0),
            "clicks": (CLICK, SECOND),
            "error_px": 0.0,
            "issue": "rays_parallel",
        },
    ],
)
def test_invalid_ladder_point_evidence_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(PropModelError):
        LadderPoint(**changes)


def test_removing_a_click_keeps_other_raw_clicks_and_invalidates_the_fit() -> None:
    point = LadderPoint((CLICK, SECOND), (0.0, 0.0, 1.0), 0.0)
    assert point.without_click("missing") is point
    changed = point.without_click("front")
    assert changed.clicks == (SECOND,) and changed.xyz is None and changed.error_px is None
    assert changed.issue == "need_two_calibrated_views"


@pytest.mark.parametrize(
    "changes",
    [
        {"step_id": ""},
        {"label": ""},
        {"points": ()},
        {"irregular": "unknown"},
        {"closed": True},
    ],
)
def test_invalid_step_identity_or_outline_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(PropModelError):
        dataclasses.replace(STEP, **changes)


@pytest.mark.parametrize(
    "arguments",
    [("", "b", 2), ("a", "", 2), ("a", "a", 2), ("a", "b", True), ("a", "b", 1), ("a", "b", 10001)],
)
def test_invalid_rung_patterns_are_rejected(arguments: tuple) -> None:
    with pytest.raises(PropModelError):
        RungPattern(*arguments)


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""},
        {"steps": (STEP, STEP)},
        {"support": "invented"},
    ],
)
def test_ladder_names_order_and_support_are_validated(changes: dict[str, Any]) -> None:
    with pytest.raises(PropModelError):
        dataclasses.replace(Ladder("ladder"), **changes)


def test_ladder_insert_and_reorder_cannot_drop_or_duplicate_observations() -> None:
    ladder = Ladder("ladder", (STEP,))
    with pytest.raises(PropModelError):
        ladder.with_step(dataclasses.replace(STEP, step_id="second"), position=2)
    with pytest.raises(PropModelError):
        ladder.reordered(["unknown"])
    with pytest.raises(PropModelError):
        ladder.reordered(["first", "first"])


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""},
        {"units": "seconds"},
        {"corners": ()},
        {"surface_width": 2.0},
        {"surface_normal": (0.0, 0.0, 1.0)},
        {"surface_width": np.inf, "surface_normal": (0.0, 0.0, 1.0)},
        {"surface_width": 0.0, "surface_normal": (0.0, 0.0, 1.0)},
        {"surface_width": 2.0, "surface_normal": (np.nan, 0.0, 1.0)},
        {"surface_width": 2.0, "surface_normal": (0.0, 0.0, 0.0)},
        {"travel_direction": (np.nan, 0.0, 0.0)},
        {"travel_direction": (0.0, 0.0, 0.0)},
        {"binding": BELT_BINDING},
        {
            "travel_direction": (1.0, 0.0, 0.0),
            "binding": BELT_BINDING,
            "visual_reference_frame": 0,
            "visual_frames": (BeltVisualFrame(0),),
        },
        {
            "travel_direction": (1.0, 0.0, 0.0),
            "visual_reference_frame": 0,
            "visual_frames": (BeltVisualFrame(0), BeltVisualFrame(0)),
        },
        {
            "travel_direction": (1.0, 0.0, 0.0),
            "visual_reference_frame": 1,
            "visual_frames": (BeltVisualFrame(0),),
        },
        {"visual_reference_frame": -1},
        {"travel_direction": (0.0, 1.0, 0.0), "binding": BELT_BINDING},
        {
            "travel_direction": (1.0, 0.0, 0.0),
            "binding": dataclasses.replace(BELT_BINDING, reference_distance=-1.0),
        },
        {
            "travel_direction": (1.0, 0.0, 0.0),
            "binding": dataclasses.replace(BELT_BINDING, reference_distance=11.0),
        },
    ],
)
def test_invalid_belt_geometry_or_motion_contract_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(PropModelError):
        dataclasses.replace(BELT, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""},
        {"units": "seconds"},
        {"surface_marks": ((0.0, 0.0, 0.0),)},
        {"surface_marks": ((np.nan, 0.0, 1.0),)},
        {"binding": BALL_BINDING},
        {
            "binding": BALL_BINDING,
            "surface_marks": ((1.0, 0.0, 0.0),),
            "visual_reference_frame": 0,
            "visual_frames": (BallVisualFrame(0),),
        },
        {"visual_reference_frame": 0, "visual_frames": (BallVisualFrame(0), BallVisualFrame(0))},
        {"visual_reference_frame": 1, "visual_frames": (BallVisualFrame(0),)},
        {"visual_reference_frame": -1},
    ],
)
def test_invalid_ball_geometry_or_motion_contract_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(PropModelError):
        dataclasses.replace(BALL, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_id": ""},
        {"channel": ""},
        {"reference_frame": -1},
        {"reference_reading": np.nan},
        {"reference_distance": np.inf},
        {"units_per_reading": 0.0},
    ],
)
def test_invalid_displacement_binding_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(PropModelError):
        dataclasses.replace(BELT_BINDING, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_id": ""},
        {"reference_frame": -1},
        {"channels": ("w", "x", "y")},
        {"channels": ("w", "x", "y", "y")},
        {"channels": ("w", "x", "y", "")},
        {"reference_values": (np.nan, 0.0, 0.0, 0.0)},
        {"orientation_correction": (0.0, 0.0, 0.0, 0.0)},
    ],
)
def test_invalid_orientation_binding_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(PropModelError):
        dataclasses.replace(BALL_BINDING, **changes)


def test_invalid_visual_frames_and_motion_readings_are_rejected() -> None:
    for call in (
        lambda: BeltVisualFrame(-1),
        lambda: BeltVisualFrame(0, lap=0.5),
        lambda: BallVisualFrame(-1),
        lambda: BallVisualFrame(0, marks=()),
        lambda: MotionCheck(0, "front", 1.0, 2.0, 0.0, (np.nan,)),
    ):
        with pytest.raises(PropModelError):
            call()


def test_prop_store_rejects_wrong_kind_keys_and_invalid_step_edits() -> None:
    store = PropStore()
    store.set("ladder", Ladder("ladder", (STEP,)))
    operations = [
        lambda: store.set("wrong", Ladder("other")),
        lambda: store.set("ladder", dataclasses.replace(BALL, name="ladder")),
        lambda: store.set_layout("absent", LadderLayout()),
        lambda: store.set_step("absent", "first", STEP),
        lambda: store.set_step("ladder", "different", STEP),
        lambda: store.move_step("absent", "first", 0),
        lambda: store.move_step("ladder", "absent", 0),
        lambda: store.move_step("ladder", "first", 1),
    ]
    for operation in operations:
        with pytest.raises(PropModelError):
            operation()
    assert store.get("ladder").steps == (STEP,)


def test_prop_and_wheel_observer_disposal_is_idempotent() -> None:
    store = PropStore()
    wheels = WheelView(store)
    events: list = []
    dispose = store.observe(events.append)
    wheel_dispose = wheels.observe(events.append)
    dispose()
    dispose()
    wheel_dispose()
    wheel_dispose()
    assert not wheels.set("absent", None)
    store.set("belt", BELT)
    assert events == []


def test_unbound_props_have_no_invented_motion() -> None:
    assert BELT.material_point(2.0) is None
    assert BALL.material_point(UnitQuaternion.identity()) is None
    with pytest.raises(PropModelError):
        TRACK.material_point(0.0, np.nan)


@pytest.mark.parametrize(
    "arguments", [((np.nan, 0.0, 0.0), 1.0), ((0.0, 0.0, 0.0), 1.0), ((1.0, 0.0, 0.0), np.inf)]
)
def test_invalid_rotation_axis_or_angle_is_rejected(arguments: tuple) -> None:
    with pytest.raises(PropModelError):
        UnitQuaternion.about_axis(*arguments)


def test_invalid_quaternion_and_material_direction_are_rejected() -> None:
    with pytest.raises(PropModelError):
        UnitQuaternion(np.nan, 0.0, 0.0, 0.0)
    with pytest.raises(PropModelError):
        UnitQuaternion.identity().rotate((np.nan, 0.0, 0.0))
    with pytest.raises(PropModelError):
        BALL.surface.material_point((2.0, 0.0, 0.0), UnitQuaternion.identity())
