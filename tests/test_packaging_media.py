"""Tests for release media staging without requiring platform media packages."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from PIL import Image


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


def test_appimage_declares_and_stages_its_desktop_icon() -> None:
    """AppImageTool receives the icon named by the desktop entry."""
    script = Path("packaging/linux/make_appimage.sh")
    icon = Path("packaging/linux/avialview.png")

    content = script.read_text(encoding="utf-8")

    assert "Icon=avialview" in content
    assert '"$script_dir/avialview.png" "$appdir/avialview.png"' in content
    assert icon.is_file()


def test_native_packagers_use_the_generated_icons() -> None:
    """Windows and PyInstaller use the platform-specific generated icon files."""
    spec = Path("packaging/avialview.spec").read_text(encoding="utf-8")
    installer = Path("packaging/windows/avialview.iss").read_text(encoding="utf-8")

    assert "icon=str(application_icon)" in spec
    assert "SetupIconFile=avialview.ico" in installer


def test_icon_generator_writes_all_platform_formats(tmp_path: Path) -> None:
    """The checked-in source deterministically produces every packaged icon."""
    source = Path("assets/icons/avialview-source.png")

    subprocess.run(
        [
            sys.executable,
            "tools/generate_icons.py",
            "--source",
            str(source),
            "--output-root",
            str(tmp_path),
        ],
        check=True,
    )

    expected = (
        tmp_path / "src/avialview/resources/avialview.png",
        tmp_path / "packaging/linux/avialview.png",
        tmp_path / "packaging/windows/avialview.ico",
        tmp_path / "packaging/macos/avialview.icns",
    )
    for path in expected:
        assert path.is_file()
    with Image.open(expected[0]) as runtime_icon:
        assert runtime_icon.size == (512, 512)
