"""Apply linked plot geometry once after every row has resized."""

from collections.abc import Callable

import pyqtgraph as pg
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid


class PlotStackView(pg.GraphicsLayoutWidget):
    """Keep the existing ViewBox links coherent through a synchronous relayout.

    Qt resizes rows sequentially. A master's resize signal otherwise aligns
    children against their old geometry, publishing wrong intermediate ranges
    and then undoing that work when each child resizes. Defer only that link
    calculation until the complete layout has its new geometry.
    """

    def __init__(
        self, views: Callable[[], list[pg.ViewBox | None]], parent: QWidget | None = None
    ) -> None:
        self._views = views
        super().__init__(parent)

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        """Restore pre-existing link blocks even if the layout raises."""
        states = [
            (view, view.linksBlocked)
            for view in self._views()
            if view is not None and isValid(view)
        ]
        for view, _blocked in states:
            view.blockLink(True)
        try:
            super().resizeEvent(event)
        finally:
            for view, blocked in states:
                view.blockLink(blocked)
        try:
            for view, blocked in states:
                if not blocked:
                    view.linkedXChanged()
                    view.linkedYChanged()
        finally:
            # pyqtgraph's link calculation unconditionally releases its
            # target's block. Preserve blocks owned by another caller too.
            for view, blocked in states:
                view.blockLink(blocked)
