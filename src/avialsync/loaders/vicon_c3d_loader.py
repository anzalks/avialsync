"""Read Vicon C3D trajectories and project them into their video camera."""

from __future__ import annotations

import logging
import re
import warnings
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import av
import c3d
import numpy as np
from scipy.spatial.transform import Rotation

from avialsync.core.calibration import CameraModel
from avialsync.core.errors import SourceOpenError
from avialsync.core.pose import PosePoint, PoseSchema
from avialsync.core.source import ChannelInfo, TimeSeriesSource

logger = logging.getLogger(__name__)
_CHUNK_SIZE = 4096
_INVALID_CHANNEL_CHARACTERS = re.compile(r'[<>:"/\\|?*]')
_COMBINED_ROLE = "pose3d_overlay2d"
_DISTORT_ITERATIONS = 25


@dataclass(frozen=True)
class ViconCameraModel(CameraModel):
    """Vue camera whose ``Vicon3Parameter`` lens maps distorted pixels to ideal ones.

    That is the reverse of OpenCV's ideal-to-distorted model, so projecting needs
    a fixed-point solve; verified against the other cameras' XCP positions,
    which land on their ring lights only in this direction.
    """

    radial_center: np.ndarray = field(default_factory=lambda: np.zeros(2))
    radial: np.ndarray = field(default_factory=lambda: np.zeros(3))

    def _ideal_pixels(self, distorted: np.ndarray) -> np.ndarray:
        offset = distorted - self.radial_center
        r2 = (offset**2).sum(axis=1, keepdims=True)
        k1, k2, k3 = self.radial
        ideal: np.ndarray = offset * (1.0 + k1 * r2 + k2 * r2**2 + k3 * r2**3) + self.radial_center
        return ideal

    def project(self, points: np.ndarray) -> np.ndarray:
        ideal = super().project(points)
        offset = ideal - self.radial_center
        distorted = offset.copy()
        k1, k2, k3 = self.radial
        for _ in range(_DISTORT_ITERATIONS):
            r2 = (distorted**2).sum(axis=1, keepdims=True)
            distorted = offset / (1.0 + k1 * r2 + k2 * r2**2 + k3 * r2**3)
        pixels: np.ndarray = distorted + self.radial_center
        return pixels

    def normalise(self, pixels: np.ndarray) -> np.ndarray:
        ideal = self._ideal_pixels(np.atleast_2d(np.asarray(pixels, dtype=np.float64)))
        return super().normalise(ideal)


def _number_list(value: str | None, name: str, count: int) -> np.ndarray:
    if value is None:
        raise SourceOpenError(f"Vicon calibration is missing {name}.")
    values = np.fromstring(value, sep=" ", dtype=np.float64)
    if len(values) != count or not np.isfinite(values).all():
        raise SourceOpenError(f"Vicon calibration has invalid {name}.")
    return values


def _c3d_reader(handle: Any) -> c3d.Reader:
    """Open C3D while hiding only the library's expected missing-analog notice."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"^No analog data found in file\.$",
            category=UserWarning,
        )
        return c3d.Reader(handle)


def camera_from_xcp(path: Path, device_id: str = "") -> CameraModel:
    """Read a Vicon Nexus video camera's projection from its XCP file."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise SourceOpenError(
            f"Could not read Vicon camera calibration {path.name}: {error}"
        ) from error

    cameras = root.findall("Camera")
    if device_id:
        cameras = [camera for camera in cameras if camera.get("DEVICEID") == device_id]
    else:
        cameras = [
            camera
            for camera in cameras
            if "VIDEO" in camera.get("TYPE", "").upper() or camera.get("ISDV") == "2"
        ]
    camera = next(
        (candidate for candidate in cameras if candidate.find("KeyFrames/KeyFrame") is not None),
        None,
    )
    if camera is None:
        raise SourceOpenError(f"{path.name} has no calibrated Vicon video camera.")

    keyframes = camera.findall("KeyFrames/KeyFrame")
    keyframe = next((item for item in keyframes if item.get("FRAME") == "0"), keyframes[0])
    try:
        width, height = (int(value) for value in camera.attrib["SENSOR_SIZE"].split())
        focal = float(keyframe.attrib["FOCAL_LENGTH"])
        principal_x, principal_y = _number_list(
            keyframe.get("PRINCIPAL_POINT"), "principal point", 2
        )
        orientation = _number_list(keyframe.get("ORIENTATION"), "orientation", 4)
        position = _number_list(keyframe.get("POSITION"), "position", 3)
        aspect = float(keyframe.get("PIXEL_ASPECT_RATIO_CORRECTION", "1"))
        radial = keyframe.get("VICON_RADIAL2", "").split()
        if radial and radial[0] != "Vicon3Parameter":
            raise SourceOpenError("Vicon calibration uses an unsupported radial distortion model.")
        coefficients = np.asarray([float(value) for value in radial[3:6]], dtype=np.float64)
        if not len(coefficients):
            coefficients = np.zeros(3, dtype=np.float64)
        if len(coefficients) != 3:
            raise SourceOpenError("Vicon calibration has invalid radial distortion coefficients.")
        radial_center = (
            np.asarray([float(value) for value in radial[1:3]], dtype=np.float64)
            if radial
            else np.asarray([principal_x, principal_y], dtype=np.float64)
        )
        if width <= 0 or height <= 0 or focal <= 0 or aspect <= 0:
            raise SourceOpenError("Vicon calibration has invalid camera image geometry.")
    except SourceOpenError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise SourceOpenError(f"{path.name} has incomplete video calibration: {error}") from error

    world_to_camera = Rotation.from_quat(orientation).as_matrix()
    translation = -world_to_camera @ position
    matrix = np.asarray(
        [
            [focal, 0.0, principal_x],
            [0.0, focal * aspect, principal_y],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    return ViconCameraModel(
        name=camera.get("DEVICEID", "Vicon video camera"),
        size=(width, height),
        matrix=matrix,
        rotation=Rotation.from_matrix(world_to_camera).as_rotvec(),
        translation=translation,
        radial_center=radial_center,
        radial=coefficients,
    )


def _channel_names(labels: list[str]) -> list[str]:
    names: list[str] = []
    used: set[str] = set()
    for index, label in enumerate(labels, start=1):
        name = _INVALID_CHANNEL_CHARACTERS.sub("_", label.strip()).strip(" .") or f"marker_{index}"
        base = name
        suffix = 2
        while name in used:
            name = f"{base}_{suffix}"
            suffix += 1
        used.add(name)
        names.append(name)
    return names


def _projection_channel_map(names: list[str]) -> dict[str, list[str]]:
    """Give projected pixels distinct channels beside each marker's world XYZ."""
    used = {f"{name}_{axis}" for name in names for axis in ("x", "y", "z")}
    result: dict[str, list[str]] = {}
    for name in names:
        projected: list[str] = []
        for axis in ("x", "y"):
            base = f"vicon_projection_{name}_{axis}"
            channel = base
            suffix = 2
            while channel in used:
                channel = f"{base}_{suffix}"
                suffix += 1
            used.add(channel)
            projected.append(channel)
        result[name] = projected
    return result


class ViconC3DLoader(TimeSeriesSource):
    """Load C3D points as native XYZ and calibrated video-frame XY pose."""

    calibration_suffix = ".xcp"

    @classmethod
    def display_name(cls) -> str:
        return "3D Marker Tracking"

    @classmethod
    def pose_roles(cls) -> tuple[str, ...]:
        return ("overlay2d", "pose3d", _COMBINED_ROLE)

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._camera: CameraModel | None = None
        self._channels: list[ChannelInfo] = []
        self._points: tuple[PosePoint, ...] = ()
        self._fps = 0.0
        self._frame_count = 0
        self._point_rate = 0.0
        self._first_frame = 0
        self._last_frame = -1
        self._video_size = (0, 0)
        self._role = "overlay2d"
        self._channel_specs: list[tuple[int, int, str]] = []

    def is_frame_indexed(self) -> bool:
        return True

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 0.9 if path.suffix.lower() == ".c3d" and path.with_suffix(".xcp").is_file() else 0.0

    @classmethod
    def prepare_import_config(cls, path: Path, config: dict[str, Any]) -> dict[str, Any]:
        """Resolve target-video dimensions before the import cache is checked."""
        prepared = dict(config)
        prepared["_vicon_projection_revision"] = 5
        if prepared.get("role") == _COMBINED_ROLE and not prepared.get("vicon_projection_channels"):
            try:
                with path.open("rb") as handle:
                    reader = _c3d_reader(handle)
                    labels = [
                        str(label).strip() for label in reader.point_labels[: reader.point_used]
                    ]
            except (OSError, ValueError) as error:
                raise SourceOpenError(
                    f"Could not read Vicon tracking labels from {path.name}: {error}"
                ) from error
            prepared["vicon_projection_channels"] = _projection_channel_map(_channel_names(labels))
        if {"video_width", "video_height"} <= prepared.keys() or not prepared.get("overlay_video"):
            return prepared

        video_path = Path(str(prepared["overlay_video"]))
        try:
            with av.open(str(video_path)) as container:
                stream = container.streams.video[0]
                width, height = int(stream.width), int(stream.height)
        except (av.FFmpegError, IndexError, OSError, TypeError, ValueError) as error:
            raise SourceOpenError(
                f"Could not inspect overlay video for {path.name}: {error}"
            ) from error
        if width <= 0 or height <= 0:
            raise SourceOpenError(f"Overlay video {video_path.name} has invalid dimensions.")
        prepared["video_width"] = width
        prepared["video_height"] = height
        return prepared

    def open(self, path: Path, config: dict[str, Any]) -> None:
        if path.suffix.lower() != ".c3d":
            raise SourceOpenError(
                f"{path.name} is not a C3D tracking file. Vicon XCP files are calibration "
                "metadata, and X2D files are not supported as tracking sources."
            )
        config = self.prepare_import_config(path, config)
        self._path = path
        self._config = config
        requested_role = str(config.get("role", "overlay2d"))
        self._role = requested_role if requested_role in self.pose_roles() else "overlay2d"
        xcp_path = Path(config.get("xcp_path", path.with_suffix(".xcp")))
        if not xcp_path.is_file():
            raise SourceOpenError(
                f"No Vicon XCP calibration was selected for {path.name}. Choose its matching "
                "calibration file to project the markers onto video."
            )
        self._camera = camera_from_xcp(xcp_path, str(config.get("camera_id", "")))
        self._fps = float(config.get("fps", 0.0))
        if self._fps <= 0.0:
            raise SourceOpenError("The paired video frame rate is required to project Vicon data.")
        self._video_size = (
            int(config.get("video_width", self._camera.size[0])),
            int(config.get("video_height", self._camera.size[1])),
        )
        if min(self._video_size) <= 0:
            raise SourceOpenError("The paired video has invalid dimensions.")

        try:
            with path.open("rb") as handle:
                reader = _c3d_reader(handle)
                self._point_rate = float(reader.point_rate)
                self._first_frame = int(reader.first_frame)
                self._last_frame = int(reader.last_frame)
                labels = [str(label).strip() for label in reader.point_labels[: reader.point_used]]
        except (OSError, ValueError) as error:
            raise SourceOpenError(
                f"Could not read C3D tracking data {path.name}: {error}"
            ) from error
        if self._point_rate <= 0.0 or not labels:
            raise SourceOpenError(f"{path.name} contains no usable 3D marker data.")

        duration = max(0.0, (self._last_frame - self._first_frame) / self._point_rate)
        self._frame_count = int(config.get("frame_count") or round(duration * self._fps) + 1)
        if self._frame_count <= 0:
            raise SourceOpenError("The paired video has no frames to overlay.")

        names = _channel_names(labels)
        has_world = self._role in ("pose3d", _COMBINED_ROLE)
        has_projection = self._role in ("overlay2d", _COMBINED_ROLE)
        self._points = tuple(
            PosePoint(
                individual="",
                bodypart=name,
                axes=("x", "y", "z") if has_world else ("x", "y"),
            )
            for name in names
        )
        self._channel_specs = []
        self._channels = []
        for point_index, point in enumerate(self._points):
            if has_world:
                for axis_index, axis in enumerate(("x", "y", "z")):
                    channel = point.channel(axis)
                    self._channels.append(ChannelInfo(channel, "mm", "Float64", self._fps))
                    self._channel_specs.append((point_index, axis_index, channel))
            if has_projection:
                if self._role == _COMBINED_ROLE:
                    projection_map = config.get("vicon_projection_channels", {})
                    projected = (
                        projection_map.get(point.name) if isinstance(projection_map, dict) else None
                    )
                    if not isinstance(projected, (list, tuple)) or len(projected) != 2:
                        raise SourceOpenError(
                            f"Vicon projection channels are missing for marker {point.name}."
                        )
                    projection_names = [str(channel) for channel in projected]
                    column_offset = 3
                else:
                    projection_names = [point.channel(axis) for axis in ("x", "y")]
                    column_offset = 0
                for axis_index, (_axis, channel) in enumerate(
                    zip(("x", "y"), projection_names, strict=True)
                ):
                    self._channels.append(ChannelInfo(channel, "px", "Float64", self._fps))
                    self._channel_specs.append((point_index, column_offset + axis_index, channel))

    def channels(self) -> list[ChannelInfo]:
        return list(self._channels)

    def pose_schema(self) -> PoseSchema:
        return PoseSchema(points=self._points, frame_indexed=True)

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        for chunk in self.read_all_chunks((ch,)):
            yield chunk[ch]

    def read_all_chunks(
        self, channels: tuple[str, ...] | None = None
    ) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
        if self._path is None or self._camera is None:
            raise SourceOpenError("Vicon source used before open().")

        selected = set(channels or (channel.name for channel in self._channels))
        point_channels = [spec for spec in self._channel_specs if spec[2] in selected]
        if not point_channels:
            return

        sample_width = 5 if self._role == _COMBINED_ROLE else 3 if self._role == "pose3d" else 2

        targets = np.arange(self._frame_count, dtype=np.float64) * self._point_rate / self._fps
        buffer: list[np.ndarray] = []
        buffer_start = 0
        next_target = 0
        previous: np.ndarray | None = None

        with self._path.open("rb") as handle:
            reader = _c3d_reader(handle)
            for frame_number, points, _analog in reader.read_frames():
                frame_offset = int(frame_number) - self._first_frame
                if frame_offset < 0:
                    continue
                while next_target < self._frame_count and targets[next_target] <= frame_offset:
                    left = int(np.floor(targets[next_target]))
                    fraction = float(targets[next_target] - left)
                    if fraction == 0.0 or previous is None:
                        positions = np.asarray(points[:, :3], dtype=np.float64)
                        valid = np.isfinite(positions).all(axis=1)
                        if points.shape[1] > 3:
                            valid &= np.asarray(points[:, 3], dtype=np.float64) >= 0.0
                    else:
                        positions = (
                            np.asarray(previous[:, :3], dtype=np.float64) * (1.0 - fraction)
                            + np.asarray(points[:, :3], dtype=np.float64) * fraction
                        )
                        valid = np.isfinite(positions).all(axis=1)
                        if points.shape[1] > 3:
                            valid &= (previous[:, 3] >= 0.0) & (points[:, 3] >= 0.0)
                    if self._role == "overlay2d":
                        sample = self._project(positions, valid)
                    elif self._role == "pose3d":
                        sample = np.full((len(self._points), 3), np.nan, dtype=np.float64)
                        sample[valid] = positions[valid]
                    else:
                        sample = np.full((len(self._points), 5), np.nan, dtype=np.float64)
                        sample[valid, :3] = positions[valid]
                        sample[:, 3:] = self._project(positions, valid.copy())
                    buffer.append(sample)
                    next_target += 1
                    if len(buffer) == _CHUNK_SIZE:
                        yield self._make_chunk(buffer, buffer_start, point_channels)
                        buffer_start += len(buffer)
                        buffer.clear()
                previous = np.asarray(points)

        while next_target < self._frame_count:
            buffer.append(np.full((len(self._points), sample_width), np.nan, dtype=np.float64))
            next_target += 1
            if len(buffer) == _CHUNK_SIZE:
                yield self._make_chunk(buffer, buffer_start, point_channels)
                buffer_start += len(buffer)
                buffer.clear()
        if buffer:
            yield self._make_chunk(buffer, buffer_start, point_channels)

    def _project(self, positions: np.ndarray, valid: np.ndarray) -> np.ndarray:
        assert self._camera is not None
        camera_points = positions @ self._camera.rotation_matrix().T + self._camera.translation
        valid &= camera_points[:, 2] > 0.0
        projected = np.full((len(positions), 2), np.nan, dtype=np.float64)
        if valid.any():
            pixels = self._camera.project(positions[valid])
            sensor = np.asarray(self._camera.size, dtype=np.float64)
            video = np.asarray(self._video_size, dtype=np.float64)
            if (video <= sensor).all():
                # Vue video modes are a centered ROI of the sensor; the XCP declares no crop.
                projected[valid] = pixels - (sensor - video) / 2.0
            else:
                projected[valid] = pixels * (video / sensor)
        return projected

    def _make_chunk(
        self,
        points: list[np.ndarray],
        first_index: int,
        point_channels: list[tuple[int, int, str]],
    ) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        values = np.stack(points)
        times = np.arange(first_index, first_index + len(points), dtype=np.float64) / self._fps
        return {
            channel: (times, values[:, point_index, column_index])
            for point_index, column_index, channel in point_channels
        }
