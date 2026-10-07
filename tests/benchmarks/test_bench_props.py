"""Frame-path budget for static props with many independently clicked steps."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from avialsync.core.physical_props import Ladder, LadderPoint, LadderStep, StepClick
from avialsync.ui.props_app import PropsApp
from tests.wheel_fixture import CAMERAS
from tests.wheel_window import VIDEOS


@pytest.mark.benchmark(group="physical-props-frame")
def test_many_ladder_steps_project_within_frame_budget(benchmark) -> None:
    """A long irregular ladder must not monopolize a 60 Hz paint tick."""
    window = SimpleNamespace(
        _calibration_state=SimpleNamespace(
            cameras={VIDEOS[name]: model for name, model in CAMERAS.items()}
        )
    )
    props = PropsApp(window)

    def clicked_step(index: int) -> LadderStep:
        world = (float(index - 32), float(index % 9), float(70 + index % 4))
        clicks = []
        for name in ("Left", "Right"):
            x, y = CAMERAS[name].project(np.asarray([world]))[0]
            clicks.append(StepClick(name, 7, float(x), float(y)))
        return LadderStep(
            str(index),
            f"Step {index}",
            (LadderPoint(clicks=tuple(clicks), xyz=world, error_px=0.0),),
        )

    steps = tuple(clicked_step(index) for index in range(64))
    props.store.set("ladder", Ladder("ladder", steps))
    drawn = benchmark(props.camera_drawing, VIDEOS["Front"], 0.0)
    assert len(drawn) == 64
    assert benchmark.stats["mean"] < 0.002
