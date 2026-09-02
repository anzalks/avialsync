"""Loading translations, and measuring how much is translatable (WP-12).

There was not one ``self.tr()`` or ``QTranslator`` anywhere: every string was
hardcoded English and untranslatable without a rewrite. For an open-source
scientific tool with an international user base that is a permanent ceiling,
and it gets more expensive every week it stands.

This is the machinery — finding a catalogue for the user's locale, installing
it, and falling back silently when there is none. It is deliberately separate
from the sweep that wraps call sites, because the two fail differently: without
the machinery a wrapped string is merely a function call, and without the
wrapping the machinery has nothing to load.

:func:`translatable_ratio` measures the second half honestly. A partial wrap is
worse than none in one specific way — it presents an application as
translatable while half of it stays English — so the coverage is a number this
module reports rather than a claim made in a docstring.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

__all__ = [
    "tr",
    "catalogue_dir",
    "install_translator",
    "translatable_ratio",
    "untranslated_calls",
]

#: One context for the whole application's own strings. Qt groups by context so
#: a translator can see where a phrase appears; per-class contexts would be
#: finer, but they also mean the same word is translated once per class, and
#: this application's vocabulary is small and consistent.
_CONTEXT = "avialsync"


def tr(text: str, disambiguation: str | None = None) -> str:
    """Mark *text* for translation and return its translation.

    A module-level function rather than ``self.tr``, because a third of the
    strings that need it are in module functions and controllers that have no
    ``self`` -- ``session_controller`` and the drop handlers especially. One
    mechanism that works everywhere beats two that each work half the time.

    ``lupdate`` extracts ``QCoreApplication.translate`` calls, so this is
    visible to the tooling as well as to Qt.
    """
    return QCoreApplication.translate(_CONTEXT, text, disambiguation)


#: Methods whose argument is read by a person and therefore needs translating.
#: `setAccessibleName` and `setAccessibleDescription` are included: a screen
#: reader is not a reason to stay in English.
USER_FACING_SETTERS = frozenset(
    {
        "setText",
        "setWindowTitle",
        "setToolTip",
        "setPlaceholderText",
        "setStatusTip",
        "setAccessibleName",
        "setAccessibleDescription",
        "setTitle",
        "addAction",
        "addTab",
        "addMenu",
    }
)


def catalogue_dir() -> Path:
    """Where compiled ``.qm`` catalogues live, inside the package."""
    return Path(__file__).resolve().parent.parent / "resources" / "i18n"


def install_translator(app: QApplication, locale: QLocale | None = None) -> bool:
    """Install a catalogue for *locale*. Returns whether one was found.

    Silent when there is none, which is the common case and not an error: an
    untranslated application in the user's locale is the status quo, and a
    warning about it on every launch would be noise.

    Qt's own catalogue is loaded too where available, so standard dialog
    buttons -- Open, Cancel, Save -- are translated even before any of this
    application's strings are.
    """
    target = locale or QLocale.system()

    qt_translator = QTranslator(app)
    qt_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if qt_translator.load(target, "qtbase", "_", qt_path):
        app.installTranslator(qt_translator)
        # Retained on the application: a QTranslator that is garbage collected
        # is uninstalled with no warning, and the UI silently reverts.
        app.setProperty("_avialsync_qt_translator", qt_translator)

    translator = QTranslator(app)
    if not translator.load(target, "avialsync", "_", str(catalogue_dir())):
        return False
    app.installTranslator(translator)
    app.setProperty("_avialsync_translator", translator)
    logger.info("Loaded translations for %s", target.name())
    return True


# ── measuring the wrap ───────────────────────────────────────────────


def _is_translated(node: ast.AST) -> bool:
    """Whether *node* is a ``tr(...)`` call rather than a bare literal."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in {"tr", "translate"}
    if isinstance(func, ast.Name):
        return func.id in {"tr", "_"}
    return False


def untranslated_calls(path: Path) -> list[tuple[int, str]]:
    """User-facing string literals in *path* that are not wrapped for translation.

    Returns ``(line, snippet)``. An empty string is ignored -- clearing a label
    is not text a person reads -- and so is an f-string, which cannot be
    extracted by ``lupdate`` and needs restructuring rather than wrapping.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return []

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else None
        if name not in USER_FACING_SETTERS:
            continue
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                if argument.value.strip() and not _is_translated(argument):
                    found.append((node.lineno, argument.value[:60]))
    return found


def translatable_ratio(root: Path) -> tuple[int, int]:
    """Return ``(wrapped, total)`` user-facing literals under *root*.

    Honest rather than flattering: this counts what is *not* yet wrapped, so
    the number moves only when the work is actually done.
    """
    total = 0
    unwrapped = 0
    for path in sorted(root.rglob("*.py")):
        calls = untranslated_calls(path)
        unwrapped += len(calls)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else None
            if name not in USER_FACING_SETTERS:
                continue
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    if argument.value.strip():
                        total += 1
                elif _is_translated(argument):
                    total += 1
    return total - unwrapped, total
