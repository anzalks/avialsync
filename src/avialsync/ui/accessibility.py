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

**The sweep has to run more than once (D-107).**  It was called exactly once,
from ``MainWindow.__init__``, against a window that by definition holds no
video panes, no plot rows, no per-source sidebar entries and no quality badges
— the application starts empty, and every one of those widgets is built later.
Eleven dialog classes were never swept at all, because none of them exists at
construction time either.  The test that should have caught it asserted
``apply_accessibility(window) == 0`` on a freshly built empty window, which is
true whether the sweep works or not.

So the sweep also runs on ``Show``, through :class:`ShowTimeSweeper` installed
on the application.  One event filter reaches every dialog, including ones
added later, at the moment its widgets exist and before anyone can interact
with them.  ``apply_accessibility`` was already documented as idempotent and
cheap on a second pass, which is what makes this safe to hang off an event.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QComboBox,
    QDialog,
    QLineEdit,
    QScrollBar,
    QWidget,
)

__all__ = [
    "GLYPH_NAMES",
    "derive_name",
    "apply_accessibility",
    "unnamed_widgets",
    "ShowTimeSweeper",
    "install_show_time_sweep",
]

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

    # A scroll bar displays nothing to derive from, so it fell through to "" and
    # stayed unnamed wherever one had not been written by hand -- which was two
    # places out of every scroll area in the application. Its orientation is the
    # only thing it can honestly be named for, and a screen reader announces the
    # role alongside it, so "Scroll vertically" is what a user hears (D-107).
    if isinstance(widget, QScrollBar):
        if widget.orientation() == Qt.Orientation.Vertical:
            return "Scroll vertically"
        return "Scroll horizontally"

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


class ShowTimeSweeper(QObject):
    """Names a dialog's controls the moment it is shown.

    The main window is swept at construction and again whenever sources
    change; dialogs cannot be, because they do not exist until someone opens
    one. Filtering ``Show`` on the application catches every one of them --
    including any added after this was written, which is the property that
    matters, since the previous arrangement was correct on the day it landed
    and silently wrong for eleven dialogs afterwards.
    """

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Show and isinstance(watched, QDialog):
            apply_accessibility(watched)
        # Never consume it: this observes, and the dialog must still be shown.
        return False


#: Marks the application object that already carries a sweeper, so a second
#: window does not install a second one.
_SWEEPER_PROPERTY = "av_show_time_sweeper"


def install_show_time_sweep(app: QObject) -> ShowTimeSweeper:
    """Install :class:`ShowTimeSweeper` on *app*, at most once, and return it.

    **One per application, not one per window.** A filter installed on the
    application object receives every event delivered to every object in the
    process, and one parented to the application is never removed -- so
    installing from ``MainWindow.__init__`` without this guard added a filter
    per window and left them all running. Two windows doubled the per-event
    cost; a test suite that constructs a hundred multiplied it by a hundred and
    took the run from two minutes to no longer finishing.

    The sweeper is parented to *app* and also recorded on it as a property. The
    parent is what keeps it alive -- an event filter with no live reference is
    collected while Qt still holds a pointer to it -- and the property is what
    makes this idempotent.
    """
    existing = app.property(_SWEEPER_PROPERTY)
    if isinstance(existing, ShowTimeSweeper):
        return existing
    sweeper = ShowTimeSweeper(app)
    app.installEventFilter(sweeper)
    app.setProperty(_SWEEPER_PROPERTY, sweeper)
    return sweeper
