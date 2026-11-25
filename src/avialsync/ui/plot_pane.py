"""Plot rendering pane using pyqtgraph and decimation pyramids."""

import logging
import math
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from weakref import ref

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAccessible, QAction, QCloseEvent, QResizeEvent
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget
from shiboken6 import isValid

from avialsync.core.channel_reader import ChannelKey, MappedChannelReader
from avialsync.core.timeline import TimeMap
from avialsync.core.trials import TimeWarp
from avialsync.engine.plot_page_worker import PlotPage, PlotPageWorker, PlotRowRequest
from avialsync.ui.accessible_views import register_painted
from avialsync.ui.annotations import AnnotationStore
from avialsync.ui.app_settings import app_settings
from avialsync.ui.channel_tree import channel_tree_paths, compact_channel_label
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import JobManager
from avialsync.ui.plot_canvas_nav import PlotCanvasNavigator
from avialsync.ui.plot_header import PlotControlStrip, PlotHeader
from avialsync.ui.plot_interactions import PlotInteractionController
from avialsync.ui.plot_modes import (
    PLOT_MODE_STACKED,
    PlotModeCanvas,
    rebuild_rows_across_stacks,
)
from avialsync.ui.plot_row import (
    Y_AUTO,
    Y_FIT_ONCE,
    Y_MANUAL,
    ChannelPlot,
    apply_channel_palette,
    apply_channel_visibility,
    create_channel_plot,
    cull_offscreen_rows,
    detach_row,
    enforce_channel_visibility,
    fit_channel_y,
    point_budget_for_width,
    set_channel_gutter_alias,
    set_channel_unit,
    update_channel_coverage,
)
from avialsync.ui.plot_stack_view import PlotStackView
from avialsync.ui.plot_sweep import PlotPresentation, SweepWindowControl
from avialsync.ui.plot_theme import apply_canvas_palette
from avialsync.ui.time_format import TimeDisplayMode, format_time

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

#: How long row construction may hold the UI thread before yielding. One row
#: costs ~8-12 ms of Qt widget construction, so a large channel selection has to
#: be built across several event-loop turns or the window stops answering
#: entirely — no playback keys, no drops, no close button.
#:
#: Chosen by measuring a 64-channel load, not by reasoning: 12 ms gave a 31-38 ms
#: worst block, 5 ms was no better (39 ms), and 8 ms won on every axis — an
#: 18-33 ms worst block *and* the shortest total load. A slice always builds at
#: least one row, so one expensive row sets the floor: shrinking this further
#: cannot push the worst case below the cost of a single row.
_ROW_BUILD_SLICE_S = 0.008
#: A plot page job is shown in the status bar only once it has run this long.
_PAGE_ANNOUNCE_S = 0.5
#: Above 64 visible stacked rows on a shown pane, offscreen culled rows defer
#: pyramid queries until scrolled into view; smaller stacks load whole.
_CULLED_PAGE_SKIP_THRESHOLD = 64

#: Every budget in this module is a fraction of a frame, so they are timed on
#: `perf_counter`, never `time.monotonic`. On Windows `monotonic` is
#: `GetTickCount64` and reports a resolution of 15.625 ms — coarser than the
#: 8 ms slice and half the 33 ms repaint interval — so a whole 128-row requery
#: could run inside one tick, read as "0 ms elapsed", and never yield: the
#: budget silently did nothing on the platform it was protecting. Measured with
#: `time.get_clock_info`, not assumed. `perf_counter` is sub-microsecond on all
#: three platforms and is monotonic too; only its epoch is undefined, and every
#: use here is a difference.
_elapsed = time.perf_counter


class PlotPane(QWidget):
    """
    Data plotting pane for multiple time-series channels.

    Uses pyqtgraph GraphicsLayoutWidget to stack channels vertically.
    All channels share the same X-axis.
    """

    # Emitted when the set of loaded readers changes so tracking/prop consumers can refresh
    sources_changed = Signal(list)  # list[MappedChannelReader]
    # Emitted when the set of visible readers changes so Values shows only active signals
    visible_sources_changed = Signal(list)  # list[MappedChannelReader]
    # Emitted when both measure points are set (t_a, t_b)
    measure_changed = Signal(float, float)
    # Emitted when measure points are cleared
    measure_cleared = Signal()
    # Emitted when user picks "Add marker here" from the plot context menu
    annotate_at_requested = Signal(float)  # t in master-clock seconds
    # Emitted when a visible plot row is left-clicked at an absolute master time.
    seek_requested = Signal(float)
    # Emitted by the row close button; MainWindow mirrors it to the sidebar checkbox.
    channel_close_requested = Signal(str, str)  # source_id, channel_id
    # Absolute current page plus cursor phase for the shared Data Streams navigator.
    view_window_changed = Signal(float, float, float)
    # Every queued row now exists; bounds derived from readers are final.
    channels_loaded = Signal()
    # Rows still queued for construction, 0 when the load is complete.
    rows_pending = Signal(int)
    page_ready = Signal(int)
    # Pointer hover master-time (float) or None when pointer leaves the plots.
    hover_time_changed = Signal(object)
    # ChannelKey | None as pointer moves between plot rows (used for 2P ROI linking).
    hovered_channel_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.channels: list[ChannelPlot] = []
        self._index_cache: (
            tuple[
                tuple[int, int, int],
                dict[ChannelKey, list[ChannelPlot]],
                dict[str, list[ChannelPlot]],
            ]
            | None
        ) = None
        self._page_generation = 0
        self._last_installed_generation = 0
        self._page_thread: QThread | None = None
        self._page_worker: PlotPageWorker | None = None
        self._page_manager: JobManager | None = None
        self._closed = False
        self._draw_every_row = False
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
        self._plot_header.view_mode_changed.connect(self.set_view_mode)
        self.reset_action = QAction(tr("Reset Plots"), self)
        self.reset_action.setToolTip(tr("Reset the shared time span and fit every visible plot"))
        self.reset_action.triggered.connect(self.reset_zoom)
        self._plot_header.reset_button.set_action(self.reset_action)
        self.presentation_combo = self._plot_header.presentation_combo
        self.page_label = self._plot_header.page_label
        self.fit_all_button = self._plot_header.fit_all_button
        self.row_height_combo = self._plot_header.row_height_combo
        self.view_mode_combo = self._plot_header.view_mode_combo
        self.reset_button = self._plot_header.reset_button
        self._view_mode = PLOT_MODE_STACKED

        self_ref = ref(self)

        def _pinned_views() -> list[pg.ViewBox | None]:
            pane = self_ref()
            if pane is None:
                return []
            return [ch.plot_item.getViewBox() for ch in pane.channels if ch.pinned_in_layout]

        def _scroll_views() -> list[pg.ViewBox | None]:
            pane = self_ref()
            if pane is None:
                return []
            return [ch.plot_item.getViewBox() for ch in pane.channels if not ch.pinned_in_layout]

        def _chart_value() -> str:
            pane = self_ref()
            return pane.accessible_value() if pane is not None else ""

        def _chart_detail() -> str:
            pane = self_ref()
            return pane.accessible_detail() if pane is not None else ""

        self._pinned_layout = PlotStackView(_pinned_views, self)
        self._pinned_layout.setAccessibleName(tr("Pinned plot rows"))
        self._pinned_layout.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._pinned_layout.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._pinned_layout.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._pinned_layout.hide()
        _layout.addWidget(self._pinned_layout)

        self.graphics_layout = PlotStackView(_scroll_views)
        self.graphics_layout.setAccessibleName(tr("Plot rows"))
        register_painted(self.graphics_layout, QAccessible.Role.Chart, _chart_value, _chart_detail)
        self.graphics_layout.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.graphics_layout.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The channel stack scrolls in an ordinary scroll area, not in the
        # graphics view. pyqtgraph's GraphicsView re-pins its scene rect to the
        # viewport on every resize (`autoPixelRange`), so its own vertical
        # scrollbar can never acquire a range however the policy is set: rows
        # past the bottom edge were clipped away with no way to reach them.
        # `_apply_stack_height` gives the view a real height instead, and this
        # scrolls it.
        self._plot_scroll = QScrollArea(self)
        self._plot_scroll.setWidgetResizable(True)
        self._plot_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._plot_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._plot_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._plot_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._plot_scroll.setAccessibleName(tr("Channel plot stack"))
        self._plot_scroll.setWidget(self.graphics_layout)
        _layout.addWidget(self._plot_scroll)
        self._mode_view = PlotModeCanvas(self)
        self._mode_view.hide()
        self._mode_view.seek_requested.connect(self._on_mode_seek_requested)
        _layout.addWidget(self._mode_view, 1)
        self._cull_timer = QTimer(self)
        self._cull_timer.setSingleShot(True)
        self._cull_timer.setInterval(0)
        self._cull_timer.timeout.connect(self._cull_offscreen_rows)
        self._plot_scroll.verticalScrollBar().valueChanged.connect(self._cull_offscreen_rows)
        # A taller or shorter pane moves the fold without moving any row.
        self._plot_scroll.verticalScrollBar().rangeChanged.connect(self._cull_timer.start)

        #: Collapsed gaps (D-218): pages, cursor and overlays are drawn in this
        #: view time; every time read back out of the plot is master time.
        self._warp = TimeWarp()
        self._master_bounds = (0.0, 0.0)
        self._sweep_control = SweepWindowControl(self)
        self._sweep_control.set_focus_target(self)
        self._sweep_control.window_changed.connect(self._on_window_changed)
        self.window_limit_spin = self._sweep_control.limit_spin
        self.window_unit_combo = self._sweep_control.unit_combo
        self.window_slider = self._sweep_control.slider
        self.window_value_label = self._sweep_control.value_label
        # One row contains the existing plot and time-span controls.
        self._plot_header.insert_span_control(self._sweep_control)
        self._header_strip = PlotControlStrip(self._plot_header, self)
        _layout.addWidget(self._header_strip)
        self._resize_refresh_timer = QTimer(self)
        self._resize_refresh_timer.setSingleShot(True)
        self._resize_refresh_timer.setInterval(75)
        self._resize_refresh_timer.timeout.connect(self._refresh_after_resize)
        self._last_point_budget = 0
        self._last_cursor_repaint = 0.0
        self._pending_rows: list[tuple[Path, str, TimeMap, str, bool]] = []
        self._finish_loading_pending = False
        self._row_build_timer = QTimer(self)
        self._row_build_timer.setSingleShot(True)
        self._row_build_timer.setInterval(0)
        self._row_build_timer.timeout.connect(self._advance_row_build)
        self._pending_pinned: set[tuple[str, str]] = set()
        self._retiring_rows: list[ChannelPlot] = []
        self._retire_timer = QTimer(self)
        self._retire_timer.setSingleShot(True)
        self._retire_timer.setInterval(1)
        self._retire_timer.timeout.connect(self._drain_retiring_rows)
        # The rows the page in flight was requested for, by request index.
        self._requested_rows: tuple[ChannelPlot, ...] = ()
        self._requested_keys: tuple[tuple[object, ...] | None, ...] = ()
        self._scroll_only_pending = False
        # Worst observed cost of one row, used to stop a slice before the next
        # row would overrun its budget rather than after one already has.
        self._row_build_cost_s = 0.0
        self._page_label_text: str | None = None

        # State
        # One TimeMap per source cache dir, shared by all of that source's rows.
        self._source_time_maps: dict[Path, TimeMap] = {}
        self._readers_by_cache_and_id: dict[tuple[Path, str], MappedChannelReader] = {}
        self._first_reader_by_cache: dict[Path, MappedChannelReader] = {}
        self._source_raw_bounds: dict[Path, tuple[float, float]] = {}
        # Units arrive once, when the import finishes, but rows are built in
        # slices across later event-loop turns; kept here so a row built after
        # the units arrived still gets its own.
        self._units: dict[ChannelKey | str, str] = {}
        self.follow_playhead = True
        self._playing = False
        self._scrubbing = False
        self._live_presentation = PlotPresentation.SCOPE
        self._time_mode = TimeDisplayMode.RELATIVE
        self._t_epoch = 0.0
        self._settings = app_settings()
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
        scene = self.graphics_layout.scene()
        scene_ref = ref(scene)
        # pyqtgraph's scene carries its own "Export..." for its stock menu, which
        # rows no longer show; triggered any other way it raised. Rows offer
        # Export in their own menu instead (axis_nav.show_plot_exporter).
        scene.contextMenu = []
        scene.sigMouseClicked.connect(
            lambda ev, r=self_ref, sr=scene_ref: (
                r()._interactions.on_scene_clicked(ev, sr())
                if r() is not None and sr() is not None
                else None
            )
        )
        scene.sigMouseMoved.connect(
            lambda pos, r=self_ref, sr=scene_ref: (
                r()._interactions.on_scene_moved(pos, sr())
                if r() is not None and sr() is not None
                else None
            )
        )
        pinned_scene = self._pinned_layout.scene()
        pinned_scene_ref = ref(pinned_scene)
        pinned_scene.contextMenu = []
        pinned_scene.sigMouseClicked.connect(
            lambda ev, r=self_ref, sr=pinned_scene_ref: (
                r()._interactions.on_scene_clicked(ev, sr())
                if r() is not None and sr() is not None
                else None
            )
        )
        pinned_scene.sigMouseMoved.connect(
            lambda pos, r=self_ref, sr=pinned_scene_ref: (
                r()._interactions.on_scene_moved(pos, sr())
                if r() is not None and sr() is not None
                else None
            )
        )
        mode_scene = self._mode_view.graphics_layout.scene()
        mode_scene.sigMouseMoved.connect(self._interactions.on_mode_moved)
        self._mode_view.context_requested.connect(self._interactions.on_mode_context_menu)
        self._navigator = PlotCanvasNavigator(self)
        self._navigator.attach(self.graphics_layout)
        self._navigator.attach(self._pinned_layout)
        self._navigator.attach(self._mode_view.graphics_layout)

    def _on_mode_seek_requested(self, x: float) -> None:
        self.seek_requested.emit(self.master_at(x))

    def changeEvent(self, event: QEvent) -> None:
        """Keep pyqtgraph's canvas aligned with an application palette change."""
        super().changeEvent(event)
        if self._closed:
            return
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self._apply_palette()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Cancel a standalone pane's outstanding page before Qt destroys it."""
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Stop requesting pages, detach C++ graphics rows, and cancel work in flight.

        Called by the window's close sequence before its jobs shut down, and by
        :meth:`closeEvent` for a standalone pane. Without the flag, the
        cancelled page's thread ends, sees a newer generation, and starts
        another page into a job manager that has already shut down.
        """
        self._closed = True
        self.cancel_pending_rows()
        self._resize_refresh_timer.stop()
        self._cull_timer.stop()
        self._retire_timer.stop()
        self._retiring_rows.clear()
        worker, thread = self._page_worker, self._page_thread
        self._page_worker = None
        self._page_thread = None
        self._requested_rows = ()
        self._requested_keys = ()
        if worker is not None:
            worker.cancel()
            for sig, slot in (
                (worker.finished, self._on_page_ready),
                (worker.error, self._on_page_error),
            ):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        if thread is not None:
            try:
                thread.finished.disconnect(self._on_page_thread_finished)
            except (RuntimeError, TypeError):
                pass
        if self._page_manager is not None:
            self._page_manager.shutdown()
        self._interactions.shutdown()
        self._navigator.shutdown()
        if self.channels:
            readers_to_close = [ch.reader.source_reader for ch in self.channels]
            for ch in self.channels:
                if isValid(ch.plot_item.vb):
                    ch.plot_item.vb.blockSignals(True)
                    ch.plot_item.setXLink(None)
                if isValid(ch.close_proxy):
                    ch.close_proxy.deleteLater()
            if isValid(self.graphics_layout):
                self.graphics_layout.clear()
            if isValid(self._pinned_layout):
                self._pinned_layout.clear()
            self.channels.clear()
            for reader in readers_to_close:
                reader.close()
        if isValid(self._mode_view):
            self._mode_view.shutdown()
        self._master_plot = None
        self._index_cache = None
        self._readers_by_cache_and_id.clear()
        self._first_reader_by_cache.clear()

    def _drain_retiring_rows(self) -> None:
        """Drop detached PlotItem wrappers in small slices so GC never stalls the UI."""
        if not self._retiring_rows:
            return
        del self._retiring_rows[:24]
        if self._retiring_rows and not self._closed:
            self._retire_timer.start()

    def _detach_rows_bulk(self, to_remove: list[ChannelPlot]) -> None:
        """Detach *to_remove* from graphics layouts without O(N^2) itemIndex scans."""
        remove_ids = {id(ch) for ch in to_remove}
        all_unpinned = all(id(ch) in remove_ids for ch in self.channels if not ch.pinned_in_layout)
        all_pinned = all(id(ch) in remove_ids for ch in self.channels if ch.pinned_in_layout)
        for ch in to_remove:
            vb_blocked = ch.plot_item.vb.blockSignals(True)
            try:
                ch.plot_item.setXLink(None)
            finally:
                ch.plot_item.vb.blockSignals(vb_blocked)
        if all_unpinned:
            self.graphics_layout.clear()
        if all_pinned:
            self._pinned_layout.clear()
        for ch in to_remove:
            if ch.pinned_in_layout:
                if not all_pinned:
                    self._pinned_layout.removeItem(ch.plot_item)
                    self._pinned_layout.removeItem(ch.close_proxy)
            elif not all_unpinned:
                self.graphics_layout.removeItem(ch.plot_item)
                self.graphics_layout.removeItem(ch.close_proxy)
            ch.close_proxy.deleteLater()

    def _retire_detached_rows(self, rows: list[ChannelPlot]) -> None:
        """Queue detached rows for sliced C++ PlotItem destruction after readers close."""
        if not rows or self._closed or len(rows) <= 24:
            return
        self._retiring_rows.extend(rows)
        if not self._retire_timer.isActive():
            self._retire_timer.start()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Coalesce resize storms before selecting a new pyramid resolution."""
        super().resizeEvent(event)
        if self._closed:
            return
        enforce_channel_visibility([ch for ch in self.channels if not ch.visible])
        if self.channels and self.sweep_start is not None:
            self._resize_refresh_timer.start()

    def _apply_palette(self) -> None:
        """Repaint the canvas, the axes, and every row's graphics for this palette.

        ``setConfigOption`` alone is what this used to be, and it is why the
        graph kept its old background and black tick numbers through a
        light/dark switch: pyqtgraph reads those globals when an item is
        *constructed* and never looks at them again. Measured — flipping both
        options left a live view's background on ``#ffffff`` and its axis pens
        on ``#000000``.

        So the globals are still set, for anything pyqtgraph builds internally
        before we can reach it, and then every object already on screen is
        re-penned explicitly. The two are not redundant: the first covers
        construction, the second covers everything already constructed.
        """
        if getattr(self, "_closed", False):
            return
        palette = self.palette()
        pg.setConfigOption("background", palette.color(palette.ColorRole.Base).name())
        pg.setConfigOption("foreground", palette.color(palette.ColorRole.Text).name())
        # This runs from `__init__` before the view exists — deliberately, so
        # the config options above are in place for its construction — and Qt
        # can also deliver a palette change part-way through the rest of it.
        # Each piece is therefore checked for rather than assumed: reaching for
        # `_interactions` from a change event that landed between building the
        # view and building the controller is an AttributeError during startup.
        view = getattr(self, "graphics_layout", None)
        if view is None:
            return
        apply_canvas_palette(view, palette)
        pinned = getattr(self, "_pinned_layout", None)
        if pinned is not None:
            apply_canvas_palette(pinned, palette)
        mode_view = getattr(self, "_mode_view", None)
        if mode_view is not None:
            mode_view.apply_palette(palette)
        for channel in getattr(self, "channels", ()):
            if isinstance(channel, ChannelPlot):
                apply_channel_palette(channel, palette)
        # Page-local overlays are rebuilt rather than re-penned: they are
        # replaced wholesale on every page change anyway, so rebuilding keeps
        # one code path for their geometry.
        interactions = getattr(self, "_interactions", None)
        if interactions is not None:
            interactions.redraw_measure_lines()
            interactions.redraw_identity_markers()

    def refresh_palette(self) -> None:
        """Reapply trace and canvas palette colours after a preference change."""
        if self._closed:
            return
        self._apply_palette()
        self._refresh_mode_view()

    def _refresh_mode_view(self) -> None:
        """Sync the Overlaid / Heatmap canvas with current channel visibility and data."""
        if self._closed or self._view_mode == PLOT_MODE_STACKED:
            return
        phase = (
            self._sweep_control.advance(self._sweep_control.last_master_time).phase
            if self.sweep_start is not None
            else 0.0
        )
        self._mode_view.render_from_channels(
            self.channels,
            self.window_duration,
            self.palette(),
            reveal=self.presentation != PlotPresentation.REVIEW,
            phase=phase,
        )

    def load_channels(
        self,
        cache_dir: Path,
        channel_names: list[str],
        offset: float = 0.0,
        drift_ms_per_hour: float = 0.0,
        source_id: str = "",
        visibility: Mapping[str, bool] | None = None,
    ) -> None:
        """Load multiple data sources from cache and build plot rows.

        Every row of one source shares a single :class:`TimeMap`, so a later
        offset edit remaps the whole source at once (see :meth:`set_source_mapping`).
        """
        if not channel_names:
            return

        time_map = self._source_time_maps.setdefault(cache_dir, TimeMap())
        if not time_map.has_exact_mapping:
            time_map.offset = float(offset)
            time_map.drift_ms_per_hour = float(drift_ms_per_hour)

        defaults = visibility or {}
        self._row_build_timer.stop()
        self._finish_loading_pending = False
        self._pending_rows.extend(
            (cache_dir, name, time_map, source_id, bool(defaults.get(name, True)))
            for name in channel_names
        )
        # Each slice yields to the event loop, and every yield used to repaint
        # and re-lay-out every row built so far: a 234-ROI NWB file froze the
        # window for ~11 s, quadratic in the row count. The view stays frozen
        # (not the window) until the last row exists, then paints once.
        self.graphics_layout.setUpdatesEnabled(False)
        self._build_pending_rows()

    def _build_pending_rows(self) -> None:
        """Build queued rows in time slices, letting the event loop run between them.

        A row costs ~8-12 ms of Qt widget construction, so building a 64-channel
        selection in one call blocked the UI thread for most of a second — the
        window went white and answered nothing: no playback keys, no drops, no
        close button. Qt graphics objects must be created on this thread,
        so the work cannot move to a worker; it is sliced instead, and a
        zero-delay timer hands control back to the event loop between slices.
        """
        started = _elapsed()
        while self._pending_rows:
            row_started = _elapsed()
            cache_dir, name, time_map, source_id, visible = self._pending_rows.pop(0)
            row = len(self.channels)
            channel = create_channel_plot(
                self.graphics_layout,
                row,
                cache_dir,
                name,
                row,
                self._request_channel_close,
                time_map,
                source_id,
                # The density chosen now, not the dataclass default.
                row_height=int(self.row_height_combo.currentData()),
                visible=visible,
            )
            if not visible:
                apply_channel_visibility(channel)
            if self._master_plot is None and visible:
                self._master_plot = channel.plot_item
            self.channels.append(channel)
            self._readers_by_cache_and_id[(cache_dir, name)] = channel.reader
            self._first_reader_by_cache.setdefault(cache_dir, channel.reader)
            self._index_cache = None
            self._label_axis(channel)
            # Laid out after it is built and moved whenever a row above it
            # changes; either way its on-screen test must be re-read.
            channel.plot_item.geometryChanged.connect(self._cull_timer.start)
            unit = self._units.get(channel.reader.key) or self._units.get(name)
            if unit:
                set_channel_unit(channel, unit)
            gaps = self._interactions.gap_times_for(channel.reader.key, name)
            if gaps:
                channel.gap_times = gaps
            # No data or XLink yet: the view stays frozen until the last row
            # exists, and `_finish_loading` settles stack geometry, links the
            # visible rows once, and requests one page from the worker.
            cost = _elapsed() - row_started
            self._row_build_cost_s = (
                cost if self._row_build_cost_s <= 0.0 else 0.7 * self._row_build_cost_s + 0.3 * cost
            )
            elapsed = _elapsed() - started
            if elapsed + self._row_build_cost_s > _ROW_BUILD_SLICE_S:
                break

        if self._pending_rows:
            self.rows_pending.emit(len(self._pending_rows))
            self._row_build_timer.start()
            return
        # Completion is its own event-loop turn. Stacking it onto the tail of a
        # slice made one block out of two, which is what kept the worst-case
        # near 90 ms.
        self._finish_loading_pending = True
        self._row_build_timer.start()

    @Slot()
    def _advance_row_build(self) -> None:
        """Run the next queued row-build slice or finalize loading on its own turn."""
        if self._closed:
            return
        if self._pending_rows:
            self._build_pending_rows()
        elif self._finish_loading_pending:
            self._finish_loading_pending = False
            self._finish_loading()

    def cancel_pending_rows(self) -> None:
        """Abandon queued row building.

        Called when the window closes. A queued slice would otherwise keep
        firing into a pane whose widgets are being destroyed, and the close must
        never wait for construction it no longer needs.
        """
        self._row_build_timer.stop()
        self._finish_loading_pending = False
        self._pending_rows.clear()
        self._page_generation += 1
        if self._page_worker is not None:
            self._page_worker.cancel()
        self.graphics_layout.setUpdatesEnabled(True)

    def clear_sources(self) -> None:
        """Remove every plotted source and its pending row work."""
        self.cancel_pending_rows()
        self._interactions._hover.discard_items()
        self._interactions.clear_measure()
        readers_to_close = [channel.reader.source_reader for channel in self.channels]
        detached = list(self.channels)
        self.graphics_layout.setUpdatesEnabled(False)
        self._pinned_layout.setUpdatesEnabled(False)
        try:
            if detached:
                self._detach_rows_bulk(detached)
            self.channels.clear()
            self._index_cache = None
            # The rows of a page still in flight hold their readers' memory maps.
            self._requested_rows = ()
            self._requested_keys = ()
            self._scroll_only_pending = False
            self._source_time_maps.clear()
            self._readers_by_cache_and_id.clear()
            self._first_reader_by_cache.clear()
            self._source_raw_bounds.clear()
            self._units.clear()
            self._pending_pinned.clear()
            self._interactions.clear_gap_markers()
            self._master_plot = None
            self._link_x_axes()
            self._relayout_rows()
        finally:
            self._pinned_layout.setUpdatesEnabled(True)
            self.graphics_layout.setUpdatesEnabled(True)
        self._refresh_mode_view()
        self.sources_changed.emit([])
        self.visible_sources_changed.emit([])
        self._interactions.redraw_page_overlays()
        for reader in readers_to_close:
            reader.close()
        self._retire_detached_rows(detached)

    def _finish_loading(self) -> None:
        """Apply the once-per-load work after the last queued row exists."""
        # pyqtgraph maps an X link through the two views' *pixel* geometry, and
        # a row created in this same call has not been laid out yet, so its
        # width is still a placeholder. Linking against that produced a wildly
        # wrong range on the final row of every load. Settle the layout first.
        #
        # `activate()` alone is not enough: it arranges children *inside* the
        # central item's current geometry, and that geometry is only refreshed
        # by a resize reaching the view. Rows are built across event-loop turns,
        # so the last resize often predates them and the central item
        # still holds its pre-show default — every row then collapses to its
        # ~8 px minimum while the pane around it is a thousand pixels wide.
        # Intermittent, because it depends on whether a resize happened to land
        # after the final row. `resizeEvent` ignores its argument and re-applies
        # the view's real size, which is what pushes geometry onto the item.
        # The stack's height is part of the geometry being pushed, so it is set
        # before the resize rather than with the rest of the row layout after it.
        self._refresh_gutter_aliases()
        self._apply_stack_height()
        self.graphics_layout.resizeEvent(None)
        self.graphics_layout.ci.layout.activate()
        # Silence non-bottom axes and cull offscreen ViewBoxes *before*
        # propagating the shared X range and re-enabling updates, so a 200+ row
        # load does not render HTML tick labels and scene bounds for rows below
        # the fold.
        self._update_axis_visibility()
        self._cull_offscreen_rows()
        self._link_x_axes()
        self.graphics_layout.setUpdatesEnabled(True)
        self._configure_shared_x_range()
        self._set_sweep_for_time(
            self._warp.to_master(self._sweep_control.last_master_time), force=True
        )
        self._apply_presentation()
        self._flush_pending_pins()
        self.sources_changed.emit([ch.reader for ch in self.channels])
        self._emit_visible_sources()
        self._interactions.redraw_annotations()
        self.rows_pending.emit(0)
        self.channels_loaded.emit()

    def _emit_visible_sources(self) -> None:
        """Publish currently visible channel readers for the Values inspector."""
        self.visible_sources_changed.emit([ch.reader for ch in self.channels if ch.visible])

    def _refresh_gutter_aliases(self) -> None:
        """Compute concise ``group · leaf`` gutter labels per source."""
        by_source: dict[str, list[ChannelPlot]] = {}
        for ch in self.channels:
            by_source.setdefault(ch.reader.source_id, []).append(ch)
        for rows in by_source.values():
            paths = channel_tree_paths([ch.name for ch in rows])
            for ch in rows:
                set_channel_gutter_alias(ch, compact_channel_label(ch.name, paths.get(ch.name)))

    def wait_for_pending_rows(self) -> None:
        """Finish any queued row building immediately.

        For callers that need every row to exist before they continue — session
        restore. Interactive loads must not use this: blocking is the
        defect the slicing exists to avoid.
        """
        self._row_build_timer.stop()
        while self._pending_rows:
            self._build_pending_rows()
        self._row_build_timer.stop()
        self._finish_loading_pending = False
        # `_build_pending_rows` defers completion to the event loop; a caller
        # that asked to wait needs it applied before it continues.
        self._finish_loading()

    def set_source_mapping(
        self, cache_dir: Path, offset: float, drift_ms_per_hour: float, *, replace: bool = False
    ) -> None:
        """Re-align one time-series source against the master clock.

        The rows keep their readers; only the shared ``TimeMap`` changes, so this
        is a redraw rather than a reload no matter how large the source is.
        """
        time_map = self._source_time_maps.get(cache_dir)
        if time_map is None:
            return
        if replace:
            time_map.set_mapping(offset, drift_ms_per_hour)
        else:
            time_map.adjust_mapping(offset, drift_ms_per_hour)
        for channel in self.channels:
            if channel.reader.cache_dir == cache_dir:
                channel.coverage_bounds = channel.reader.coverage()
                channel._loaded_page_key = None  # type: ignore[attr-defined]
        self.update_plots()
        self._interactions.redraw_annotations()

    def set_source_exact_mapping(
        self, cache_dir: Path, master_times: np.ndarray, source_times: np.ndarray
    ) -> None:
        """Apply measured frame timing to existing and future rows of a source."""
        time_map = self._source_time_maps.setdefault(cache_dir, TimeMap())
        time_map.set_exact_mapping(master_times, source_times)
        for channel in self.channels:
            if channel.reader.cache_dir == cache_dir:
                channel.coverage_bounds = channel.reader.coverage()
                channel._loaded_page_key = None  # type: ignore[attr-defined]
        if self.channels:
            self.update_plots()

    def source_mapping(self, cache_dir: Path) -> tuple[float, float]:
        """Return the ``(offset, drift_ms_per_hour)`` currently applied to a source."""
        time_map = self.source_time_map(cache_dir)
        if time_map is None:
            return 0.0, 0.0
        return time_map.offset, time_map.drift_ms_per_hour

    def reader_for(self, cache_dir: Path, channel_id: str) -> MappedChannelReader | None:
        """Return the ``MappedChannelReader`` for ``(cache_dir, channel_id)`` in O(1)."""
        self._channel_maps()
        return self._readers_by_cache_and_id.get((cache_dir, channel_id))

    def source_time_map(self, cache_dir: Path) -> TimeMap | None:
        """Return the shared ``TimeMap`` for *cache_dir* in O(1), or ``None``."""
        self._channel_maps()
        first = self._first_reader_by_cache.get(cache_dir)
        if first is not None:
            return first.time_map
        return self._source_time_maps.get(cache_dir)

    def record_source_raw_bounds(self, cache_dir: Path, raw_bounds: tuple[float, float]) -> None:
        """Record unmapped ``(t0, t1)`` bounds for *cache_dir* so ``source_bounds`` stays O(1)."""
        if len(raw_bounds) == 2 and math.isfinite(raw_bounds[0]) and math.isfinite(raw_bounds[1]):
            self._source_raw_bounds[cache_dir] = (float(raw_bounds[0]), float(raw_bounds[1]))

    def source_bounds(self, cache_dir: Path) -> tuple[float, float] | None:
        """Return one source's master-time coverage across all of its channels."""
        self._channel_maps()
        raw_cached = self._source_raw_bounds.get(cache_dir)
        first_reader = self._first_reader_by_cache.get(cache_dir)
        if raw_cached is not None and (
            first_reader is not None or any(row[0] == cache_dir for row in self._pending_rows)
        ):
            tm = (
                first_reader.time_map
                if first_reader is not None
                else self._source_time_maps.get(cache_dir)
            )
            if tm is not None:
                m0, m1 = tm.to_master(raw_cached[0]), tm.to_master(raw_cached[1])
                return min(m0, m1), max(m0, m1)

        source_rows = [ch for ch in self.channels if ch.reader.cache_dir == cache_dir]
        if not source_rows:
            return None
        raw_spans: list[tuple[float, float]] = []
        master_spans: list[tuple[float, float]] = []
        shared_tm = source_rows[0].reader.time_map
        all_share_tm = True
        for ch in source_rows:
            if ch.reader.time_map is not shared_tm:
                all_share_tm = False
            src_reader = getattr(ch.reader, "source_reader", None)
            src_cov = getattr(src_reader, "coverage", None)
            if callable(src_cov):
                rb = src_cov()
                if rb is not None:
                    raw_spans.append(rb)
                    master_spans.append(
                        (ch.reader.time_map.to_master(rb[0]), ch.reader.time_map.to_master(rb[1]))
                    )
                continue
            mb = ch.reader.coverage()
            if mb is not None:
                master_spans.append(mb)
                all_share_tm = False
        if not master_spans:
            return None
        if (
            all_share_tm
            and raw_spans
            and not any(row[0] == cache_dir for row in self._pending_rows)
        ):
            self._source_raw_bounds[cache_dir] = (
                min(s[0] for s in raw_spans),
                max(s[1] for s in raw_spans),
            )
        return min(s[0] for s in master_spans), max(s[1] for s in master_spans)

    def read_channels_from(self, source_id: str, directories: Mapping[str, Path]) -> None:
        """Read one source's rows from the directories named in *directories*.

        What makes an accepted identity swap visible in the plots: the row keeps
        its colour, its Y scale, its unit and its visibility, and only the
        arrays underneath it change (:mod:`avialsync.core.edit_cache`).  Every
        channel is named, including the unedited ones, so undoing the last edit
        points the rows home again by the same path that pointed them away.
        """
        touched = False
        for channel in self.channels:
            directory = directories.get(channel.reader.channel_id)
            if directory is None or channel.reader.source_id != source_id:
                continue
            if channel.reader.source_reader.cache_dir != directory:
                channel.reader.read_from(directory)
                channel._loaded_page_key = None  # type: ignore[attr-defined]
                touched = True
        if touched:
            self.update_plots()

    def remove_channels(self, cache_dir: Path) -> None:
        """Remove all channels associated with a specific cache_dir (source)."""
        self._source_time_maps.pop(cache_dir, None)
        self._source_raw_bounds.pop(cache_dir, None)
        self._first_reader_by_cache.pop(cache_dir, None)
        removed_pending = [row for row in self._pending_rows if row[0] == cache_dir]
        if removed_pending:
            self._pending_rows = [row for row in self._pending_rows if row[0] != cache_dir]
            for _dir, name, _tm, source_id, _vis in removed_pending:
                key = ChannelKey(source_id, name)
                self._units.pop(key, None)
                self._interactions.forget_gap_markers(key)
            if not self._pending_rows:
                self.graphics_layout.setUpdatesEnabled(True)
        to_remove = [ch for ch in self.channels if ch.reader.cache_dir == cache_dir]
        if to_remove:
            self._interactions._hover.discard_items()
        for ch in to_remove:
            self._units.pop(ch.reader.key, None)
            self._source_raw_bounds.pop(ch.reader.cache_dir, None)
            self._readers_by_cache_and_id.pop((ch.reader.cache_dir, ch.reader.channel_id), None)
            self._interactions.forget_gap_markers(ch.reader.key)
        if to_remove:
            remove_ids = {id(ch) for ch in to_remove}
            if any(id(ch) in remove_ids for ch in self._requested_rows):
                self._requested_rows = ()
                self._requested_keys = ()
            self.graphics_layout.setUpdatesEnabled(False)
            self._pinned_layout.setUpdatesEnabled(False)
            try:
                self._detach_rows_bulk(to_remove)
                self.channels = [ch for ch in self.channels if id(ch) not in remove_ids]
                self._index_cache = None
                if any(self._master_plot == ch.plot_item for ch in to_remove):
                    self._master_plot = self.channels[0].plot_item if self.channels else None
                self._link_x_axes()
                self._relayout_rows()
            finally:
                self._pinned_layout.setUpdatesEnabled(True)
                if not self._pending_rows:
                    self.graphics_layout.setUpdatesEnabled(True)
        else:
            self._link_x_axes()
            self._relayout_rows()
        self._refresh_mode_view()

        self.sources_changed.emit([ch.reader for ch in self.channels])
        self._emit_visible_sources()
        self._interactions.redraw_page_overlays()
        for ch in to_remove:
            ch.reader.source_reader.close()
        self._retire_detached_rows(to_remove)

    def _channel_maps(
        self,
    ) -> tuple[dict[ChannelKey, list[ChannelPlot]], dict[str, list[ChannelPlot]]]:
        sig = (
            len(self.channels),
            id(self.channels[0]) if self.channels else 0,
            id(self.channels[-1]) if self.channels else 0,
        )
        if self._index_cache is not None and self._index_cache[0] == sig:
            return self._index_cache[1], self._index_cache[2]
        by_key: dict[ChannelKey, list[ChannelPlot]] = {}
        by_name: dict[str, list[ChannelPlot]] = {}
        by_cache_id: dict[tuple[Path, str], MappedChannelReader] = {}
        first_by_cache: dict[Path, MappedChannelReader] = {}
        for ch in self.channels:
            reader = ch.reader
            key = getattr(reader, "key", None)
            channel_id = getattr(reader, "channel_id", None)
            cache_dir = getattr(reader, "cache_dir", None)
            if isinstance(key, ChannelKey):
                by_key.setdefault(key, []).append(ch)
            if isinstance(channel_id, str):
                by_name.setdefault(channel_id, []).append(ch)
            if isinstance(cache_dir, Path) and isinstance(channel_id, str):
                by_cache_id[(cache_dir, channel_id)] = reader
            if isinstance(cache_dir, Path):
                first_by_cache.setdefault(cache_dir, reader)
        self._readers_by_cache_and_id = by_cache_id
        self._first_reader_by_cache = first_by_cache
        self._index_cache = (sig, by_key, by_name)
        return by_key, by_name

    def _matching(self, channel: ChannelKey | str) -> list[ChannelPlot]:
        """Resolve a channel reference to the rows it identifies.

        A :class:`ChannelKey` selects exactly one source's row.  A bare name is
        ambiguous by construction — two files can both contain ``force_z`` — so
        it matches every owner and says so, rather than silently picking one.
        """
        by_key, by_name = self._channel_maps()
        if isinstance(channel, ChannelKey):
            return list(by_key.get(channel, ()))
        matches = list(by_name.get(channel, ()))
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
        if isinstance(channel, ChannelKey):
            self._pending_rows = [
                row
                for row in self._pending_rows
                if not (row[3] == channel.source_id and row[1] == channel.channel_id)
            ]
        else:
            self._pending_rows = [row for row in self._pending_rows if row[1] != channel]
        if not self._pending_rows:
            self.graphics_layout.setUpdatesEnabled(True)
        to_remove = self._matching(channel)
        if to_remove:
            self._interactions._hover.discard_items()
        for ch in to_remove:
            self._units.pop(ch.reader.key, None)
            self._source_raw_bounds.pop(ch.reader.cache_dir, None)
            self._readers_by_cache_and_id.pop((ch.reader.cache_dir, ch.reader.channel_id), None)
            self._interactions.forget_gap_markers(ch.reader.key)
            ch.plot_item.setXLink(None)
            owner = self._pinned_layout if ch.pinned_in_layout else self.graphics_layout
            detach_row(owner, ch)
            self.channels.remove(ch)

            if self._master_plot == ch.plot_item:
                self._master_plot = self.channels[0].plot_item if self.channels else None
        self._index_cache = None

        self._link_x_axes()
        self._relayout_rows()
        self._refresh_mode_view()

        self.sources_changed.emit([ch.reader for ch in self.channels])
        self._emit_visible_sources()
        self._interactions.redraw_page_overlays()
        for ch in to_remove:
            ch.reader.source_reader.close()
        self._retire_detached_rows(to_remove)

    def load_source(self, cache_dir: Path, channel_id: str) -> None:
        """Backwards compatibility for the original single-channel load."""
        self.load_channels(cache_dir, [channel_id])

    def _channel_page_key(self, channel: ChannelPlot, budget: int) -> tuple[object, ...] | None:
        if self.sweep_start is None:
            return None
        tm = channel.reader.time_map
        src_reader = getattr(channel.reader, "source_reader", None)
        active_dir = getattr(src_reader, "cache_dir", channel.reader.cache_dir)
        return (
            self.sweep_start,
            self.window_duration,
            budget,
            self._warp,
            active_dir,
            tm.offset,
            tm.drift_ms_per_hour,
            id(getattr(tm, "_exact_master", None)),
        )

    def update_plots(self) -> None:
        """Request a worker-prepared page; install only its latest complete result.

        No pyramid row is queried here. Requests coalesce: one page is in
        flight at a time, a newer request cancels it, and the newest is started
        when it stops. Every row of a page is installed in one callback, so
        rows never disagree about which page they show.
        """
        if self.sweep_start is None or not self.channels:
            return
        self._scroll_only_pending = False
        self._page_generation += 1
        self._hold_rows_at_their_times()
        if self._page_worker is not None:
            self._page_worker.cancel()
            return
        self._start_page_job()

    def _request_uncull_page(self) -> None:
        """Load page data only for newly scrolled-into-view rows lacking the current page."""
        if self.sweep_start is None or not self.channels or self._closed:
            return
        if self._page_worker is None:
            self._scroll_only_pending = True
        self._page_generation += 1
        if self._page_worker is not None:
            self._page_worker.cancel()
            return
        self._start_page_job()

    def _hold_rows_at_their_times(self) -> None:
        """Keep each row's samples at their true time until its new page arrives.

        The axis and cursor move with the page at once; the data follows from a
        worker. Offsetting a row by how far its data's page start is from the
        new one shows the previous samples where they belong -- usually off
        screen -- rather than drawn under times they were never recorded at.
        """
        if self.sweep_start is None:
            return
        for channel in self.channels:
            if channel.visible and channel.page_t0 is not None:
                channel.curve.setPos(channel.page_t0 - self.sweep_start, 0.0)

    def _start_page_job(self) -> None:
        if self._closed or self.sweep_start is None or not self.channels:
            return
        scroll_only = self._scroll_only_pending
        self._scroll_only_pending = False
        t0 = self.sweep_start
        budget = point_budget_for_width(int(self.graphics_layout.viewport().width()))
        self._last_point_budget = budget
        visible = [channel for channel in self.channels if channel.visible]
        skip_culled = (
            len(visible) > _CULLED_PAGE_SKIP_THRESHOLD
            and self._view_mode == PLOT_MODE_STACKED
            and not self._draw_every_row
            and self.isVisible()
        )
        candidates = [ch for ch in visible if not ch.culled] if skip_culled else visible
        if scroll_only:
            candidates = [
                ch
                for ch in candidates
                if getattr(ch, "_loaded_page_key", None) != self._channel_page_key(ch, budget)
            ]
            if not candidates:
                self._last_installed_generation = self._page_generation
                return
        self._requested_rows = tuple(candidates)
        self._requested_keys = tuple(
            self._channel_page_key(ch, budget) for ch in self._requested_rows
        )
        rows = tuple(
            PlotRowRequest(
                index,
                channel.reader.source_reader,
                channel.reader.source_id,
                channel.reader.time_map.copy(),
            )
            for index, channel in enumerate(self._requested_rows)
        )
        worker = PlotPageWorker(
            self._page_generation, t0, t0 + self.window_duration, budget, rows, self._warp
        )
        self._page_worker = worker

        def configure(thread: QThread) -> None:
            worker.finished.connect(self._on_page_ready)
            worker.error.connect(self._on_page_error)
            thread.finished.connect(self._on_page_thread_finished)

        # Registered like every job, but announced only if it outlasts
        # the half-second reporting threshold: a page usually lands within a frame or two.
        label = tr("Preparing plot page")
        run_job = getattr(self.window(), "_run_job", None)
        if callable(run_job):
            self._page_thread = run_job(
                worker, label=label, configure=configure, announce_after_s=_PAGE_ANNOUNCE_S
            )
        else:
            if self._page_manager is None:
                self._page_manager = JobManager(self)
            self._page_thread = self._page_manager.start(
                label, worker, configure=configure, announce_after_s=_PAGE_ANNOUNCE_S
            )

    @Slot(object)
    def _on_page_ready(self, page: object) -> None:
        """Install a whole current page in one callback; drop anything older."""
        if not isinstance(page, PlotPage) or page.generation != self._page_generation:
            return
        if self.sweep_start != page.t0:
            return
        # Rows are matched by identity, not position: a row removed while the
        # page was prepared must not hand its curve to the row after it.
        alive = {id(channel) for channel in self.channels}
        suspend = not self._pending_rows
        if suspend:
            self.graphics_layout.setUpdatesEnabled(False)
            self._pinned_layout.setUpdatesEnabled(False)
        try:
            for index, x, y in page.rows:
                if index >= len(self._requested_rows):
                    continue
                channel = self._requested_rows[index]
                if id(channel) not in alive:
                    continue
                channel.curve.setData(x, y)
                if channel.curve.pos().x() != 0.0:
                    channel.curve.setPos(0.0, 0.0)
                channel.page_t0 = page.t0
                if index < len(self._requested_keys):
                    channel._loaded_page_key = self._requested_keys[index]  # type: ignore[attr-defined]
                if channel.y_mode == Y_AUTO or (
                    channel.y_mode == Y_FIT_ONCE and channel.y_range is None
                ):
                    fit_channel_y(channel)
                    if channel.y_mode == Y_FIT_ONCE and channel.y_range is not None:
                        channel.y_mode = Y_MANUAL
            self._last_installed_generation = page.generation
            self._refresh_mode_view()
        finally:
            if suspend:
                self._pinned_layout.setUpdatesEnabled(True)
                self.graphics_layout.setUpdatesEnabled(True)
        self.page_ready.emit(page.generation)

    @Slot(str)
    def _on_page_error(self, message: str) -> None:
        logger.warning("Plot page preparation failed: %s", message)

    @Slot()
    def _on_page_thread_finished(self) -> None:
        finished = self._page_worker
        self._page_worker = None
        self._page_thread = None
        # Its page has landed or been discarded; holding the rows would keep a
        # removed row's memory maps open, which Windows will not delete under.
        self._requested_rows = ()
        self._requested_keys = ()
        if finished is not None and finished.generation != self._page_generation:
            self._start_page_job()

    def set_cursor(self, t: float, *, immediate: bool = False) -> None:
        """Advance the fixed sweep from the master-clock time."""
        if immediate or self._playing:
            self._sweep_control.follow_time_if_outside(self._warp.to_view(t))
        self._set_sweep_for_time(t, immediate_cursor=immediate)

    @property
    def view_mode(self) -> str:
        """Current multi-channel presentation: ``'stacked'``, ``'overlay'``, or ``'heatmap'``."""
        return self._view_mode

    def set_view_mode(self, mode: str) -> None:
        """Switch between stacked rows, grouped signal bands, overlaid traces, and heatmap."""
        if mode not in ("stacked", "grouped", "overlay", "heatmap") or mode == self._view_mode:
            return
        self._view_mode = mode
        idx = self.view_mode_combo.findData(mode)
        if idx >= 0 and self.view_mode_combo.currentIndex() != idx:
            self.view_mode_combo.blockSignals(True)
            self.view_mode_combo.setCurrentIndex(idx)
            self.view_mode_combo.blockSignals(False)
        stacked = mode == PLOT_MODE_STACKED
        self._plot_scroll.setVisible(stacked)
        has_pinned = any(ch.pinned_in_layout and ch.visible for ch in self.channels)
        self._pinned_layout.setVisible(stacked and has_pinned)
        self._mode_view.setVisible(not stacked)
        if not stacked:
            self._mode_view.set_mode(mode)
            self._refresh_mode_view()
            self._interactions.redraw_page_overlays()
            if self.sweep_start is not None:
                budget = point_budget_for_width(int(self.graphics_layout.viewport().width()))
                if any(
                    ch.visible
                    and getattr(ch, "_loaded_page_key", None) != self._channel_page_key(ch, budget)
                    for ch in self.channels
                ):
                    self.update_plots()

    def set_channel_pinned(self, channel: ChannelKey | str, pinned: bool) -> None:
        """Pin *channel* to the sticky top stack or return it to the scrollable stack."""
        changed = False
        for ch in self._matching(channel):
            if ch.pinned != bool(pinned):
                ch.pinned = bool(pinned)
                changed = True
        if changed:
            rebuild_rows_across_stacks(self)

    def clear_pending_pins(self) -> None:
        """Forget deferred session-restore channel pins."""
        self._pending_pinned.clear()

    def apply_pinned_channels(
        self,
        entries: list[dict[str, str]],
        relink_map: Mapping[str, str] | None = None,
    ) -> None:
        """Pin channels immediately when loaded, and defer unloaded ones until rows build."""
        remap = relink_map or {}
        for item in entries:
            chan = str(item.get("channel", ""))
            if not chan:
                continue
            raw_src = str(item.get("source_id", ""))
            src = remap.get(raw_src, raw_src) if raw_src else ""
            self._pending_pinned.add((src, chan))
        self._flush_pending_pins()

    def _flush_pending_pins(self) -> None:
        if not self._pending_pinned or not self.channels:
            return
        changed = False
        for ch in self.channels:
            exact = (ch.reader.source_id, ch.name)
            loose = ("", ch.name)
            if exact in self._pending_pinned or loose in self._pending_pinned:
                self._pending_pinned.discard(exact)
                self._pending_pinned.discard(loose)
                if not ch.pinned:
                    ch.pinned = True
                    changed = True
        if changed:
            rebuild_rows_across_stacks(self)

    def scroll_to_channel(self, channel: ChannelKey | str) -> bool:
        """Scroll the channel stack to bring *channel* into view; returns True if found."""
        matches = [ch for ch in self._matching(channel) if ch.visible]
        if not matches:
            return False
        target = matches[0]
        if target.pinned_in_layout:
            return True
        y_top = int(target.plot_item.geometry().top())
        bar = self._plot_scroll.verticalScrollBar()
        bar.setValue(max(0, y_top - 12))
        return True

    def zoom_around_cursor(
        self, seconds: float, anchor_view_t: float, fraction: float = 0.5
    ) -> None:
        """Zoom the shared time span while keeping *anchor_view_t* under *fraction*."""
        if seconds <= 0:
            self.reset_zoom()
            return
        self._sweep_control.zoom_around(seconds, anchor_view_t, fraction)

    def set_manual_view_start(self, view_start: float) -> None:
        """Pan the shared time window horizontally in view-time seconds."""
        if not self._sweep_control.set_manual_start(view_start):
            return
        self._set_sweep_for_time(
            self._warp.to_master(self._sweep_control.last_master_time), force=True
        )

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

    def is_channel_visible(self, channel: ChannelKey | str) -> bool:
        """Whether *channel* is currently shown.

        Needed so a group toggle can record what it is replacing: undoing a
        half-hidden group has to restore the mixture, not turn everything on.
        Defaults to True for a channel this pane does not own, which is the
        state an unknown row would have if it were added.
        """
        rows = self._matching(channel)
        return all(row.visible for row in rows) if rows else True

    def set_channel_visible(self, channel: ChannelKey | str, visible: bool) -> None:
        """Show or hide the plot row(s) identified by *channel*."""
        need_relink = False
        for ch in self._matching(channel):
            ch.visible = visible
            apply_channel_visibility(ch)
            if not visible and ch.plot_item == self._master_plot:
                need_relink = True
            elif visible and self._master_plot is None:
                need_relink = True
            elif (
                visible
                and self._master_plot is not None
                and ch.plot_item != self._master_plot
                and ch.plot_item.vb.linkedView(0) is not self._master_plot.vb
            ):
                ch.plot_item.layout.activate()
                if self.window_duration > 0:
                    ch.plot_item.setXRange(0.0, self.window_duration, padding=0)
                ch.plot_item.setXLink(self._master_plot)
        if need_relink:
            self._link_x_axes()
        if visible and self.sweep_start is not None:
            # The shown row's page comes from the worker like any other.
            self.update_plots()
        else:
            self._refresh_mode_view()
        self._redraw_sweep_overlays()
        self._relayout_rows()
        self._emit_visible_sources()

    def set_channels_visible(
        self,
        updates: Mapping[ChannelKey, bool] | Mapping[str, bool] | Mapping[ChannelKey | str, bool],
    ) -> None:
        """Batch-update visibility across many channels with one relayout and page refresh."""
        if not updates:
            return
        by_key, _by_name = self._channel_maps()
        to_apply: list[tuple[ChannelPlot, bool]] = []
        any_shown = False
        for target, visible in updates.items():
            rows = (
                list(by_key.get(target, ()))
                if isinstance(target, ChannelKey)
                else self._matching(target)
            )
            for ch in rows:
                if ch.visible != visible:
                    to_apply.append((ch, visible))
                    if visible:
                        any_shown = True
        if not to_apply:
            return
        if len(to_apply) <= 8:
            need_relink = False
            for ch, visible in to_apply:
                ch.visible = visible
                apply_channel_visibility(ch)
                if not visible and ch.plot_item == self._master_plot:
                    need_relink = True
                elif visible and self._master_plot is None:
                    need_relink = True
                elif (
                    visible
                    and self._master_plot is not None
                    and ch.plot_item != self._master_plot
                    and ch.plot_item.vb.linkedView(0) is not self._master_plot.vb
                ):
                    ch.plot_item.layout.activate()
                    if self.window_duration > 0:
                        ch.plot_item.setXRange(0.0, self.window_duration, padding=0)
                    ch.plot_item.setXLink(self._master_plot)
            if need_relink:
                self._link_x_axes()
            if any_shown and self.sweep_start is not None:
                self.update_plots()
            else:
                self._refresh_mode_view()
            self._redraw_sweep_overlays()
            self._relayout_rows()
            self._emit_visible_sources()
            return
        self.graphics_layout.setUpdatesEnabled(False)
        self._pinned_layout.setUpdatesEnabled(False)
        try:
            for ch, visible in to_apply:
                ch.visible = visible
                if not visible:
                    ch.plot_item.setXLink(None)
                apply_channel_visibility(ch)
            self._relayout_rows()
            self.graphics_layout.resizeEvent(None)
            self.graphics_layout.ci.layout.activate()
            if self._pinned_layout.isVisible():
                self._pinned_layout.resizeEvent(None)
                self._pinned_layout.ci.layout.activate()
            self._cull_timer.stop()
            self._cull_offscreen_rows()
            self._link_x_axes()
        finally:
            self._pinned_layout.setUpdatesEnabled(True)
            if not self._pending_rows:
                self.graphics_layout.setUpdatesEnabled(True)
        if any_shown and self.sweep_start is not None:
            self.update_plots()
        else:
            self._refresh_mode_view()
        self._redraw_sweep_overlays()
        self._emit_visible_sources()

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

    def set_channel_y_mode(self, channel_id: ChannelKey | str, mode: str) -> None:
        """Set one row's explicit Fit/Auto/Manual amplitude behaviour."""
        if mode not in {Y_FIT_ONCE, Y_AUTO, Y_MANUAL}:
            raise ValueError(f"Unknown plot Y mode: {mode}")
        for ch in self._matching(channel_id):
            ch.y_mode = mode
            if mode == Y_FIT_ONCE:
                ch.y_range = None
                fit_channel_y(ch)
                if ch.y_range is not None:
                    ch.y_mode = Y_MANUAL
            elif mode == Y_AUTO:
                fit_channel_y(ch)

    def set_channel_unit(self, channel: ChannelKey | str, unit: str) -> None:
        """Update the fixed channel gutter after import metadata is available."""
        self._units[channel] = unit
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
        self._master_bounds = (t0, t1)
        self._sweep_control.set_bounds(self._warp.to_view(t0), self._warp.to_view(t1))

    def set_time_warp(self, warp: TimeWarp) -> None:
        """Draw with the timeline's collapsed gaps, or without (D-218).

        The sweep runs in view time, so a page never spends its width on time
        no source recorded; what a person reads or clicks is master time.
        """
        if warp == self._warp:
            return
        last = self._sweep_control.last_master_time
        master_last = self._warp.to_master(last)
        self._warp = warp
        self.set_timeline_bounds(*self._master_bounds)
        for channel in self.channels:
            self._label_axis(channel)
        self._set_sweep_for_time(master_last, force=True)

    def x_of(self, t_master: float) -> float | None:
        """Where master *t_master* is drawn on the page, or ``None`` with no page."""
        start = self.sweep_start
        return None if start is None else self._warp.to_view(t_master) - start

    def master_at(self, x: float) -> float:
        """The master time drawn at page position *x*."""
        return self._warp.to_master((self.sweep_start or 0.0) + x)

    def x_range(self, t0: float, t1: float) -> tuple[float, float] | None:
        """Master ``[t0, t1]`` clipped to the page, as page positions."""
        start = self.sweep_start
        if start is None:
            return None
        left = max(0.0, self._warp.to_view(t0) - start)
        right = min(self.window_duration, self._warp.to_view(t1) - start)
        return (left, right) if right >= left else None

    def _label_axis(self, channel: object) -> None:
        """Label the time axis in master seconds from the page start, across breaks."""
        axis = channel.plot_item.getAxis("bottom")  # type: ignore[attr-defined]
        plain = type(axis).tickStrings.__get__(axis)
        if not self._warp:
            axis.tickStrings = plain
            return

        pane_ref = ref(self)

        def strings(values: list[float], scale: float, spacing: float) -> list[str]:
            pane = pane_ref()
            if pane is None:
                return [str(text) for text in plain(values, scale, spacing)]
            origin = pane.master_at(0.0)
            shifted = [pane.master_at(value) - origin for value in values]
            return [str(text) for text in plain(shifted, scale, spacing)]

        axis.tickStrings = strings
        axis.picture = None
        axis.update()

    @property
    def window_duration(self) -> float:
        """Return the fixed X-window duration in seconds."""
        return self._sweep_control.window_duration

    @property
    def sweep_start(self) -> float | None:
        """Return the start of the currently displayed sweep, in view time.

        View time is master time unless gaps are collapsed (D-218); convert
        page positions with :meth:`master_at` and :meth:`x_of`, never by adding
        this.
        """
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
        """Request every row for the new span from the page worker.

        At 128 channels a synchronous requery averaged 38 ms against the
        30 ms UI-callback ceiling; no page is queried on this thread now.
        """
        self._configure_shared_x_range()
        self._set_sweep_for_time(
            self._warp.to_master(self._sweep_control.last_master_time), force=True
        )

    def _refresh_after_resize(self) -> None:
        enforce_channel_visibility(self.channels)
        point_budget = point_budget_for_width(int(self.graphics_layout.viewport().width()))
        if point_budget != self._last_point_budget:
            self.update_plots()

    def _configure_shared_x_range(self) -> None:
        """Set the window on the link master, which propagates to every row.

        Only the master is set. Assigning a range to an already-linked child
        feeds back through the link and rescales the master instead, which
        desynchronised the rows it was meant to align. A row gets its range
        *before* it is linked — see :meth:`_build_pending_rows`.
        """
        if self._master_plot is None or self.window_duration <= 0:
            return
        self._master_plot.setXRange(0.0, self.window_duration, padding=0)
        # pyqtgraph applies each linked view's new transform lazily, at the
        # start of the next paint, and that change itself requests a second
        # full repaint. Applying them now makes a span change one paint: 31-47
        # ms of UI time at 48 rows became 21-24 ms.
        scene = self.graphics_layout.scene()
        if scene is not None:
            scene.prepareForPaint()

    def _link_x_axes(self) -> None:
        self._master_plot = next(
            (ch.plot_item for ch in self.channels if ch.visible),
            self.channels[0].plot_item if self.channels else None,
        )
        if self._master_plot is None:
            return
        self._master_plot.layout.activate()
        if self.window_duration > 0:
            self._master_plot.setXRange(0.0, self.window_duration, padding=0)
        for ch in self.channels:
            if not ch.visible:
                ch.plot_item.setXLink(None)
                continue
            if ch.plot_item == self._master_plot:
                ch.plot_item.setXLink(None)
                continue
            if ch.plot_item.vb.linkedView(0) is not self._master_plot.vb:
                ch.plot_item.layout.activate()
                if self.window_duration > 0:
                    ch.plot_item.setXRange(0.0, self.window_duration, padding=0)
                ch.plot_item.setXLink(self._master_plot)
        self._configure_shared_x_range()

    def _relayout_rows(self) -> None:
        """Re-apply everything that depends on which rows are visible.

        The visible set changes in exactly four places -- a load finishing, a
        source removed, a row removed, a row hidden -- and both the shared axis
        and the stack height are wrong until it is re-read. Keeping them behind
        one call is what stops the next such place from remembering only one.
        """
        self._apply_stack_height()
        self._update_axis_visibility()
        self._cull_timer.start()

    @Slot()
    def _cull_offscreen_rows(self) -> None:
        """Hide the data items of rows more than a viewport out of view."""
        if self._pending_rows and not self._draw_every_row:
            return
        height = self._plot_scroll.viewport().height()
        if self._draw_every_row or not self.isVisible() or height <= 0:
            top, bottom = -math.inf, math.inf
        else:
            # A scroll re-culls before it repaints, so the margin only covers a
            # relayout, whose re-cull waits one event-loop turn: half a viewport
            # each side keeps a moved row from showing empty for that frame.
            top = self._plot_scroll.verticalScrollBar().value() - height / 2
            bottom = top + 2 * height
        position = self._sweep_control.advance(self._sweep_control.last_master_time)
        pinned = [ch for ch in self.channels if ch.pinned_in_layout]
        unpinned = [ch for ch in self.channels if not ch.pinned_in_layout]
        changed_p = cull_offscreen_rows(
            pinned, -math.inf, math.inf, phase=position.phase, sweep_start=self.sweep_start
        )
        changed_u = cull_offscreen_rows(
            unpinned, top, bottom, phase=position.phase, sweep_start=self.sweep_start
        )
        if changed_p or changed_u:
            self._redraw_sweep_overlays()
            if self.sweep_start is not None and not self._closed:
                budget = point_budget_for_width(int(self.graphics_layout.viewport().width()))
                if any(
                    ch.visible
                    and not ch.culled
                    and getattr(ch, "_loaded_page_key", None) != self._channel_page_key(ch, budget)
                    for ch in self.channels
                ):
                    self._request_uncull_page()

    @contextmanager
    def every_row_drawn(self) -> Iterator[None]:
        """Draw every row for the duration, for a capture of the whole stack."""
        self._draw_every_row = True
        self._cull_offscreen_rows()
        try:
            yield
        finally:
            self._draw_every_row = False
            self._cull_offscreen_rows()

    def _apply_stack_height(self) -> None:
        """Give the channel stack the height its visible rows actually need.

        Under the scroll area this is what produces a scrollbar: while the rows
        fit, the stack stays exactly viewport-high and they share the space as
        before; past that it grows and the scroll area scrolls it, instead of
        the rows below the fold being clipped away unreachably.

        Spacing and margins are read from the layout rather than assumed. They
        come from the style, so a hard-coded guess is a few pixels of drift per
        row, and at thirty rows that is a scrollbar that stops short of the last
        one.
        """
        visible = [
            channel for channel in self.channels if channel.visible and not channel.pinned_in_layout
        ]
        layout = self.graphics_layout.ci.layout
        spacing = max(0.0, layout.verticalSpacing())
        _, top, _, bottom = layout.getContentsMargins()
        wanted = sum(channel.row_height for channel in visible)
        if visible:
            wanted += spacing * (len(visible) - 1) + top + bottom
        self.graphics_layout.setMinimumHeight(math.ceil(wanted))

        pinned_vis = [
            channel for channel in self.channels if channel.visible and channel.pinned_in_layout
        ]
        if pinned_vis:
            p_layout = self._pinned_layout.ci.layout
            p_spacing = max(0.0, p_layout.verticalSpacing())
            _, p_top, _, p_bottom = p_layout.getContentsMargins()
            p_wanted = (
                sum(ch.row_height for ch in pinned_vis)
                + p_spacing * (len(pinned_vis) - 1)
                + p_top
                + p_bottom
            )
            self._pinned_layout.setFixedHeight(math.ceil(p_wanted))
            if self._view_mode == PLOT_MODE_STACKED:
                self._pinned_layout.show()
        else:
            self._pinned_layout.hide()

    def _update_axis_visibility(self) -> None:
        """Use one shared bottom X axis while keeping all rows X-linked."""
        unpinned_vis = [ch for ch in self.channels if ch.visible and not ch.pinned_in_layout]
        pinned_vis = [ch for ch in self.channels if ch.visible and ch.pinned_in_layout]
        bottom = unpinned_vis[-1] if unpinned_vis else (pinned_vis[-1] if pinned_vis else None)
        for channel in self.channels:
            axis = channel.plot_item.getAxis("bottom")
            show = channel is bottom
            axis.setStyle(showValues=show)
            axis.showLabel(show)
            # Recomputing the SI prefix rewrites the axis label's HTML on every
            # range change, and setHtml is the single most expensive thing a
            # span change does at 128 rows. Only one bottom axis is ever on
            # screen, so the other rows were re-rendering a label nobody sees.
            axis.enableAutoSIPrefix(show)

    def _set_row_height(self, height: int) -> None:
        """Use one scrollable channel stack rather than shrinking many rows indefinitely."""
        for channel in self.channels:
            channel.row_height = height
            apply_channel_visibility(channel)
        self._apply_stack_height()

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
        if self._view_mode != PLOT_MODE_STACKED:
            phase = (
                self._sweep_control.advance(self._sweep_control.last_master_time).phase
                if self.sweep_start is not None
                else 0.0
            )
            self._mode_view.set_cursor_phase(phase, reveal=not review)

    def _set_sweep_for_time(
        self, t: float, *, force: bool = False, immediate_cursor: bool = False
    ) -> float:
        """Derive sweep position from master time and refresh only at boundaries."""
        position = self._sweep_control.advance(self._warp.to_view(t))
        needs_initial_page = self._page_generation == 0 and bool(self.channels)
        if position.changed or force or needs_initial_page:
            self.update_plots()
            self._redraw_sweep_overlays()

        # Time has already advanced; from here down we are only moving pixels.
        # A page boundary changes *what* is drawn, so it is never deferred.
        if not (position.changed or force or immediate_cursor) and not self._cursor_repaint_due():
            return position.phase

        # Two items per visible row: the trace and the cursor.  This loop is the
        # 30 Hz repaint path, so anything added here is paid per row per frame.
        for ch in self.channels:
            if ch.visible and not ch.culled:
                ch.cursor_line.setValue(position.phase)
                ch.curve.set_sweep_position(position.phase)
        if self._view_mode != PLOT_MODE_STACKED:
            self._mode_view.set_cursor_phase(
                position.phase, reveal=self.presentation != PlotPresentation.REVIEW
            )
        self._update_page_label(position.start)
        # The strip is in master time: the page's master edges, and the playhead.
        first = self._warp.to_master(position.start)
        last = self._warp.to_master(position.start + self.window_duration)
        self.view_window_changed.emit(first, last - first, t - first)
        return position.phase

    def _cursor_repaint_due(self) -> bool:
        """Return whether enough time has passed to justify repainting the scene.

        Stamps the clock as a side effect when it returns True.  Ticks arrive
        every ~16.7 ms and the interval is ~33 ms, so at most one tick's worth
        of cursor movement is ever deferred — below the threshold at which the
        motion reads as stepped, and it frees roughly half the plot's share of
        the UI thread for video presentation.
        """
        now = _elapsed()
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
        end = self._warp.to_master(start + self.window_duration)
        start = self._warp.to_master(start)
        # The page spans a whole window, so this text is identical on almost
        # every tick; setText would still relayout the header each time.
        text = (
            f"{format_time(start, self._time_mode, self._t_epoch)} – "
            f"{format_time(end, self._time_mode, self._t_epoch)}"
        )
        if text != self._page_label_text:
            self._page_label_text = text
            self.page_label.setText(text)

    def accessible_value(self) -> str:
        """Each shown row's value at the playhead, read on query."""
        visible = [channel for channel in self.channels if channel.visible][:32]
        if not visible or self.sweep_start is None:
            return tr("No channels are shown.")
        t = self.master_at(float(visible[0].cursor_line.value()))
        parts = []
        for channel in visible:
            sample = channel.reader.available_sample_at(t)
            value = "—" if sample is None else f"{sample[1]:.4g}"
            unit = f" {channel.unit}" if channel.unit else ""
            parts.append(f"{channel.name}: {value}{unit}")
        return "; ".join(parts)

    def accessible_detail(self) -> str:
        shown = sum(channel.visible for channel in self.channels)
        return tr("{n} channel rows over a {window} s window").format(
            n=shown, window=f"{self.window_duration:g}"
        )

    def hide_channel_row(self, channel_id: ChannelKey | str) -> None:
        """Hide a row as its close tool does, from the row's context menu."""
        self._request_channel_close(channel_id)

    def _request_channel_close(self, channel_id: ChannelKey | str) -> None:
        """Row close button: hide this source's row and tell the sidebar which one."""
        matches = self._matching(channel_id)
        if isinstance(channel_id, ChannelKey):
            key = matches[0].reader.key if matches else channel_id
        else:
            match = next((ch for ch in matches if ch.visible), None) or (
                matches[0] if matches else None
            )
            key = match.reader.key if match is not None else ChannelKey("", channel_id)
        self.set_channel_visible(key, False)
        self.channel_close_requested.emit(key.source_id, key.channel_id)

    def _display_x(self, absolute_t: float) -> float | None:
        x = self.x_of(absolute_t)
        if x is None:
            return None
        if -1e-9 <= x <= self.window_duration + 1e-9:
            return max(0.0, min(self.window_duration, x))
        return None

    def _redraw_sweep_overlays(self) -> None:
        self._redraw_coverage()
        self._interactions.redraw_page_overlays()

    def _redraw_coverage(self) -> None:
        if self.sweep_start is None:
            return
        for ch in self.channels:
            if not ch.culled:
                update_channel_coverage(ch, self.x_range)

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

    def set_segment_boundaries(self, times: list[float]) -> None:
        """Draw a dashed line on every row where one trial ends and the next begins."""
        self._interactions.set_segment_boundaries(times)

    def set_gap_markers(self, channel_id: ChannelKey | str, gap_times: list[float]) -> None:
        """Overlay thin red vertical lines at gap positions for one channel."""
        self._interactions.set_gap_markers(channel_id, gap_times)

    def set_gap_markers_bulk(
        self,
        markers_by_channel: (
            Mapping[ChannelKey, Sequence[float]]
            | Mapping[str, Sequence[float]]
            | Mapping[ChannelKey | str, Sequence[float]]
        ),
    ) -> None:
        """Overlay gap markers across many channels with one redraw."""
        self._interactions.set_gap_markers_bulk(markers_by_channel)

    def set_identity_events(self, source_id: str, events: list[tuple[float, str]]) -> None:
        """Mark accepted flip boundaries on rows belonging to one pose source."""
        self._interactions.set_identity_events(source_id, events)

    def set_annotation_store(self, store: AnnotationStore) -> None:
        """Subscribe to and render the authoritative annotation store."""
        self._interactions.set_annotation_store(store)

    def set_x_range(self, t0: float, t1: float) -> None:
        """Compatibility alias for setting master timeline bounds."""
        self.set_timeline_bounds(t0, t1)
