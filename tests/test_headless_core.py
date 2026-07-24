"""Headless core guard test."""

import subprocess
import sys


def test_core_is_headless() -> None:
    code = 'import sys; sys.modules["PySide6"] = None; import kinochronix.core'
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"Core import failed without PySide6: {result.stderr}"
