"""Plot rendering pane using pyqtgraph and decimation pyramids."""

import logging
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from avialview.ui.plot_row import (
    ChannelPlot,
    apply_channel_visibility,
    create_channel_plot,
    enforce_channel_visibility,
    point_budget_for_width,
    refresh_channel_plot,
    update_channel_coverage,
)
from avialview.ui.plot_sweep import SweepWindowControl

logger = logging.getLogger(__name__)


class PlotPane(QWidget):
    """
    Data plotting pane for multiple time-series channels.

    Uses pyqtgraph GraphicsLayoutWidget to stack channels vertically.
    All channels share the same X-axis.
    """

    # Emitted when the set of active readers changes so ReadoutPanel can refresh
    sources_changed = Signal(list)  # list[PyramidReader]
    # Emitted when both measure points are set (t_a, t_b)
    measure_changed = Signal(float, float)
    # Emitted when user picks "Add marker here" from the plot context menu (D-022)
    annotate_at_requested = Signal(float)  # t in master-clock seconds
    # Emitted by the row close button; MainWindow mirrors it to the sidebar checkbox.
    channel_close_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        _layout = QVBoxLayout()
        _layout.setContentsMargins(0, 0, 0, 0)
        _layout.setSpacing(0)
        self.setLayout(_layout)

        self._apply_palette()

        self.graphics_layout = pg.GraphicsLayoutWidget()
        self.graphics_layout.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        _layout.addWidget(self.graphics_layout)

        self._sweep_control = SweepWindowControl(self)
        self._sweep_control.window_changed.connect(self._on_window_changed)
        self.window_limit_spin = self._sweep_control.limit_spin
        self.window_unit_combo = self._sweep_control.unit_combo
        self.window_slider = self._sweep_control.slider
        self.window_value_label = self._sweep_control.value_label
        _layout.addWidget(self._sweep_control)
        self._resize_refresh_timer = QTimer(self)
        self._resize_refresh_timer.setSingleShot(True)
        self._resize_refresh_timer.setInterval(75)
        self._resize_refresh_timer.timeout.connect(self._refresh_after_resize)
        self._last_point_budget = 0

        # State
        self.channels: list[ChannelPlot] = []
        self.follow_playhead = True

        self._annotation_store = None
        self._annotation_items: list[tuple[pg.PlotItem, object]] = []

        # Measure markers (A/B pins for Δ measurement, separate from loop A/B)
        self._measure_a: float | None = None
        self._measure_b: float | None = None
        self._measure_a_lines: list[pg.InfiniteLine] = []
        self._measure_b_lines: list[pg.InfiniteLine] = []

        # The first plot is the single X-range authority for every linked row.
        self._master_plot: pg.PlotItem | None = None

        # Extra QAction objects injected by MainWindow (e.g. reset-zoom) so
        # the context menu shares the exact same action instances as the menu bar.
        self._extra_context_actions: list = []

        # Right-click context menu on the plot scene
        self.graphics_layout.scene().sigMouseClicked.connect(self._on_scene_clicked)

    def changeEvent(self, event: QEvent) -> None:
        """Keep pyqtgraph's canvas aligned with an application palette change."""
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self._apply_palette()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Coalesce resize storms before selecting a new pyramid resolution."""
        super().resizeEvent(event)
        enforce_channel_visibility(self.channels)
        if self.channels and self.sweep_start is not None:
            self._resize_refresh_timer.start()

    def _apply_palette(self) -> None:
        """Apply the active Qt palette to pyqtgraph's global canvas settings."""
        palette = self.palette()
        pg.setConfigOption("background", palette.color(palette.ColorRole.Base).name())
        pg.setConfigOption("foreground", palette.color(palette.ColorRole.Text).name())

    def load_channels(self, cache_dir: Path, channel_names: list[str]) -> None:
        """Load multiple data sources from cache and build plot rows."""
        if not channel_names:
            return

        start_row = len(self.channels)

        for i, ch_name in enumerate(channel_names):
            channel = create_channel_plot(
                self.graphics_layout,
                start_row + i,
                cache_dir,
                ch_name,
                start_row + i,
                self._request_channel_close,
            )
            if self._master_plot is None:
                self._master_plot = channel.plot_item
            else:
                channel.plot_item.setXLink(self._master_plot)
            self.channels.append(channel)

        self._configure_shared_x_range()
        self._set_sweep_for_time(self._sweep_control.last_master_time, force=True)
        self.sources_changed.emit([ch.reader for ch in self.channels])
        self._redraw_annotations()

    def remove_channels(self, cache_dir: Path) -> None:
        """Remove all channels associated with a specific cache_dir (source)."""
        to_remove = [ch for ch in self.channels if ch.reader.cache_dir == cache_dir]
        for ch in to_remove:
            self.graphics_layout.removeItem(ch.plot_item)
            self.graphics_layout.removeItem(ch.close_proxy)
            self.channels.remove(ch)

            if self._master_plot == ch.plot_item:
                self._master_plot = self.channels[0].plot_item if self.channels else None

        self._link_x_axes()

        self.sources_changed.emit([ch.reader for ch in self.channels])
        self._redraw_annotations()

    def remove_channel(self, channel_id: str) -> None:
        """Remove a single channel by its channel_id, regardless of cache_dir."""
        to_remove = [ch for ch in self.channels if ch.reader.channel_id == channel_id]
        for ch in to_remove:
            self.graphics_layout.removeItem(ch.plot_item)
            self.graphics_layout.removeItem(ch.close_proxy)
            self.channels.remove(ch)

            if self._master_plot == ch.plot_item:
                self._master_plot = self.channels[0].plot_item if self.channels else None

        self._link_x_axes()

        self.sources_changed.emit([ch.reader for ch in self.channels])
        self._redraw_annotations()

    def load_source(self, cache_dir: Path, channel_id: str) -> None:
        """Backwards compatibility for Phase 2 single-channel load."""
        self.load_channels(cache_dir, [channel_id])

    def update_plots(self) -> None:
        """Refresh the current sweep from the decimation pyramid."""
        if self.sweep_start is None or not self.channels:
            return

        t0 = self.sweep_start
        t1 = t0 + self.window_duration
        point_budget = point_budget_for_width(int(self.graphics_layout.viewport().width()))
        self._last_point_budget = point_budget

        for ch in self.channels:
            if not ch.visible:
                continue
            refresh_channel_plot(ch, t0, t1, point_budget)

    def set_cursor(self, t: float) -> None:
        """Advance the fixed sweep from the master-clock time."""
        self._set_sweep_for_time(t)

    def set_zoom_window(self, seconds: float) -> None:
        """Compatibility alias for setting the shared continuous window."""
        self.set_window_duration(seconds)

    def set_window_duration(self, seconds: float) -> None:
        """Set the fixed sweep duration shared by every plot row."""
        if seconds <= 0:
            self.reset_zoom()
            return
        self._sweep_control.set_window_duration(seconds)

    def set_follow_playhead(self, follow: bool) -> None:
        """Retain the legacy state flag without creating another navigation model."""
        self.follow_playhead = follow

    def set_channel_visible(self, channel_id: str, visible: bool) -> None:
        """Show or hide a specific channel's plot row."""
        for ch in self.channels:
            if ch.name == channel_id:
                ch.visible = visible
                apply_channel_visibility(ch)
                if visible:
                    if self.sweep_start is not None:
                        refresh_channel_plot(
                            ch,
                            self.sweep_start,
                            self.sweep_start + self.window_duration,
                            point_budget_for_width(int(self.graphics_layout.viewport().width())),
                        )
                        self._redraw_sweep_overlays()
                break

    def reset_zoom(self) -> None:
        """Set the shared sweep window to the full master-timeline duration."""
        self._sweep_control.reset_window()
        for ch in self.channels:
            ch.plot_item.enableAutoRange(axis="y")

    def zoom_in(self) -> None:
        """Move the shared continuous X-window slider one small step inward."""
        self._sweep_control.zoom_in()

    def zoom_out(self) -> None:
        """Move the shared continuous X-window slider one small step outward."""
        self._sweep_control.zoom_out()

    def set_timeline_bounds(self, t0: float, t1: float) -> None:
        """Set the master bounds used to anchor deterministic sweep restarts."""
        self._sweep_control.set_bounds(t0, t1)

    @property
    def window_duration(self) -> float:
        """Return the fixed X-window duration in seconds."""
        return self._sweep_control.window_duration

    @property
    def sweep_start(self) -> float | None:
        """Return the absolute start of the currently displayed sweep."""
        return self._sweep_control.sweep_start

    def _on_window_changed(self, _seconds: float) -> None:
        self._configure_shared_x_range()
        self._set_sweep_for_time(self._sweep_control.last_master_time, force=True)

    def _refresh_after_resize(self) -> None:
        enforce_channel_visibility(self.channels)
        point_budget = point_budget_for_width(int(self.graphics_layout.viewport().width()))
        if point_budget != self._last_point_budget:
            self.update_plots()

    def _configure_shared_x_range(self) -> None:
        if self._master_plot is None or self.window_duration <= 0:
            return
        self._master_plot.setXRange(0.0, self.window_duration, padding=0)

    def _link_x_axes(self) -> None:
        if self._master_plot is None:
            return
        for ch in self.channels:
            if ch.plot_item != self._master_plot:
                ch.plot_item.setXLink(self._master_plot)
        self._configure_shared_x_range()

    def _set_sweep_for_time(self, t: float, *, force: bool = False) -> float:
        """Derive sweep position from master time and refresh only at boundaries."""
        position = self._sweep_control.advance(t)
        if position.changed or force:
            self.update_plots()
            self._redraw_sweep_overlays()

        for ch in self.channels:
            if ch.visible:
                ch.cursor_line.setValue(position.phase)
                ch.curve.set_sweep_position(position.phase)
                ch.envelope_upper.set_sweep_position(position.phase)
        return position.phase

    def _request_channel_close(self, channel_id: str) -> None:
        self.set_channel_visible(channel_id, False)
        self.channel_close_requested.emit(channel_id)

    def _display_x(self, absolute_t: float) -> float | None:
        if self.sweep_start is None:
            return None
        x = absolute_t - self.sweep_start
        if -1e-9 <= x <= self.window_duration + 1e-9:
            return max(0.0, min(self.window_duration, x))
        return None

    def _redraw_sweep_overlays(self) -> None:
        self._redraw_coverage()
        self._redraw_gap_markers()
        self._redraw_measure_lines()
        self._redraw_annotations()

    def _redraw_coverage(self) -> None:
        if self.sweep_start is None:
            return
        sweep_end = self.sweep_start + self.window_duration
        for ch in self.channels:
            update_channel_coverage(ch, self.sweep_start, sweep_end)

    def set_context_actions(self, actions: list) -> None:
        """Register extra QAction objects to appear in the right-click context menu.

        MainWindow passes its own QAction instances (e.g. the View→Reset Zoom
        action) so the context menu shares the exact same object — enabling
        the object-identity test mandated by D-022.
        """
        self._extra_context_actions = list(actions)

    # ── Measure markers ──────────────────────────────────────────────

    def set_measure_a(self, t: float) -> None:
        """Place measure pin A at time *t* on all channels."""
        self._measure_a = t
        self._redraw_measure_lines()
        if self._measure_b is not None:
            self.measure_changed.emit(min(t, self._measure_b), max(t, self._measure_b))

    def set_measure_b(self, t: float) -> None:
        """Place measure pin B at time *t* on all channels."""
        self._measure_b = t
        self._redraw_measure_lines()
        if self._measure_a is not None:
            self.measure_changed.emit(min(self._measure_a, t), max(self._measure_a, t))

    def clear_measure(self) -> None:
        """Remove both measure pins."""
        self._measure_a = None
        self._measure_b = None
        self._redraw_measure_lines()

    def _redraw_measure_lines(self) -> None:
        for line in self._measure_a_lines + self._measure_b_lines:
            for ch in self.channels:
                try:
                    ch.plot_item.removeItem(line)
                except RuntimeError:
                    logger.debug("Plot item was already deleted", exc_info=True)
        self._measure_a_lines.clear()
        self._measure_b_lines.clear()

        pen_a = pg.mkPen(color=(0, 255, 100), width=2, style=Qt.PenStyle.DashLine)
        pen_b = pg.mkPen(color=(255, 80, 80), width=2, style=Qt.PenStyle.DashLine)
        for ch in self.channels:
            if not ch.visible:
                continue
            x_a = self._display_x(self._measure_a) if self._measure_a is not None else None
            x_b = self._display_x(self._measure_b) if self._measure_b is not None else None
            if x_a is not None:
                la = pg.InfiniteLine(pos=x_a, angle=90, movable=False, pen=pen_a)
                la.setZValue(5)
                ch.plot_item.addItem(la)
                self._measure_a_lines.append(la)
            if x_b is not None:
                lb = pg.InfiniteLine(pos=x_b, angle=90, movable=False, pen=pen_b)
                lb.setZValue(5)
                ch.plot_item.addItem(lb)
                self._measure_b_lines.append(lb)

    def _on_scene_clicked(self, ev) -> None:
        if ev.button() != Qt.MouseButton.RightButton:
            return
        if not self._master_plot:
            return
        if self.sweep_start is None:
            return
        scene_pos = ev.scenePos()
        if not self._master_plot.vb.sceneBoundingRect().contains(scene_pos):
            return
        view_pos = self._master_plot.vb.mapSceneToView(scene_pos)
        t = self.sweep_start + float(view_pos.x())

        menu = QMenu()

        # Annotate at clicked position (D-022)
        act_annot = menu.addAction(f"Add marker here  ({t:.3f} s)")
        menu.addSeparator()

        # Measure sub-group
        act_a = menu.addAction(f"Set Measure A  ({t:.3f} s)")
        act_b = menu.addAction(f"Set Measure B  ({t:.3f} s)")
        menu.addSeparator()
        act_clear = menu.addAction("Clear Measure")

        # Extra actions injected by MainWindow (e.g. Reset Zoom — same QAction
        # object as the View menu item, verified by identity in tests).
        if self._extra_context_actions:
            menu.addSeparator()
            for extra in self._extra_context_actions:
                menu.addAction(extra)

        chosen = menu.exec(ev.screenPos().toPoint())
        if chosen == act_annot:
            self.annotate_at_requested.emit(t)
        elif chosen == act_a:
            self.set_measure_a(t)
        elif chosen == act_b:
            self.set_measure_b(t)
        elif chosen == act_clear:
            self.clear_measure()
        # Extra actions fire through their own triggered signal — no elif needed.
        ev.accept()

    # ── Gap markers ──────────────────────────────────────────────────

    def set_gap_markers(self, channel_id: str, gap_times: list[float]) -> None:
        """Overlay thin red vertical lines at gap positions for one channel."""
        for ch in self.channels:
            if ch.name != channel_id:
                continue
            ch.gap_times = tuple(gap_times)
            self._redraw_gap_markers()
            break

    def _redraw_gap_markers(self) -> None:
        pen = pg.mkPen(color=(255, 60, 60), width=1, style=Qt.PenStyle.DotLine)
        for ch in self.channels:
            for line in ch.gap_markers:
                ch.plot_item.removeItem(line)
            ch.gap_markers.clear()
            if not ch.visible:
                continue
            for t in ch.gap_times:
                x = self._display_x(t)
                if x is None:
                    continue
                line = pg.InfiniteLine(pos=x, angle=90, movable=False, pen=pen)
                line.setZValue(3)
                ch.plot_item.addItem(line)
                ch.gap_markers.append(line)

    # ── Annotation / misc ────────────────────────────────────────────

    def set_annotation_store(self, store: object) -> None:
        self._annotation_store = store
        self._annotation_store.changed.connect(self._redraw_annotations)
        self._redraw_annotations()

    def set_x_range(self, t0: float, t1: float) -> None:
        """Compatibility alias for setting master timeline bounds."""
        self.set_timeline_bounds(t0, t1)

    def _redraw_annotations(self) -> None:
        """Draw point and range markers from the annotation store on all channels."""
        for plot_item, item in self._annotation_items:
            plot_item.removeItem(item)
        self._annotation_items.clear()

        if not self._annotation_store:
            return

        from PySide6.QtCore import Qt

        for marker in self._annotation_store.markers:
            c = pg.mkColor(marker.color)
            for ch in self.channels:
                if not ch.visible:
                    continue
                if marker.t_end is None:
                    x = self._display_x(marker.t_start)
                    if x is None:
                        continue
                    pen = pg.mkPen(c, width=2, style=Qt.PenStyle.DashLine)
                    line = pg.InfiniteLine(pos=x, angle=90, movable=False, pen=pen)
                    ch.plot_item.addItem(line)
                    self._annotation_items.append((ch.plot_item, line))
                else:
                    if self.sweep_start is None:
                        continue
                    marker_start = max(marker.t_start, self.sweep_start)
                    marker_end = min(marker.t_end, self.sweep_start + self.window_duration)
                    if marker_end < marker_start:
                        continue
                    c_brush = pg.mkColor(marker.color)
                    c_brush.setAlpha(40)
                    region = pg.LinearRegionItem(
                        values=[
                            marker_start - self.sweep_start,
                            marker_end - self.sweep_start,
                        ],
                        movable=False,
                        brush=c_brush,
                        pen=pg.mkPen(c, width=1, style=Qt.PenStyle.DashLine),
                    )
                    region.setZValue(-5)
                    ch.plot_item.addItem(region)
                    self._annotation_items.append((ch.plot_item, region))
