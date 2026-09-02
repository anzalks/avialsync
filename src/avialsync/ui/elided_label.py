"""A label that shortens its text instead of widening its parent.

``QLabel`` reports the full width of its text as its minimum, and a file path
is one long unbreakable token: ``setWordWrap(True)`` finds nowhere to break it,
so the label keeps demanding its full width and the sidebar it sits in is
pushed past the viewport. Measured on a real session path -- 98 characters, a
sensible depth for lab storage -- a source panel's minimum went from 187 px to
491 px, and with the sidebar's horizontal scrollbar off the surplus was not
scrolled to, it was cut off.

Elision fixes it at the right level. The label takes whatever width the layout
has, and fits its text to that width, so no path length can ever set the
sidebar's minimum again.

Where to put the ellipsis is a real choice, not a detail. The default here is
:attr:`Qt.TextElideMode.ElideMiddle`, because the two informative parts of a
path are its beginning and its end -- which drive it is in and which file it
is -- and the interchangeable directories are in between. ``ElideRight`` on a
path shows the user a column of identical prefixes.

The full text is always the tooltip, so nothing is lost by shortening it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

__all__ = ["ElidedLabel"]


class ElidedLabel(QLabel):
    """A ``QLabel`` that elides to its available width.

    Use it anywhere the text is data rather than interface -- a path, a
    filename, a channel name -- where the string's length is the user's choice
    and must not become a layout constraint.
    """

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle,
    ) -> None:
        super().__init__(parent)
        self._mode = mode
        self._full_text = ""
        # `Ignored` is the part that does the work. Without it the label still
        # reports its full text width as a minimum and nothing below changes.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802  (Qt naming)
        """Store the full text, display as much of it as fits."""
        self._full_text = text
        if not self.toolTip() or self.toolTip() == self._full_text:
            self.setToolTip(text)
        self._relayout_text()

    def fullText(self) -> str:  # noqa: N802  (Qt naming)
        """The unabridged text, whatever is currently displayed."""
        return self._full_text

    def text(self) -> str:
        """The full text, so callers reading it back get what they set.

        Returning the elided form here would leak ellipses into anything that
        copies a path out of the interface.
        """
        return self._full_text

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802  (Qt naming)
        super().resizeEvent(event)
        self._relayout_text()

    def _relayout_text(self) -> None:
        metrics = QFontMetrics(self.font())
        available = max(
            0, self.width() - self.contentsMargins().left() - self.contentsMargins().right()
        )
        if available <= 0:
            # Before the first layout pass there is no width to fit to. Show
            # the full text; the resize event that follows will trim it.
            QLabel.setText(self, self._full_text)
            return
        QLabel.setText(self, metrics.elidedText(self._full_text, self._mode, available))

    def minimumSizeHint(self):  # noqa: ANN201
        """A few characters' worth, never the whole string."""
        hint = super().minimumSizeHint()
        hint.setWidth(min(hint.width(), QFontMetrics(self.font()).horizontalAdvance("…" * 8)))
        return hint
