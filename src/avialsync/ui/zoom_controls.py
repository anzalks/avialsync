"""Zoom in, zoom out and reset: one strip of glyph buttons for every picture pane.

The video, two-photon and 3D panes each carry their own strip and their own
zoom; only the look is shared, so the three read as one control wherever it
appears. The owner places the strip over its picture (bottom left, as the video
pane always has) and connects the signals to its own view.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from avialsync.ui.design_tokens import spacing
from avialsync.ui.i18n import tr
from avialsync.ui.icons import set_svg_icon

__all__ = ["ZOOM_STEP", "ZoomControls"]

#: Factor one button press zooms by.
ZOOM_STEP = 1.25


class ZoomControls(QWidget):
    """Three 24 px glyph buttons that ask the owning view to zoom or reset."""

    zoom_in_requested = Signal()
    zoom_out_requested = Signal()
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = self._layout = QHBoxLayout(self)
        layout.setContentsMargins(spacing("s"), spacing("s"), spacing("s"), spacing("s"))
        layout.setSpacing(0)

        # Glyph-only: the "+" and "-" text beside the glyphs said the same twice.
        self.zoom_in_button = self._button("zoom-in", tr("Zoom in"))
        self.zoom_in_button.clicked.connect(self.zoom_in_requested)
        self.zoom_out_button = self._button("zoom-out", tr("Zoom out"))
        self.zoom_out_button.clicked.connect(self.zoom_out_requested)
        # Inked like the zoom glyphs rather than in the platform's full-colour
        # reload artwork, which was the one blue mark in the strip.
        self.reset_zoom_button = self._button("reset", tr("Reset zoom"))
        self.reset_zoom_button.clicked.connect(self.reset_requested)
        for button in (self.zoom_in_button, self.zoom_out_button, self.reset_zoom_button):
            layout.addWidget(button)

    def add_glyph_button(self, glyph: str, name: str) -> QPushButton:
        """Add an owner-specific button to the strip, drawn like the zoom ones.

        For a control that belongs to the picture as much as zoom does -- a
        camera's display levels -- so it sits with them rather than in a
        toolbar that acts on every pane at once.
        """
        button = self._button(glyph, name)
        self._layout.addWidget(button)
        return button

    def _button(self, glyph: str, name: str) -> QPushButton:
        button = QPushButton(self)
        set_svg_icon(button, glyph)
        button.setToolTip(name)
        button.setAccessibleName(name)
        button.setFlat(False)
        button.setFixedSize(24, 24)
        return button
