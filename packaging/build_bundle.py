"""Build a one-directory AvialSync bundle for the current platform.

Nothing is staged into the bundle beforehand. Every media binary arrives inside
PyAV's wheel and is collected by PyInstaller's ``av`` hook (D-075), so there is
no media root to point this at any more.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_bundle(dist_dir: Path) -> None:
    """Run PyInstaller over the project spec."""
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
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    build_bundle(args.dist_dir)


if __name__ == "__main__":
    main()
