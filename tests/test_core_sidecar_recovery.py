"""Damaged optional sidecars preserve every readable observation and never abort a load."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from avialsync.core import custom_markers, identity_sidecar, point_edit_sidecar
from avialsync.core.custom_markers import CustomMarker, CustomMarkerStore
from avialsync.core.identity_swaps import SwapEvent
from avialsync.core.point_edit_sidecar import Correction


@pytest.mark.parametrize("module", [identity_sidecar, point_edit_sidecar])
def test_unreadable_encoding_is_an_optional_sidecar_failure(tmp_path: Path, module) -> None:
    source = tmp_path / "pose.csv"
    module.sidecar_path(source).write_bytes(b"\xff\xfe\xff\xfe")
    assert module.read(source) is None


@pytest.mark.parametrize("module", [identity_sidecar, point_edit_sidecar])
def test_permission_failure_is_reported_without_losing_the_source(
    tmp_path: Path, monkeypatch, module
) -> None:
    def inaccessible(_path: Path) -> str:
        raise PermissionError("read-only recording")

    monkeypatch.setattr(module, "read_text", inaccessible)
    assert module.read(tmp_path / "pose.csv") is None


@pytest.mark.parametrize("groups", ["not JSON", "{}", json.dumps([None, {"members": None}])])
def test_bad_group_metadata_does_not_discard_readable_swaps(tmp_path: Path, groups: str) -> None:
    source = tmp_path / "pose.csv"
    identity_sidecar.sidecar_path(source).write_text(
        f"# unstructured comment\n# source_bytes: invalid\n# groups: {groups}\n"
        "frame,group,lane_a,lane_b,parts\n2,animals,a,b,*\n",
        encoding="utf-8",
    )
    result = identity_sidecar.read(source)
    assert result is not None and result.events == [SwapEvent(2, "animals", ("a", "b"))]
    assert result.groups == [] and result.source_bytes is None


def test_bad_correction_size_metadata_preserves_valid_rows(tmp_path: Path) -> None:
    source = tmp_path / "pose.csv"
    point_edit_sidecar.sidecar_path(source).write_text(
        "# source_bytes: invalid\nframe,bodypart,x,y\n2,head,1.0,2.0\n",
        encoding="utf-8",
    )
    result = point_edit_sidecar.read(source)
    assert result is not None and result.source_bytes is None
    assert result.entries == [Correction(2, "head", 1.0, 2.0, "head")]


def test_writing_for_an_unavailable_source_does_not_invent_size(tmp_path: Path) -> None:
    source = tmp_path / "missing.csv"
    swaps = identity_sidecar.write(source, [SwapEvent(2, "animals", ("a", "b"))])
    fixes = point_edit_sidecar.write(source, [Correction(2, "head", 1.0, 2.0)])
    assert "source_bytes" not in swaps.read_text()
    assert "source_bytes" not in fixes.read_text()


@pytest.mark.parametrize("reader", [custom_markers.read_2d, custom_markers.read_3d])
def test_custom_marker_missing_or_unreadable_files_are_optional(
    tmp_path: Path, monkeypatch, reader
) -> None:
    assert reader(tmp_path / "missing.csv") == {}

    def inaccessible(_path: Path) -> str:
        raise PermissionError("read-only recording")

    monkeypatch.setattr(custom_markers, "read_text", inaccessible)
    assert reader(tmp_path / "markers.csv") == {}


def test_two_dimensional_marker_reader_keeps_readable_rows_after_bad_frames(tmp_path: Path) -> None:
    path = tmp_path / "markers.csv"
    path.write_text(
        "scorer,marker,marker,other\nbodyparts,head,head,tail\ncoords,x,y,x\n"
        "bad,1,2,3\ninf,1,2,3\n1,bad,2,3\n2,1\n3,1,2,3\n",
        encoding="utf-8",
    )
    assert custom_markers.read_2d(path) == {("head", 3): (1.0, 2.0)}
    path.write_text("too short\n", encoding="utf-8")
    assert custom_markers.read_2d(path) == {}


def test_three_dimensional_marker_reader_keeps_readable_rows_after_bad_frames(
    tmp_path: Path,
) -> None:
    path = tmp_path / "markers.csv"
    path.write_text(
        "head_x,head_y,head_z,head_error,fnum\n"
        "1,2,3,0,bad\n1,2,3,0,inf\nbad,2,3,0,1\n1,2,3,bad,2\n1,2,3,,3\n",
        encoding="utf-8",
    )
    assert custom_markers.read_3d(path) == {
        ("head", 2): ((1.0, 2.0, 3.0), None),
        ("head", 3): ((1.0, 2.0, 3.0), None),
    }


def test_custom_marker_observer_disposal_and_sparse_export(tmp_path: Path) -> None:
    store = CustomMarkerStore()
    changes: list = []
    dispose = store.observe(changes.append)
    dispose()
    dispose()
    # Each frame has only one landmark; the other's cells must stay empty.
    markers = [CustomMarker("a", 0, xyz=(1.0, 2.0, 3.0)), CustomMarker("b", 1, xyz=(4.0, 5.0, 6.0))]
    output = custom_markers.write_3d(tmp_path / "out.csv", markers)
    restored = custom_markers.read_3d(output)
    assert set(restored) == {("a", 0), ("b", 1)}
    assert changes == []
