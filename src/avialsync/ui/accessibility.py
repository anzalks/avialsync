"""Making the interface reachable without sight (WP-12).

The state before this: 40 ``setAccessibleName`` calls against roughly 90
interactive widgets, one ``setAccessibleDescription``, and no status tips. A
screen reader met a window full of unnamed buttons.

The obvious fix is to add the missing calls by hand. That fixes today and not
tomorrow — the ninety-first widget is added without one, and nothing says so.
So this is a sweep instead: it walks the constructed window, derives a name for
anything that lacks one from what the widget already displays, and a test
asserts that nothing interactive is left unnamed.

Derivation, not invention. A button's own label is what a sighted user reads,
so it is the right name for someone who cannot see it; a tooltip already
explains the control, so it is the right description. Where a widget shows an
icon or a bare glyph — the transport's ``[``, ``]``, ``◀``, ``▶`` — there is
nothing to derive from, and those are named explicitly in :data:`GLYPH_NAMES`
because a symbol is not a word.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QComboBox,
    QLineEdit,
    QWidget,
)

__all__ = ["GLYPH_NAMES", "derive_name", "apply_accessibility", "unnamed_widgets"]

#: Controls whose visible label is a symbol. A screen reader announcing
#: "left square bracket" tells someone nothing about what the control does, and
#: these are exactly the transport controls a keyboard user relies on.
GLYPH_NAMES: dict[str, str] = {
    "[": "Set loop start",
    "]": "Set loop end",
    "✕": "Clear the loop range",
    "◀": "Step back one frame",
    "▶": "Step forward one frame",
    "–1s": "Jump back one second",
    "+1s": "Jump forward one second",
    "−1s": "Jump back one second",
    "-1s": "Jump back one second",
    "⚠": "Show what is unusual about this source",
    "X": "Remove this source",
    "⚙": "Open settings",
}

#: Widget types a keyboard or screen-reader user has to operate.
INTERACTIVE = (QAbstractButton, QAbstractSlider, QComboBox, QLineEdit)


def _is_qt_internal(widget: QWidget) -> bool:
    """Whether *widget* is a private child Qt built inside another control.

    A QSpinBox contains its own QLineEdit named ``qt_spinbox_lineedit``. Naming
    it would make a screen reader announce the same control twice, once
    meaninglessly: the spin box is what the user operates and what carries the
    name.
    """
    return widget.objectName().startswith("qt_")


def derive_name(widget: QWidget) -> str:
    """A usable accessible name for *widget*, or "" if nothing can be derived.

    Order matters: an explicit name beats a glyph translation, which beats the
    visible text, which beats a tooltip. Each step is more specific than the
    one after it.
    """
    existing = widget.accessibleName()
    if existing:
        return existing

    text = ""
    if isinstance(widget, QAbstractButton):
        text = widget.text().replace("&", "").strip()
    elif isinstance(widget, QLineEdit):
        text = widget.placeholderText().strip()

    if text in GLYPH_NAMES:
        return GLYPH_NAMES[text]
    if text:
        return text

    tooltip = widget.toolTip().strip()
    if tooltip:
        # First sentence only: a tooltip can be a paragraph, and a name is
        # announced every time focus lands on the control.
        return tooltip.split(". ")[0].rstrip(".")
    return ""


def apply_accessibility(root: QWidget) -> int:
    """Name every unnamed interactive widget under *root*. Returns how many.

    Idempotent, and safe to call again after new widgets appear — a control
    that already has a name is left alone, so an explicit one is never
    overwritten by a derived one.
    """
    named = 0
    for widget in root.findChildren(QWidget):
        if not isinstance(widget, INTERACTIVE) or _is_qt_internal(widget):
            continue

        if not widget.accessibleName():
            name = derive_name(widget)
            if name:
                widget.setAccessibleName(name)
                named += 1

        # The description is the *why*, and the tooltip is already written to
        # be exactly that. Only set it where it adds something the name did
        # not already say.
        if not widget.accessibleDescription():
            tooltip = widget.toolTip().strip()
            if tooltip and tooltip != widget.accessibleName():
                widget.setAccessibleDescription(tooltip)

    return named


def unnamed_widgets(root: QWidget) -> list[QWidget]:
    """Interactive widgets under *root* that a screen reader could not announce.

    The check the test uses. A widget here is one someone would have to
    operate blind, with nothing said about what it does.
    """
    return [
        widget
        for widget in root.findChildren(QWidget)
        if isinstance(widget, INTERACTIVE)
        and not _is_qt_internal(widget)
        and widget.isVisible()
        and not widget.accessibleName()
    ]
