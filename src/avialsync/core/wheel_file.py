"""Wheel-specific encoding inside the generalized physical-prop sidecar.

Beside the 3D pose, like the calibration it was triangulated with, and never
inside a pose file. The **clicks are the authority**: they are
what the user did, and everything else in the file -- the geometry, the fit
report, the encoder binding -- was computed from them or declared beside them.
The fit report is stored rather than recomputed because reading a wheel back
must not need the calibration to be found first; it is also what makes the file
readable on its own, the way anipose's ``calibration.toml`` carries its error.

A removed wheel keeps its file, marked ``removed = true``: nothing here deletes a
file from a data folder, and undoing the removal writes it back in full.

Headless.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from avialsync.core.rotary_calibration import RotaryObservation
from avialsync.core.rotary_motion import PeriodicRotaryMotion, RotaryHarmonic
from avialsync.core.toml_format import toml_value
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

__all__ = [
    "write_wheel",
    "write_removed",
    "read_wheels",
]


def _line(key: str, value: object) -> str:
    return f"{key} = {toml_value(value)}"


def _table(header: str, fields: list[tuple[str, object]]) -> list[str]:
    """One TOML table; a field whose value is None is left out (TOML has no null)."""
    return ["", header, *(_line(key, value) for key, value in fields if value is not None)]


def write_wheel(folder: Path | str, wheel: Wheel) -> Path:
    """Write *wheel* using the generalized physical-prop sidecar."""
    from avialsync.core.prop_file import write_prop

    return write_prop(folder, wheel)


def wheel_sections(wheel: Wheel) -> list[str]:
    """Serialize wheel-specific tables for a generalized prop record."""
    spec, geometry, fit, binding = wheel.spec, wheel.geometry, wheel.fit, wheel.binding
    lines: list[str] = []
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
        if binding.motion_model is not None:
            model = binding.motion_model
            lines += _table(
                "[encoder.motion]",
                [
                    ("kind", "periodic_rotary"),
                    ("version", 1),
                    ("gain", model.gain),
                    ("offset_degrees", model.offset_degrees),
                    ("source", binding.motion_source or None),
                ],
            )
            for harmonic in model.harmonics:
                lines += _table(
                    "[[encoder.motion.harmonic]]",
                    [
                        ("order", harmonic.order),
                        ("sine_degrees", harmonic.sine_degrees),
                        ("cosine_degrees", harmonic.cosine_degrees),
                    ],
                )
    lines += _records(wheel)
    return lines


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
    for seen in wheel.binding.rotation_observations if wheel.binding is not None else ():
        lines += _table(
            "[[encoder.rotation_observation]]",
            [
                ("frame", seen.evidence_index),
                ("encoder_angle", seen.reading),
                ("angle_degrees", seen.angle_degrees),
            ],
        )
    return lines


def write_removed(folder: Path | str, name: str) -> Path | None:
    """Mark a wheel removed in its generalized prop sidecar."""
    from avialsync.core.prop_file import write_removed as write_prop_removed

    return write_prop_removed(folder, name, kind="wheel")


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
    motion = _parse_motion(encoder.get("motion"))
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
        rotation_observations=tuple(
            RotaryObservation(
                reading=float(item["encoder_angle"]),
                angle_degrees=float(item["angle_degrees"]),
                evidence_index=(None if item.get("frame") is None else int(item["frame"])),
            )
            for item in document.get("encoder", {}).get("rotation_observation", ())
        ),
        motion_model=motion,
        motion_source=str(encoder.get("motion", {}).get("source", "")),
    )


def _parse_motion(value: Any) -> PeriodicRotaryMotion | None:
    """Read an optional versioned periodic transfer from an encoder table."""
    if value is None:
        return None
    model = _mapping(value)
    if model.get("kind") != "periodic_rotary" or int(model.get("version", 0)) != 1:
        raise ValueError("Unsupported encoder motion model.")
    # A gain-only model writes no harmonic tables at all.
    raw_harmonics = model.get("harmonic", [])
    if not isinstance(raw_harmonics, list):
        raise ValueError("Encoder motion harmonics must be a table array.")
    return PeriodicRotaryMotion(
        gain=float(model["gain"]),
        offset_degrees=float(model["offset_degrees"]),
        harmonics=tuple(
            RotaryHarmonic(
                order=int(_mapping(harmonic)["order"]),
                sine_degrees=float(_mapping(harmonic).get("sine_degrees", 0.0)),
                cosine_degrees=float(_mapping(harmonic).get("cosine_degrees", 0.0)),
            )
            for harmonic in raw_harmonics
        ),
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("An encoder motion model must be a TOML table.")
    return value


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


def parse_wheel_document(document: Mapping[str, Any]) -> Wheel | None:
    """Parse wheel-specific tables embedded in one generalized prop record."""
    return _parse(document)


def read_wheels(folder: Path | str) -> list[Wheel]:
    """Read wheel records from canonical ``_prop.toml`` sidecars only."""
    from avialsync.core.prop_file import read_props

    props, _issues = read_props(folder)
    return [prop for prop in props if isinstance(prop, Wheel)]
