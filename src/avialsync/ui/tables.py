"""A table whose grid lines follow the theme.

``QTableView`` takes its grid colour from the style hint
``SH_Table_GridLineColor``, not from the palette, and the macOS style answers a
fixed near-black (measured ``#141414``) under the Dark and Light appearances
alike: a hard black lattice on a white table, and a darker one than the surface
on a dark table. No palette role reaches it, and a stylesheet would hand the
whole table, scrollbars included, to Qt's stylesheet style.

:class:`ThemedTable` keeps Qt's grid geometry -- the reserved pixel between
cells, which cell widgets and editors already respect -- and repaints those
same pixels in :func:`theme.separator_color` after Qt has drawn them. Use it
wherever a ``QTableWidget`` shows its grid.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QTableWidget

from avialsync.ui.theme import separator_color


def _visible(first: int, last: int, count: int) -> range:
    """Indices from *first* to *last*, where -1 means "past the end"."""
    if count <= 0:
        return range(0)
    start = 0 if first < 0 else first
    stop = count - 1 if last < 0 else last
    return range(start, stop + 1)


class ThemedTable(QTableWidget):
    """A ``QTableWidget`` whose grid is drawn in the theme's separator colour."""

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        if not self.showGrid():
            return
        viewport = self.viewport()
        rows = [
            row
            for row in _visible(self.rowAt(0), self.rowAt(viewport.height() - 1), self.rowCount())
            if not self.isRowHidden(row)
        ]
        columns = [
            column
            for column in _visible(
                self.columnAt(0), self.columnAt(viewport.width() - 1), self.columnCount()
            )
            if not self.isColumnHidden(column)
        ]
        if not rows or not columns:
            return

        left = self.columnViewportPosition(columns[0])
        right = self.columnViewportPosition(columns[-1]) + self.columnWidth(columns[-1]) - 1
        top = self.rowViewportPosition(rows[0])
        bottom = self.rowViewportPosition(rows[-1]) + self.rowHeight(rows[-1]) - 1

        # Filled, not stroked: a one-pixel pen is centred on the coordinate, so
        # on a 2x display it covered one device row of Qt's own two and left
        # half of the black line showing beside it -- measured.
        colour = separator_color(self.palette())
        painter = QPainter(viewport)
        try:
            for row in rows:
                y = self.rowViewportPosition(row) + self.rowHeight(row) - 1
                painter.fillRect(left, y, right - left + 1, 1, colour)
            for column in columns:
                x = self.columnViewportPosition(column) + self.columnWidth(column) - 1
                painter.fillRect(x, top, 1, bottom - top + 1, colour)
        finally:
            painter.end()
