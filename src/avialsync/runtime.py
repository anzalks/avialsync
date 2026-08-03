"""Locate bundled and environment-provided media runtime tools.

The installed application must not depend on the caller's current directory.
Release bundles place their media runtime beside the executable, while source
checkouts may obtain it from the active conda environment or ``PATH``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

_DLL_DIRECTORIES: list[object] = []
_DLL_DIRECTORY_PATHS: set[Path] = set()


class MediaRuntimeError(RuntimeError):
    """Raised when a required externally supplied media executable is unavailable."""


def media_search_dirs() -> tuple[Path, ...]:
    """Return existing directories that may contain bundled media tools."""
    candidates: list[Path] = []
    configured = os.environ.get("AVIALSYNC_MEDIA_ROOT")
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


def _windows_winget_media_dirs() -> tuple[Path, ...]:
    """Return FFmpeg bin directories installed by WinGet outside the active PATH.

    ``conda activate`` can replace rather than extend the user PATH.  WinGet's
    package directory is stable, so inspect only its direct package children
    and their conventional ``bin`` directories as a bounded fallback.
    """
    if sys.platform != "win32":
        return ()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return ()
    package_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
    if not package_root.is_dir():
        return ()
    candidates: list[Path] = []
    for package in package_root.iterdir():
        if not package.is_dir() or "ffmpeg" not in package.name.lower():
            continue
        for directory in package.glob("**/bin"):
            if directory.is_dir():
                candidates.append(directory)
    return tuple(candidates)


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
    if resolved:
        return Path(resolved)
    for directory in _windows_winget_media_dirs():
        for candidate_name in names:
            candidate = directory / candidate_name
            if candidate.is_file():
                return candidate
    return None


def require_media_executable(name: str) -> Path:
    """Return a media executable or raise an actionable runtime dependency error."""
    executable = find_media_executable(name)
    if executable is None:
        raise MediaRuntimeError(
            f"{name} was not found. Install the AvialSync desktop release, or for a source "
            "install a standalone FFmpeg build and make its bin directory available on PATH."
        )
    return executable


def require_ffprobe() -> Path:
    """Return ffprobe or raise an actionable runtime dependency error."""
    return require_media_executable("ffprobe")


def require_ffmpeg() -> Path:
    """Return ffmpeg or raise an actionable runtime dependency error."""
    return require_media_executable("ffmpeg")


class NoWindowKwargs(TypedDict, total=False):
    """Subprocess keyword arguments that suppress a console window.

    A ``TypedDict`` rather than ``dict[str, int]`` so mypy can still resolve the
    overloads of ``subprocess.run``/``Popen`` when this is splatted into them.
    ``total=False`` because the mapping is empty off Windows.
    """

    creationflags: int


def no_window_kwargs() -> NoWindowKwargs:
    """Return subprocess kwargs that keep a child process from opening a console.

    A windowed Windows build has no console of its own, so every ``ffprobe`` or
    ``ffmpeg`` child is given a fresh one — which flashes on screen and steals
    focus.  A four-camera session opens four of them during load.  ``ffmpeg``
    exports and proxy builds do the same.

    ``CREATE_NO_WINDOW`` exists only on Windows; every other platform gets an
    empty mapping, so call sites can unconditionally splat the result.
    """
    if sys.platform != "win32":
        return NoWindowKwargs()
    # subprocess.CREATE_NO_WINDOW is Windows-only, hence the guarded lookup.
    return NoWindowKwargs(creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
