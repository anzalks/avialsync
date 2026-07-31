"""Plot rendering pane using pyqtgraph and decimation pyramids."""

import logging
import time
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QEvent, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QResizeEvent
from PySide6.QtWidgets import QVBoxLayout, QWidget

from avialview.core.channel_reader import ChannelKey
from avialview.core.timeline import TimeMap
from avialview.ui.annotations import AnnotationStore
from avialview.ui.plot_header import PlotHeader
from avialview.ui.plot_interactions import PlotInteractionController
from avialview.ui.plot_row import (
    Y_AUTO,
    Y_FIT_ONCE,
    Y_MANUAL,
    ChannelPlot,
    apply_channel_visibility,
    create_channel_plot,
    enforce_channel_visibility,
    fit_channel_y,
    point_budget_for_width,
    refresh_channel_plot,
    set_channel_unit,
    update_channel_coverage,
)
from avialview.ui.plot_sweep import PlotPresentation, SweepWindowControl
from avialview.ui.time_format import TimeDisplayMode, format_time

logger = logging.getLogger(__name__)

#: Rate at which the sweep cursor and revealed curves are actually redrawn.
#: The master clock still ticks at 60 Hz and ``set_cursor`` still sees every
#: tick — only the repaint is throttled.  Repainting the plot scene costs ~7 ms
#: at 16 rows and ~13 ms at 32, out of a 16.7 ms tick budget shared with every
#: video pane's ``paintGL``; at 60 Hz that starves video presentation and is
#: what makes frames look choppy.  30 Hz is above the rate at which cursor
#: motion reads as stepped.
_CURSOR_REPAINT_HZ = 30.0
_CURSOR_REPAINT_INTERVAL_S = 1.0 / _CURSOR_REPAINT_HZ

#: Half a 60 Hz tick of slack on the "is a repaint due yet" test.  Ticks land on
#: a 16.7 ms grid and the interval is 33.3 ms, so without slack a tick that is
#: due to the microsecond gets deferred a whole further tick and the real rate
#: beats down to ~22 Hz instead of the intended 30.
_CURSOR_REPAINT_SLACK_S = 1.0 / 120.0


class PlotPane(QWidget):
    """
    Data plotting pane for multiple time-series channels.

    Uses pyqtgraph GraphicsLayoutWidget to stack channels vertically.
    All channels share the same X-axis.
    """

    # Emitted when the set of active readers changes so ReadoutPanel can refresh
    sources_changed = Signal(list)  # list[MappedChannelReader]
    # Emitted when both measure points are set (t_a, t_b)
    measure_changed = Signal(float, float)
    # Emitted when user picks "Add marker here" from the plot context menu (D-022)
    annotate_at_requested = Signal(float)  # t in master-clock seconds
    # Emitted by the row close button; MainWindow mirrors it to the sidebar checkbox.
    channel_close_requested = Signal(str, str)  # source_id, channel_id
    # Absolute current page plus cursor phase for the shared Data Streams navigator.
    view_window_changed = Signal(float, float, float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        _layout = QVBoxLayout()
        _layout.setContentsMargins(0, 0, 0, 0)
        _layout.setSpacing(0)
        self.setLayout(_layout)

        self._apply_palette()

        self._plot_header = PlotHeader(self)
        self._plot_header.presentation_changed.connect(self._on_presentation_changed)
        self._plot_header.fit_all_requested.connect(self.fit_all_y)
        self._plot_header.row_height_changed.connect(self._set_row_height)
        self._plot_header.reset_requested.connect(self.reset_zoom)
        self.presentation_combo = self._plot_header.presentation_combo
        self.page_label = self._plot_header.page_label
        self.fit_all_button = self._plot_header.fit_all_button
        self.row_height_combo = self._plot_header.row_height_combo
        self.reset_button = self._plot_header.reset_button
        _layout.addWidget(self._plot_header)

        self.graphics_layout = pg.GraphicsLayoutWidget()
        self.graphics_layout.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.graphics_layout.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.graphics_layout.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
        self._last_cursor_repaint = 0.0
        self._page_label_text: str | None = None

        # State
        self.channels: list[ChannelPlot] = []
        # One TimeMap per source cache dir, shared by all of that source's rows.
        self._source_time_maps: dict[Path, TimeMap] = {}
        self.follow_playhead = True
        self._playing = False
        self._scrubbing = False
        self._live_presentation = PlotPresentation.SCOPE
        self._time_mode = TimeDisplayMode.RELATIVE
        self._t_epoch = 0.0
        self._settings = QSettings("AvialView", "AvialView")
        saved_presentation = self._settings.value(
            "plot/live_presentation", PlotPresentation.SCOPE.value
        )
        try:
            self._live_presentation = PlotPresentation(str(saved_presentation))
        except ValueError:
            self._live_presentation = PlotPresentation.SCOPE
        self._plot_header.set_presentation(self._live_presentation)

        # The first plot is the single X-range authority for every linked row.
        self._master_plot: pg.PlotItem | None = None
        self._interactions = PlotInteractionController(self)
        self.graphics_layout.scene().sigMouseClicked.connect(self._interactions.on_scene_clicked)

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

    def load_channels(
        self,
        cache_dir: Path,
        channel_names: list[str],
        offset: float = 0.0,
        drift_ppm: float = 0.0,
        source_id: str = "",
    ) -> None:
        """Load multiple data sources from cache and build plot rows.

        Every row of one source shares a single :class:`TimeMap`, so a later
        offset edit remaps the whole source at once (see :meth:`set_source_mapping`).
        """
        if not channel_names:
            return

        start_row = len(self.channels)
        time_map = self._source_time_maps.setdefault(cache_dir, TimeMap())
        time_map.offset = float(offset)
        time_map.drift_ppm = float(drift_ppm)

        for i, ch_name in enumerate(channel_names):
            channel = create_channel_plot(
                self.graphics_layout,
                start_row + i,
                cache_dir,
                ch_name,
                start_row + i,
                self._request_channel_close,
                time_map,
                source_id,
            )
            if self._master_plot is None:
                self._master_plot = channel.plot_item
            else:
                channel.plot_item.setXLink(self._master_plot)
            self.channels.append(channel)

        self._configure_shared_x_range()
        self._update_axis_visibility()
        self._set_sweep_for_time(self._sweep_control.last_master_time, force=True)
        self._apply_presentation()
        self.sources_changed.emit([ch.reader for ch in self.channels])
        self._interactions.redraw_annotations()

    def set_source_mapping(self, cache_dir: Path, offset: float, drift_ppm: float) -> None:
        """Re-align one time-series source against the master clock.

        The rows keep their readers; only the shared ``TimeMap`` changes, so this
        is a redraw rather than a reload no matter how large the source is.
        """
        time_map = self._source_time_maps.get(cache_dir)
        if time_map is None:
            return
        time_map.offset = float(offset)
        time_map.drift_ppm = float(drift_ppm)
        for channel in self.channels:
            if channel.reader.cache_dir == cache_dir:
                channel.coverage_bounds = channel.reader.coverage()
        self.update_plots()
        self._interactions.redraw_annotations()

    def source_mapping(self, cache_dir: Path) -> tuple[float, float]:
        """Return the ``(offset, drift_ppm)`` currently applied to a source."""
        time_map = self._source_time_maps.get(cache_dir)
        if time_map is None:
            return 0.0, 0.0
        return time_map.offset, time_map.drift_ppm

    def source_bounds(self, cache_dir: Path) -> tuple[float, float] | None:
        """Return one source's master-time coverage across all of its channels."""
        spans = [
            bounds
            for channel in self.channels
            if channel.reader.cache_dir == cache_dir
            and (bounds := channel.reader.coverage()) is not None
        ]
        if not spans:
            return None
        return min(span[0] for span in spans), max(span[1] for span in spans)

    def remove_channels(self, cache_dir: Path) -> None:
        """Remove all channels associated with a specific cache_dir (source)."""
        self._source_time_maps.pop(cache_dir, None)
        to_remove = [ch for ch in self.channels if ch.reader.cache_dir == cache_dir]
        for ch in to_remove:
            self.graphics_layout.removeItem(ch.plot_item)
            self.graphics_layout.removeItem(ch.close_proxy)
            self.channels.remove(ch)

            if self._master_plot == ch.plot_item:
                self._master_plot = self.channels[0].plot_item if self.channels else None

        self._link_x_axes()
        self._update_axis_visibility()

        self.sources_changed.emit([ch.reader for ch in self.channels])
        self._interactions.redraw_annotations()

    def _matching(self, channel: ChannelKey | str) -> list[ChannelPlot]:
        """Resolve a channel reference to the rows it identifies.

        A :class:`ChannelKey` selects exactly one source's row.  A bare name is
        ambiguous by construction — two files can both contain ``force_z`` — so
        it matches every owner and says so, rather than silently picking one.
        """
        if isinstance(channel, ChannelKey):
            return [ch for ch in self.channels if ch.reader.key == channel]
        matches = [ch for ch in self.channels if ch.reader.channel_id == channel]
        owners = {ch.reader.source_id for ch in matches}
        if len(owners) > 1:
            logger.warning(
                "Channel name %r is owned by %d sources; applying to all. "
                "Pass a ChannelKey to address one source.",
                channel,
                len(owners),
            )
        return matches

    def remove_channel(self, channel: ChannelKey | str) -> None:
        """Remove the row(s) identified by *channel*."""
        to_remove = self._matching(channel)
        for ch in to_remove:
            self.graphics_layout.removeItem(ch.plot_item)
            self.graphics_layout.removeItem(ch.close_proxy)
            self.channels.remove(ch)

            if self._master_plot == ch.plot_item:
                self._master_plot = self.channels[0].plot_item if self.channels else None

        self._link_x_axes()
        self._update_axis_visibility()

        self.sources_changed.emit([ch.reader for ch in self.channels])
        self._interactions.redraw_annotations()

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
            if ch.y_mode == Y_FIT_ONCE and ch.y_range is None:
                fit_channel_y(ch)
                if ch.y_range is not None:
                    ch.y_mode = Y_MANUAL

    def set_cursor(self, t: float, *, immediate: bool = False) -> None:
        """Advance the fixed sweep from the master-clock time.

        Called on every 60 Hz tick.  Advancing the sweep *state* is cheap
        (~0.2 ms at 16 rows); repainting the scene is not (~7 ms), and it shares
        the UI thread with every video pane's ``paintGL``.  Pixels are therefore
        moved at :data:`_CURSOR_REPAINT_HZ` while time keeps advancing at the
        full tick rate.  Pass ``immediate`` for discrete events — a seek, a
        pause, a frame step — where a stale cursor would be a lie.
        """
        self._set_sweep_for_time(t, force=immediate)

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

    def set_channel_visible(self, channel: ChannelKey | str, visible: bool) -> None:
        """Show or hide the plot row(s) identified by *channel*."""
        for ch in self._matching(channel):
            ch.visible = visible
            apply_channel_visibility(ch)
            if visible and self.sweep_start is not None:
                refresh_channel_plot(
                    ch,
                    self.sweep_start,
                    self.sweep_start + self.window_duration,
                    point_budget_for_width(int(self.graphics_layout.viewport().width())),
                )
                self._redraw_sweep_overlays()
        self._update_axis_visibility()

    def reset_zoom(self) -> None:
        """Set the shared sweep window to the full master-timeline duration."""
        for ch in self.channels:
            ch.y_mode = Y_FIT_ONCE
            ch.y_range = None
        self._sweep_control.reset_window()

    def fit_all_y(self) -> None:
        """Fit the current bounded page once, then keep playback visually stable."""
        for ch in self.channels:
            if not ch.visible:
                continue
            ch.y_mode = Y_FIT_ONCE
            ch.y_range = None
            fit_channel_y(ch)
            if ch.y_range is not None:
                ch.y_mode = Y_MANUAL

    def set_channel_y_mode(self, channel_id: str, mode: str) -> None:
        """Set one row's explicit Fit/Auto/Manual amplitude behaviour."""
        if mode not in {Y_FIT_ONCE, Y_AUTO, Y_MANUAL}:
            raise ValueError(f"Unknown plot Y mode: {mode}")
        for ch in self.channels:
            if ch.name == channel_id:
                ch.y_mode = mode
                if mode == Y_FIT_ONCE:
                    ch.y_range = None
                    fit_channel_y(ch)
                    if ch.y_range is not None:
                        ch.y_mode = Y_MANUAL
                elif mode == Y_AUTO:
                    fit_channel_y(ch)
                break

    def set_channel_unit(self, channel: ChannelKey | str, unit: str) -> None:
        """Update the fixed channel gutter after import metadata is available."""
        for ch in self._matching(channel):
            set_channel_unit(ch, unit)

    def set_channel_units(self, units: dict[ChannelKey | str, str]) -> None:
        """Update all known channel units without changing reader identity or data."""
        for channel, unit in units.items():
            self.set_channel_unit(channel, unit)

    def set_playing(self, playing: bool) -> None:
        """Select live Sweep/Scope painting or complete Review painting."""
        if self._playing == playing:
            return
        self._playing = playing
        self._apply_presentation()

    def set_scrubbing(self, scrubbing: bool) -> None:
        """Reveal a complete page while approximate master-time scrubbing is active."""
        if self._scrubbing == scrubbing:
            return
        self._scrubbing = scrubbing
        self._apply_presentation()

    @property
    def presentation(self) -> PlotPresentation:
        """Return the effective presentation after playback/scrub state is applied."""
        if not self._playing or self._scrubbing:
            return PlotPresentation.REVIEW
        return self._live_presentation

    def set_time_mode(self, mode: TimeDisplayMode, t_epoch: float = 0.0) -> None:
        """Format the shared page label with the same mode as transport/readout."""
        self._time_mode = mode
        self._t_epoch = t_epoch
        self._update_page_label()

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

    # Compatibility accessors retained for existing measurement integrations.
    @property
    def _measure_a(self) -> float | None:
        return self._interactions._measure_a

    @property
    def _measure_b(self) -> float | None:
        return self._interactions._measure_b

    @property
    def _measure_a_lines(self) -> list[pg.InfiniteLine]:
        return self._interactions._measure_a_lines

    @property
    def _measure_b_lines(self) -> list[pg.InfiniteLine]:
        return self._interactions._measure_b_lines

    @property
    def _extra_context_actions(self) -> list[QAction]:
        return self._interactions._extra_context_actions

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

    def _update_axis_visibility(self) -> None:
        """Use one shared bottom X axis while keeping all rows X-linked."""
        visible = [channel for channel in self.channels if channel.visible]
        bottom = visible[-1] if visible else None
        for channel in self.channels:
            axis = channel.plot_item.getAxis("bottom")
            show = channel is bottom
            axis.setStyle(showValues=show)
            axis.showLabel(show)

    def _set_row_height(self, height: int) -> None:
        """Use one scrollable channel stack rather than shrinking many rows indefinitely."""
        for channel in self.channels:
            channel.row_height = height
            apply_channel_visibility(channel)

    def _on_presentation_changed(self, _index: int) -> None:
        data = self.presentation_combo.currentData()
        if isinstance(data, PlotPresentation):
            self._live_presentation = data
        else:
            self._live_presentation = PlotPresentation(str(data))
        self._settings.setValue("plot/live_presentation", self._live_presentation.value)
        self._apply_presentation()

    def _apply_presentation(self) -> None:
        """Change paint-only state without re-querying pyramid data."""
        presentation = self.presentation
        review = presentation == PlotPresentation.REVIEW
        for channel in self.channels:
            channel.curve.set_reveal_enabled(not review)

    def _set_sweep_for_time(self, t: float, *, force: bool = False) -> float:
        """Derive sweep position from master time and refresh only at boundaries."""
        position = self._sweep_control.advance(t)
        if position.changed or force:
            self.update_plots()
            self._redraw_sweep_overlays()

        # Time has already advanced; from here down we are only moving pixels.
        # A page boundary changes *what* is drawn, so it is never deferred.
        if not (position.changed or force) and not self._cursor_repaint_due():
            return position.phase

        # Two items per visible row: the trace and the cursor.  This loop is the
        # 30 Hz repaint path, so anything added here is paid per row per frame.
        for ch in self.channels:
            if ch.visible:
                ch.cursor_line.setValue(position.phase)
                ch.curve.set_sweep_position(position.phase)
        self._update_page_label(position.start)
        self.view_window_changed.emit(position.start, self.window_duration, position.phase)
        return position.phase

    def _cursor_repaint_due(self) -> bool:
        """Return whether enough time has passed to justify repainting the scene.

        Stamps the clock as a side effect when it returns True.  Ticks arrive
        every ~16.7 ms and the interval is ~33 ms, so at most one tick's worth
        of cursor movement is ever deferred — below the threshold at which the
        motion reads as stepped, and it frees roughly half the plot's share of
        the UI thread for video presentation.
        """
        now = time.monotonic()
        due_after = _CURSOR_REPAINT_INTERVAL_S - _CURSOR_REPAINT_SLACK_S
        if (now - self._last_cursor_repaint) < due_after:
            return False
        self._last_cursor_repaint = now
        return True

    def _update_page_label(self, start: float | None = None) -> None:
        if start is None:
            start = self.sweep_start
        if start is None or self.window_duration <= 0:
            self.page_label.clear()
            return
        end = start + self.window_duration
        # The page spans a whole window, so this text is identical on almost
        # every tick; setText would still relayout the header each time.
        text = (
            f"{format_time(start, self._time_mode, self._t_epoch)} – "
            f"{format_time(end, self._time_mode, self._t_epoch)}"
        )
        if text != self._page_label_text:
            self._page_label_text = text
            self.page_label.setText(text)

    def _request_channel_close(self, channel_id: str) -> None:
        """Row close button: hide this source's row and tell the sidebar which one."""
        match = next((ch for ch in self.channels if ch.reader.channel_id == channel_id), None)
        key = match.reader.key if match is not None else ChannelKey("", channel_id)
        self.set_channel_visible(key, False)
        self.channel_close_requested.emit(key.source_id, key.channel_id)

    def _display_x(self, absolute_t: float) -> float | None:
        if self.sweep_start is None:
            return None
        x = absolute_t - self.sweep_start
        if -1e-9 <= x <= self.window_duration + 1e-9:
            return max(0.0, min(self.window_duration, x))
        return None

    def _redraw_sweep_overlays(self) -> None:
        self._redraw_coverage()
        self._interactions.redraw_page_overlays()

    def _redraw_coverage(self) -> None:
        if self.sweep_start is None:
            return
        sweep_end = self.sweep_start + self.window_duration
        for ch in self.channels:
            update_channel_coverage(ch, self.sweep_start, sweep_end)

    def set_context_actions(self, actions: list[QAction]) -> None:
        """Register shared QActions, including the View menu's Reset Zoom action."""
        self._interactions.set_context_actions(actions)

    def set_measure_a(self, t: float) -> None:
        """Place measure pin A at time *t* on all channels."""
        self._interactions.set_measure_a(t)

    def set_measure_b(self, t: float) -> None:
        """Place measure pin B at time *t* on all channels."""
        self._interactions.set_measure_b(t)

    def clear_measure(self) -> None:
        """Remove both measure pins."""
        self._interactions.clear_measure()

    def set_gap_markers(self, channel_id: str, gap_times: list[float]) -> None:
        """Overlay thin red vertical lines at gap positions for one channel."""
        self._interactions.set_gap_markers(channel_id, gap_times)

    def set_annotation_store(self, store: AnnotationStore) -> None:
        """Subscribe to and render the authoritative annotation store."""
        self._interactions.set_annotation_store(store)

    def set_x_range(self, t0: float, t1: float) -> None:
        """Compatibility alias for setting master timeline bounds."""
        self.set_timeline_bounds(t0, t1)
