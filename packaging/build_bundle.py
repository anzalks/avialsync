"""Build a one-directory AvialSync bundle for the current platform."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_bundle(media_root: Path | None, dist_dir: Path) -> None:
    """Run PyInstaller with only staged, local media libraries included."""
    env = os.environ.copy()
    if media_root is not None:
        env["AVIALSYNC_MEDIA_ROOT"] = str(media_root.resolve())
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        str(ROOT / "packaging" / "avialsync.spec"),
    ]
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-root", type=Path)
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    build_bundle(args.media_root, args.dist_dir)


if __name__ == "__main__":
    main()
