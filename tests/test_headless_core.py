"""Headless core guard test."""

import ast
import subprocess
import sys
from pathlib import Path


def test_core_is_headless() -> None:
    code = 'import sys; sys.modules["PySide6"] = None; import avialview.core'
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"Core import failed without PySide6: {result.stderr}"


def _production_trees():
    for path in Path("src/avialview").rglob("*.py"):
        yield path, ast.parse(path.read_text(encoding="utf-8"))


def test_production_code_has_no_silent_broad_exception_handlers() -> None:
    """Unexpected failures must be reported, not converted into blank UI state."""
    offenders = []
    for path, tree in _production_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            catches_exception = isinstance(node.type, ast.Name) and node.type.id == "Exception"
            only_passes = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
            if catches_exception and only_passes:
                offenders.append(f"{path}:{node.lineno}")

    assert offenders == []


def test_production_code_has_no_blocking_qt_or_shell_process_hacks() -> None:
    """Guard the UI-thread and cross-platform subprocess architecture rules."""
    offenders = []
    for path, tree in _production_trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == "processEvents":
                offenders.append(f"{path}:{node.lineno}: processEvents")
            if any(
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            ):
                offenders.append(f"{path}:{node.lineno}: shell=True")

    assert offenders == []
