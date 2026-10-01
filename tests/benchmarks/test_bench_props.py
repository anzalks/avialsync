"""Frame-path budget for static props with many independently clicked steps."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from avialsync.core.physical_props import Ladder, LadderPoint, LadderStep, StepClick
from avialsync.ui.props_app import PropsApp
from tests.wheel_fixture import CAMERAS
from tests.wheel_window import VIDEOS


@pytest.mark.benchmark(group="physical-props-frame")
def test_many_ladder_steps_project_within_frame_budget(benchmark) -> None:
    """A long irregular ladder must not monopolize a 60 Hz paint tick."""
    window = SimpleNamespace(
        _calibration_state=SimpleNamespace(cameras={VIDEOS["Front"]: CAMERAS["Front"]})
    )
    props = PropsApp(window)
    steps = tuple(
        LadderStep(
            str(index),
            f"Step {index}",
            (
                LadderPoint(
                    clicks=(
                        StepClick("Left", 7, float(index * 3), float(index % 5)),
                        StepClick("Right", 7, float(index * 4), float(index % 7)),
                    ),
                    xyz=(float(index * 5), float(index % 9), float(index % 4)),
                    error_px=0.2,
                ),
            ),
        )
        for index in range(64)
    )
    props.store.set("ladder", Ladder("ladder", steps))
    drawn = benchmark(props.camera_drawing, VIDEOS["Front"], 0.0)
    assert len(drawn) == 64
    assert benchmark.stats["mean"] < 0.002
