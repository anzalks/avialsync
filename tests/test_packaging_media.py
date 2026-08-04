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


def test_linux_media_staging_keeps_versioned_shared_objects(monkeypatch, tmp_path: Path) -> None:
    """The Linux branch has never run in CI; pin what it accepts and rejects."""
    source = tmp_path / "source"
    source.mkdir()
    for name in (
        "libmpv.so.2",
        "libavcodec.so.62",
        "libavutil.so.60.26.100",
        "ffmpeg",
        "ffprobe",
    ):
        (source / name).write_bytes(b"runtime")
    # libavcodec.3 is a man page: it matches the same name prefix as the
    # library and is installed beside it.
    for name in ("avcodec.h", "libavcodec.a", "libmpv.pc", "mpv-symbolic.svg", "libavcodec.3"):
        (source / name).write_bytes(b"not runtime")
    stager = _media_stager()
    monkeypatch.setattr(stager.sys, "platform", "linux")

    staged = {path.name for path in stager.stage_media_files([source], tmp_path / "media")}

    assert staged == {
        "ffmpeg",
        "ffprobe",
        "libmpv.so.2",
        "libavcodec.so.62",
        "libavutil.so.60.26.100",
    }


def test_windows_media_staging_rejects_package_manager_metadata(
    monkeypatch, tmp_path: Path
) -> None:
    """Chocolatey ships nuspec/html/txt beside the binaries; none of it is code."""
    source = tmp_path / "source"
    source.mkdir()
    for name in ("libmpv-2.dll", "ffmpeg.exe", "ffprobe.exe", "dependency.dll"):
        (source / name).write_bytes(b"runtime")
    for name in ("ffmpeg.nuspec", "ffmpeg-all.html", "ffmpeg-release-essentials.7z.txt"):
        (source / name).write_bytes(b"not runtime")
    stager = _media_stager()
    monkeypatch.setattr(stager.sys, "platform", "win32")

    staged = {path.name for path in stager.stage_media_files([source], tmp_path / "media")}

    assert staged == {"libmpv-2.dll", "ffmpeg.exe", "ffprobe.exe", "dependency.dll"}


def test_media_staging_links_aliases_instead_of_duplicating_them(
    monkeypatch, tmp_path: Path
) -> None:
    """A versioned library and its aliases must not be staged as three copies.

    Homebrew's layout, so the platform is pinned the way the Windows case
    pins its own: ``.dylib`` is only a media file on darwin, and left to the
    host this passed on macOS and failed everywhere else.
    """
    source = tmp_path / "source"
    source.mkdir()
    real = source / "libavcodec.62.28.102.dylib"
    real.write_bytes(b"x" * 4096)
    (source / "libavcodec.62.dylib").symlink_to("libavcodec.62.28.102.dylib")
    (source / "libavcodec.dylib").symlink_to("libavcodec.62.28.102.dylib")
    (source / "libmpv.dylib").write_bytes(b"mpv")
    (source / "ffmpeg").write_bytes(b"ffmpeg")
    (source / "ffprobe").write_bytes(b"ffprobe")
    destination = tmp_path / "media"
    stager = _media_stager()
    monkeypatch.setattr(stager.sys, "platform", "darwin")

    staged = stager.stage_media_files([source], destination)

    # Every name a linker might ask for is still present…
    assert {path.name for path in staged} >= {
        "libavcodec.dylib",
        "libavcodec.62.dylib",
        "libavcodec.62.28.102.dylib",
    }
    # …but only one of them holds the bytes, and the aliases still resolve.
    assert (destination / "libavcodec.dylib").is_symlink()
    assert (destination / "libavcodec.62.dylib").is_symlink()
    assert not (destination / "libavcodec.62.28.102.dylib").is_symlink()
    assert (destination / "libavcodec.dylib").resolve() == (
        destination / "libavcodec.62.28.102.dylib"
    )
    assert (destination / "libavcodec.dylib").read_bytes() == b"x" * 4096


def test_appimage_declares_and_stages_its_desktop_icon() -> None:
    """AppImageTool receives the icon named by the desktop entry."""
    script = Path("packaging/linux/make_appimage.sh")
    icon = Path("packaging/linux/avialsync.png")

    content = script.read_text(encoding="utf-8")

    assert "Icon=avialsync" in content
    assert '"$script_dir/avialsync.png" "$appdir/avialsync.png"' in content
    assert 'ln -s avialsync.png "$appdir/.DirIcon"' in content
    assert 'desktop-file-validate "$appdir/avialsync.desktop"' in content
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
    (bundle / "avialsync").write_text("bundle executable", encoding="utf-8")
    helpers = tmp_path / "helpers"
    helpers.mkdir()
    validator = helpers / "desktop-file-validate"
    validator.write_text('#!/usr/bin/env sh\ntest -f "$1"\n', encoding="utf-8")
    appimagetool = helpers / "appimagetool"
    appimagetool.write_text(
        "#!/usr/bin/env sh\n"
        'test -f "$1/AppRun"\n'
        'test -f "$1/avialsync.desktop"\n'
        'test -f "$1/avialsync.png"\n'
        'test -L "$1/.DirIcon"\n'
        'touch "$2"\n',
        encoding="utf-8",
    )
    validator.chmod(0o755)
    appimagetool.chmod(0o755)
    output = tmp_path / "AvialSync.AppImage"
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
    spec = Path("packaging/avialsync.spec").read_text(encoding="utf-8")
    installer = Path("packaging/windows/avialsync.iss").read_text(encoding="utf-8")

    assert "icon=str(application_icon)" in spec
    assert "SetupIconFile=avialsync.ico" in installer


def test_windows_installer_does_not_require_administrator() -> None:
    """A lab user without an administrator password must still be able to install.

    Inno's default is ``PrivilegesRequired=admin``. Two things have to hold
    together: the directive that stops the forced elevation, and ``{auto*}``
    constants everywhere a path is written. A hardcoded ``{pf}``/``{commonpf}``
    or ``{commonprograms}`` would send a non-elevated install at Program Files
    and fail at the first file it wrote.
    """
    installer = Path("packaging/windows/avialsync.iss").read_text(encoding="utf-8")

    assert "PrivilegesRequired=lowest" in installer
    assert "PrivilegesRequiredOverridesAllowed=dialog" in installer
    for machine_only in ("{pf}", "{pf32}", "{pf64}", "{commonpf}", "{commonprograms}"):
        assert machine_only not in installer, f"{machine_only} breaks a per-user install"


def test_icon_generator_writes_all_platform_formats(tmp_path: Path) -> None:
    """The checked-in source deterministically produces every packaged icon."""
    source = Path("assets/avial_sync.png")

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
        tmp_path / "src/avialsync/resources/avialsync.png",
        tmp_path / "packaging/linux/avialsync.png",
        tmp_path / "packaging/windows/avialsync.ico",
        tmp_path / "packaging/macos/avialsync.icns",
    )
    for path in expected:
        assert path.is_file()
    with Image.open(expected[0]) as runtime_icon:
        assert runtime_icon.size == (512, 512)
