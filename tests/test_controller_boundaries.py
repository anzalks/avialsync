"""Freeze the controller boundary while the old window coupling shrinks.

Each allowed private access is counted at the current baseline, so moving a
field behind a state object removes its allowance. New controller modules start
with no allowance at all. Deliberate changes to the boundary require updating
the baseline in the same review as the code and its reason.
"""

from __future__ import annotations

import ast
import graphlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLLERS = ROOT / "src" / "avialsync" / "ui" / "controllers"
MENU_BUILDERS = ROOT / "src" / "avialsync" / "ui" / "menus"
MAIN_WINDOW = ROOT / "src" / "avialsync" / "ui" / "main_window.py"
BASELINE = Path(__file__).with_name("controller_private_access_baseline.json")


def _baseline() -> dict:
    """Read the reviewed ceiling for old private accesses and long functions."""
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_controllers_cannot_add_private_window_accesses() -> None:
    """An existing access may disappear; none may appear or multiply."""
    allowed = _baseline()["private_accesses"]
    for path in sorted(CONTROLLERS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        actual = Counter(
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "window"
            and node.attr.startswith("_")
        )
        ceiling = Counter(allowed.get(path.name, {}))
        excess = actual - ceiling
        assert not excess, f"{path.name} adds private window accesses: {dict(excess)}"


def test_window_and_controllers_cannot_grow_past_the_reviewed_ceiling() -> None:
    """Oversized legacy modules may shrink; new modules stay under 500 lines."""
    baseline = _baseline()
    assert (
        len(MAIN_WINDOW.read_text(encoding="utf-8").splitlines()) <= baseline["main_window_lines"]
    )
    for path in sorted([*CONTROLLERS.glob("*.py"), *MENU_BUILDERS.glob("*.py")]):
        lines = len(path.read_text(encoding="utf-8").splitlines())
        ceiling = max(500, baseline["oversized_controller_lines"].get(path.name, 0))
        assert lines <= ceiling, f"{path.name} grew to {lines} lines; ceiling is {ceiling}"


def test_new_controller_functions_stay_bounded() -> None:
    """Long legacy functions may shrink; new functions stay under 60 lines."""
    exceptions = _baseline()["long_functions"]
    for path in [
        MAIN_WINDOW,
        *sorted(CONTROLLERS.glob("*.py")),
        *sorted(MENU_BUILDERS.glob("*.py")),
    ]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            assert node.end_lineno is not None
            length = node.end_lineno - node.lineno + 1
            ceiling = exceptions.get(path.name, {}).get(node.name, 60)
            assert length <= ceiling, (
                f"{path.name}:{node.name} is {length} lines; ceiling is {ceiling}"
            )


def test_controller_imports_form_an_acyclic_graph() -> None:
    """A deferred import cannot hide a cycle between controller modules."""
    paths = {path.stem: path for path in CONTROLLERS.glob("*.py")}
    prefix = "avialsync.ui.controllers"
    dependencies: dict[str, set[str]] = {name: set() for name in paths}
    for name, path in paths.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if node.module == prefix:
                dependencies[name].update(alias.name for alias in node.names if alias.name in paths)
            elif node.module.startswith(prefix + "."):
                target = node.module[len(prefix) + 1 :].split(".", 1)[0]
                if target in paths:
                    dependencies[name].add(target)
    try:
        list(graphlib.TopologicalSorter(dependencies).static_order())
    except graphlib.CycleError as error:
        raise AssertionError(f"Controller import cycle: {error.args[1]}") from error
