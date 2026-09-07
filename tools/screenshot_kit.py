"""Shared capture helpers for the documentation screenshots.

Two things every screenshot tool in this directory needs, and got wrong
independently before this existed:

**Pin the appearance.** An unpinned theme follows whichever preference the
developer last saved, so the same command produced light-mode images on one
machine and dark-mode on another, and the docs ended up with a mix.

**Do not run these under ``QT_QPA_PLATFORM=offscreen``.** The offscreen plugin
has no native menu bar, so Qt draws one inside the window and every capture
gains a File/View/Help strip that a real macOS user never sees.

The third thing is new: a guide screenshot has to show *where to click*. A
picture of a dialog does not tell anyone which of its nine fields matters for
the step being described, so :func:`capture` draws a red box around the widgets
a step actually uses, and numbers them when order matters.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from avialsync.ui import theme

#: Highlight colour. Chosen to stay legible on both the dark chrome and the
#: black video panes, and to be distinguishable by someone who cannot separate
#: red from green — nothing in the UI itself is this colour, so the box reads as
#: an annotation rather than as part of the application.
HIGHLIGHT = QColor(255, 64, 64)
HIGHLIGHT_WIDTH = 3

#: Padding between a widget's bounds and its box, so the outline never sits on
#: top of the text it is pointing at.
_PAD = 4


def pin_appearance(app: QApplication) -> None:
    """Force the documented appearance without touching saved preferences.

    ``apply_theme`` persists, which would silently rewrite the preference of
    whoever runs this. The private ``_apply`` is used deliberately for its
    ``persist=False``: taking a screenshot must not be a settings change.
    """
    theme._apply(app, theme.THEME_DARK, persist=False)


def pin_layout(window: QWidget) -> None:
    """Put the panes back where a first run puts them.

    ``MainWindow.__init__`` restores saved geometry, so a developer who has
    ever dragged a splitter photographs their own arrangement: one run left the
    video pane 85 px tall with a blank band under the plots, which reads as a
    layout bug in the application rather than as the personal setting it was.
    Re-seeding the documented ratios is the same guarantee
    :func:`pin_appearance` gives for the theme, and like it, it writes nothing
    back -- the proportion store this touches lives on the window, not on disk.

    Call it *after* ``show()`` and a :func:`settle`: a splitter redistributes
    sizes on its first real resize, so seeding before the window has its final
    size seeds nothing.
    """
    window._apply_default_splitter_sizes()


def capture(
    window: QWidget,
    path: Path,
    highlights: Sequence[QWidget] = (),
    *,
    numbered: bool = False,
) -> None:
    """Grab *window* and save it, boxing each widget in *highlights*.

    Args:
        window: The widget to capture. Usually the main window or a dialog.
        path: Destination PNG.
        highlights: Widgets to outline, in the order the reader should use them.
        numbered: Draw a step number on each box. Use when the order matters;
            leave off when the boxes are alternatives or a single target, where
            numbers would imply a sequence that does not exist.
    """
    pixmap = window.grab()
    if highlights:
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(HIGHLIGHT, HIGHLIGHT_WIDTH))
        for index, widget in enumerate(highlights, start=1):
            box = _bounds_in(window, widget)
            if box is None:
                continue
            painter.drawRoundedRect(box, 5, 5)
            if numbered:
                _draw_step_number(painter, box, index)
        painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(path))


def _bounds_in(window: QWidget, widget: QWidget) -> QRect | None:
    """Return *widget*'s padded rectangle in *window* coordinates.

    Returns None for a widget that is hidden or has no size yet, so a step that
    highlights something not currently on screen produces a plain screenshot
    rather than a box drawn at the origin.
    """
    if not widget.isVisible() or widget.width() <= 0 or widget.height() <= 0:
        return None
    top_left = widget.mapTo(window, QPoint(0, 0))
    return QRect(top_left, widget.size()).adjusted(-_PAD, -_PAD, _PAD, _PAD)


def _draw_step_number(painter: QPainter, box: QRect, number: int) -> None:
    """Draw a filled step badge on the box's top-left corner."""
    radius = 11
    centre = box.topLeft()
    circle = QRect(centre.x() - radius, centre.y() - radius, radius * 2, radius * 2)
    painter.save()
    painter.setBrush(HIGHLIGHT)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(circle)
    painter.setPen(QPen(QColor(255, 255, 255)))
    font = QFont(painter.font())
    font.setBold(True)
    font.setPointSize(max(9, radius))
    painter.setFont(font)
    painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(number))
    painter.restore()


def settle(app: QApplication, rounds: int = 40) -> None:
    """Drain the event loop without blocking it.

    Sleeping here would be detected by the UI heartbeat as a stall and latched
    into the status bar, so the screenshot would advertise a freeze this harness
    itself caused.

    ``processEvents`` deliberately does not deliver ``DeferredDelete``: Qt holds
    those until the event loop that posted them returns, which never happens in
    a script that drives the UI by hand. A widget replaced during capture --
    the sidebar's "No sensor data loaded." note, once a file loads -- is then
    only *removed from its layout* and keeps painting at its last geometry, so
    the screenshot shows the placeholder overlapping the card that replaced it.
    A real user never sees that frame. Flushing them here makes the capture
    agree with the running application.
    """
    for _ in range(rounds):
        app.processEvents()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
