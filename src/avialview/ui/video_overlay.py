"""Transparent tracking overlay used by :mod:`avialview.ui.video_pane`."""

from __future__ import annotations

from typing import Any

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget


class PaintCanvas(QWidget):
    """Paint the current tracking points without obscuring video."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAutoFillBackground(False)
        self.readers: list[Any] = []
        self.t = 0.0

    def set_readers(self, readers: list[Any]) -> None:
        self.readers = readers
        self.update()

    def update_time(self, t: float) -> None:
        self.t = t
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw only complete XY points at the current source time."""
        del event
        if not self.readers:
            return
        pane = self.parent()
        player = getattr(pane, "mpv", None)
        if player is None:
            return
        try:
            video_width = player.dwidth
            video_height = player.dheight
        except (AttributeError, RuntimeError):
            return
        if not video_width or not video_height:
            return

        points: dict[str, dict[str, float]] = {}
        for reader in self.readers:
            value = reader.value_at(self.t)
            if np.isnan(value):
                continue
            for suffix in ("_x", "_y"):
                if reader.channel_id.endswith(suffix):
                    points.setdefault(reader.channel_id[:-2], {})[suffix[1:]] = value

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(0, 255, 255), 3))
        painter.setBrush(QColor(0, 255, 255))
        scale = min(self.width() / video_width, self.height() / video_height)
        offset_x = (self.width() - video_width * scale) / 2.0
        offset_y = (self.height() - video_height * scale) / 2.0
        for point in points.values():
            if "x" not in point or "y" not in point:
                continue
            x = offset_x + point["x"] * scale
            y = offset_y + point["y"] * scale
            painter.drawEllipse(int(x) - 3, int(y) - 3, 6, 6)
