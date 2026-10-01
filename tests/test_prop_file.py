"""Versioned physical-prop sidecars keep raw ladder evidence and isolate damage."""

from __future__ import annotations

import numpy as np
import pytest

from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import Ladder, LadderPoint, LadderStep, StepClick
from avialsync.core.prop_file import (
    PROP_SUFFIX,
    is_prop_path,
    prop_path,
    read_props,
    write_ladder,
    write_removed,
)
from avialsync.core.registry import LoaderRegistry
from tests.wheel_fixture import CAMERAS


def _point(world: tuple[float, float, float], cameras: tuple[str, ...]) -> LadderPoint:
    point = LadderPoint()
    for index, name in enumerate(cameras):
        x, y = CAMERAS[name].project(np.asarray(world))[0]
        point = point.with_click(StepClick(name, 20 + index, float(x), float(y)))
    return point.resolved(CAMERAS)


def _ladder() -> Ladder:
    return Ladder(
        "horizontal ladder",
        (
            LadderStep("first", 'Step "one"\nraised', (_point((-50, 0, 60), ("Front", "Left")),)),
            LadderStep(
                "second",
                "Uneven rung",
                (
                    _point((11, -15, 77), ("Front", "Right")),
                    _point((24, 16, 79), ("Front",)),
                ),
            ),
        ),
        calibration="calibration.toml",
        units="mm",
    )


def test_ladder_sidecar_round_trips_clicks_order_and_fit_without_calibration(tmp_path) -> None:
    ladder = _ladder()
    target = write_ladder(tmp_path, ladder)
    assert target == tmp_path / f"horizontal ladder{PROP_SUFFIX}"
    assert target.exists()
    loaded, issues = read_props(tmp_path)
    assert issues == []
    assert loaded == [ladder]
    assert loaded[0].steps[0].points[0].xyz is not None
    assert loaded[0].steps[1].points[1].xyz is None
    assert len(loaded[0].steps[1].points[1].clicks) == 1


def test_removal_keeps_a_tombstone_and_rewriting_restores_the_prop(tmp_path) -> None:
    ladder = _ladder()
    target = write_ladder(tmp_path, ladder)
    assert write_removed(tmp_path, ladder.name) == target
    assert target.exists()
    assert read_props(tmp_path) == ([], [])
    write_ladder(tmp_path, ladder)
    assert read_props(tmp_path) == ([ladder], [])


def test_unadopted_sidecar_cannot_be_replaced_but_its_tombstone_can_be_reused(tmp_path) -> None:
    ladder = _ladder()
    target = write_ladder(tmp_path, ladder)
    original = target.read_bytes()
    with pytest.raises(PropModelError, match="already uses this name"):
        write_ladder(tmp_path, Ladder(ladder.name), overwrite_existing=False)
    with pytest.raises(PropModelError, match="already uses this name"):
        write_removed(tmp_path, ladder.name, overwrite_existing=False)
    assert target.read_bytes() == original
    write_removed(tmp_path, ladder.name)
    write_ladder(tmp_path, ladder, overwrite_existing=False)
    assert read_props(tmp_path) == ([ladder], [])


def test_removing_a_prop_that_was_never_saved_writes_nothing(tmp_path) -> None:
    assert write_removed(tmp_path, "absent") is None
    assert list(tmp_path.iterdir()) == []


def test_future_version_and_kind_are_reported_without_hiding_good_props(tmp_path) -> None:
    good = _ladder()
    write_ladder(tmp_path, good)
    (tmp_path / f"future{PROP_SUFFIX}").write_text(
        '[prop]\nversion = 2\nkind = "ladder"\nname = "future"\n', encoding="utf-8"
    )
    (tmp_path / f"ball{PROP_SUFFIX}").write_text(
        '[prop]\nversion = 1\nkind = "ball"\nname = "ball"\n', encoding="utf-8"
    )
    props, issues = read_props(tmp_path)
    assert props == [good]
    assert {issue.filename for issue in issues} == {"future.prop.toml", "ball.prop.toml"}
    assert {issue.reason for issue in issues} == {"unsupported_version", "unsupported_kind"}


def test_writing_a_ladder_never_overwrites_an_unknown_kind(tmp_path) -> None:
    target = prop_path(tmp_path, "horizontal ladder")
    future = '[prop]\nversion = 1\nkind = "ball"\nname = "horizontal ladder"\n'
    target.write_text(future, encoding="utf-8")
    with pytest.raises(PropModelError):
        write_ladder(tmp_path, _ladder())
    with pytest.raises(PropModelError):
        write_removed(tmp_path, "horizontal ladder")
    assert target.read_text(encoding="utf-8") == future


def test_writing_a_ladder_never_overwrites_damaged_evidence(tmp_path) -> None:
    ladder = _ladder()
    target = write_ladder(tmp_path, ladder)
    damaged = target.read_text(encoding="utf-8").replace("frame = 20", 'frame = "twenty"', 1)
    target.write_text(damaged, encoding="utf-8")
    with pytest.raises(PropModelError):
        write_ladder(tmp_path, ladder)
    assert target.read_text(encoding="utf-8") == damaged


def test_one_corrupt_file_costs_only_that_prop(tmp_path) -> None:
    good = _ladder()
    write_ladder(tmp_path, good)
    (tmp_path / f"broken{PROP_SUFFIX}").write_text("[prop\n", encoding="utf-8")
    props, issues = read_props(tmp_path)
    assert props == [good]
    assert len(issues) == 1 and issues[0].filename == "broken.prop.toml"


@pytest.mark.parametrize(
    "bad_field",
    ['removed = "false"', "removed = 1", "version = 1.5"],
)
def test_typed_sidecar_fields_do_not_silently_change_evidence(tmp_path, bad_field: str) -> None:
    good = _ladder()
    write_ladder(tmp_path, good)
    (tmp_path / f"bad{PROP_SUFFIX}").write_text(
        f'[prop]\nversion = 1\nkind = "ladder"\nname = "bad"\n{bad_field}\n',
        encoding="utf-8",
    )
    props, issues = read_props(tmp_path)
    assert props == [good]
    assert len(issues) == 1 and issues[0].filename == "bad.prop.toml"


def test_a_filename_mismatch_is_reported_not_silently_adopted(tmp_path) -> None:
    target = write_ladder(tmp_path, _ladder())
    target.rename(tmp_path / f"another{PROP_SUFFIX}")
    props, issues = read_props(tmp_path)
    assert props == []
    assert len(issues) == 1 and issues[0].reason == "name_mismatch"


@pytest.mark.parametrize("name", ["../escape", "CON", "bad:windows", "trailing ", ""])
def test_prop_filename_is_safe_on_all_platforms(tmp_path, name: str) -> None:
    with pytest.raises(PropModelError):
        prop_path(tmp_path, name)


def test_prop_sidecars_are_not_sources_or_wheel_files(tmp_path) -> None:
    target = write_ladder(tmp_path, _ladder())
    assert is_prop_path(target)
    assert not is_prop_path(tmp_path / "existing.wheel.toml")
    assert LoaderRegistry().find_best_loader(target) is None
