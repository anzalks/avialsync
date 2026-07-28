"""Stage locally installed LGPL media libraries for a release bundle.

Downloads are deliberately not performed here: release CI obtains media from its operating-system
package manager, then this script stages only the discovered files. This keeps package provenance
in the workflow and prevents an unreviewed URL from becoming a supply-chain dependency.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

MEDIA_EXECUTABLES = frozenset({"ffmpeg", "ffmpeg.exe", "ffprobe", "ffprobe.exe"})
MEDIA_LIBRARY_PREFIXES = (
    "libmpv",
    "mpv-",
    "avcodec",
    "avdevice",
    "avfilter",
    "avformat",
    "avutil",
    "swresample",
    "swscale",
)


def _is_media_runtime_file(path: Path) -> bool:
    """Return whether a package-manager file belongs in the media runtime."""
    name = path.name.lower()
    if name in MEDIA_EXECUTABLES or name.startswith(MEDIA_LIBRARY_PREFIXES):
        return True
    if sys.platform == "win32":
        return path.suffix.lower() == ".dll"
    if sys.platform == "darwin":
        return path.suffix.lower() == ".dylib"
    return False


def discover_media_files(sources: list[Path]) -> list[Path]:
    """Find mpv/ffmpeg runtime files in the supplied package-manager directories."""
    found: dict[str, Path] = {}
    for source in sources:
        if not source.is_dir():
            continue
        for path in source.rglob("*"):
            if path.is_file() and _is_media_runtime_file(path):
                found.setdefault(path.name, path)
    return sorted(found.values())


def validate_media_files(files: list[Path]) -> None:
    """Require the tools needed for video playback and metadata probing."""
    names = {path.name.lower() for path in files}
    required = (
        ("ffmpeg.exe", "ffmpeg"),
        ("ffprobe.exe", "ffprobe"),
        ("libmpv-2.dll", "libmpv.dll", "libmpv.dylib", "libmpv.so", "libmpv.so.2"),
    )
    missing = [
        alternatives[0]
        for alternatives in required
        if not any(name in names for name in alternatives)
    ]
    if missing:
        raise RuntimeError(f"Media runtime is incomplete; missing: {', '.join(missing)}")


def stage_media_files(sources: list[Path], destination: Path) -> list[Path]:
    """Copy discovered runtime media files into a clean bundle-local directory."""
    files = discover_media_files(sources)
    validate_media_files(files)
    destination.mkdir(parents=True, exist_ok=True)
    staged = []
    for source in files:
        target = destination / source.name
        shutil.copy2(source, target)
        staged.append(target)
    return staged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    staged = stage_media_files(args.source, args.destination)
    print("Staged media files:")
    for path in staged:
        print(path)


if __name__ == "__main__":
    main()
