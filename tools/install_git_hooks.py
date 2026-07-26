"""Enable the repository's versioned Git hooks for the current clone."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Point this clone at the repository-managed hook directory."""
    subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"],
        cwd=REPOSITORY_ROOT,
        check=True,
    )
    print("Enabled repository hooks from .githooks/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
