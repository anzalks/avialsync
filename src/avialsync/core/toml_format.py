"""Writing the small TOML files this application keeps beside the data.

``tomllib`` reads TOML and the standard library has no writer. The files written
here are a handful of flat tables -- a calibration, a wheel -- so a formatter of
a dozen lines serves them all, and one of them keeps the layout anipose itself
writes, which leaves a file diffable against one anipose made.

Headless (architecture rule 2).
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

__all__ = ["toml_value", "write_atomic"]


def toml_value(value: object) -> str:
    """Format one value the way anipose's own writer lays it out."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return repr(float(value))
    if isinstance(value, np.ndarray):
        return toml_value(value.tolist())
    if isinstance(value, (list, tuple)):
        return "[ " + " ".join(f"{toml_value(item)}," for item in value) + "]"
    raise TypeError(f"Cannot write {type(value).__name__} to TOML")


def write_atomic(path: Path, lines: list[str]) -> Path:
    """Write *lines* to *path* through a temporary file and one rename.

    A reader never sees half a file, and a failed write leaves the previous
    version where it was.
    """
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path
