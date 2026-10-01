"""Versioned sidecars for physical props, beside their recording (D-149).

The first supported kind is a user-clicked ladder. A future kind or damaged
file costs only that prop: :func:`read_props` returns a per-file issue for the
UI to report. Raw camera clicks are the authority; stored 3D coordinates and
reprojection errors let a prop draw when calibration is temporarily absent.
Wheel files retain their D-113 format and are read by ``wheel_file``.
"""

from __future__ import annotations

import logging
import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import Ladder, LadderPoint, LadderStep, Point3, StepClick
from avialsync.core.toml_format import toml_value, write_atomic

__all__ = [
    "PROP_SUFFIX",
    "PropFileIssueCode",
    "PropFileIssue",
    "prop_path",
    "is_prop_path",
    "write_ladder",
    "write_removed",
    "read_props",
]

logger = logging.getLogger(__name__)
PROP_SUFFIX = ".prop.toml"
_VERSION = 1
_HEADER = "# AvialSync physical prop (D-149). Camera clicks are the authority."
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{index}" for prefix in ("COM", "LPT") for index in range(1, 10)
}
_FORBIDDEN_NAME = set('<>:"/\\|?*')
PropFileIssueCode = Literal["damaged", "unsupported_version", "unsupported_kind", "name_mismatch"]


@dataclass(frozen=True)
class PropFileIssue:
    """A prop sidecar that could not be adopted, without hiding other props."""

    filename: str
    reason: PropFileIssueCode
    detail: str = ""


def _safe_name(name: str) -> None:
    if (
        not name
        or name.strip(" .") != name
        or any(char in _FORBIDDEN_NAME or ord(char) < 32 for char in name)
        or name.split(".", 1)[0].upper() in _WINDOWS_RESERVED
    ):
        raise PropModelError("A prop name must be a safe filename on every platform.")


def prop_path(folder: Path | str, name: str) -> Path:
    """The kind-tagged sidecar for *name* inside the recording's 3D folder."""
    _safe_name(name)
    return Path(folder) / f"{name}{PROP_SUFFIX}"


def is_prop_path(path: Path | str) -> bool:
    """Whether a path is a physical-prop sidecar, not a source to import."""
    return Path(path).name.lower().endswith(PROP_SUFFIX)


def _table(header: str, fields: list[tuple[str, object | None]]) -> list[str]:
    return [
        "",
        header,
        *(f"{key} = {toml_value(value)}" for key, value in fields if value is not None),
    ]


def _assert_owned(target: Path, name: str) -> None:
    """Never replace a damaged or future-format record with an older writer."""
    if not target.exists():
        return
    try:
        document = tomllib.loads(target.read_text(encoding="utf-8"))
        head = _mapping(document["prop"])
        if (
            _integer(head["version"]) != _VERSION
            or head.get("kind") != "ladder"
            or _text(head["name"]) != name
        ):
            raise PropModelError("A different or newer prop file already uses this name.")
        _flag(head, "removed")
        _, issue = _parse(document, target)
        if issue is not None:
            raise PropModelError("An unreadable prop file already uses this name.")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, PropModelError) as exc:
        raise PropModelError("An unreadable prop file already uses this name.") from exc


def write_ladder(folder: Path | str, ladder: Ladder) -> Path:
    """Atomically write actual step clicks and their last solved 3D positions."""
    folder = Path(folder)
    target = prop_path(folder, ladder.name)
    _assert_owned(target, ladder.name)
    folder.mkdir(parents=True, exist_ok=True)
    lines = [_HEADER]
    lines += _table(
        "[prop]",
        [
            ("version", _VERSION),
            ("kind", "ladder"),
            ("name", ladder.name),
            ("calibration", ladder.calibration),
            ("units", ladder.units),
            ("removed", False),
        ],
    )
    for step in ladder.steps:
        lines += _table(
            "[[step]]",
            [("id", step.step_id), ("label", step.label), ("closed", step.closed)],
        )
        for point in step.points:
            lines += _table(
                "[[step.point]]",
                [
                    ("xyz", point.xyz),
                    ("error_px", point.error_px),
                    ("issue", point.issue),
                ],
            )
            for click in point.clicks:
                lines += _table(
                    "[[step.point.click]]",
                    [
                        ("camera", click.camera),
                        ("frame", click.frame),
                        ("x", click.x),
                        ("y", click.y),
                    ],
                )
    return write_atomic(target, lines)


def write_removed(folder: Path | str, name: str) -> Path | None:
    """Mark an existing prop removed, retaining a sidecar for undo/recovery."""
    target = prop_path(folder, name)
    if not target.exists():
        return None
    _assert_owned(target, name)
    lines = [
        _HEADER,
        *_table(
            "[prop]",
            [("version", _VERSION), ("kind", "ladder"), ("name", name), ("removed", True)],
        ),
    ]
    return write_atomic(target, lines)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise PropModelError("A prop record must be a TOML table.")
    return value


def _records(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise PropModelError("A prop record list must be a TOML array of tables.")
    return [_mapping(item) for item in value]


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise PropModelError("A prop text field must be a string.")
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PropModelError("A prop frame or version must be an integer.")
    return value


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PropModelError("A prop coordinate must be a number.")
    result = float(value)
    if not math.isfinite(result):
        raise PropModelError("A prop coordinate must be finite.")
    return result


def _flag(row: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = row.get(key, default)
    if type(value) is not bool:
        raise PropModelError("A prop flag must be true or false.")
    return value


def _point3(value: object) -> Point3:
    if not isinstance(value, list) or len(value) != 3:
        raise PropModelError("A solved prop point needs three coordinates.")
    return (_number(value[0]), _number(value[1]), _number(value[2]))


def _parse_point(row: Mapping[str, Any]) -> LadderPoint:
    clicks = tuple(
        StepClick(
            _text(click["camera"]),
            _integer(click["frame"]),
            _number(click["x"]),
            _number(click["y"]),
        )
        for click in _records(row.get("click", []))
    )
    xyz = None if "xyz" not in row else _point3(row["xyz"])
    error = None if "error_px" not in row else _number(row["error_px"])
    issue = row.get("issue")
    if issue is not None and issue not in (
        "need_two_calibrated_views",
        "rays_parallel",
        "invalid_solution",
    ):
        raise PropModelError("The point has an unknown solve status.")
    return LadderPoint(clicks=clicks, xyz=xyz, error_px=error, issue=issue)


def _parse_ladder(head: Mapping[str, Any], document: Mapping[str, Any]) -> Ladder:
    steps = tuple(
        LadderStep(
            step_id=_text(row["id"]),
            label=_text(row["label"]),
            points=tuple(_parse_point(point) for point in _records(row["point"])),
            closed=_flag(row, "closed"),
        )
        for row in _records(document.get("step", []))
    )
    return Ladder(
        name=_text(head["name"]),
        steps=steps,
        calibration=_text(head.get("calibration", "")),
        units=_text(head.get("units", "")),
    )


def _parse(document: Mapping[str, Any], path: Path) -> tuple[Ladder | None, PropFileIssue | None]:
    head = _mapping(document["prop"])
    version = _integer(head["version"])
    if version != _VERSION:
        return None, PropFileIssue(path.name, "unsupported_version", str(version))
    if _flag(head, "removed"):
        return None, None
    kind = head.get("kind")
    if kind != "ladder":
        return None, PropFileIssue(path.name, "unsupported_kind", str(kind))
    ladder = _parse_ladder(head, document)
    if prop_path(path.parent, ladder.name) != path:
        return None, PropFileIssue(path.name, "name_mismatch", ladder.name)
    return ladder, None


def read_props(folder: Path | str) -> tuple[list[Ladder], list[PropFileIssue]]:
    """Read every supported prop while reporting damaged and future records."""
    props: list[Ladder] = []
    issues: list[PropFileIssue] = []
    folder = Path(folder)
    if not folder.is_dir():
        return props, issues
    for path in sorted(folder.glob(f"*{PROP_SUFFIX}")):
        try:
            prop, issue = _parse(tomllib.loads(path.read_text(encoding="utf-8")), path)
        except (
            OSError,
            UnicodeError,
            tomllib.TOMLDecodeError,
            KeyError,
            TypeError,
            ValueError,
            PropModelError,
        ):
            logger.warning("Could not read prop file %s", path, exc_info=True)
            issues.append(PropFileIssue(path.name, "damaged"))
            continue
        if issue is not None:
            issues.append(issue)
        elif prop is not None:
            props.append(prop)
    return props, issues
