"""Locate bundled and environment-provided media runtime tools.

The installed application must not depend on the caller's current directory.
Release bundles place their media runtime beside the executable, while source
checkouts may obtain it from the active conda environment or ``PATH``.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_DLL_DIRECTORIES: list[object] = []
_DLL_DIRECTORY_PATHS: set[Path] = set()


class MediaRuntimeError(RuntimeError):
    """Raised when a required externally supplied media executable is unavailable."""


def media_search_dirs() -> tuple[Path, ...]:
    """Return existing directories that may contain bundled media tools."""
    candidates: list[Path] = []
    configured = os.environ.get("AVIALVIEW_MEDIA_ROOT")
    if configured:
        candidates.append(Path(configured))

    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(frozen_root))
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)

    candidates.append(Path(sys.prefix) / "Library" / "bin")

    unique: list[Path] = []
    for candidate in candidates:
        if candidate.is_dir() and candidate not in unique:
            unique.append(candidate)
    return tuple(unique)


def configure_media_runtime() -> None:
    """Make bundled and conda media libraries discoverable before importing mpv."""
    global _DLL_DIRECTORIES, _DLL_DIRECTORY_PATHS
    directories = tuple(
        directory
        for directory in media_search_dirs()
        if any(candidate.name.lower().startswith("libmpv") for candidate in directory.iterdir())
    )
    if directories:
        existing_path = os.environ.get("PATH", "")
        prefixes = [
            str(directory) for directory in directories if str(directory) not in existing_path
        ]
        if prefixes:
            os.environ["PATH"] = os.pathsep.join([*prefixes, existing_path])

    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        for directory in directories:
            if directory not in _DLL_DIRECTORY_PATHS:
                _DLL_DIRECTORIES.append(os.add_dll_directory(str(directory)))
                _DLL_DIRECTORY_PATHS.add(directory)


def find_media_executable(name: str) -> Path | None:
    """Return the bundled or PATH-resolved executable named ``name``."""
    configure_media_runtime()
    names = (f"{name}.exe", name) if sys.platform == "win32" else (name,)
    for directory in media_search_dirs():
        for candidate_name in names:
            candidate = directory / candidate_name
            if candidate.is_file():
                return candidate
    resolved = shutil.which(name)
    return Path(resolved) if resolved else None


def require_media_executable(name: str) -> Path:
    """Return a media executable or raise an actionable runtime dependency error."""
    executable = find_media_executable(name)
    if executable is None:
        raise MediaRuntimeError(
            f"{name} was not found. Install the AvialView desktop release, or for a source "
            "install a standalone FFmpeg build and make its bin directory available on PATH."
        )
    return executable


def require_ffprobe() -> Path:
    """Return ffprobe or raise an actionable runtime dependency error."""
    return require_media_executable("ffprobe")


def require_ffmpeg() -> Path:
    """Return ffmpeg or raise an actionable runtime dependency error."""
    return require_media_executable("ffmpeg")
