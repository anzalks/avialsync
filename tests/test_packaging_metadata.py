"""Tests for published-package compatibility metadata."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_package_caps_python_at_3_12() -> None:
    """Published metadata supports exactly the tested Python range."""
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    assert metadata["project"]["requires-python"] == ">=3.11,<3.13"
