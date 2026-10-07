"""The workspace column scrolls when the window is shorter than it (D-182).

Every pane in the column -- videos, 3D, plots, Data Streams, transport -- has
a floor, and their sum is the window's minimum height. At the default font it
fits a 640x480 display; at 16 pt it needed 487 px and at 20 pt 545 px, and a
minimum taller than the display leaves the window unresizable and the bottom of
it unreachable. Each pane is already near its floor, so shrinking panes cannot
cover every font size.

Instead the column sits in a scroll area. When the window is taller than the
column's minimum -- every ordinary case -- the area hands the column the whole
viewport and draws nothing of its own. Only when it is shorter does a vertical
scrollbar appear, so every surface stays reachable rather than the window
refusing to shrink.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget

from avialsync.ui.i18n import tr

__all__ = ["scroll_when_short"]


def scroll_when_short(column: QWidget) -> QScrollArea:
    """Wrap *column* so a short window scrolls it instead of growing past the display."""
    area = QScrollArea()
    area.setObjectName("workspace_scroll")
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setWidget(column)
    # After setWidget, which turns the content's fill back on: the column reads
    # as the window's surface, not as a box inside it.
    column.setAutoFillBackground(False)
    area.viewport().setAutoFillBackground(False)
    area.verticalScrollBar().setAccessibleName(tr("Scroll the workspace"))
    area.horizontalScrollBar().setAccessibleName(tr("Scroll the workspace sideways"))
    return area
