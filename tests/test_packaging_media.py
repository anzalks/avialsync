"""Tests for release media staging without requiring platform media packages."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
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
    (source / "ffprobe").write_bytes(b"ffprobe")
    (source / "unrelated.txt").write_text("ignore", encoding="utf-8")
    destination = tmp_path / "media"

    staged = _media_stager().stage_media_files([source], destination)

    assert [path.name for path in staged] == ["ffmpeg", "ffprobe", "libmpv.dylib"]
    assert not (destination / "unrelated.txt").exists()


def test_media_staging_rejects_a_runtime_without_ffprobe(tmp_path: Path) -> None:
    """A release cannot ship video playback without metadata probing."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "libmpv.dylib").write_bytes(b"mpv")
    (source / "ffmpeg").write_bytes(b"ffmpeg")

    with pytest.raises(RuntimeError, match="ffprobe"):
        _media_stager().stage_media_files([source], tmp_path / "media")


def test_windows_media_staging_keeps_dependency_dlls(monkeypatch, tmp_path: Path) -> None:
    """A Windows libmpv bundle needs its adjacent dependency DLLs as well."""
    source = tmp_path / "source"
    source.mkdir()
    for name in ("libmpv-2.dll", "ffmpeg.exe", "ffprobe.exe", "dependency.dll"):
        (source / name).write_bytes(b"runtime")
    stager = _media_stager()
    monkeypatch.setattr(stager.sys, "platform", "win32")

    staged = stager.stage_media_files([source], tmp_path / "media")

    assert {path.name for path in staged} == {
        "dependency.dll",
        "ffmpeg.exe",
        "ffprobe.exe",
        "libmpv-2.dll",
    }


def test_appimage_declares_and_stages_its_desktop_icon() -> None:
    """AppImageTool receives the icon named by the desktop entry."""
    script = Path("packaging/linux/make_appimage.sh")
    icon = Path("packaging/linux/avialview.png")

    content = script.read_text(encoding="utf-8")

    assert "Icon=avialview" in content
    assert '"$script_dir/avialview.png" "$appdir/avialview.png"' in content
    assert 'ln -s avialview.png "$appdir/.DirIcon"' in content
    assert 'desktop-file-validate "$appdir/avialview.desktop"' in content
    assert icon.is_file()


def test_linux_release_installs_desktop_entry_validator() -> None:
    """The AppImage desktop entry is validated before AppImageTool consumes it."""
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "desktop-file-utils ffmpeg libmpv2 libfuse2t64" in workflow


@pytest.mark.skipif(
    sys.platform == "win32", reason="AppImage assembly requires a Linux shell environment"
)
def test_appimage_builder_stages_all_required_root_entries(tmp_path: Path) -> None:
    """The manually assembled AppDir conforms before AppImageTool receives it."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "avialview").write_text("bundle executable", encoding="utf-8")
    helpers = tmp_path / "helpers"
    helpers.mkdir()
    validator = helpers / "desktop-file-validate"
    validator.write_text('#!/usr/bin/env sh\ntest -f "$1"\n', encoding="utf-8")
    appimagetool = helpers / "appimagetool"
    appimagetool.write_text(
        "#!/usr/bin/env sh\n"
        'test -f "$1/AppRun"\n'
        'test -f "$1/avialview.desktop"\n'
        'test -f "$1/avialview.png"\n'
        'test -L "$1/.DirIcon"\n'
        'touch "$2"\n',
        encoding="utf-8",
    )
    validator.chmod(0o755)
    appimagetool.chmod(0o755)
    output = tmp_path / "AvialView.AppImage"
    environment = os.environ | {
        "APPIMAGETOOL": str(appimagetool),
        "PATH": f"{helpers}:{os.environ['PATH']}",
    }

    subprocess.run(
        ["bash", "packaging/linux/make_appimage.sh", str(bundle), str(output)],
        check=True,
        env=environment,
    )

    assert output.is_file()


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
