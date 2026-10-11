"""How a sidecar beside a source file is named.

A sidecar takes the source's **full** file name with every dot made an
underscore, then its own tag: ``pose.csv`` -> ``pose_csv_avialfix.csv``.

* **The full name**, not the stem, so ``a.csv`` and ``a.h5`` in one folder
  cannot share a corrections file.
* **Underscores**, so the only extension a sidecar has is its real one.  A file
  manager, a spreadsheet and ``pathlib.Path.suffix`` all read
  ``pose_csv_avialfix.csv`` as a CSV, where ``pose.csv.avialfix.csv`` read as a
  file of type ``.avialfix.csv`` to some and of ``.csv`` to others.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["beside", "flat_name", "on_disk"]


def flat_name(source: Path | str) -> str:
    """Return *source*'s file name with every dot replaced by an underscore."""
    return Path(source).name.replace(".", "_")


def on_disk(source: Path | str) -> Path:
    """Where a source's sidecars are named from: itself, or for a name inside a file, beside it.

    A joined stream is named inside its first file (``a.avi/joined_parts``,
    D-219), which no folder holds; its sidecars sit beside that file instead,
    named after both: ``a_avi_joined_parts``.
    """
    path = Path(source)
    if path.parent.is_file():
        return path.parent.with_name(f"{flat_name(path.parent)}_{path.name}")
    return path


def beside(source: Path | str, suffix: str) -> Path:
    """Return the sidecar named *suffix* that belongs beside *source*."""
    path = on_disk(source)
    return path.with_name(f"{flat_name(path)}{suffix}")
