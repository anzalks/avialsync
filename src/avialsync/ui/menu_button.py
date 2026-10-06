"""A glyph button that opens a menu, drawn like every other glyph button (D-181).

``setMenu`` makes the platform style draw a drop-down arrow under or beside the
glyph -- on macOS a small chevron below the ``⋯`` -- so overflow buttons looked
unlike the glyph buttons beside them. This button keeps its menu
to itself and opens it on click, so it draws exactly as a plain tool button
does: one glyph, no arrow.
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QMenu, QPushButton, QWidget

from avialsync.ui.design_tokens import ControlRole
from avialsync.ui.icons import set_svg_icon

__all__ = ["MenuGlyphButton"]


class MenuGlyphButton(QPushButton):
    """Glyph *glyph*; a click opens :meth:`menu`, which Qt itself never sees."""

    def __init__(self, glyph: str, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # A flat push button, as every other glyph in the window is: macOS draws
        # a QToolButton with a frame, which made overflow glyphs look boxed.
        self.setFlat(True)
        self.setIconSize(QSize(16, 16))
        self.setAccessibleName(name)
        self.setToolTip(name)
        self.setProperty("av_role", str(ControlRole.TOOL))
        set_svg_icon(self, glyph)
        self._menu = QMenu(self)
        self._menu.setAccessibleName(name)
        self.clicked.connect(self.show_menu)

    def menu(self) -> QMenu:
        """The button's menu; kept from Qt so the style draws no arrow."""
        return self._menu

    def show_menu(self) -> None:
        """Open the menu under the button without blocking (no ``exec``)."""
        self._menu.popup(self.mapToGlobal(self.rect().bottomLeft()))
