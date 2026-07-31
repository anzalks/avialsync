"""The engine layer must not depend on the UI layer (V-13, ARCHITECTURE §1).

`engine/player.py` imported `ui.plot_pane`, `ui.transport`, `ui.video_grid`, and
`ui.video_pane` at module scope, and `seeker`/`export_worker` did the same. That
makes `engine` impossible to import, test, or reuse headlessly even though every
one of those names was used purely as a type annotation.

Qt itself is fine here — the engine is `QObject`-based. What is not fine is a
*module-scope* dependency on a widget module.
"""

from __future__ import annotations

import ast
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1] / "src" / "avialview" / "engine"


def _is_type_checking_guard(node: ast.stmt) -> bool:
    """Whether an `if` statement is the `if TYPE_CHECKING:` guard."""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _ui_imports(tree: ast.Module) -> tuple[list[int], list[int]]:
    """Return ``(module_scope_linenos, deferred_linenos)`` for `avialview.ui` imports."""
    module_scope: list[int] = []
    deferred: list[int] = []

    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("avialview.ui"):
            module_scope.append(node.lineno)
        elif _is_type_checking_guard(node):
            for sub in ast.walk(node):
                if isinstance(sub, ast.ImportFrom) and (sub.module or "").startswith(
                    "avialview.ui"
                ):
                    deferred.append(sub.lineno)
    return module_scope, deferred


def test_no_engine_module_imports_ui_at_module_scope() -> None:
    offenders: list[str] = []
    for path in sorted(ENGINE_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_scope, _deferred = _ui_imports(tree)
        offenders.extend(f"engine/{path.name}:{lineno}" for lineno in module_scope)

    assert not offenders, (
        "The engine layer must not import ui/ at module scope (ARCHITECTURE §1). "
        "These names are annotations — move them under `if TYPE_CHECKING:`. "
        "Offenders: " + ", ".join(offenders)
    )


def test_the_scan_actually_finds_the_deferred_imports() -> None:
    """Guard the guard: if the scan matched nothing the test above is vacuous."""
    total_deferred = 0
    for path in sorted(ENGINE_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        _module_scope, deferred = _ui_imports(tree)
        total_deferred += len(deferred)

    assert total_deferred >= 6, f"expected the annotation imports to be found, saw {total_deferred}"


def test_engine_does_not_reach_into_private_widget_state() -> None:
    """`player` read `transport._bounds`; Transport now publishes `bounds`."""
    source = (ENGINE_ROOT / "player.py").read_text(encoding="utf-8")

    assert "transport._bounds" not in source
    assert "self.transport.bounds" in source


def test_transport_publishes_bounds() -> None:
    from avialview.ui.transport import Transport

    assert isinstance(Transport.bounds, property)
