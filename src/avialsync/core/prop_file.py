"""Versioned sidecars for physical props, beside their recording (D-149).

Each kind has its own typed table under one versioned ``<name>_prop.toml`` record.
Raw camera clicks remain authoritative for ladders and wheels; declared belt
and ball geometry is kept separate from motion evidence. Damaged or future
records cost only that prop and are reported individually.
"""

from __future__ import annotations

import logging
import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeVar

from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import (
    LADDER_SUPPORTS,
    STEP_IRREGULARITIES,
    BallBinding,
    BallProp,
    BallSurface,
    BallVisualFrame,
    BeltBinding,
    BeltProp,
    BeltRollers,
    BeltSideView,
    BeltTrack,
    BeltVisualFrame,
    Ladder,
    LadderPoint,
    LadderStep,
    MotionCheck,
    PhysicalProp,
    Point3,
    RungPattern,
    StepClick,
    UnitQuaternion,
)
from avialsync.core.toml_format import toml_value, write_atomic
from avialsync.core.wheel import Wheel
from avialsync.core.wheel_file import parse_wheel_document, wheel_sections

__all__ = [
    "PROP_SUFFIX",
    "PropRecord",
    "PropFileIssueCode",
    "PropFileIssue",
    "prop_path",
    "is_prop_path",
    "prop_kind",
    "write_prop",
    "write_ladder",
    "write_belt",
    "write_ball",
    "write_wheel",
    "write_removed",
    "read_prop_records",
    "read_props",
]

logger = logging.getLogger(__name__)
PROP_SUFFIX = "_prop.toml"
_VERSION = 1
_HEADER = "# AvialSync physical prop (D-149). Camera clicks are the authority."
PropKind = Literal["ladder", "wheel", "belt", "ball"]
PropRecord = PhysicalProp
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{index}" for prefix in ("COM", "LPT") for index in range(1, 10)
}
_FORBIDDEN_NAME = set('<>:"/\\|?*')
_Choice = TypeVar("_Choice", bound=str)
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


def _assert_owned(target: Path, name: str, kind: PropKind) -> bool:
    """Validate an existing record; return whether it contains an active prop."""
    if not target.exists():
        return False
    try:
        document = tomllib.loads(target.read_text(encoding="utf-8"))
        head = _mapping(document["prop"])
        if (
            _integer(head["version"]) != _VERSION
            or head.get("kind") != kind
            or _text(head["name"]) != name
        ):
            raise PropModelError("A different or newer prop file already uses this name.")
        _flag(head, "removed")
        prop, issue = _parse(document, target)
        if issue is not None:
            raise PropModelError("An unreadable prop file already uses this name.")
        return prop is not None
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, PropModelError) as exc:
        raise PropModelError("An unreadable prop file already uses this name.") from exc


def _ladder_sections(ladder: Ladder) -> list[str]:
    """Serialize actual step clicks and their last solved 3D positions."""
    lines: list[str] = []
    pattern = ladder.pattern
    if ladder.support != "none" or pattern is not None:
        lines += _table(
            "[ladder]",
            [
                ("support", ladder.support),
                ("pattern_first", None if pattern is None else pattern.first),
                ("pattern_second", None if pattern is None else pattern.second),
                ("rung_count", None if pattern is None else pattern.count),
            ],
        )
    for step in ladder.steps:
        lines += _table(
            "[[step]]",
            [
                ("id", step.step_id),
                ("label", step.label),
                ("closed", step.closed),
                ("irregular", step.irregular or None),
            ],
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
    return lines


def _belt_sections(belt: BeltProp) -> list[str]:
    lines = _table(
        "[belt]",
        [
            ("units", belt.units),
            ("closed", belt.track.closed),
            ("travel_direction", belt.travel_direction),
            ("surface_width", belt.surface_width),
            ("surface_normal", belt.surface_normal),
        ],
    )
    for vertex in belt.track.vertices:
        lines += _table("[[belt.vertex]]", [("xyz", vertex)])
    if belt.rollers is not None:
        lines += _table(
            "[belt.rollers]",
            [
                ("first", belt.rollers.first),
                ("second", belt.rollers.second),
                ("radius", belt.rollers.radius),
                ("width", belt.rollers.width),
                ("top_normal", belt.rollers.top_normal),
            ],
        )
    for corner in belt.corners or ():
        lines += _table("[[belt.corner]]", [])
        lines += _visual_clicks("belt.corner", corner)
    if belt.side_view is not None:
        view = belt.side_view
        lines += _table(
            "[belt.side_view]",
            [
                ("camera", view.camera),
                ("frame", view.frame),
                ("hub_first", view.pixels[0]),
                ("hub_second", view.pixels[1]),
                ("top_first", view.pixels[2]),
                ("top_second", view.pixels[3]),
            ],
        )
    if belt.binding is not None:
        binding = belt.binding
        lines += _table(
            "[belt.binding]",
            [
                ("source_id", binding.source_id),
                ("channel", binding.channel),
                ("reference_frame", binding.reference_frame),
                ("reference_reading", binding.reference_reading),
                ("reference_distance", binding.reference_distance),
                ("units_per_reading", binding.units_per_reading),
            ],
        )
        lines += _motion_check_sections("belt", binding.checks)
    if belt.visual_frames:
        lines += _table("[belt.visual]", [("reference_frame", belt.visual_reference_frame)])
        for observed in belt.visual_frames:
            lines += _table(
                "[[belt.visual.frame]]", [("frame", observed.frame), ("lap", observed.lap)]
            )
            lines += _visual_clicks("belt.visual.frame", observed.point)
    return lines


def _ball_sections(ball: BallProp) -> list[str]:
    lines = _table(
        "[ball]",
        [
            ("units", ball.units),
            ("centre", ball.surface.centre),
            ("radius", ball.surface.radius),
        ],
    )
    for mark in ball.surface_marks:
        lines += _table("[[ball.surface_mark]]", [("direction", mark)])
    if ball.binding is not None:
        binding = ball.binding
        lines += _table(
            "[ball.binding]",
            [
                ("source_id", binding.source_id),
                ("channels", binding.channels),
                ("reference_frame", binding.reference_frame),
                (
                    "reference_orientation",
                    (
                        binding.reference_orientation.w,
                        binding.reference_orientation.x,
                        binding.reference_orientation.y,
                        binding.reference_orientation.z,
                    ),
                ),
                ("reference_values", binding.reference_values),
            ],
        )
        lines += _motion_check_sections("ball", binding.checks)
    if ball.visual_frames:
        lines += _table("[ball.visual]", [("reference_frame", ball.visual_reference_frame)])
        for observed in ball.visual_frames:
            lines += _table("[[ball.visual.frame]]", [("frame", observed.frame)])
            for index, visual_mark in enumerate(observed.marks):
                lines += _table("[[ball.visual.frame.mark]]", [("index", index)])
                lines += _visual_clicks("ball.visual.frame.mark", visual_mark)
    return lines


def _visual_clicks(parent: str, point: LadderPoint) -> list[str]:
    """Write only raw pixels; triangulation is derived from current calibration."""
    lines: list[str] = []
    for click in point.clicks:
        lines += _table(
            f"[[{parent}.click]]",
            [("camera", click.camera), ("frame", click.frame), ("x", click.x), ("y", click.y)],
        )
    return lines


def _motion_check_sections(kind: str, checks: tuple[MotionCheck, ...]) -> list[str]:
    lines: list[str] = []
    for check in checks:
        lines += _table(
            f"[[{kind}.binding.check]]",
            [
                ("frame", check.frame),
                ("camera", check.camera),
                ("x", check.x),
                ("y", check.y),
                ("residual_px", check.residual_px),
                ("source_values", check.source_values),
            ],
        )
    return lines


def prop_kind(prop: PropRecord) -> PropKind:
    """Return the stable sidecar kind for a typed prop record."""
    if isinstance(prop, Wheel):
        return "wheel"
    if isinstance(prop, Ladder):
        return "ladder"
    if isinstance(prop, BeltProp):
        return "belt"
    if isinstance(prop, BallProp):
        return "ball"
    raise PropModelError("This physical-prop kind cannot be saved.")


def write_prop(folder: Path | str, prop: PropRecord, *, overwrite_existing: bool = True) -> Path:
    """Atomically write one typed prop record to its generalized sidecar."""
    folder = Path(folder)
    name = prop.name
    kind = prop_kind(prop)
    target = prop_path(folder, name)
    if not target.exists() and folder.is_dir():
        for other in folder.glob(f"*{PROP_SUFFIX}"):
            if other.name.casefold() == target.name.casefold():
                raise PropModelError("A saved prop already uses this name.")
    active = _assert_owned(target, name, kind)
    if active and not overwrite_existing:
        raise PropModelError("A saved prop already uses this name; its evidence was kept.")
    folder.mkdir(parents=True, exist_ok=True)
    lines = [_HEADER]
    lines += _table(
        "[prop]",
        [
            ("version", _VERSION),
            ("kind", kind),
            ("name", name),
            ("calibration", prop.calibration if isinstance(prop, Ladder) else None),
            ("units", prop.units if isinstance(prop, Ladder) else None),
            ("removed", False),
        ],
    )
    if isinstance(prop, Ladder):
        lines += _ladder_sections(prop)
    elif isinstance(prop, BeltProp):
        lines += _belt_sections(prop)
    elif isinstance(prop, BallProp):
        lines += _ball_sections(prop)
    else:
        lines += wheel_sections(prop)
    return write_atomic(target, lines)


def write_ladder(folder: Path | str, ladder: Ladder, *, overwrite_existing: bool = True) -> Path:
    """Compatibility wrapper for writing a ladder in the generalized format."""
    return write_prop(folder, ladder, overwrite_existing=overwrite_existing)


def write_belt(folder: Path | str, belt: BeltProp, *, overwrite_existing: bool = True) -> Path:
    """Write a belt's declared fixed path and optional direction."""
    return write_prop(folder, belt, overwrite_existing=overwrite_existing)


def write_ball(folder: Path | str, ball: BallProp, *, overwrite_existing: bool = True) -> Path:
    """Write a ball's declared sphere and optional surface marks."""
    return write_prop(folder, ball, overwrite_existing=overwrite_existing)


def write_wheel(folder: Path | str, wheel: Wheel, *, overwrite_existing: bool = True) -> Path:
    """Write wheel clicks, fit, and binding in the generalized format."""
    return write_prop(folder, wheel, overwrite_existing=overwrite_existing)


def write_removed(
    folder: Path | str,
    name: str,
    *,
    kind: PropKind = "ladder",
    overwrite_existing: bool = True,
) -> Path | None:
    """Mark an existing prop removed, retaining a sidecar for undo/recovery."""
    target = prop_path(folder, name)
    if not target.exists():
        return None
    active = _assert_owned(target, name, kind)
    if active and not overwrite_existing:
        raise PropModelError("A saved prop already uses this name; its evidence was kept.")
    lines = [
        _HEADER,
        *_table(
            "[prop]",
            [("version", _VERSION), ("kind", kind), ("name", name), ("removed", True)],
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


def _pixel(value: object) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise PropModelError("A clicked pixel needs two coordinates.")
    return (_number(value[0]), _number(value[1]))


def _quaternion(value: object) -> UnitQuaternion:
    return UnitQuaternion(*_point4(value))


def _point4(value: object) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) != 4:
        raise PropModelError("A ball orientation needs four quaternion components.")
    return (_number(value[0]), _number(value[1]), _number(value[2]), _number(value[3]))


def _values(value: object) -> tuple[float, ...]:
    if not isinstance(value, list):
        raise PropModelError("Motion source readings must be a list.")
    return tuple(_number(item) for item in value)


def _motion_checks(value: object) -> tuple[MotionCheck, ...]:
    return tuple(
        MotionCheck(
            _integer(row["frame"]),
            _text(row["camera"]),
            _number(row["x"]),
            _number(row["y"]),
            _number(row["residual_px"]),
            _values(row.get("source_values", [])),
        )
        for row in _records(value)
    )


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
            irregular=_choice(row.get("irregular", ""), STEP_IRREGULARITIES),
        )
        for row in _records(document.get("step", []))
    )
    table = _mapping(document.get("ladder", {}))
    pattern = (
        RungPattern(
            _text(table["pattern_first"]),
            _text(table["pattern_second"]),
            _integer(table["rung_count"]),
        )
        if "rung_count" in table
        else None
    )
    return Ladder(
        name=_text(head["name"]),
        steps=steps,
        calibration=_text(head.get("calibration", "")),
        units=_text(head.get("units", "")),
        support=_choice(table.get("support", "none"), LADDER_SUPPORTS),
        pattern=pattern,
    )


def _choice(value: object, choices: tuple[_Choice, ...]) -> _Choice:
    """One of a closed set of stable codes; an unknown code is a damaged record."""
    for choice in choices:
        if value == choice:
            return choice
    raise PropModelError("A prop field has an unknown value.")


def _parse_belt(head: Mapping[str, Any], document: Mapping[str, Any]) -> BeltProp:
    table = _mapping(document["belt"])
    vertices = tuple(_point3(row["xyz"]) for row in _records(table.get("vertex", [])))
    direction = table.get("travel_direction")
    binding_table = table.get("binding")
    binding = None
    if binding_table is not None:
        row = _mapping(binding_table)
        binding = BeltBinding(
            _text(row["source_id"]),
            _text(row["channel"]),
            _integer(row["reference_frame"]),
            _number(row["reference_reading"]),
            _number(row["reference_distance"]),
            _number(row["units_per_reading"]),
            _motion_checks(row.get("check", [])),
        )
    visual = table.get("visual")
    visual_table = _mapping(visual) if visual is not None else None
    visual_frames = (
        tuple(
            BeltVisualFrame(
                _integer(row["frame"]),
                _parse_point({"click": row.get("click", [])}),
                None if "lap" not in row else _integer(row["lap"]),
            )
            for row in _records(visual_table.get("frame", []))
        )
        if visual_table is not None
        else ()
    )
    corners = tuple(
        _parse_point({"click": row.get("click", [])}) for row in _records(table.get("corner", []))
    )
    if len(corners) not in (0, 4):
        raise PropModelError("A belt placement needs exactly four clicked corners.")
    side_table = table.get("side_view")
    side_view = None
    if side_table is not None:
        side = _mapping(side_table)
        side_view = BeltSideView(
            _text(side["camera"]),
            _integer(side["frame"]),
            (
                _pixel(side["hub_first"]),
                _pixel(side["hub_second"]),
                _pixel(side["top_first"]),
                _pixel(side["top_second"]),
            ),
        )
    roller_table = table.get("rollers")
    rollers = (
        BeltRollers(
            _point3(roller_table["first"]),
            _point3(roller_table["second"]),
            _number(roller_table["radius"]),
            _number(roller_table["width"]),
            _point3(roller_table["top_normal"]),
        )
        if isinstance(roller_table, dict)
        else None
    )
    return BeltProp(
        name=_text(head["name"]),
        track=BeltTrack(vertices, closed=_flag(table, "closed")),
        units=_text(table.get("units", "")),
        travel_direction=None if direction is None else _point3(direction),
        binding=binding,
        visual_reference_frame=None
        if visual_table is None
        else _integer(visual_table["reference_frame"]),
        visual_frames=visual_frames,
        surface_width=None if "surface_width" not in table else _number(table["surface_width"]),
        surface_normal=None if "surface_normal" not in table else _point3(table["surface_normal"]),
        rollers=rollers,
        corners=(corners[0], corners[1], corners[2], corners[3]) if corners else None,
        side_view=side_view,
    )


def _parse_ball(head: Mapping[str, Any], document: Mapping[str, Any]) -> BallProp:
    table = _mapping(document["ball"])
    marks = tuple(_point3(row["direction"]) for row in _records(table.get("surface_mark", [])))
    binding_table = table.get("binding")
    binding = None
    if binding_table is not None:
        row = _mapping(binding_table)
        channels = row["channels"]
        if not isinstance(channels, list) or len(channels) != 4:
            raise PropModelError("A ball orientation needs four channel names.")
        binding = BallBinding(
            _text(row["source_id"]),
            (_text(channels[0]), _text(channels[1]), _text(channels[2]), _text(channels[3])),
            _integer(row["reference_frame"]),
            _quaternion(row["reference_orientation"]),
            _motion_checks(row.get("check", [])),
            None if "reference_values" not in row else _point4(row["reference_values"]),
        )
    visual = table.get("visual")
    visual_table = _mapping(visual) if visual is not None else None
    visual_frames: tuple[BallVisualFrame, ...] = ()
    if visual_table is not None:
        parsed: list[BallVisualFrame] = []
        for row in _records(visual_table.get("frame", [])):
            mark_rows = _records(row.get("mark", []))
            if len(mark_rows) != 3 or {_integer(mark["index"]) for mark in mark_rows} != {0, 1, 2}:
                raise PropModelError("Ball visual frames need three named marks.")
            by_index = {_integer(mark["index"]): mark for mark in mark_rows}
            parsed.append(
                BallVisualFrame(
                    _integer(row["frame"]),
                    (
                        _parse_point({"click": by_index[0].get("click", [])}),
                        _parse_point({"click": by_index[1].get("click", [])}),
                        _parse_point({"click": by_index[2].get("click", [])}),
                    ),
                )
            )
        visual_frames = tuple(parsed)
    return BallProp(
        name=_text(head["name"]),
        surface=BallSurface(_point3(table["centre"]), _number(table["radius"])),
        units=_text(table.get("units", "")),
        surface_marks=marks,
        binding=binding,
        visual_reference_frame=None
        if visual_table is None
        else _integer(visual_table["reference_frame"]),
        visual_frames=visual_frames,
    )


def _parse(
    document: Mapping[str, Any], path: Path
) -> tuple[PropRecord | None, PropFileIssue | None]:
    head = _mapping(document["prop"])
    version = _integer(head["version"])
    if version != _VERSION:
        return None, PropFileIssue(path.name, "unsupported_version", str(version))
    if _flag(head, "removed"):
        return None, None
    kind = head.get("kind")
    if kind not in ("ladder", "wheel", "belt", "ball"):
        return None, PropFileIssue(path.name, "unsupported_kind", str(kind))
    prop: PropRecord
    if kind == "ladder":
        prop = _parse_ladder(head, document)
    elif kind == "wheel":
        wheel = parse_wheel_document(document)
        if wheel is None:
            return None, PropFileIssue(path.name, "damaged")
        prop = wheel
    elif kind == "belt":
        prop = _parse_belt(head, document)
    else:
        prop = _parse_ball(head, document)
    if prop.name != _text(head["name"]) or prop_path(path.parent, prop.name) != path:
        return None, PropFileIssue(path.name, "name_mismatch", prop.name)
    return prop, None


def read_prop_records(
    folder: Path | str,
) -> tuple[list[PropRecord], list[PropFileIssue], set[str]]:
    """Read generalized records, issues, and names hidden by removal tombstones."""
    props: list[PropRecord] = []
    issues: list[PropFileIssue] = []
    tombstones: set[str] = set()
    seen_names: set[str] = set()
    folder = Path(folder)
    if not folder.is_dir():
        return props, issues, tombstones
    for path in sorted(folder.glob(f"*{PROP_SUFFIX}")):
        try:
            document = tomllib.loads(path.read_text(encoding="utf-8"))
            head = _mapping(document["prop"])
            if (
                _integer(head["version"]) == _VERSION
                and head.get("kind") in ("ladder", "wheel", "belt", "ball")
                and _flag(head, "removed")
            ):
                name = _text(head["name"])
                if prop_path(path.parent, name) != path:
                    issues.append(PropFileIssue(path.name, "name_mismatch", name))
                    continue
                tombstones.add(name)
                continue
            prop, issue = _parse(document, path)
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
            folded_name = prop.name.casefold()
            if folded_name in seen_names:
                issues.append(PropFileIssue(path.name, "name_mismatch", prop.name))
                continue
            seen_names.add(folded_name)
            props.append(prop)
    return props, issues, tombstones


def read_props(folder: Path | str) -> tuple[list[PropRecord], list[PropFileIssue]]:
    """Read every supported prop while reporting damaged and future records."""
    props, issues, _tombstones = read_prop_records(folder)
    return props, issues
