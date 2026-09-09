"""A pane splitter whose draggable boundary is visible in every appearance.

Qt's own splitter handle is not faint, it is *short*. Measured on a 600 px
boundary: the style's centre grip reaches a lightness contrast of 0.31 against
the window on the Dark appearance and 0.22 on Light — plenty — but it marks
only 12 and 6 columns respectively, a ~16 px speck in the middle of an edge as
wide as the window. Between the video, 3D, plot and Data Streams panes that
reads as a smudge rather than as a boundary, which is why the workspace looked
like it had no separators at all.

So this trades intensity for extent: one quieter rule running the entire
length, which is what makes an edge legible as an edge and says where the whole
draggable boundary is rather than where its middle happens to be.

What this does *not* do matters as much. It paints inside the handle Qt already
lays out: handle width, hit area, drag behaviour, collapse rules and every
pane's geometry are untouched, so it changes what the boundary looks like and
nothing about how it works (AGENTS, "themes are appearance-only"). It is not a
stylesheet either — an application stylesheet wraps Qt's style engine and can
move control metrics, which is the thing that rule exists to prevent.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QEnterEvent, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import QSplitter, QSplitterHandle

from avialsync.ui.theme import separator_color


class _PaneHandle(QSplitterHandle):
    """One boundary, drawn as a hairline rule that answers to the pointer."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        # Qt tracks hover for a widget only when asked. Without this the rule
        # never brightens, and the boundary gives no sign that it is grabbable.
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Fill with the window surface, then lay one rule down the middle.

        Deliberately not a call up to ``QSplitterHandle.paintEvent``: the
        style's own grip is the thing that is invisible under a light palette,
        and drawing over it would leave that artefact underneath.
        """
        del event
        painter = QPainter(self)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.color(QPalette.ColorRole.Window))
        painter.setPen(separator_color(palette, active=self.underMouse()))
        bounds = self.rect()
        if self.orientation() == Qt.Orientation.Horizontal:
            # A horizontal splitter lays its panes out left-to-right, so the
            # boundary between two of them is a *vertical* rule.
            middle = bounds.center().x()
            painter.drawLine(middle, bounds.top(), middle, bounds.bottom())
        else:
            middle = bounds.center().y()
            painter.drawLine(bounds.left(), middle, bounds.right(), middle)

    def enterEvent(self, event: QEnterEvent) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event: QEvent) -> None:
        super().leaveEvent(event)
        self.update()

    def changeEvent(self, event: QEvent) -> None:
        """Repaint for a new appearance; a self-painting widget has to ask."""
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self.update()


class PaneSplitter(QSplitter):
    """A :class:`QSplitter` whose boundaries can be seen in both appearances."""

    def createHandle(self) -> QSplitterHandle:
        """Return the drawn handle in place of the style's own."""
        return _PaneHandle(self.orientation(), self)
