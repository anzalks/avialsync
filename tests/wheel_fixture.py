"""A synthetic running wheel and the rig that films it, for the wheel tests (D-113).

Ground truth for method validation only: a 36-bar wheel of radius 100 and
half-width 25 at a known place, three known pinhole cameras looking down at its
top, and the clicks those cameras would record with half a pixel of noise --
about what a careful click on a sharp bar end achieves. Never a stand-in for
recorded data.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from avialsync.core.calibration import CameraModel
from avialsync.core.wheel import LEFT, RIGHT, EndClick, WheelGeometry

TRUTH = WheelGeometry(
    centre=(0.0, 0.0, 0.0),
    axle=(1.0, 0.0, 0.0),
    zero=(0.0, 0.0, 1.0),
    radius=100.0,
    half_width=25.0,
    bar_count=36,
)
NOISE_PX = 0.5


def _camera(name: str, position: tuple[float, float, float]) -> CameraModel:
    """A pinhole at *position* looking at the top of the wheel, OpenCV axes."""
    centre = np.asarray(position, dtype=np.float64)
    forward = np.asarray([0.0, 0.0, 90.0]) - centre
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0.0, 0.0, 1.0])
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    rotation = np.vstack((right, down, forward))
    return CameraModel(
        name=name,
        size=(1280, 1024),
        matrix=np.array([[1000.0, 0.0, 640.0], [0.0, 1000.0, 512.0], [0.0, 0.0, 1.0]]),
        rotation=Rotation.from_matrix(rotation).as_rotvec(),
        translation=-rotation @ centre,
    )


CAMERAS = {
    "Front": _camera("Front", (0.0, -320.0, 260.0)),
    "Left": _camera("Left", (-260.0, -240.0, 220.0)),
    "Right": _camera("Right", (260.0, -240.0, 220.0)),
}


def clicks_for(slots: list[int], seed: int = 1) -> tuple[EndClick, ...]:
    """What the cameras record for the bars in *slots*, clicked in that order."""
    rng = np.random.default_rng(seed)
    ends = TRUTH.bar_ends()
    clicks = []
    for bar, slot in enumerate(slots):
        for side_index, side in enumerate((LEFT, RIGHT)):
            click = EndClick(bar=bar, side=side)
            for name, camera in CAMERAS.items():
                x, y = camera.project(ends[slot % TRUTH.bar_count, side_index])[0]
                noise = rng.normal(0.0, NOISE_PX, 2)
                click = click.with_view(name, x + noise[0], y + noise[1])
            clicks.append(click)
    return tuple(clicks)
