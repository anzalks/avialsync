"""Publication handles collisions and permission failures without replacing old user data."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from avialsync.core import artifact_io
from avialsync.core.artifacts import get_kind
from avialsync.core.errors import ExportError


def test_explicit_kind_and_legacy_source_stem_are_supported(tmp_path: Path) -> None:
    kind = get_kind("pointfix")
    assert get_kind(kind) is kind
    with pytest.raises(ValueError, match="user-selected"):
        get_kind("annotations").target_for(tmp_path / "source.csv")
    legacy = dataclasses.replace(kind, source_stem=True)
    assert legacy.target_for(tmp_path / "source.csv").name == "source" + kind.sidecar_suffix


def test_refused_existing_artifact_is_preserved(tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    with pytest.raises(ExportError, match="already exists"):
        artifact_io.publish_dir(target, lambda path: None, kind="dlc-retraining")


def test_permission_failure_keeps_previous_file_and_cleans_stage(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "output.csv"
    target.write_text("old", encoding="utf-8")

    def denied(*args) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(artifact_io, "_retrying", denied)
    with pytest.raises(ExportError, match="in use"):
        artifact_io.publish(target, lambda path: path.write_text("new"), kind="data-slice-csv")
    assert target.read_text() == "old" and list(tmp_path.iterdir()) == [target]


def test_directory_collision_created_during_write_is_preserved(tmp_path: Path) -> None:
    target = tmp_path / "dataset"

    def race(stage: Path) -> None:
        (stage / "partial").write_text("our staged data")
        target.mkdir()
        (target / "keep").write_text("another writer")

    with pytest.raises(ExportError, match="already exists"):
        artifact_io.publish_dir(target, race, kind="dlc-retraining")
    assert (target / "keep").read_text() == "another writer"
    assert list(tmp_path.iterdir()) == [target]


def test_directory_permission_failure_cleans_only_its_own_stage(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "dataset"

    def denied(*args) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(artifact_io, "_retrying", denied)
    with pytest.raises(ExportError, match="in use"):
        artifact_io.publish_dir(
            target, lambda stage: (stage / "partial").write_text("data"), kind="dlc-retraining"
        )
    assert list(tmp_path.iterdir()) == []


def test_directory_sync_has_a_portable_non_posix_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(artifact_io, "os", SimpleNamespace(name="nt"))
    artifact_io._sync_directory(tmp_path)
