"""The settings store is opened in one place, and the sandbox reaches it.

``QSettings("AvialSync", "AvialSync")`` ignores ``setDefaultFormat`` and always
opens the native store, so the suite's sandbox in ``conftest.py`` never applied
to it and every run wrote into the developer's installed application
(INTERFACE_DESIGN_PLAN F-36). ``ui/app_settings.app_settings`` passes the
default format explicitly.
"""

from __future__ import annotations

import ast
from pathlib import Path

from PySide6.QtCore import QSettings

from avialsync.ui.app_settings import app_settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
#: This file opens the native store only to read its file name and writes nothing.
_ALLOWED = {
    REPOSITORY_ROOT / "src" / "avialsync" / "ui" / "app_settings.py",
    Path(__file__).resolve(),
}


def _settings_constructions(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == "QSettings":
            lines.append(node.lineno)
    return lines


def test_nothing_else_opens_a_settings_store() -> None:
    offenders = []
    for folder in ("src", "tests", "tools"):
        for path in sorted((REPOSITORY_ROOT / folder).rglob("*.py")):
            if path in _ALLOWED:
                continue
            offenders += [
                f"{path.relative_to(REPOSITORY_ROOT)}:{line}"
                for line in _settings_constructions(path)
            ]
    assert not offenders, (
        "open the store with avialsync.ui.app_settings.app_settings(); "
        f"QSettings(org, app) ignores the sandbox: {offenders}"
    )


def test_the_suite_writes_into_its_sandbox_not_the_real_store() -> None:
    native = QSettings(
        QSettings.Format.NativeFormat, QSettings.Scope.UserScope, "AvialSync", "AvialSync"
    )
    assert app_settings().fileName() != native.fileName()
    assert app_settings().format() == QSettings.Format.IniFormat
