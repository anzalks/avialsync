"""Stateful interaction controller for plot measurements, markers, and menus."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

from avialsync.ui.annotations import AnnotationStore
from avialsync.ui.plot_overlays import (
    redraw_annotations,
    redraw_gap_markers,
    redraw_measure_lines,
    show_context_menu,
)
from avialsync.ui.plot_row import Y_AUTO, Y_FIT_ONCE, Y_MANUAL

if TYPE_CHECKING:
    from avialsync.ui.plot_pane import PlotPane


class PlotInteractionController:
    """Own page-local overlay state while delegating semantic actions to PlotPane."""

    def __init__(self, pane: PlotPane) -> None:
        self._pane = pane
        self._extra_context_actions: list[QAction] = []
        self._measure_a: float | None = None
        self._measure_b: float | None = None
        self._measure_a_lines: list[pg.InfiniteLine] = []
        self._measure_b_lines: list[pg.InfiniteLine] = []
        self._annotation_store: AnnotationStore | None = None
        self._annotation_items: list[tuple[pg.PlotItem, object]] = []

    def set_context_actions(self, actions: list[QAction]) -> None:
        """Register shared QActions for the plot context menu."""
        self._extra_context_actions = list(actions)

    def set_measure_a(self, time: float) -> None:
        """Place measurement pin A and publish a complete A/B interval."""
        self._measure_a = time
        self.redraw_measure_lines()
        if self._measure_b is not None:
            self._pane.measure_changed.emit(min(time, self._measure_b), max(time, self._measure_b))

    def set_measure_b(self, time: float) -> None:
        """Place measurement pin B and publish a complete A/B interval."""
        self._measure_b = time
        self.redraw_measure_lines()
        if self._measure_a is not None:
            self._pane.measure_changed.emit(min(self._measure_a, time), max(self._measure_a, time))

    def clear_measure(self) -> None:
        """Remove both measurement pins."""
        self._measure_a = None
        self._measure_b = None
        self.redraw_measure_lines()

    def redraw_measure_lines(self) -> None:
        """Refresh measurement pins in the current shared page."""
        self._measure_a_lines, self._measure_b_lines = redraw_measure_lines(
            self._pane.channels,
            self._measure_a,
            self._measure_b,
            self._pane._display_x,
            self._measure_a_lines,
            self._measure_b_lines,
        )

    def set_gap_markers(self, channel_id: str, gap_times: list[float]) -> None:
        """Update stored gap evidence for one channel and redraw the page."""
        for channel in self._pane.channels:
            if channel.name == channel_id:
                channel.gap_times = tuple(gap_times)
                self.redraw_gap_markers()
                return

    def redraw_gap_markers(self) -> None:
        """Refresh all visible gap evidence."""
        redraw_gap_markers(self._pane.channels, self._pane._display_x)

    def set_annotation_store(self, store: AnnotationStore) -> None:
        """Subscribe to authoritative annotation changes once."""
        self._annotation_store = store
        store.changed.connect(self.redraw_annotations)
        self.redraw_annotations()

    def redraw_annotations(self) -> None:
        """Refresh page-local annotation graphics."""
        self._annotation_items = redraw_annotations(
            self._pane.channels,
            self._annotation_store,
            self._pane._display_x,
            self._pane.sweep_start,
            self._pane.window_duration,
            self._annotation_items,
        )

    def redraw_page_overlays(self) -> None:
        """Refresh overlays whose X coordinates depend on the current page."""
        self.redraw_gap_markers()
        self.redraw_measure_lines()
        self.redraw_annotations()

    def on_scene_clicked(self, event: Any) -> None:
        """Handle a right-click only when it lands inside a visible channel row."""
        if event.button() != Qt.MouseButton.RightButton or self._pane.sweep_start is None:
            return
        scene_pos = event.scenePos()
        channel = next(
            (
                candidate
                for candidate in self._pane.channels
                if candidate.visible
                and candidate.plot_item.vb.sceneBoundingRect().contains(scene_pos)
            ),
            None,
        )
        if channel is None:
            return
        choice = show_context_menu(
            event, channel, self._pane.sweep_start, self._extra_context_actions
        )
        if choice is None:
            return
        if choice.action == "annotate":
            self._pane.annotate_at_requested.emit(choice.time)
        elif choice.action == "measure_a":
            self.set_measure_a(choice.time)
        elif choice.action == "measure_b":
            self.set_measure_b(choice.time)
        elif choice.action == "clear_measure":
            self.clear_measure()
        elif choice.action == "fit_y":
            self._pane.set_channel_y_mode(choice.channel_id, Y_FIT_ONCE)
        elif choice.action == "auto_y":
            self._pane.set_channel_y_mode(choice.channel_id, Y_AUTO)
        elif choice.action == "hold_y":
            self._pane.set_channel_y_mode(choice.channel_id, Y_MANUAL)
        event.accept()
