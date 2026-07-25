"""Stage locally installed LGPL media libraries for a release bundle.

Downloads are deliberately not performed here: release CI obtains media from its operating-system
package manager, then this script stages only the discovered files. This keeps package provenance
in the workflow and prevents an unreviewed URL from becoming a supply-chain dependency.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

LIBRARY_NAMES = ("libmpv", "mpv-", "mpv.dll", "ffmpeg", "ffmpeg.exe")


def discover_media_files(sources: list[Path]) -> list[Path]:
    """Find mpv/ffmpeg runtime files in the supplied package-manager directories."""
    found: dict[str, Path] = {}
    for source in sources:
        if not source.is_dir():
            continue
        for path in source.rglob("*"):
            if path.is_file() and path.name.lower().startswith(LIBRARY_NAMES):
                found.setdefault(path.name, path)
    return sorted(found.values())


def stage_media_files(sources: list[Path], destination: Path) -> list[Path]:
    """Copy discovered runtime media files into a clean bundle-local directory."""
    files = discover_media_files(sources)
    if not files:
        raise RuntimeError("No libmpv or ffmpeg runtime files found in the supplied media sources.")
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
