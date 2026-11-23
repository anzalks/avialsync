"""Synthetic frame timing and orientation evidence for moving prop marks."""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from avialsync.core.physical_props import (
    BallBinding,
    BallProp,
    BallSurface,
    BeltBinding,
    BeltProp,
    BeltTrack,
    UnitQuaternion,
)
from avialsync.ui import prop_motion
from avialsync.ui.controllers import wheel_display
from tests.wheel_fixture import CAMERAS


def _window() -> SimpleNamespace:
    video = "/rec/Front.mp4"
    pane = SimpleNamespace(
        frame_record_at=lambda _t: (8, 1.0),
        time_map=SimpleNamespace(to_master=lambda t: t),
    )
    return SimpleNamespace(
        video_grid=SimpleNamespace(pane_paths=lambda: [video], panes=[pane]),
        clock=SimpleNamespace(state=SimpleNamespace(t=1.7)),
        _calibration_state=SimpleNamespace(cameras={video: CAMERAS["Front"]}),
        _sensor_cache_dirs={"sensor": Path("/cache/sensor"), "imu": Path("/cache/imu")},
        plot_pane=SimpleNamespace(channels=[]),
    )


def test_belt_uses_presented_frame_and_records_a_later_click(monkeypatch) -> None:
    window = _window()
    monkeypatch.setattr(wheel_display, "frame_master_time", lambda _window, _frame: 0.0)
    seen: list[float] = []
    remapped = {"delta": 0.0}

    def sample(t: float) -> tuple[int, float]:
        seen.append(t)
        return 12, (102.0 if t == 1.0 else 100.0) + remapped["delta"]

    window.plot_pane.channels.append(
        SimpleNamespace(
            reader=SimpleNamespace(
                channel_id="distance",
                cache_dir=Path("/cache/sensor"),
                available_sample_at=sample,
            )
        )
    )
    belt = BeltProp(
        "belt",
        BeltTrack(((0.0, 0.0, 70.0), (10.0, 0.0, 70.0))),
        travel_direction=(1.0, 0.0, 0.0),
        binding=BeltBinding("sensor", "distance", 7, 100.0, 5.0, 1.0),
    )
    expected = CAMERAS["Front"].project(np.asarray((7.0, 0.0, 70.0)))[0]
    check = prop_motion.check_click(window, belt, "/rec/Front.mp4", *expected)
    assert check is not None
    assert check.frame == 8 and check.residual_px == pytest.approx(0.0)
    assert check.source_values == (102.0,)
    assert seen == [1.0, 0.0]
    remapped["delta"] = 40.0
    assert prop_motion.material_point(window, belt, 1.0) == pytest.approx((7.0, 0.0, 70.0))
    assert prop_motion.material_point(window, belt, 0.0) == pytest.approx((5.0, 0.0, 70.0))
    window.plot_pane.channels[0].reader.available_sample_at = lambda _t: None
    assert prop_motion.material_point(window, belt, 1.0) is None


def test_ball_requires_same_sample_for_all_quaternion_components(monkeypatch) -> None:
    window = _window()
    monkeypatch.setattr(wheel_display, "frame_master_time", lambda _window, _frame: 0.0)
    q = UnitQuaternion.about_axis((1.0, 0.0, 0.0), math.pi / 2).composed(
        UnitQuaternion.about_axis((0.0, 0.0, 1.0), math.pi / 2)
    )
    values = (q.w, q.x, q.y, q.z)
    for channel, value, start in zip(
        ("qw", "qx", "qy", "qz"), values, (1.0, 0.0, 0.0, 0.0), strict=True
    ):
        reader = SimpleNamespace(
            channel_id=channel,
            cache_dir=Path("/cache/imu"),
            available_sample_at=lambda t, value=value, start=start: (
                (12, value) if t == 1.0 else (0, start)
            ),
        )
        window.plot_pane.channels.append(SimpleNamespace(reader=reader))
    ball = BallProp(
        "ball",
        BallSurface((0.0, 0.0, 70.0), 2.0),
        surface_marks=((1.0, 0.0, 0.0),),
        binding=BallBinding("imu", ("qw", "qx", "qy", "qz"), 7, UnitQuaternion.identity()),
    )
    point = ball.surface.material_point((1.0, 0.0, 0.0), q)
    expected = CAMERAS["Front"].project(np.asarray(point))[0]
    check = prop_motion.check_click(window, ball, "/rec/Front.mp4", *expected)
    assert check is not None and check.residual_px == pytest.approx(0.0, abs=1e-8)
    assert check.source_values == pytest.approx(values)
    window.plot_pane.channels[-1].reader.available_sample_at = lambda _t: (11, q.z)
    assert prop_motion.material_point(window, ball, 1.0) is None
    window.plot_pane.channels[-1].reader.available_sample_at = lambda _t: None
    assert prop_motion.material_point(window, ball, 1.0) is None


def test_belt_linear_interpolation_and_ball_geodesic_slerp_between_samples(
    tmp_path: Path,
) -> None:
    """MappedChannelReader-backed props interpolate belt scalars and SLERP ball quaternions."""
    from avialsync.core.channel_reader import MappedChannelReader
    from avialsync.core.pyramid import PyramidBuilder, PyramidReader
    from avialsync.core.timeline import TimeMap

    window = _window()
    sensor_cache = tmp_path / "sensor"
    imu_cache = tmp_path / "imu"
    sensor_cache.mkdir()
    imu_cache.mkdir()
    window._sensor_cache_dirs = {"sensor": sensor_cache, "imu": imu_cache}

    # 0.0 -> 0.1 s normal interval, then a > 10x gap from 0.2 -> 5.0 s.
    times = np.asarray([0.0, 0.1, 0.2, 5.0], dtype=np.float64)
    PyramidBuilder(sensor_cache, "distance").build_and_save(
        times, np.asarray([10.0, 20.0, 30.0, 40.0], dtype=np.float64)
    )
    window.plot_pane.channels.append(
        SimpleNamespace(
            reader=MappedChannelReader(PyramidReader(sensor_cache, "distance"), TimeMap(), "sensor")
        )
    )
    assert prop_motion.scalar_reading(window, "sensor", "distance", 0.05) == pytest.approx(15.0)
    # Refuses interpolation across the observed timestamp gap (0.2 -> 5.0).
    assert prop_motion.scalar_reading(window, "sensor", "distance", 2.5) is None

    # Quaternion samples: q(0.0) = identity, q(0.1) = -rot_z(90 deg) (antipodal shortest-arc test).
    q_end = UnitQuaternion.about_axis((0.0, 0.0, 1.0), math.pi / 2.0)
    q_series = {
        "qw": np.asarray([1.0, -q_end.w, -q_end.w, 1.0], dtype=np.float64),
        "qx": np.asarray([0.0, -q_end.x, -q_end.x, 0.0], dtype=np.float64),
        "qy": np.asarray([0.0, -q_end.y, -q_end.y, 0.0], dtype=np.float64),
        "qz": np.asarray([0.0, -q_end.z, -q_end.z, 0.0], dtype=np.float64),
    }
    tm = TimeMap()
    for ch_name, arr in q_series.items():
        PyramidBuilder(imu_cache, ch_name).build_and_save(times, arr)
        window.plot_pane.channels.append(
            SimpleNamespace(
                reader=MappedChannelReader(PyramidReader(imu_cache, ch_name), tm, "imu")
            )
        )

    ball = BallProp(
        "ball",
        BallSurface((0.0, 0.0, 70.0), 2.0),
        surface_marks=((1.0, 0.0, 0.0),),
        binding=BallBinding("imu", ("qw", "qx", "qy", "qz"), 0, UnitQuaternion.identity()),
    )
    mid_q = prop_motion.orientation(window, ball, 0.05)
    expected_mid = UnitQuaternion.about_axis((0.0, 0.0, 1.0), math.pi / 4.0)
    assert mid_q is not None
    assert mid_q.rotate((1.0, 0.0, 0.0)) == pytest.approx(
        expected_mid.rotate((1.0, 0.0, 0.0)), abs=1e-6
    )
    assert prop_motion.orientation(window, ball, 2.5) is None
