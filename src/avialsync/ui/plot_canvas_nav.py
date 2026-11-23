"""Direct canvas navigation for time-series plots: cursor-anchored zoom and drag pan.

Unmodified wheel events pass straight through to the vertical channel scroll area.
Holding ``Ctrl`` (or ``Cmd`` on macOS) zooms the shared time span around the
time under the mouse pointer; middle-button drag or ``Shift`` + left-drag pans
the shared viewport horizontally across master time without moving the playhead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pyqtgraph as pg
from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from avialsync.ui.plot_pane import PlotPane

__all__ = ["PlotCanvasNavigator"]

_ZOOM_FACTOR_PER_STEP = 0.80


@dataclass
class _PanDrag:
    start_x: float
    initial_view_start: float
    vb_width: float
    moved: bool = False


class PlotCanvasNavigator(QObject):
    """Event filter handling Ctrl+wheel zoom, middle/Shift+left pan, and hover exit."""

    def __init__(self, pane: PlotPane) -> None:
        super().__init__(pane)
        self._pane = pane
        self._pan: _PanDrag | None = None
        self.suppress_click = False
        self._views: dict[QWidget, pg.GraphicsLayoutWidget] = {}

    def attach(self, graphics_widget: pg.GraphicsLayoutWidget) -> None:
        """Install navigation filtering on *graphics_widget*'s viewport."""
        viewport = graphics_widget.viewport()
        if viewport is None:
            return
        self._views[viewport] = graphics_widget
        viewport.setMouseTracking(True)
        viewport.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if not isinstance(watched, QWidget) or watched not in self._views:
            return super().eventFilter(watched, event)
        graphics = self._views[watched]
        etype = event.type()

        if etype == QEvent.Type.Wheel and isinstance(event, QWheelEvent):
            return self._handle_wheel(graphics, event)
        if etype == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            return self._handle_press(graphics, watched, event)
        if etype == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
            return self._handle_move(watched, event)
        if etype == QEvent.Type.MouseButtonRelease and isinstance(event, QMouseEvent):
            return self._handle_release(watched, event)
        if etype == QEvent.Type.Leave:
            self._pane._interactions.clear_hover()
        return super().eventFilter(watched, event)

    def _viewbox_at(
        self, graphics: pg.GraphicsLayoutWidget, local_pos: QPointF
    ) -> pg.ViewBox | None:
        scene_pos = graphics.mapToScene(local_pos.toPoint())
        if self._pane.view_mode != "stacked":
            vb = self._pane._mode_view.plot_item.vb
            return vb if vb.sceneBoundingRect().contains(scene_pos) else vb
        for ch in self._pane.channels:
            if ch.visible and ch.plot_item.scene() is graphics.scene():
                vb = ch.plot_item.vb
                if vb.sceneBoundingRect().contains(scene_pos):
                    return vb
        for ch in self._pane.channels:
            if ch.visible and ch.plot_item.scene() is graphics.scene():
                return ch.plot_item.vb
        return None

    def _handle_wheel(self, graphics: pg.GraphicsLayoutWidget, event: QWheelEvent) -> bool:
        mods = event.modifiers()
        zoom_mod = bool(
            mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        )
        if not zoom_mod:
            return False
        if self._pane.sweep_start is None or self._pane.window_duration <= 0:
            return False
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta == 0:
            return True
        vb = self._viewbox_at(graphics, event.position())
        if vb is None:
            return False
        scene_pos = graphics.mapToScene(event.position().toPoint())
        x_view = float(vb.mapSceneToView(scene_pos).x())
        old_dur = self._pane.window_duration
        frac = min(1.0, max(0.0, x_view / old_dur))
        anchor_view_t = float(self._pane.sweep_start) + frac * old_dur
        steps = delta / 120.0
        new_dur = old_dur * (_ZOOM_FACTOR_PER_STEP**steps)
        self._pane.zoom_around_cursor(new_dur, anchor_view_t, frac)
        event.accept()
        return True

    def _handle_press(
        self, graphics: pg.GraphicsLayoutWidget, viewport: QWidget, event: QMouseEvent
    ) -> bool:
        is_pan = event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        )
        if not is_pan or self._pane.sweep_start is None:
            self.suppress_click = False
            return False
        vb = self._viewbox_at(graphics, event.position())
        if vb is None:
            return False
        vb_width = max(1.0, float(vb.sceneBoundingRect().width()))
        self._pan = _PanDrag(
            start_x=float(event.position().x()),
            initial_view_start=float(self._pane.sweep_start),
            vb_width=vb_width,
        )
        self.suppress_click = True
        viewport.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()
        return True

    def _handle_move(self, viewport: QWidget, event: QMouseEvent) -> bool:
        if self._pan is None:
            return False
        dx = float(event.position().x()) - self._pan.start_x
        if abs(dx) >= 2.0:
            self._pan.moved = True
        dt = -(dx / self._pan.vb_width) * self._pane.window_duration
        self._pane.set_manual_view_start(self._pan.initial_view_start + dt)
        viewport.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()
        return True

    def _handle_release(self, viewport: QWidget, event: QMouseEvent) -> bool:
        if self._pan is None:
            return False
        if event.button() not in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            return False
        self._pan = None
        viewport.unsetCursor()
        event.accept()
        return True
