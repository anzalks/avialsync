"""How a sidecar beside a source file is named (D-160).

A sidecar takes the source's **full** file name with every dot made an
underscore, then its own tag: ``pose.csv`` -> ``pose_csv_avialfix.csv``.

* **The full name**, not the stem, so ``a.csv`` and ``a.h5`` in one folder
  cannot share a corrections file (D-099).
* **Underscores**, so the only extension a sidecar has is its real one.  A file
  manager, a spreadsheet and ``pathlib.Path.suffix`` all read
  ``pose_csv_avialfix.csv`` as a CSV, where ``pose.csv.avialfix.csv`` read as a
  file of type ``.avialfix.csv`` to some and of ``.csv`` to others.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["beside", "flat_name"]


def flat_name(source: Path | str) -> str:
    """Return *source*'s file name with every dot replaced by an underscore."""
    return Path(source).name.replace(".", "_")


def beside(source: Path | str, suffix: str) -> Path:
    """Return the sidecar named *suffix* that belongs beside *source*."""
    path = Path(source)
    return path.with_name(f"{flat_name(path)}{suffix}")
