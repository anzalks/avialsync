"""Current prop records carry projection context and portable source references."""

from __future__ import annotations

import dataclasses
import shutil
import tomllib
from pathlib import Path

import numpy as np
import pytest

from avialsync.core.calibration import ImageCorrection
from avialsync.core.physical_props import (
    BallBinding,
    BallProp,
    BallSurface,
    BeltBinding,
    BeltProp,
    BeltTrack,
    Ladder,
)
from avialsync.core.prop_context import PropCamera, PropContext
from avialsync.core.prop_file import PROP_VERSION, read_props, write_prop
from avialsync.core.wheel import EncoderBinding, Wheel, WheelFit, WheelSpec
from tests.wheel_fixture import CAMERAS, TRUTH, clicks_for


def saved_wheel(folder: Path, *, binding: bool = False, frame: int = 0) -> Wheel:
    """A generated wheel whose cameras and encoder live in one portable recording."""
    correction = ImageCorrection(((1.0, 0.0, 4.0), (0.0, 1.0, -3.0), (0.0, 0.0, 1.0)))
    cameras = tuple(
        PropCamera.capture(
            str(folder / f"{name}.mp4"), dataclasses.replace(camera, correction=correction)
        )
        for name, camera in CAMERAS.items()
    )
    return Wheel(
        WheelSpec("wheel", 36),
        frame,
        clicks_for([0, 1]),
        WheelFit(TRUTH, (0, 1), (), (), ()),
        binding=EncoderBinding(str(folder / "encoder.csv"), "angle", 10.0) if binding else None,
        calibration=str(folder / "unavailable-calibration.toml"),
        context=PropContext(cameras, "Front", frame / 30),
    )


def test_current_record_carries_effective_camera_projection_without_external_files(
    tmp_path: Path,
) -> None:
    wheel = saved_wheel(tmp_path)
    target = write_prop(tmp_path / "pose-3d", wheel)
    record = tomllib.loads(target.read_text())
    assert record["prop"]["version"] == PROP_VERSION
    assert len(record["context"]["camera"]) == 3
    assert record["context"]["camera"][0]["source_relative"]
    loaded, issues = read_props(target.parent)
    assert not issues and loaded == [wheel]
    assert not Path(wheel.calibration).exists()
    points = TRUTH.bar_ends().reshape(-1, 3)
    for before, after in zip(wheel.context.cameras, loaded[0].context.cameras, strict=True):
        assert after.model.project(points) == pytest.approx(before.model.project(points))
        assert after.model is after.model
        assert not after.model.matrix.flags.writeable
        assert not after.model.rotation.flags.writeable


@pytest.mark.parametrize("kind", ["wheel", "belt", "ball"])
def test_recording_move_resolves_sensor_and_camera_sources_from_the_toml(
    tmp_path: Path, kind: str
) -> None:
    old = tmp_path / "old"
    wheel = saved_wheel(old, binding=True)
    source = str(old / "encoder.csv")
    if kind == "wheel":
        record = wheel
    elif kind == "belt":
        record = BeltProp(
            "belt",
            BeltTrack(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))),
            travel_direction=(1.0, 0.0, 0.0),
            binding=BeltBinding(source, "angle", 0, 0.0, 0.0, 1.0),
            context=wheel.context,
        )
    else:
        from avialsync.core.physical_props import UnitQuaternion

        record = BallProp(
            "ball",
            BallSurface((0.0, 0.0, 0.0), 1.0),
            surface_marks=((1.0, 0.0, 0.0),),
            binding=BallBinding(source, ("w", "x", "y", "z"), 0, UnitQuaternion.identity()),
            context=wheel.context,
        )
    write_prop(old / "pose-3d", record)
    moved = tmp_path / "moved"
    shutil.move(str(old), moved)
    loaded, issues = read_props(moved / "pose-3d")
    assert not issues
    assert loaded[0].binding.source_id == str(moved / "encoder.csv")
    assert loaded[0].context.cameras[0].source == str(moved / "Front.mp4")


@pytest.mark.parametrize("version", [1, 2, PROP_VERSION + 1])
def test_only_the_current_format_is_loaded_and_unsupported_files_stay_unchanged(
    tmp_path: Path, version: int
) -> None:
    path = write_prop(tmp_path, Ladder("old"))
    text = path.read_text().replace(f"version = {PROP_VERSION}", f"version = {version}", 1)
    path.write_text(text)
    records, issues = read_props(tmp_path)
    assert not records and issues[0].reason == "unsupported_version"
    assert path.read_text() == text


def test_bad_context_is_reported_without_hiding_a_readable_prop(tmp_path: Path) -> None:
    path = write_prop(tmp_path, saved_wheel(tmp_path))
    text = path.read_text().replace('reference_camera = "Front"', 'reference_camera = "missing"')
    path.write_text(text)
    write_prop(tmp_path, Ladder("good"))
    records, issues = read_props(tmp_path)
    assert records == [Ladder("good")]
    assert [(issue.filename, issue.reason) for issue in issues] == [(path.name, "damaged")]


def test_context_preserves_non_linear_camera_corrections(tmp_path: Path) -> None:
    wheel = saved_wheel(tmp_path)
    correction = ImageCorrection(
        ((1.0, 0.0, 2.0), (0.0, 1.0, 1.0), (0.0, 0.0, 1.0)),
        ((0.0, 0.0), (100.0, 0.0), (0.0, 100.0), (100.0, 100.0)),
        ((0.0, 1.0), (1.0, 0.0), (0.0, -1.0), (-1.0, 0.0)),
        0.1,
        100.0,
        (1280, 1024),
    )
    camera = dataclasses.replace(wheel.context.cameras[0], correction=correction)
    wheel = dataclasses.replace(wheel, context=PropContext((camera,), "Front", 0.0))
    write_prop(tmp_path, wheel)
    records, issues = read_props(tmp_path)
    assert not issues
    points = np.array([[1.0, 2.0, 10.0]])
    assert records[0].context.cameras[0].model.project(points) == pytest.approx(
        camera.model.project(points)
    )


@pytest.mark.parametrize(
    "change",
    [
        {"reference_time": True},
        {"reference_time": "0.0"},
        {"reference_time": float("nan")},
        {"reference_camera": "absent"},
    ],
)
def test_context_rejects_invalid_reference_values(tmp_path: Path, change) -> None:
    from avialsync.core.errors import PropModelError
    from avialsync.core.prop_context import parse_context

    path = write_prop(tmp_path, saved_wheel(tmp_path))
    data = tomllib.loads(path.read_text())
    data["context"].update(change)
    with pytest.raises(PropModelError):
        parse_context(data, tmp_path)


def _camera_row(data: dict) -> dict:
    return data["context"]["camera"][0]


@pytest.mark.parametrize(
    "corrupt",
    [
        pytest.param(lambda d: d.update(context=5), id="context-not-a-table"),
        pytest.param(lambda d: d["context"].update(camera=[5]), id="camera-not-a-table"),
        pytest.param(lambda d: d["context"].update(reference_camera=5), id="reference-not-a-name"),
        pytest.param(lambda d: _camera_row(d).update(source=5), id="source-not-a-string"),
        pytest.param(lambda d: _camera_row(d).update(distortions="0"), id="coefficients-not-array"),
        pytest.param(
            lambda d: _camera_row(d).update(distortions=[float("nan")]), id="coefficient-not-finite"
        ),
        pytest.param(lambda d: _camera_row(d).update(matrix="eye"), id="matrix-not-array"),
        pytest.param(lambda d: _camera_row(d).update(size=[1.5, 2]), id="size-not-integer"),
        pytest.param(lambda d: _camera_row(d).update(size=[0, 360]), id="size-not-positive"),
        pytest.param(lambda d: _camera_row(d).update(correction=5), id="correction-not-a-table"),
        pytest.param(
            lambda d: _camera_row(d)["correction"].update(affine=[[0, 0, 0], [0, 0, 0], [0, 0, 1]]),
            id="correction-singular",
        ),
        pytest.param(
            lambda d: _camera_row(d).update(matrix=[[0, 0, 0], [0, 1, 0], [0, 0, 1]]),
            id="projection-without-focal-length",
        ),
    ],
)
def test_a_damaged_context_is_refused_rather_than_projected(tmp_path: Path, corrupt) -> None:
    """Each malformed field is named and refused before any geometry is drawn through it."""
    from avialsync.core.errors import PropModelError
    from avialsync.core.prop_context import parse_context

    path = write_prop(tmp_path, saved_wheel(tmp_path))
    data = tomllib.loads(path.read_text())
    corrupt(data)
    with pytest.raises(PropModelError):
        parse_context(data, tmp_path)


def test_context_identities_and_reference_time_are_checked_on_construction(
    tmp_path: Path,
) -> None:
    from avialsync.core.errors import PropModelError

    camera = saved_wheel(tmp_path).context.cameras[0]
    with pytest.raises(PropModelError, match="unique"):
        PropContext((camera, camera))
    with pytest.raises(PropModelError, match="finite"):
        PropContext((camera,), camera.name, float("inf"))


def test_a_source_on_another_drive_keeps_its_absolute_path(tmp_path: Path, monkeypatch) -> None:
    """Windows has no relative path between drives; the dependency stays named, not guessed."""
    from avialsync.core import prop_context

    def no_common_root(_path: str, _start: object) -> str:
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    monkeypatch.setattr(prop_context.os.path, "relpath", no_common_root)
    source = str(tmp_path / "camera.mp4")
    assert prop_context.source_fields("source", source, tmp_path / "pose-3d") == [
        ("source", source),
        ("source_relative", False),
    ]
