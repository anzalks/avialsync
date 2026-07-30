"""Headless core guard test."""

import ast
import subprocess
import sys
from pathlib import Path


def test_core_is_headless() -> None:
    code = 'import sys; sys.modules["PySide6"] = None; import avialview.core'
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"Core import failed without PySide6: {result.stderr}"


def test_every_core_module_imports_without_pyside6() -> None:
    """Architecture rule 2 applies per module, not only to the package __init__.

    Importing just ``avialview.core`` misses any submodule the package does not
    pull in — ``core/session.py`` imported QSettings that way for several phases.
    """
    modules = sorted(
        f"avialview.core.{path.stem}"
        for path in Path("src/avialview/core").glob("*.py")
        if path.stem != "__init__"
    )
    assert modules, "No core modules discovered — check the path."
    code = (
        'import sys; sys.modules["PySide6"] = None\n'
        "import importlib\n"
        f"for name in {modules!r}:\n"
        "    importlib.import_module(name)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, (
        "A core/ module imports PySide6 (architecture rule 2). "
        f"Move the Qt-dependent code into ui/.\n{result.stderr}"
    )


def test_no_core_module_imports_pyside6_statically() -> None:
    """Catch the violation even when a lazy import hides it at runtime."""
    offenders = []
    for path in sorted(Path("src/avialview/core").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name.split(".")[0] == "PySide6" for name in names):
                offenders.append(f"{path}:{node.lineno}")

    assert offenders == [], f"core/ must never import PySide6: {offenders}"


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
