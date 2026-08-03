"""Tests for bundled and environment-provided media runtime discovery."""

from pathlib import Path

from avialsync import runtime


def test_find_media_executable_prefers_configured_runtime(monkeypatch, tmp_path: Path) -> None:
    """A bundle-local ffprobe wins over an unrelated process PATH."""
    executable_name = "ffprobe.exe" if runtime.sys.platform == "win32" else "ffprobe"
    ffprobe = tmp_path / executable_name
    ffprobe.write_bytes(b"probe")
    monkeypatch.setenv("AVIALSYNC_MEDIA_ROOT", str(tmp_path))
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: None)

    assert runtime.find_media_executable("ffprobe") == ffprobe


def test_require_ffprobe_explains_how_to_fix_missing_runtime(monkeypatch) -> None:
    """Source users receive an actionable error instead of a subprocess failure."""
    monkeypatch.setattr(runtime, "find_media_executable", lambda _name: None)

    try:
        runtime.require_ffprobe()
    except runtime.MediaRuntimeError as error:
        assert "FFmpeg" in str(error)
    else:
        raise AssertionError("Missing ffprobe must raise MediaRuntimeError")


def test_find_media_executable_uses_winget_fallback(monkeypatch, tmp_path: Path) -> None:
    """Activated conda environments still find a user-installed WinGet FFmpeg."""
    package_root = tmp_path / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg.Shared" / "bin"
    package_root.mkdir(parents=True)
    ffprobe = package_root / "ffprobe.exe"
    ffprobe.write_bytes(b"probe")
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: None)

    assert runtime.find_media_executable("ffprobe") == ffprobe
