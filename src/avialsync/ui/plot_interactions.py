"""Stateful interaction controller for plot measurements, markers, and menus."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

from avialsync.core.channel_reader import ChannelKey
from avialsync.ui.annotations import AnnotationStore
from avialsync.ui.axis_nav import show_plot_exporter
from avialsync.ui.plot_crosshair import HoverCrosshair, redraw_measure_callouts
from avialsync.ui.plot_modes import toggle_channel_pin
from avialsync.ui.plot_overlays import (
    redraw_annotations,
    redraw_gap_markers,
    redraw_identity_markers,
    redraw_measure_lines,
    show_context_menu,
    show_mode_context_menu,
)
from avialsync.ui.plot_row import Y_AUTO, Y_FIT_ONCE, Y_MANUAL, ChannelPlot, reveal_row_tools

if TYPE_CHECKING:
    from avialsync.ui.plot_pane import PlotPane

logger = logging.getLogger(__name__)


class PlotInteractionController:
    """Own page-local overlay state while delegating semantic actions to PlotPane."""

    def __init__(self, pane: PlotPane) -> None:
        self._pane = pane
        self._extra_context_actions: list[QAction] = []
        self._measure_a: float | None = None
        self._measure_b: float | None = None
        self._measure_a_lines: list[pg.InfiniteLine] = []
        self._measure_b_lines: list[pg.InfiniteLine] = []
        self._measure_callout_items: list[tuple[pg.PlotItem, object]] = []
        self._hover = HoverCrosshair()
        self._last_hovered_key: ChannelKey | None = None
        self._annotation_store: AnnotationStore | None = None
        self._annotation_items: list[tuple[pg.PlotItem, object]] = []
        self._identity_events: dict[str, tuple[tuple[float, str], ...]] = {}
        self._identity_items: list[tuple[pg.PlotItem, pg.InfiniteLine]] = []
        self._segment_bounds: tuple[float, ...] = ()
        self._segment_items: list[tuple[pg.PlotItem, pg.InfiniteLine]] = []
        self._gap_times: dict[ChannelKey | str, tuple[float, ...]] = {}

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

    def _real_channels(self) -> list[ChannelPlot]:
        return [ch for ch in self._pane.channels if isinstance(ch, ChannelPlot)]

    def _overlay_targets(self) -> list[Any]:
        """Return stacked rows plus the Overlaid/Heatmap canvas when channels exist."""
        rows = self._real_channels()
        targets: list[Any] = list(rows)
        mode_view = getattr(self._pane, "_mode_view", None)
        if mode_view is not None and getattr(mode_view, "plot_item", None) is not None:
            has_visible = any(ch.visible for ch in rows)
            targets.append(SimpleNamespace(plot_item=mode_view.plot_item, visible=has_visible))
        return targets

    def redraw_measure_lines(self) -> None:
        """Refresh measurement pins in the current shared page."""
        self._measure_a_lines, self._measure_b_lines = redraw_measure_lines(
            self._overlay_targets(),
            self._measure_a,
            self._measure_b,
            self._pane._display_x,
            self._measure_a_lines,
            self._measure_b_lines,
            self._pane.palette(),
        )
        self._measure_callout_items = redraw_measure_callouts(
            self._real_channels(),
            self._measure_a,
            self._measure_b,
            self._pane.x_range,
            self._measure_callout_items,
            self._pane.palette(),
        )

    def clear_hover(self) -> None:
        """Hide hover crosshair and notify listeners when pointer exits the plots."""
        if self._last_hovered_key is not None:
            self._last_hovered_key = None
            self._pane.hovered_channel_changed.emit(None)
        if self._hover.clear():
            self._pane.hover_time_changed.emit(None)

    def set_gap_markers(self, channel_id: ChannelKey | str, gap_times: list[float]) -> None:
        """Update stored gap evidence for one channel and redraw the page."""
        stored = tuple(gap_times)
        self._gap_times[channel_id] = stored
        matched = False
        for channel in self._pane.channels:
            matches = (
                channel.reader.key == channel_id
                if isinstance(channel_id, ChannelKey)
                else channel.name == channel_id
            )
            if matches:
                channel.gap_times = stored
                matched = True
        if matched:
            self.redraw_gap_markers()

    def gap_times_for(self, key: ChannelKey, name: str) -> tuple[float, ...]:
        """Return queued gap evidence for a newly constructed row, if any."""
        if key in self._gap_times:
            return self._gap_times[key]
        return self._gap_times.get(name, ())

    def forget_gap_markers(self, key: ChannelKey) -> None:
        """Drop queued gap evidence for a removed source channel."""
        self._gap_times.pop(key, None)

    def clear_gap_markers(self) -> None:
        """Drop all queued gap evidence when clearing sources."""
        self._gap_times.clear()

    def redraw_gap_markers(self) -> None:
        """Refresh all visible gap evidence."""
        redraw_gap_markers(self._real_channels(), self._pane._display_x, self._pane.palette())

    def set_identity_events(self, source_id: str, events: list[tuple[float, str]]) -> None:
        """Show accepted flips from one source on that source's plot rows."""
        self._identity_events[source_id] = tuple(events)
        self.redraw_identity_markers()

    def redraw_identity_markers(self) -> None:
        """Refresh page-local flip boundaries from the accepted event store."""
        self._identity_items = redraw_identity_markers(
            self._real_channels(),
            self._identity_events,
            self._pane._display_x,
            self._pane.palette(),
            self._identity_items,
        )

    def set_segment_boundaries(self, times: list[float]) -> None:
        """Mark where the recording's trials meet, on every plot row."""
        self._segment_bounds = tuple(sorted(times))
        self.redraw_segment_boundaries()

    def redraw_segment_boundaries(self) -> None:
        """Draw the trial boundaries that fall on the visible page."""
        for plot_item, line in self._segment_items:
            try:
                plot_item.removeItem(line)
            except RuntimeError:
                logger.debug("Plot item was already deleted", exc_info=True)
        self._segment_items = []
        if not self._segment_bounds:
            return
        palette = self._pane.palette()
        pen = pg.mkPen(palette.color(palette.ColorRole.Mid), width=1, style=Qt.PenStyle.DashLine)
        for channel in self._overlay_targets():
            if not channel.visible:
                continue
            for time in self._segment_bounds:
                x = self._pane._display_x(time)
                if x is None:
                    continue
                line = pg.InfiniteLine(pos=x, angle=90, movable=False, pen=pen)
                line.setZValue(2)
                channel.plot_item.addItem(line)
                self._segment_items.append((channel.plot_item, line))

    def set_annotation_store(self, store: AnnotationStore) -> None:
        """Subscribe to authoritative annotation changes once."""
        self._annotation_store = store
        store.changed.connect(self.redraw_annotations)
        self.redraw_annotations()

    def redraw_annotations(self) -> None:
        """Refresh page-local annotation graphics."""
        store = self._annotation_store
        self._annotation_items = redraw_annotations(
            self._overlay_targets(),
            store,
            self._pane._display_x,
            self._pane.x_range,
            self._annotation_items,
            master_at=self._pane.master_at,
            x_of=self._pane.x_of,
            on_marker_moved=store.set_span if store is not None else None,
        )

    def redraw_page_overlays(self) -> None:
        """Refresh overlays whose X coordinates depend on the current page."""
        self.redraw_gap_markers()
        self.redraw_measure_lines()
        self.redraw_annotations()
        self.redraw_identity_markers()
        self.redraw_segment_boundaries()

    def on_scene_moved(self, scene_pos: Any, scene: object = None) -> None:
        """Reveal row tools and update synchronized hover crosshair on pointer motion."""
        scene_rows = [
            ch for ch in self._pane.channels if scene is None or ch.plot_item.scene() is scene
        ]
        reveal_row_tools(scene_rows, float(scene_pos.y()))
        if self._pane.sweep_start is None or self._pane.window_duration <= 0:
            return
        hovered = next(
            (
                candidate
                for candidate in scene_rows
                if candidate.visible
                and candidate.plot_item.vb.sceneBoundingRect().contains(scene_pos)
            ),
            None,
        )
        if hovered is None:
            self.clear_hover()
            return
        if hovered.reader.key != self._last_hovered_key:
            self._last_hovered_key = hovered.reader.key
            self._pane.hovered_channel_changed.emit(hovered.reader.key)
        x_page = float(hovered.plot_item.vb.mapSceneToView(scene_pos).x())
        x_clamped = min(self._pane.window_duration, max(0.0, x_page))
        t_master = self._pane.master_at(x_clamped)
        self._hover.update(self._pane.channels, hovered, x_clamped, t_master, self._pane.palette())
        self._pane.hover_time_changed.emit(t_master)

    def on_scene_clicked(self, event: Any, scene: object = None) -> None:
        """Seek on left-clicks and show actions for right-clicks in visible rows."""
        nav = getattr(self._pane, "_navigator", None)
        if nav is not None and nav.suppress_click:
            nav.suppress_click = False
            return
        if self._pane.sweep_start is None:
            return
        scene_pos = event.scenePos()
        channel = next(
            (
                candidate
                for candidate in self._pane.channels
                if candidate.visible
                and (scene is None or candidate.plot_item.scene() is scene)
                and candidate.plot_item.vb.sceneBoundingRect().contains(scene_pos)
            ),
            None,
        )
        if channel is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            mods = (
                event.modifiers() if hasattr(event, "modifiers") else Qt.KeyboardModifier.NoModifier
            )
            if bool(mods & Qt.KeyboardModifier.ShiftModifier):
                return
            view_pos = channel.plot_item.vb.mapSceneToView(scene_pos)
            self._pane.seek_requested.emit(self._pane.master_at(float(view_pos.x())))
            event.accept()
            return
        if event.button() != Qt.MouseButton.RightButton:
            return
        choice = show_context_menu(
            event, channel, self._pane.master_at, self._extra_context_actions
        )
        if choice is not None:
            self._apply_context_choice(choice, channel)
            event.accept()

    def _apply_context_choice(self, choice: Any, channel: Any) -> None:
        target: ChannelKey | str = (
            choice.channel_key if choice.channel_key is not None else choice.channel_id
        )
        if choice.action == "annotate":
            self._pane.annotate_at_requested.emit(choice.time)
        elif choice.action == "measure_a":
            self.set_measure_a(choice.time)
        elif choice.action == "measure_b":
            self.set_measure_b(choice.time)
        elif choice.action == "clear_measure":
            self.clear_measure()
        elif choice.action == "fit_y":
            self._pane.set_channel_y_mode(target, Y_FIT_ONCE)
        elif choice.action == "auto_y":
            self._pane.set_channel_y_mode(target, Y_AUTO)
        elif choice.action == "hold_y":
            self._pane.set_channel_y_mode(target, Y_MANUAL)
        elif choice.action == "pin":
            toggle_channel_pin(self._pane, target)
        elif choice.action == "export":
            show_plot_exporter(channel.plot_item)
        elif choice.action == "hide":
            self._pane.hide_channel_row(target)

    def on_mode_moved(self, scene_pos: Any) -> None:
        """Update synchronized hover hairline over the Overlaid / Heatmap canvas."""
        mode_view = getattr(self._pane, "_mode_view", None)
        if mode_view is None or self._pane.sweep_start is None or self._pane.window_duration <= 0:
            return
        vb = mode_view.plot_item.vb
        if not vb.sceneBoundingRect().contains(scene_pos):
            self.clear_hover()
            return
        x_page = float(vb.mapSceneToView(scene_pos).x())
        x_clamped = min(self._pane.window_duration, max(0.0, x_page))
        t_master = self._pane.master_at(x_clamped)
        targets = self._overlay_targets()
        self._hover.update(targets, None, x_clamped, t_master, self._pane.palette())
        self._pane.hover_time_changed.emit(t_master)

    def on_mode_context_menu(self, event: Any) -> None:
        """Show time-axis context menu on Overlaid / Heatmap canvas."""
        mode_view = getattr(self._pane, "_mode_view", None)
        if mode_view is None or self._pane.sweep_start is None:
            return
        choice = show_mode_context_menu(
            event, mode_view.plot_item, self._pane.master_at, self._extra_context_actions
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
