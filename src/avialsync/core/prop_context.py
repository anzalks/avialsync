"""Portable, immutable projection context carried by an accepted physical prop."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.calibration import CameraModel, ImageCorrection
from avialsync.core.errors import PropModelError
from avialsync.core.toml_format import toml_value


@dataclass(frozen=True)
class PropCamera:
    """One camera's effective projection, independent of its calibration file."""

    source: str
    name: str
    size: tuple[int, int]
    matrix: tuple[tuple[float, ...], ...]
    distortions: tuple[float, ...]
    rotation: tuple[float, ...]
    translation: tuple[float, ...]
    correction: ImageCorrection | None = field(default=None, compare=False)
    _correction_key: tuple[object, ...] = field(default=(), init=False, repr=False)

    def __post_init__(self) -> None:
        if self.correction is not None:
            object.__setattr__(
                self,
                "_correction_key",
                tuple(getattr(self.correction, item.name) for item in fields(self.correction)),
            )
        vectors = (*self.matrix, self.distortions, self.rotation, self.translation)
        if (
            not self.source
            or not self.name
            or len(self.size) != 2
            or min(self.size) <= 0
            or len(self.matrix) != 3
            or any(len(row) != 3 for row in self.matrix)
            or len(self.rotation) != 3
            or len(self.translation) != 3
            or not all(math.isfinite(v) for row in vectors for v in row)
            or self.matrix[0][0] <= 0
            or self.matrix[1][1] <= 0
        ):
            raise PropModelError("A saved prop needs a finite, complete camera projection.")

    @classmethod
    def capture(cls, source: str, model: CameraModel) -> PropCamera:
        """Freeze the small native arrays; image-correction tuples are already immutable."""
        return cls(
            source,
            model.name,
            model.size,
            tuple(tuple(float(v) for v in row) for row in model.matrix),
            tuple(float(v) for v in model.distortions),
            tuple(float(v) for v in model.rotation),
            tuple(float(v) for v in model.translation),
            model.correction,
        )

    @cached_property
    def model(self) -> CameraModel:
        """Reconstruct once, never on each paint."""
        arrays = [
            np.asarray(value, dtype=np.float64)
            for value in (self.matrix, self.distortions, self.rotation, self.translation)
        ]
        for array in arrays:
            array.setflags(write=False)
        return CameraModel(
            self.name,
            self.size,
            arrays[0],
            arrays[1],
            arrays[2],
            arrays[3],
            correction=self.correction,
        )


@dataclass(frozen=True)
class PropContext:
    """Geometry's cameras and the camera whose frames name its observations."""

    cameras: tuple[PropCamera, ...] = ()
    reference_camera: str = ""
    reference_time: float | None = None

    def __post_init__(self) -> None:
        names = [camera.name for camera in self.cameras]
        sources = [camera.source for camera in self.cameras]
        if len(set(names)) != len(names) or len(set(sources)) != len(sources):
            raise PropModelError("Saved prop camera identities must be unique.")
        if self.reference_camera and self.reference_camera not in names:
            raise PropModelError("The prop's reference camera is missing from its context.")
        if self.reference_time is not None and not math.isfinite(self.reference_time):
            raise PropModelError("A prop's reference timestamp must be finite.")


def source_fields(key: str, source: str, folder: Path) -> list[tuple[str, object]]:
    """Make native absolute paths portable without changing logical source ids."""
    relative = False
    if Path(source).is_absolute():
        try:
            source = Path(os.path.relpath(source, folder)).as_posix()
            relative = True
        except ValueError:
            # Different Windows drives have no relative path; keep the named dependency.
            pass
    return [(key, source), (f"{key}_relative", relative)]


def read_source(row: Mapping[str, Any], key: str, folder: Path) -> str:
    """Resolve a recording-relative reference; never guess a replacement file."""
    source = row[key]
    relative = row.get(f"{key}_relative", False)
    if not isinstance(source, str) or type(relative) is not bool:
        raise PropModelError("A prop source reference is malformed.")
    return os.path.abspath(folder / source) if relative else source


def _table(name: str, fields: list[tuple[str, object]]) -> list[str]:
    return ["", name, *(f"{key} = {toml_value(value)}" for key, value in fields)]


def context_sections(context: PropContext, folder: Path) -> list[str]:
    """Encode every effective camera, including the image-space correction."""
    fields: list[tuple[str, object]] = [("reference_camera", context.reference_camera)]
    if context.reference_time is not None:
        fields.append(("reference_time", context.reference_time))
    lines = _table("[context]", fields)
    for camera in context.cameras:
        lines += _table(
            "[[context.camera]]",
            [
                *source_fields("source", camera.source, folder),
                ("name", camera.name),
                ("size", camera.size),
                ("matrix", camera.matrix),
                ("distortions", camera.distortions),
                ("rotation", camera.rotation),
                ("translation", camera.translation),
            ],
        )
        correction = camera.correction
        if correction is not None:
            fields = [
                ("affine", correction.affine),
                ("control_pixels", correction.control_pixels),
                ("displacements", correction.displacements),
                ("smoothing", correction.smoothing),
                ("scale", correction.scale),
                ("source", correction.source),
            ]
            if correction.size is not None:
                fields.append(("size", correction.size))
            lines += _table("[context.camera.correction]", fields)
    return lines


def _number(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise PropModelError("Saved camera values must be finite numbers.")
    return float(value)


def _numbers(value: Any) -> tuple[float, ...]:
    if not isinstance(value, list) or any(type(v) not in (int, float) for v in value):
        raise PropModelError("Saved camera coefficients must be numeric arrays.")
    result = tuple(float(v) for v in value)
    if not all(math.isfinite(v) for v in result):
        raise PropModelError("Saved camera coefficients must be finite.")
    return result


def _rows(value: Any) -> tuple[tuple[float, ...], ...]:
    if not isinstance(value, list):
        raise PropModelError("Saved camera matrices must be arrays.")
    return tuple(_numbers(row) for row in value)


def _size(value: Any) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2 or any(type(v) is not int for v in value):
        raise PropModelError("A saved camera needs an integer image size.")
    if min(value) <= 0:
        raise PropModelError("A saved camera needs a positive image size.")
    return value[0], value[1]


def _correction(row: Mapping[str, Any]) -> ImageCorrection | None:
    data = row.get("correction")
    if data is None:
        return None
    if not isinstance(data, dict):
        raise PropModelError("A saved camera correction must be a table.")
    affine, controls, offsets = (
        _rows(data[key]) for key in ("affine", "control_pixels", "displacements")
    )
    smoothing, scale = _number(data["smoothing"]), _number(data["scale"])
    if (
        len(affine) != 3
        or any(len(r) != 3 for r in affine)
        or len(controls) != len(offsets)
        or any(len(r) != 2 for r in (*controls, *offsets))
        or not math.isfinite(smoothing)
        or smoothing < 0
        or not math.isfinite(scale)
        or scale <= 0
        or abs(float(np.linalg.det(np.asarray(affine)[:2, :2]))) < 1e-12
    ):
        raise PropModelError("A saved camera correction is incomplete or singular.")
    return ImageCorrection(
        tuple((r[0], r[1], r[2]) for r in affine),
        tuple((r[0], r[1]) for r in controls),
        tuple((r[0], r[1]) for r in offsets),
        smoothing,
        scale,
        _size(data["size"]) if "size" in data else None,
        str(data.get("source", "")),
    )


def parse_context(document: Mapping[str, Any], folder: Path) -> PropContext:
    """Validate the current record's projection context before adoption."""
    data = document["context"]
    if not isinstance(data, dict) or not isinstance(data.get("camera", []), list):
        raise PropModelError("A prop needs its own projection context table.")
    cameras: list[PropCamera] = []
    for row in data.get("camera", []):
        if not isinstance(row, dict) or not isinstance(row["name"], str):
            raise PropModelError("A prop camera needs a name and projection.")
        cameras.append(
            PropCamera(
                read_source(row, "source", folder),
                row["name"],
                _size(row["size"]),
                _rows(row["matrix"]),
                _numbers(row["distortions"]),
                _numbers(row["rotation"]),
                _numbers(row["translation"]),
                _correction(row),
            )
        )
    reference = data.get("reference_camera", "")
    if not isinstance(reference, str):
        raise PropModelError("A prop reference camera must be a name.")
    return PropContext(
        tuple(cameras),
        reference,
        _number(data["reference_time"]) if "reference_time" in data else None,
    )
