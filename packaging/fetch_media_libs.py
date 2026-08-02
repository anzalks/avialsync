"""Stage locally installed LGPL media libraries for a release bundle.

Downloads are deliberately not performed here: release CI obtains media from its operating-system
package manager, then this script stages only the discovered files. This keeps package provenance
in the workflow and prevents an unreviewed URL from becoming a supply-chain dependency.
"""

from __future__ import annotations

import argparse
import os
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
# Package managers install headers, static archives, pkg-config files, and icon
# artwork beside the runtime libraries, and those match the name rules above
# (``avcodec.h``, ``mpv-symbolic.svg``).  The spec declares every staged file as
# a PyInstaller *binary*, so anything that is not loadable code must be rejected
# here rather than shipped and post-processed as one.
NON_RUNTIME_SUFFIXES = frozenset(
    {
        ".a",
        ".cmake",
        ".h",
        ".hpp",
        ".json",
        ".la",
        ".md",
        ".pc",
        ".png",
        ".svg",
        ".txt",
        ".xml",
    }
)


def _is_media_runtime_file(path: Path) -> bool:
    """Return whether a package-manager file belongs in the media runtime."""
    name = path.name.lower()
    if path.suffix.lower() in NON_RUNTIME_SUFFIXES:
        return False
    if name in MEDIA_EXECUTABLES or name.startswith(MEDIA_LIBRARY_PREFIXES):
        return True
    if sys.platform == "win32":
        return path.suffix.lower() == ".dll"
    if sys.platform == "darwin":
        return path.suffix.lower() == ".dylib"
    # Linux names these libraries with a "lib" prefix (libavcodec.so.62, not
    # avcodec.dll), so the bare-name rules above match none of them: the ffmpeg
    # libraries reached the bundle only as transitive dependencies of the
    # ffmpeg binary. Match the prefixed form too, but require the shape of a
    # shared object as well — the man pages installed beside them
    # (libavcodec.3) otherwise match exactly the same name prefixes.
    unprefixed = name.removeprefix("lib")
    return ".so" in name and unprefixed.startswith(MEDIA_LIBRARY_PREFIXES)


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
    staged_names = {path.name for path in files}
    staged = []
    for source in files:
        target = destination / source.name
        target.unlink(missing_ok=True)
        # Package managers ship a versioned library beside unversioned aliases
        # (libavcodec.dylib and libavcodec.62.dylib both point at
        # libavcodec.62.28.102.dylib). Following every one of them copied the
        # same library three times under three names. Recreate the alias as a
        # link when its target is staged too: everything lands in one flat
        # directory, so a same-directory relative link still resolves.
        alias = os.readlink(source) if source.is_symlink() else None
        if alias is not None and "/" not in alias and alias in staged_names:
            target.symlink_to(alias)
        else:
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
