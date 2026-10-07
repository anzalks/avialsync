"""Frame-path budget for evidence-backed belt and ball material marks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from avialsync.core.physical_props import (
    BallBinding,
    BallProp,
    BallSurface,
    BallVisualFrame,
    BeltBinding,
    BeltProp,
    BeltTrack,
    BeltVisualFrame,
    LadderPoint,
    StepClick,
    UnitQuaternion,
)
from avialsync.core.visual_prop_tracking import ball_visual_state, belt_visual_state
from avialsync.ui import prop_motion
from avialsync.ui.controllers import wheel_display
from tests.wheel_fixture import CAMERAS


def test_bench_belt_and_ball_marks_for_three_cameras(benchmark, monkeypatch) -> None:
    """One frame's two source samples and six camera projections fit the cursor budget."""
    belt = BeltProp(
        "belt",
        BeltTrack(((0.0, 0.0, 70.0), (10.0, 0.0, 70.0))),
        travel_direction=(1.0, 0.0, 0.0),
        binding=BeltBinding("sensor", "distance", 7, 100.0, 5.0, 1.0),
    )
    ball = BallProp(
        "ball",
        BallSurface((0.0, 0.0, 70.0), 2.0),
        surface_marks=((1.0, 0.0, 0.0),),
        binding=BallBinding("imu", ("qw", "qx", "qy", "qz"), 7, UnitQuaternion.identity()),
    )
    quaternion = UnitQuaternion.about_axis((0.0, 0.0, 1.0), 1.0)
    rows = []
    for source, channel, value in (
        ("sensor", "distance", 102.0),
        *zip(
            ("imu",) * 4,
            ("qw", "qx", "qy", "qz"),
            (quaternion.w, quaternion.x, quaternion.y, quaternion.z),
            strict=True,
        ),
    ):
        rows.append(
            SimpleNamespace(
                reader=SimpleNamespace(
                    cache_dir=Path(f"/cache/{source}"),
                    channel_id=channel,
                    available_sample_at=lambda _t, value=value: (12, value),
                )
            )
        )
    window = SimpleNamespace(
        _sensor_cache_dirs={"sensor": Path("/cache/sensor"), "imu": Path("/cache/imu")},
        plot_pane=SimpleNamespace(channels=rows),
    )
    monkeypatch.setattr(wheel_display, "frame_master_time", lambda _window, _frame: 0.0)

    def frame() -> None:
        for prop in (belt, ball):
            point = prop_motion.material_point(window, prop, 1.0)
            assert point is not None
            xyz = np.asarray(point)
            for camera in CAMERAS.values():
                camera.project(xyz)

    benchmark(frame)
    stats = benchmark.stats
    if stats is None:
        pytest.skip("benchmark statistics unavailable")
    assert float(stats["mean"]) <= 0.002


def test_bench_visual_belt_and_ball_frame_fit(benchmark) -> None:
    """Stereo triangulation plus orientation must fit one 60 Hz frame slice."""

    def observed(world: tuple[float, float, float]) -> LadderPoint:
        clicks = []
        for name in ("Front", "Left"):
            xy = CAMERAS[name].project(np.asarray(world))[0]
            clicks.append(StepClick(name, 7, float(xy[0]), float(xy[1])))
        return LadderPoint(tuple(clicks))

    belt = BeltProp(
        "belt",
        BeltTrack(((0.0, 0.0, 70.0), (10.0, 0.0, 70.0))),
        travel_direction=(1.0, 0.0, 0.0),
        visual_reference_frame=7,
        visual_frames=(BeltVisualFrame(7, observed((5.0, 0.0, 70.0))),),
    )
    ball = BallProp(
        "ball",
        BallSurface((0.0, 0.0, 70.0), 5.0),
        visual_reference_frame=7,
        visual_frames=(
            BallVisualFrame(
                7,
                (
                    observed((5.0, 0.0, 70.0)),
                    observed((0.0, 5.0, 70.0)),
                    observed((0.0, 0.0, 75.0)),
                ),
            ),
        ),
    )

    def frame() -> None:
        belt_state = belt_visual_state(belt, 7, CAMERAS)
        ball_state = ball_visual_state(ball, 7, CAMERAS)
        assert belt_state is not None and ball_state is not None
        for mark in (belt_state.point, *ball_state.marks):
            for camera in CAMERAS.values():
                camera.project(np.asarray(mark))

    benchmark(frame)
    assert benchmark.stats["mean"] < 0.01
