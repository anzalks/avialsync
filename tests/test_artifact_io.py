"""Publication preserves old files and never writes onto imported sources."""

from __future__ import annotations

from pathlib import Path

import pytest

from avialsync.core.artifact_io import publish, publish_dir
from avialsync.core.artifact_provenance import companion_path, record, write_companion
from avialsync.core.errors import ExportError


def test_publish_replaces_complete_file_and_cleans_stage(tmp_path: Path) -> None:
    target = tmp_path / "slice.csv"
    target.write_text("old", encoding="utf-8")
    seen: list[Path] = []

    def write(path: Path) -> None:
        seen.append(path)
        assert path.parent == target.parent
        assert path.suffix == ".csv"
        assert target.read_text(encoding="utf-8") == "old"
        path.write_text("new", encoding="utf-8")

    assert publish(target, write, kind="data-slice-csv") == target
    assert target.read_text(encoding="utf-8") == "new"
    assert not seen[0].exists()


def test_failed_publish_keeps_old_file_and_removes_stage(tmp_path: Path) -> None:
    target = tmp_path / "slice.csv"
    target.write_text("old", encoding="utf-8")

    def fail(path: Path) -> None:
        path.write_text("partial", encoding="utf-8")
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        publish(target, fail, kind="data-slice-csv")
    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("name", ["CON.csv", "bad:name.csv", "trailing. "])
def test_rejects_nonportable_name(tmp_path: Path, name: str) -> None:
    with pytest.raises(ExportError):
        publish(tmp_path / name, lambda path: path.write_text("x"), kind="annotations")


def test_rejects_loaded_source_and_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.csv"
    source.write_text("original", encoding="utf-8")
    with pytest.raises(ExportError, match="loaded source"):
        publish(source, lambda path: path.write_text("x"), kind="corrected-pose", sources=[source])
    assert source.read_text(encoding="utf-8") == "original"

    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setenv("AVIALSYNC_CACHE_DIR", str(cache))
    with pytest.raises(ExportError, match="cache"):
        publish(cache / "bad.csv", lambda path: path.write_text("x"), kind="annotations")


def test_publish_dir_cleans_failed_tree(tmp_path: Path) -> None:
    target = tmp_path / "labeled-data"

    def fail(path: Path) -> None:
        (path / "frame.png").write_bytes(b"partial")
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        publish_dir(target, fail, kind="dlc-retraining")
    assert list(tmp_path.iterdir()) == []


def test_publish_dir_commits_complete_tree(tmp_path: Path) -> None:
    target = tmp_path / "labeled-data"
    publish_dir(
        target,
        lambda stage: (stage / "frame.png").write_bytes(b"complete"),
        kind="dlc-retraining",
    )
    assert (target / "frame.png").read_bytes() == b"complete"


def test_companion_has_versioned_provenance(tmp_path: Path) -> None:
    source = tmp_path / "camera.mp4"
    source.write_bytes(b"frames")
    target = tmp_path / "pose.csv"
    payload = record(
        "corrected-pose",
        (source,),
        session=tmp_path / "trial.avv",
        time_maps={"camera.mp4": {"offset_seconds": 0.2, "drift_ms_per_hour": 1.5}},
        edit_counts={"corrected_points": 3},
    )
    companion = write_companion(target, payload)
    assert companion == companion_path(target)
    assert payload["format"] == "avialsync-corrected-pose/1"
    assert payload["sources"] == [{"name": "camera.mp4", "size_bytes": 6}]
    assert payload["written"].endswith("Z")
    assert payload["time_maps"]["camera.mp4"]["drift_ms_per_hour"] == 1.5
    assert '"corrected_points": 3' in companion.read_text(encoding="utf-8")


def test_companion_cannot_replace_a_loaded_source(tmp_path: Path) -> None:
    target = tmp_path / "pose.csv"
    source = companion_path(target)
    source.write_text("original", encoding="utf-8")
    with pytest.raises(ExportError, match="loaded source"):
        write_companion(target, record("corrected-pose"), sources=(source,))
    assert source.read_text(encoding="utf-8") == "original"


def _refuse_first(monkeypatch, module, name: str, times: int) -> list[int]:
    """Make ``module.name`` raise Windows's momentary refusal *times* times."""
    real = getattr(module, name)
    calls: list[int] = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) <= times:
            raise PermissionError(13, "in use by a scanner")
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, flaky)
    return calls


def test_a_momentary_refusal_to_replace_is_waited_out(tmp_path: Path, monkeypatch) -> None:
    import avialsync.core.artifact_io as artifact_io

    monkeypatch.setattr(artifact_io, "_RETRY_DELAYS", (0.0, 0.0))
    target = tmp_path / "slice.csv"
    target.write_text("old", encoding="utf-8")
    calls = _refuse_first(monkeypatch, artifact_io.os, "replace", 1)

    publish(target, lambda path: path.write_text("new", encoding="utf-8"), kind="data-slice-csv")

    assert target.read_text(encoding="utf-8") == "new"
    assert len(calls) == 2


def test_a_lasting_refusal_is_reported_and_keeps_the_old_file(tmp_path: Path, monkeypatch) -> None:
    import avialsync.core.artifact_io as artifact_io

    monkeypatch.setattr(artifact_io, "_RETRY_DELAYS", (0.0, 0.0))
    target = tmp_path / "slice.csv"
    target.write_text("old", encoding="utf-8")
    calls = _refuse_first(monkeypatch, artifact_io.os, "replace", 99)

    with pytest.raises(ExportError, match="in use"):
        publish(
            target, lambda path: path.write_text("new", encoding="utf-8"), kind="data-slice-csv"
        )

    assert target.read_text(encoding="utf-8") == "old"
    assert len(calls) == 3
    assert sorted(path.name for path in tmp_path.iterdir()) == ["slice.csv"]


def test_a_reader_racing_a_replacement_waits_for_it(tmp_path: Path, monkeypatch) -> None:
    import avialsync.core.artifact_io as artifact_io

    monkeypatch.setattr(artifact_io, "_RETRY_DELAYS", (0.0,))
    target = tmp_path / "markers.csv"
    target.write_text("rung", encoding="utf-8")
    calls = _refuse_first(monkeypatch, Path, "read_text", 1)

    assert artifact_io.read_text(target) == "rung"
    assert len(calls) == 2
