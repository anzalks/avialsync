"""Multi-camera calibration in anipose's ``calibration.toml`` form.

A point placed by hand in every camera view becomes a 3D point only through a
calibration: each camera's intrinsics and its pose in one shared world frame.
anipose writes exactly that to ``calibration.toml`` and triangulated the pose
this application shows with it, so reading the same file puts a hand-placed
marker in the same frame and the same units as the ``_eks.csv`` beside it.

**The camera model is OpenCV's**, which is what anipose hands to
``cv2.projectPoints``: ``matrix`` is ``K``, ``distortions`` are
``(k1, k2, p1, p2, k3)``, ``rotation`` is a Rodrigues vector and
``translation`` places the world origin in camera coordinates, so a world point
``X`` lands at ``R @ X + t``. Skew is not part of that model -- OpenCV reads
only ``fx, fy, cx, cy`` from ``K`` -- which is why :func:`fit_camera` fits
without it rather than writing a term every reader would silently drop.

**A fitted calibration is a reconstruction, not a measurement.** When the
original file is lost, :func:`fit_camera` recovers each camera from pairs the
session already holds: the triangulated 3D pose and that camera's own 2D
tracking. It reproduces the projection well -- a few pixels, about the error
anipose itself reports -- but the tracked volume is a few centimetres seen from
tens of centimetres, which does not pin focal length and principal point down
separately. The intrinsics it writes are therefore numbers that project
correctly, not physical properties of the lens, and no distortion is fitted:
the data cannot tell distortion from a focal-length change, and a fitted term
only made the solution wander. ``metadata`` records that it was fitted.

No OpenCV here: the model is a dozen lines of numpy, and ``pip install
avialsync`` must not grow a native dependency for them (AGENTS.md tech stack).
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from avialsync.core.errors import CalibrationError

__all__ = [
    "CameraModel",
    "Calibration",
    "read_calibration",
    "write_calibration",
    "triangulate",
    "fit_camera",
]

#: Pairs used to fit one camera. The solve is over-determined a thousandfold
#: long before this; the cap keeps a long session's fit to a second or two.
_FIT_SAMPLES = 20_000
#: Pairs worse than this share of the fit are dropped before refining, so a
#: mislabelled frame in the tracking does not pull a camera towards it.
_TRIM_PERCENTILE = 90.0
_UNDISTORT_ITERATIONS = 20


@dataclass(frozen=True)
class CameraModel:
    """One camera: OpenCV intrinsics, distortion, and pose in the world frame."""

    name: str
    size: tuple[int, int]
    matrix: np.ndarray
    distortions: np.ndarray = field(default_factory=lambda: np.zeros(5))
    rotation: np.ndarray = field(default_factory=lambda: np.zeros(3))
    translation: np.ndarray = field(default_factory=lambda: np.zeros(3))

    def rotation_matrix(self) -> np.ndarray:
        """The 3x3 rotation taking world axes to camera axes."""
        matrix: np.ndarray = Rotation.from_rotvec(self.rotation).as_matrix()
        return matrix

    def project(self, points: np.ndarray) -> np.ndarray:
        """Project world points ``(N, 3)`` to pixels ``(N, 2)``, with distortion."""
        world = np.atleast_2d(np.asarray(points, dtype=np.float64))
        camera = world @ self.rotation_matrix().T + self.translation
        normalised = camera[:, :2] / camera[:, 2:3]
        distorted = self._distort(normalised)
        fx, fy = self.matrix[0, 0], self.matrix[1, 1]
        cx, cy = self.matrix[0, 2], self.matrix[1, 2]
        pixels: np.ndarray = np.column_stack((fx * distorted[:, 0] + cx, fy * distorted[:, 1] + cy))
        return pixels

    def normalise(self, pixels: np.ndarray) -> np.ndarray:
        """Undo intrinsics and distortion: pixels ``(N, 2)`` to ideal ``x/z, y/z``.

        OpenCV's ``undistortPoints`` fixed-point iteration: the forward model
        has no closed-form inverse, and at the distortion a lab lens shows the
        iteration settles well inside a hundredth of a pixel.
        """
        pixels = np.atleast_2d(np.asarray(pixels, dtype=np.float64))
        fx, fy = self.matrix[0, 0], self.matrix[1, 1]
        cx, cy = self.matrix[0, 2], self.matrix[1, 2]
        observed = np.column_stack(((pixels[:, 0] - cx) / fx, (pixels[:, 1] - cy) / fy))
        if not np.any(self.distortions):
            return observed
        k1, k2, p1, p2, k3 = self._coefficients()
        ideal = observed.copy()
        for _ in range(_UNDISTORT_ITERATIONS):
            x, y = ideal[:, 0], ideal[:, 1]
            r2 = x * x + y * y
            radial = 1.0 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
            dx = 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x)
            dy = p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y
            ideal = np.column_stack(
                ((observed[:, 0] - dx) / radial, (observed[:, 1] - dy) / radial)
            )
        return ideal

    def extrinsic(self) -> np.ndarray:
        """``[R | t]``, the 3x4 projection in normalised camera coordinates."""
        return np.column_stack((self.rotation_matrix(), self.translation))

    def _coefficients(self) -> tuple[float, float, float, float, float]:
        padded = np.zeros(5)
        count = min(5, len(self.distortions))
        padded[:count] = self.distortions[:count]
        return (
            float(padded[0]),
            float(padded[1]),
            float(padded[2]),
            float(padded[3]),
            float(padded[4]),
        )

    def _distort(self, normalised: np.ndarray) -> np.ndarray:
        if not np.any(self.distortions):
            return normalised
        k1, k2, p1, p2, k3 = self._coefficients()
        x, y = normalised[:, 0], normalised[:, 1]
        r2 = x * x + y * y
        radial = 1.0 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
        distorted: np.ndarray = np.column_stack(
            (
                x * radial + 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x),
                y * radial + p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y,
            )
        )
        return distorted


@dataclass(frozen=True)
class Calibration:
    """Every camera of one rig, plus what the file says about how it was made."""

    cameras: tuple[CameraModel, ...]
    metadata: dict[str, str | float | bool] = field(default_factory=dict)

    @property
    def names(self) -> tuple[str, ...]:
        """Camera names, in file order."""
        return tuple(camera.name for camera in self.cameras)

    def camera(self, name: str) -> CameraModel | None:
        """Return the camera called *name*, or None."""
        for camera in self.cameras:
            if camera.name == name:
                return camera
        return None


# ── the file ─────────────────────────────────────────────────────────


def read_calibration(path: Path | str) -> Calibration:
    """Read an anipose ``calibration.toml``.

    Raises :class:`CalibrationError` naming what is wrong: a file that cannot
    be read, one with no cameras, or a fisheye camera, whose model this module
    does not implement and must not approximate with the pinhole one.
    """
    path = Path(path)
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise CalibrationError(f"Could not read calibration {path}: {error}") from error

    cameras: list[CameraModel] = []
    for key in sorted(k for k in document if k.startswith("cam_")):
        section = document[key]
        if section.get("fisheye", False):
            raise CalibrationError(
                f"Camera {section.get('name', key)} in {path.name} is a fisheye camera, "
                "which AvialSync cannot triangulate yet."
            )
        try:
            width, height = (int(v) for v in section["size"])
            cameras.append(
                CameraModel(
                    name=str(section.get("name", key)),
                    size=(width, height),
                    matrix=np.asarray(section["matrix"], dtype=np.float64).reshape(3, 3),
                    distortions=np.asarray(section.get("distortions", [0.0] * 5), dtype=np.float64),
                    rotation=np.asarray(section["rotation"], dtype=np.float64).reshape(3),
                    translation=np.asarray(section["translation"], dtype=np.float64).reshape(3),
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise CalibrationError(f"Camera {key} in {path.name} is incomplete: {error}") from error
    if not cameras:
        raise CalibrationError(f"{path.name} describes no cameras.")
    metadata = document.get("metadata", {})
    return Calibration(
        cameras=tuple(cameras),
        metadata={str(k): v for k, v in metadata.items() if isinstance(v, (str, float, int, bool))},
    )


def _toml_value(value: object) -> str:
    """Format one value the way anipose's own writer lays it out."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return repr(float(value))
    if isinstance(value, np.ndarray):
        return _toml_value(value.tolist())
    if isinstance(value, (list, tuple)):
        return "[ " + " ".join(f"{_toml_value(item)}," for item in value) + "]"
    raise TypeError(f"Cannot write {type(value).__name__} to TOML")


def write_calibration(path: Path | str, calibration: Calibration) -> Path:
    """Write *calibration* as an anipose ``calibration.toml``, atomically.

    Hand-written rather than a TOML library: the layout is a handful of flat
    tables, and matching anipose's own output keeps the file diffable against
    one it wrote.
    """
    path = Path(path)
    lines: list[str] = []
    for index, camera in enumerate(calibration.cameras):
        lines += [
            f"[cam_{index}]",
            f"name = {_toml_value(camera.name)}",
            f"size = {_toml_value(list(camera.size))}",
            f"matrix = {_toml_value(camera.matrix)}",
            f"distortions = {_toml_value(camera.distortions)}",
            f"rotation = {_toml_value(camera.rotation)}",
            f"translation = {_toml_value(camera.translation)}",
            "",
        ]
    lines.append("[metadata]")
    lines += [f"{key} = {_toml_value(value)}" for key, value in calibration.metadata.items()]
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


# ── triangulation ────────────────────────────────────────────────────


def triangulate(
    views: Sequence[tuple[CameraModel, tuple[float, float]]],
) -> tuple[np.ndarray, float]:
    """Triangulate one point seen by two or more cameras.

    Linear least squares on undistorted coordinates -- anipose's
    ``triangulate_simple`` -- then the mean reprojection error in pixels, which
    is what anipose writes as ``<point>_error``. Raises
    :class:`CalibrationError` for fewer than two views: one ray has no depth.
    """
    if len(views) < 2:
        raise CalibrationError("A 3D point needs the same marker in at least two cameras.")
    rows: list[np.ndarray] = []
    for camera, pixel in views:
        x, y = camera.normalise(np.asarray([pixel], dtype=np.float64))[0]
        projection = camera.extrinsic()
        rows.append(x * projection[2] - projection[0])
        rows.append(y * projection[2] - projection[1])
    solution = np.linalg.svd(np.asarray(rows))[2][-1]
    point: np.ndarray = solution[:3] / solution[3]
    errors = [
        float(np.linalg.norm(camera.project(point)[0] - np.asarray(pixel)))
        for camera, pixel in views
    ]
    return point, float(np.mean(errors))


# ── fitting a camera from 3D↔2D pairs ────────────────────────────────


def _normalising_transform(points: np.ndarray) -> np.ndarray:
    """Hartley normalisation: centre, and scale to unit mean distance."""
    dimension = points.shape[1]
    centre = points.mean(axis=0)
    spread = np.linalg.norm(points - centre, axis=1).mean() / np.sqrt(dimension)
    transform = np.eye(dimension + 1)
    transform[:dimension, :dimension] /= spread
    transform[:dimension, dimension] = -centre / spread
    return transform


def _direct_linear_transform(world: np.ndarray, pixels: np.ndarray) -> np.ndarray:
    """The 3x4 projection that best maps *world* to *pixels*, linearly."""
    t_world = _normalising_transform(world)
    t_image = _normalising_transform(pixels)
    w = (t_world @ np.column_stack((world, np.ones(len(world)))).T).T
    p = (t_image @ np.column_stack((pixels, np.ones(len(pixels)))).T).T
    system = np.zeros((2 * len(w), 12))
    system[0::2, 4:8] = -w
    system[0::2, 8:] = p[:, 1:2] * w
    system[1::2, 0:4] = w
    system[1::2, 8:] = -p[:, 0:1] * w
    solution = np.linalg.svd(system, full_matrices=False)[2][-1].reshape(3, 4)
    projection: np.ndarray = np.linalg.inv(t_image) @ solution @ t_world
    # Scale is free; the sign is not. Points must sit in front of the camera.
    if np.median(projection[2] @ np.column_stack((world, np.ones(len(world)))).T) < 0:
        projection = -projection
    return projection


def _decompose(projection: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split ``P = K [R | t]`` by RQ decomposition, with a positive-diagonal K."""
    q, r = np.linalg.qr(np.flipud(projection[:, :3]).T)
    intrinsic = np.flipud(r.T)[:, ::-1]
    rotation = np.flipud(q.T)
    signs = np.diag(np.sign(np.diag(intrinsic)))
    intrinsic = intrinsic @ signs
    rotation = signs @ rotation
    translation = np.linalg.solve(intrinsic, projection[:, 3])
    if np.linalg.det(rotation) < 0:
        rotation, translation = -rotation, -translation
    return intrinsic / intrinsic[2, 2], rotation, translation


def _model_from(name: str, size: tuple[int, int], params: np.ndarray) -> CameraModel:
    fx, fy, cx, cy = params[6:10]
    return CameraModel(
        name=name,
        size=size,
        matrix=np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]]),
        rotation=np.asarray(params[0:3], dtype=np.float64),
        translation=np.asarray(params[3:6], dtype=np.float64),
    )


def fit_camera(
    name: str,
    size: tuple[int, int],
    world: np.ndarray,
    pixels: np.ndarray,
    *,
    seed: int = 0,
) -> tuple[CameraModel, float]:
    """Recover one camera from matching world points and their pixels.

    A linear DLT on a trimmed sample gives the starting point; its skew is
    dropped (see the module docstring) and a robust least-squares refinement
    then fits ``fx, fy, cx, cy`` and the pose. Returns the camera and its median
    reprojection error in pixels over every pair given.

    Raises :class:`CalibrationError` when there are too few finite pairs to
    constrain eleven parameters with any margin.
    """
    world = np.asarray(world, dtype=np.float64).reshape(-1, 3)
    pixels = np.asarray(pixels, dtype=np.float64).reshape(-1, 2)
    finite = np.isfinite(world).all(axis=1) & np.isfinite(pixels).all(axis=1)
    world, pixels = world[finite], pixels[finite]
    if len(world) < 50:
        raise CalibrationError(
            f"Only {len(world)} usable 3D/2D pairs for {name}; at least 50 are needed."
        )
    rng = np.random.default_rng(seed)
    sample = rng.permutation(len(world))[:_FIT_SAMPLES]

    projection = _direct_linear_transform(world[sample], pixels[sample])
    for _ in range(3):
        projected = np.column_stack((world[sample], np.ones(len(sample)))) @ projection.T
        residual = np.linalg.norm(projected[:, :2] / projected[:, 2:3] - pixels[sample], axis=1)
        sample = sample[residual <= np.percentile(residual, _TRIM_PERCENTILE)]
        projection = _direct_linear_transform(world[sample], pixels[sample])

    intrinsic, rotation, translation = _decompose(projection)
    start = np.concatenate(
        (
            Rotation.from_matrix(rotation).as_rotvec(),
            translation,
            [intrinsic[0, 0], intrinsic[1, 1], intrinsic[0, 2], intrinsic[1, 2]],
        )
    )
    fit_world, fit_pixels = world[sample], pixels[sample]

    def residuals(params: np.ndarray) -> np.ndarray:
        projected = _model_from(name, size, params).project(fit_world)
        flat: np.ndarray = (projected - fit_pixels).ravel()
        return flat

    solution = least_squares(
        residuals, start, loss="soft_l1", f_scale=5.0, x_scale="jac", max_nfev=4000
    )
    camera = _model_from(name, size, np.asarray(solution.x))
    error = np.linalg.norm(camera.project(world) - pixels, axis=1)
    return camera, float(np.median(error))
