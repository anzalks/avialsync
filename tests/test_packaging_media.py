"""Tests for release media staging without requiring platform media packages."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _media_stager():
    path = Path("packaging/fetch_media_libs.py")
    spec = importlib.util.spec_from_file_location("fetch_media_libs", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_media_staging_copies_only_runtime_media_files(tmp_path: Path) -> None:
    """The release bundle receives media runtimes, not arbitrary package-manager files."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "libmpv.dylib").write_bytes(b"mpv")
    (source / "ffmpeg").write_bytes(b"ffmpeg")
    (source / "unrelated.txt").write_text("ignore", encoding="utf-8")
    destination = tmp_path / "media"

    staged = _media_stager().stage_media_files([source], destination)

    assert [path.name for path in staged] == ["ffmpeg", "libmpv.dylib"]
    assert not (destination / "unrelated.txt").exists()
