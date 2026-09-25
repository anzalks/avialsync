"""Where a wheel lives: ``pose-3d/<name>.wheel.toml`` (D-113).

Beside the 3D pose, like the calibration it was triangulated with, and never
inside a pose file (the D-099 rule). The **clicks are the authority**: they are
what the user did, and everything else in the file -- the geometry, the fit
report, the encoder binding -- was computed from them or declared beside them.
The fit report is stored rather than recomputed because reading a wheel back
must not need the calibration to be found first; it is also what makes the file
readable on its own, the way anipose's ``calibration.toml`` carries its error.

A removed wheel keeps its file, marked ``removed = true``: nothing here deletes a
file from a data folder, and undoing the removal writes it back in full.

Headless (architecture rule 2).
"""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from avialsync.core.toml_format import toml_value, write_atomic
from avialsync.core.wheel import (
    ClickResidual,
    EncoderBinding,
    EndClick,
    Wheel,
    WheelCheck,
    WheelFit,
    WheelGeometry,
    WheelSpec,
)

logger = logging.getLogger(__name__)

__all__ = [
    "WHEEL_SUFFIX",
    "wheel_path",
    "is_wheel_path",
    "write_wheel",
    "write_removed",
    "read_wheels",
]

WHEEL_SUFFIX = ".wheel.toml"
_HEADER = "# AvialSync wheel (D-113). The clicks are the authority; the rest was fitted from them."


def wheel_path(folder: Path | str, name: str) -> Path:
    """The file wheel *name* is kept in, inside *folder*."""
    return Path(folder) / f"{name}{WHEEL_SUFFIX}"


def is_wheel_path(path: Path | str) -> bool:
    """Whether *path* is one of our wheel files, which no loader may claim."""
    return Path(path).name.lower().endswith(WHEEL_SUFFIX)


def _line(key: str, value: object) -> str:
    return f"{key} = {toml_value(value)}"


def _table(header: str, fields: list[tuple[str, object]]) -> list[str]:
    """One TOML table; a field whose value is None is left out (TOML has no null)."""
    return ["", header, *(_line(key, value) for key, value in fields if value is not None)]


def write_wheel(folder: Path | str, wheel: Wheel) -> Path:
    """Write *wheel* atomically, creating the ``pose-3d`` folder if needed."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    spec, geometry, fit, binding = wheel.spec, wheel.geometry, wheel.fit, wheel.binding
    lines = [_HEADER]
    lines += _table(
        "[wheel]",
        [
            ("name", spec.name),
            ("bar_count", spec.bar_count),
            ("radius", spec.radius),
            ("units", spec.units),
            ("frame", wheel.frame),
            ("flipped", wheel.flipped),
            ("calibration", wheel.calibration),
            ("bar_diameter", wheel.bar_diameter),
            ("removed", False),
        ],
    )
    lines += _table(
        "[geometry]",
        [
            ("centre", list(geometry.centre)),
            ("axle", list(geometry.axle)),
            ("zero", list(geometry.zero)),
            ("radius", geometry.radius),
            ("half_width", geometry.half_width),
        ],
    )
    lines += _table(
        "[fit]",
        [
            ("indices", list(fit.indices)),
            ("spacing_deg", list(fit.spacing_deg)),
            ("parallel_deg", list(fit.parallel_deg)),
            ("ambiguous", fit.ambiguous),
            ("can_flip", fit.can_flip),
            # Read by people, not by this module: the residuals are the record.
            ("median_px", fit.median_px),
            ("max_px", fit.max_px),
            ("implied_radius", fit.implied_radius),
        ],
    )
    if binding is not None:
        lines += _table(
            "[encoder]",
            [
                ("source", binding.source_id),
                ("channel", binding.channel),
                ("reference_angle", binding.reference_angle),
                ("sign", binding.sign),
                ("ratio", binding.ratio),
                ("measured", binding.measured),
            ],
        )
    lines += _records(wheel)
    return write_atomic(wheel_path(folder, spec.name), lines)


def _records(wheel: Wheel) -> list[str]:
    """The clicks, the residuals, and the checks, as arrays of tables."""
    lines: list[str] = []
    for click in wheel.clicks:
        lines += _table(
            "[[click]]",
            [
                ("bar", click.bar),
                ("side", click.side),
                ("cameras", [camera for camera, _, _ in click.views]),
                ("x", [x for _, x, _ in click.views]),
                ("y", [y for _, _, y in click.views]),
            ],
        )
    for residual in wheel.fit.residuals:
        lines += _table(
            "[[residual]]",
            [
                ("bar", residual.bar),
                ("side", residual.side),
                ("camera", residual.camera),
                ("pixels", residual.pixels),
            ],
        )
    for item in wheel.binding.checks if wheel.binding is not None else ():
        lines += _table(
            "[[check]]",
            [
                ("frame", item.frame),
                ("encoder_angle", item.encoder_angle),
                ("camera", item.camera),
                ("x", item.x),
                ("y", item.y),
            ],
        )
    return lines


def write_removed(folder: Path | str, name: str) -> Path | None:
    """Mark wheel *name*'s file removed, keeping the file; None if it never existed."""
    target = wheel_path(folder, name)
    if not target.exists():
        return None
    lines = [_HEADER, *_table("[wheel]", [("name", name), ("removed", True)])]
    return write_atomic(target, lines)


def _triple(values: Any) -> tuple[float, float, float]:
    x, y, z = (float(v) for v in values)
    return (x, y, z)


def _parse_fit(document: Mapping[str, Any], geometry: WheelGeometry) -> WheelFit:
    report = document.get("fit", {})
    implied = report.get("implied_radius")
    return WheelFit(
        geometry=geometry,
        indices=tuple(int(i) for i in report.get("indices", ())),
        residuals=tuple(
            ClickResidual(int(r["bar"]), str(r["side"]), str(r["camera"]), float(r["pixels"]))
            for r in document.get("residual", ())
        ),
        spacing_deg=tuple(float(v) for v in report.get("spacing_deg", ())),
        parallel_deg=tuple(float(v) for v in report.get("parallel_deg", ())),
        implied_radius=None if implied is None else float(implied),
        ambiguous=bool(report.get("ambiguous", False)),
        can_flip=bool(report.get("can_flip", False)),
    )


def _parse_binding(document: Mapping[str, Any]) -> EncoderBinding | None:
    encoder = document.get("encoder")
    if encoder is None:
        return None
    return EncoderBinding(
        source_id=str(encoder["source"]),
        channel=str(encoder["channel"]),
        reference_angle=float(encoder["reference_angle"]),
        sign=float(encoder.get("sign", 1.0)),
        ratio=float(encoder.get("ratio", 1.0)),
        measured=bool(encoder.get("measured", False)),
        checks=tuple(
            WheelCheck(
                frame=int(k["frame"]),
                encoder_angle=float(k["encoder_angle"]),
                camera=str(k["camera"]),
                x=float(k["x"]),
                y=float(k["y"]),
            )
            for k in document.get("check", ())
        ),
    )


def _parse(document: Mapping[str, Any]) -> Wheel | None:
    head = document["wheel"]
    if head.get("removed", False):
        return None
    radius = head.get("radius")
    spec = WheelSpec(
        name=str(head["name"]),
        bar_count=int(head["bar_count"]),
        radius=None if radius is None else float(radius),
        units=str(head.get("units", "")),
    )
    shape = document["geometry"]
    geometry = WheelGeometry(
        centre=_triple(shape["centre"]),
        axle=_triple(shape["axle"]),
        zero=_triple(shape["zero"]),
        radius=float(shape["radius"]),
        half_width=float(shape["half_width"]),
        bar_count=spec.bar_count,
    )
    clicks = tuple(
        EndClick(
            bar=int(c["bar"]),
            side=str(c["side"]),
            views=tuple(
                (str(camera), float(x), float(y))
                for camera, x, y in zip(c["cameras"], c["x"], c["y"], strict=True)
            ),
        )
        for c in document.get("click", ())
    )
    return Wheel(
        spec=spec,
        frame=int(head["frame"]),
        clicks=clicks,
        fit=_parse_fit(document, geometry),
        flipped=bool(head.get("flipped", False)),
        bar_diameter=None if head.get("bar_diameter") is None else float(head["bar_diameter"]),
        binding=_parse_binding(document),
        calibration=str(head.get("calibration", "")),
    )


def read_wheels(folder: Path | str) -> tuple[list[Wheel], list[str]]:
    """Every wheel kept in *folder*, and the names of files that could not be read.

    A damaged file costs that wheel only (AGENTS rule 10); the caller says which.
    """
    wheels: list[Wheel] = []
    unreadable: list[str] = []
    folder = Path(folder)
    if not folder.is_dir():
        return wheels, unreadable
    for path in sorted(folder.glob(f"*{WHEEL_SUFFIX}")):
        try:
            wheel = _parse(tomllib.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError, ValueError):
            logger.warning("Could not read wheel file %s", path, exc_info=True)
            unreadable.append(path.name)
            continue
        if wheel is not None:
            wheels.append(wheel)
    return wheels, unreadable
