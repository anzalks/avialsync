"""Video rendering pane: decode with PyAV, blit with Qt.

One path on every platform (D-075).  There is no render context, no ``wid``
embedding, and no headless special case, because nothing here talks to a media
player any more — the pane owns a decoder, asks it for the frame at a given
master time, and paints the result.

That inversion is the point of the migration.  Under libmpv the pane asked a
player where it had got to and tried to keep it near the master clock; now the
application decodes, so it *is* the clock, and sync is exact by construction
rather than by a tuned control loop.
"""

import logging
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import (
    Q_ARG,
    QMetaObject,
    QObject,
    QPointF,
    QRectF,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QCloseEvent,
    QFontDatabase,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.errors import SourceOpenError
from avialsync.core.source import VideoMetadata
from avialsync.engine.display_pipeline import (
    DisplayLevels,
    SourceFormat,
    auto_levels,
    probe_format,
    to_display_array,
)
from avialsync.engine.pyav_reader import PyAVReader
from avialsync.ui.i18n import tr
from avialsync.ui.theme import set_font_family
from avialsync.ui.video_overlay import PaintCanvas
from avialsync.ui.video_timing import VideoTimingMixin, displayed_frame_rate, format_video_osd

logger = logging.getLogger(__name__)

#: Fastest rate at which a pane repaints its OSD text and tracking overlay.
#: Matches the presentation rate the timeline observers already use
#: (``engine.player._PRESENTATION_HZ``): decoded frames arrive far faster than
#: this on high-fps footage, but nobody can read a clock or follow a marker
#: above ~20 Hz, and every extra repaint is UI-thread time the decoders need.
_OSD_MAX_HZ = 20.0
_OSD_MIN_INTERVAL_S = 1.0 / _OSD_MAX_HZ

#: Slack on the "is the next paint due yet" test.  Below one timer tick there is
#: nothing to gain by deferring, and an exact comparison would arm a timer for a
#: rounding error's worth of time.  This is only meaningful because the clock
#: below resolves far finer than it: measured against ``time.monotonic``'s
#: 15.625 ms step on Windows, a 1 ms slack can never be the reason anything is
#: painted, and the deferral it exists to prevent happens anyway.
_OSD_DUE_EPSILON_S = 0.001

#: How long a decode thread gets to finish its current frame at teardown.
#: A worst-case cold jump is ~120 ms, so this is generous; it exists only so a
#: wedged decoder cannot hold the UI thread for the length of a job timeout.
_DECODER_STOP_TIMEOUT_MS = 3000

#: Decode threads that outlived their timeout, retained until they finish.
#:
#: A decode thread is created as ``QThread(self)`` — parented to its pane — so
#: destroying the pane destroys it too. When the teardown wait times out, that
#: means Qt destroys a *running* QThread, which prints
#: "QThread: Destroyed while thread '' is still running" and can abort the
#: process outright. Closing the window with a camera mid-seek was enough to
#: reach it.
#:
#: The fix is the one ``ui/job_manager.py`` already uses for the same hazard:
#: detach the thread from its parent and hold a reference here until it really
#: finishes. Waiting longer is not an option — the window always closes
#: (``MainWindow.closeEvent``), and a wedged decoder must not be able to
#: prevent that.
_ABANDONED_DECODERS: set[tuple[QThread, object]] = set()


def _abandon_decoder(thread: QThread, worker: object) -> None:
    """Detach a decode thread that would not stop, and keep it alive.

    The worker is retained beside the thread for the same reason it is retained
    while running: a QObject moved to a QThread with no owning Python reference
    is collected out from under it.
    """
    entry = (thread, worker)
    _ABANDONED_DECODERS.add(entry)
    # setParent is called from the thread that owns the QThread *object* — the
    # UI thread — not from the thread of execution, which is what makes it safe
    # here even though run() is still going.
    thread.setParent(None)
    thread.finished.connect(lambda: _ABANDONED_DECODERS.discard(entry))


def drain_abandoned_decoders(timeout_ms: int = 2000) -> None:
    """Wait for detached decode threads, for tests and interpreter shutdown.

    Production does not need this: the window has already closed. But a running
    QThread alive at interpreter shutdown makes Qt abort, which turns a clean
    test run into a crash report — the same reasoning as ``job_manager``'s
    drain.
    """
    for entry in list(_ABANDONED_DECODERS):
        thread, _worker = entry
        try:
            thread.quit()
            thread.wait(timeout_ms)
            finished = thread.isFinished()
        except RuntimeError:
            # The C++ object was already deleted after finishing; a Python
            # wrapper outliving it is not a leak worth reporting.
            finished = True
        if finished:
            _ABANDONED_DECODERS.discard(entry)


#: `perf_counter`, never `time.monotonic` — the same reason as
#: `plot_pane._elapsed` and `player._now`.  On Windows through Python 3.12,
#: `monotonic` is `GetTickCount64` and steps 15.625 ms at a time, so the 50 ms
#: OSD interval could only ever be measured as a multiple of that: the throttle
#: ran at 16 Hz rather than the 20 Hz it documents, and the trailing paint armed
#: a 3.125 ms timer that re-armed itself unchanged every time it fired until the
#: clock finally ticked over, because the clock could not resolve its own
#: deadline.  `perf_counter` is sub-microsecond on all three platforms and is
#: monotonic too; only its epoch is undefined, and every use here is a
#: difference.
_elapsed = time.perf_counter


class DecodeWorker(QObject):
    """Owns one :class:`PyAVReader` on a decode thread.

    Requests coalesce: only the newest requested time is ever decoded.  The UI
    thread posts a time and an invocation; whichever invocation runs first takes
    the latest time and the rest find nothing to do.  That is what lets a 60 Hz
    tick drive a decoder that takes longer than a tick without ever queueing a
    backlog of frames nobody will see — sync correctness beats frame
    completeness (AGENTS.md rule 6).

    Each request carries an id the caller assigns, and the id travels *with* the
    time rather than beside it, so a coalesced request keeps the id of the time
    that survived.  ``frame_ready`` echoes it, which is what lets the pane tell
    "the frame I asked for" from "a frame" — see :meth:`VideoPane.seek`.
    """

    opened = Signal(object, int, int, str)  # frame_times, width, height, codec
    failed = Signal(str)
    # request id, frame index, pts seconds, RGB array
    frame_ready = Signal(int, int, float, object)
    #: The pixel format of the first decoded frame, so the UI can offer
    #: controls sized to what the recording actually is (D-093).
    format_detected = Signal(object)

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path
        self._reader: PyAVReader | None = None
        self._lock = threading.Lock()
        self._pending: tuple[int, float] | None = None
        #: Display window, read on the decode thread and written from the UI
        #: one, so it has its own lock rather than sharing the request lock.
        self._levels_lock = threading.Lock()
        self._levels = DisplayLevels()
        #: Format of the last decoded frame, published so the UI can offer
        #: controls sized to what the recording actually is.
        self.source_format: SourceFormat | None = None

    @Slot()
    def open(self) -> None:
        """Open the file and publish its timestamp table."""
        try:
            reader = PyAVReader(self._path)
        except SourceOpenError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:  # pragma: no cover - defensive
            self.failed.emit(f"Could not open {self._path}: {error}")
            return
        self._reader = reader
        stream = reader.stream
        self.opened.emit(
            reader.frame_times,
            int(stream.codec_context.width),
            int(stream.codec_context.height),
            str(stream.codec_context.name or ""),
        )

    def request(self, request_id: int, source_time: float) -> None:
        """Record the newest wanted time and its id. Safe to call from the UI thread."""
        with self._lock:
            self._pending = (request_id, source_time)

    @Slot()
    def decode_pending(self) -> None:
        """Decode the newest requested time, if one is still outstanding."""
        with self._lock:
            pending = self._pending
            self._pending = None
        if pending is None or self._reader is None:
            return
        request_id, source_time = pending
        try:
            index = self._reader.index_at_time(source_time)
            frame = self._reader.frame_at_index(index)
            # Windowed here, on the decode thread. A lookup table applied in
            # paintEvent would turn a 2 ms budget into a 3 ms violation on
            # every frame (D-093). The reader still caches `av.VideoFrame`
            # objects, so a levels change costs a re-conversion, not a
            # re-decode.
            with self._levels_lock:
                levels = self._levels
            if self.source_format is None:
                # Read once, from the frame. Nothing here assumes a depth: a
                # 10-, 12-, 14- or 8-bit recording all describe themselves.
                self.source_format = probe_format(frame)
                self.format_detected.emit(self.source_format)
            rgb, _is_grey = to_display_array(frame, levels)
        except Exception as error:
            # A decode failure is one lost frame, not a lost session: the next
            # request re-seeks from scratch. Swallowing it here keeps a damaged
            # region of a file from taking the pane down with it.
            logger.warning("Could not decode %s at %.6fs", self._path, source_time, exc_info=error)
            return
        self.frame_ready.emit(request_id, index, self._reader.time_at_index(index), rgb)

    @Slot(object)
    def set_levels(self, levels: object) -> None:
        """Adopt a new display window, applied to the next decoded frame."""
        if isinstance(levels, DisplayLevels):
            with self._levels_lock:
                self._levels = levels

    @Slot()
    def shutdown(self) -> None:
        """Close the reader on its own thread, where it was opened."""
        with self._lock:
            self._pending = None
        if self._reader is not None:
            self._reader.close()
            self._reader = None


class VideoSurface(QWidget):
    """Paint the decoded frame with an independent zoom and pan transform.

    :meth:`frame_geometry` is also the tracking overlay's single source of
    truth, so markers follow the same transform as the image.
    """

    view_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._image: QImage | None = None
        #: The array the QImage borrows. QImage does not copy the buffer, so
        #: dropping this would leave it pointing at freed memory.
        self._buffer: np.ndarray | None = None
        self._video_size = (0, 0)
        self._zoom = 1.0
        self._pan = QPointF()
        self._pan_origin: QPointF | None = None

    def set_video_size(self, width: int, height: int) -> None:
        """Publish the decoded video dimensions before its first frame arrives."""
        size = (width, height)
        if self._video_size == size:
            return
        self._video_size = size
        self._clamp_pan()
        self.update()
        self.view_changed.emit()

    def set_frame(self, rgb: np.ndarray) -> None:
        """Show a decoded frame, either ``(H, W, 3)`` RGB or ``(H, W)`` grey.

        The shape decides the format rather than an assumption: a windowed
        high-bit-depth source arrives as a single plane, which is one third the
        bytes to upload because swscale's grey-to-RGB triplication never
        happened.
        """
        if rgb.ndim == 2:
            height, width = rgb.shape
            image_format = QImage.Format.Format_Grayscale8
        else:
            height, width, _ = rgb.shape
            image_format = QImage.Format.Format_RGB888

        self.set_video_size(width, height)
        # Retained: QImage borrows this buffer rather than copying it.
        self._buffer = rgb
        self._image = QImage(rgb.data, width, height, rgb.strides[0], image_format)
        self.update()

    def clear(self) -> None:
        """Drop the displayed frame."""
        self._image = None
        self._buffer = None
        self.update()

    def frame_geometry(
        self, target_width: int | None = None, target_height: int | None = None
    ) -> tuple[float, float, float] | None:
        """Return ``(scale, offset_x, offset_y)`` for a target widget size."""
        width = self.width() if target_width is None else target_width
        height = self.height() if target_height is None else target_height
        geometry = self._base_geometry(width, height)
        if geometry is None:
            return None
        scale, offset_x, offset_y = geometry
        return scale, offset_x + self._pan.x(), offset_y + self._pan.y()

    def zoom_by(self, factor: float, anchor: QPointF | None = None) -> None:
        """Scale the view around ``anchor`` while preserving the sampled pixel."""
        if factor <= 0.0:
            return
        previous = self.frame_geometry()
        next_zoom = min(max(self._zoom * factor, 1.0), 20.0)
        if next_zoom == self._zoom:
            return
        if anchor is None:
            anchor = QPointF(self.width() / 2.0, self.height() / 2.0)
        self._zoom = next_zoom
        if previous is not None:
            scale, offset_x, offset_y = previous
            source_x = (anchor.x() - offset_x) / scale
            source_y = (anchor.y() - offset_y) / scale
            base_geometry = self._base_geometry(self.width(), self.height())
            if base_geometry is not None:
                new_scale, new_offset_x, new_offset_y = base_geometry
                self._pan = QPointF(
                    anchor.x() - new_offset_x - source_x * new_scale,
                    anchor.y() - new_offset_y - source_y * new_scale,
                )
        self._clamp_pan()
        self.update()
        self.view_changed.emit()

    def pan_by(self, delta: QPointF) -> None:
        """Shift the magnified frame by ``delta`` widget pixels, clamped to its edges."""
        if delta.isNull():
            return
        self._pan += delta
        self._clamp_pan()
        self.update()
        self.view_changed.emit()

    def reset_view(self) -> None:
        """Restore the fitted, centred video view."""
        if self._zoom == 1.0 and self._pan.isNull():
            return
        self._zoom = 1.0
        self._pan = QPointF()
        self.update()
        self.view_changed.emit()

    def _base_geometry(
        self, target_width: int, target_height: int
    ) -> tuple[float, float, float] | None:
        video_width, video_height = self._video_size
        if target_width <= 0 or target_height <= 0 or video_width <= 0 or video_height <= 0:
            return None
        scale = min(target_width / video_width, target_height / video_height) * self._zoom
        width = video_width * scale
        height = video_height * scale
        return scale, (target_width - width) / 2.0, (target_height - height) / 2.0

    def _clamp_pan(self) -> None:
        """Keep a panned image from revealing empty space beyond its edges."""
        geometry = self._base_geometry(self.width(), self.height())
        if geometry is None:
            self._pan = QPointF()
            return
        scale, _, _ = geometry
        video_width, video_height = self._video_size
        max_x = max(0.0, (video_width * scale - self.width()) / 2.0)
        max_y = max(0.0, (video_height * scale - self.height()) / 2.0)
        self._pan = QPointF(
            min(max(self._pan.x(), -max_x), max_x),
            min(max(self._pan.y(), -max_y), max_y),
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Constrain the retained pan when the pane changes size."""
        super().resizeEvent(event)
        self._clamp_pan()
        self.view_changed.emit()

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Zoom around the mouse cursor with the scroll wheel."""
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.zoom_by(1.15**steps, event.position())
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start a middle-button pan when the view is magnified."""
        if event.button() == Qt.MouseButton.MiddleButton and self._zoom > 1.0:
            self._pan_origin = event.position()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Pan the magnified frame with the held middle button."""
        if self._pan_origin is None or not event.buttons() & Qt.MouseButton.MiddleButton:
            super().mouseMoveEvent(event)
            return
        position = event.position()
        delta = position - self._pan_origin
        self._pan_origin = position
        self.pan_by(delta)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish a middle-button pan gesture."""
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_origin is not None:
            self._pan_origin = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Blit the frame using the current view transform."""
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        image = self._image
        if image is None or image.isNull():
            return
        geometry = self.frame_geometry()
        if geometry is None:
            return
        scale, offset_x, offset_y = geometry
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(
            QRectF(
                offset_x,
                offset_y,
                image.width() * scale,
                image.height() * scale,
            ),
            image,
        )


class VideoPane(VideoTimingMixin, QWidget):
    """Video rendering pane.

    Decodes with PyAV on a per-pane worker thread and blits the result.  The
    same path runs on Windows, macOS, and Linux, headless or not; if you find
    yourself adding a ``sys.platform`` branch here, that is a signal to stop and
    reconsider (AGENTS.md rule 6).
    """

    double_clicked = Signal(object)
    right_clicked = Signal(object)  # emits QPoint (global position)
    _osd_update = Signal()
    frame_presented = Signal(float)  # delivered source timestamp
    #: The recording's own pixel format, once a frame has been decoded. The
    #: UI sizes its display controls from this rather than assuming a depth.
    source_format_detected = Signal(object)
    file_loaded = Signal()
    open_failed = Signal(str)
    #: A finished "Fix Tracker" drag, as a
    #: :class:`~avialsync.core.point_edits.PointMove`. Forwarded from the paint
    #: canvas so callers wire to the pane rather than reaching into its chrome.
    point_moved = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.time_pos = 0.0
        self._is_vfr = False
        self._frame_times: np.ndarray | None = None
        self._nominal_fps = 0.0
        self._decoder_fps = 0.0
        self._metadata = VideoMetadata()
        self.is_seeking = False
        self._media_loaded = False
        self._pending_seek: float | None = None
        #: Id of the most recent seek. A frame clears `is_seeking` only when it
        #: carries this id, so an older decode cannot answer for a newer seek.
        self._seek_id = 0
        self._target_pause = True
        #: Resolved overlay visibility for this pane, global default merged
        #: with any per-camera override by the window (D-090).
        #: What this recording actually is, read from a decoded frame.
        self.source_format: SourceFormat | None = None
        self._display_levels = DisplayLevels()
        #: Last requested source time, so a levels change can re-show the same
        #: frame rather than waiting for the next seek.
        self._last_source_time: float | None = None
        self._overlay_visible: dict[str, bool] = {}
        #: Retained so a layer toggled back on can restore the label rather
        #: than showing an empty box.
        self._label_text = ""
        self._osd_lock = threading.Lock()
        self._pending_osd: tuple[float, float] = (0.0, 0.0)
        self._osd_event_pending = False
        self._osd_flush_timer: QTimer | None = None
        self._last_osd_flush = 0.0
        #: Decoded video dimensions, published once at open.  The overlay reads
        #: this to map track coordinates onto the widget.
        self.video_size: tuple[int, int] | None = None

        self._thread: QThread | None = None
        self._worker: DecodeWorker | None = None

        from avialsync.core.timeline import TimeMap

        self.time_map = TimeMap()
        self._source_bounds: tuple[float, float] | None = None
        self._master_has_footage: bool | None = None

        self._grid = QGridLayout()
        self.setLayout(self._grid)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        self.surface = VideoSurface(self)
        self.surface.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._grid.addWidget(self.surface, 0, 0)

        self._build_overlay_chrome()
        self.surface.view_changed.connect(self.paint_canvas.update)
        self._osd_update.connect(self._flush_osd_update)
        self.surface.installEventFilter(self)

    # ── media ────────────────────────────────────────────────────────

    @property
    def has_media(self) -> bool:
        """Whether this pane holds an opened decoder."""
        return self._worker is not None and self._media_loaded

    def open(self, path: str) -> None:
        """Open a video file on this pane's decode thread."""
        self._shutdown_decoder()
        self._media_loaded = False

        worker = DecodeWorker(path)
        thread = QThread(self)
        # Named so that any Qt warning about it identifies the camera. The
        # unnamed default is why "QThread: Destroyed while thread '' is still
        # running" gave no clue which pane it came from.
        thread.setObjectName(f"avialsync-decode:{Path(path).name}")
        worker.moveToThread(thread)
        # The worker must be held for the thread's whole life: a QObject moved
        # to a QThread with no owning Python reference is collected out from
        # under it (HANDOUT.md trap 0a).
        self._worker = worker
        self._thread = thread

        worker.opened.connect(self._on_opened)
        worker.failed.connect(self._on_open_failed)
        worker.frame_ready.connect(self._on_frame_ready)
        worker.format_detected.connect(self._on_format_detected)
        thread.started.connect(worker.open)
        thread.start()

    @Slot(object)
    def _on_format_detected(self, source_format: object) -> None:
        """Publish what this recording actually is, once it has been decoded."""
        if isinstance(source_format, SourceFormat):
            self.source_format = source_format
            self.source_format_detected.emit(source_format)

    def set_display_levels(self, levels: DisplayLevels) -> None:
        """Apply a display window to this camera.

        Queued to the decode thread rather than applied here: the conversion
        runs there, and a lookup table built on the UI thread would be work in
        the wrong place even if the table itself is cheap.
        """
        self._display_levels = levels
        worker = self._worker
        if worker is not None:
            QMetaObject.invokeMethod(
                worker,
                "set_levels",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(object, levels),
            )
            # Re-request the frame on screen so the change is visible while
            # paused, which is when someone sets levels. The reader caches the
            # decoded frame, so this is a re-conversion, not a re-decode.
            if self._last_source_time is not None:
                self.seek(self._last_source_time)

    def display_levels(self) -> DisplayLevels:
        return self._display_levels

    def auto_display_levels(self) -> DisplayLevels | None:
        """Levels chosen from the frame currently on screen.

        Uses the displayed 8-bit buffer rather than re-decoding: it is what the
        user is looking at when they press Auto, and re-reading the source frame
        from the UI thread would be file work in the wrong place.

        Returns ``None`` when this camera has no window to choose -- ordinary
        8-bit colour already fills the screen's range.
        """
        if self.source_format is None or not self.source_format.needs_windowing:
            return None
        buffer = getattr(getattr(self, "surface", None), "_buffer", None)
        if buffer is None:
            return None
        # The buffer is already mapped to 8 bits, so measure it on that scale
        # and express the result against the source's own.
        eight_bit = SourceFormat(pix_fmt="gray", bits=8, component_count=1)
        return auto_levels(np.asarray(buffer), eight_bit)

    @Slot(object, int, int, str)
    def _on_opened(self, frame_times: np.ndarray, width: int, height: int, codec: str) -> None:
        """Adopt the decoder's timestamp table and show the first wanted frame."""
        self._frame_times = frame_times
        self.video_size = (width, height)
        self.surface.set_video_size(width, height)
        if not self._metadata.codec or self._metadata.codec == "unknown":
            self._metadata = replace(self._metadata, codec=codec, width=width, height=height)
        self._media_loaded = True

        pending = self._pending_seek
        self._pending_seek = None
        self.seek(pending if pending is not None else self.time_pos)
        self.file_loaded.emit()

    @Slot(str)
    def _on_open_failed(self, reason: str) -> None:
        """Leave a pane that says why it is empty rather than one that lies."""
        logger.warning("Video pane could not open its source: %s", reason)
        self.lbl_no_footage.setText(f"Video unavailable\n{reason}")
        self.lbl_no_footage.setVisible(True)
        self.open_failed.emit(reason)

    @Slot(int, int, float, object)
    def _on_frame_ready(self, request_id: int, index: int, pts: float, rgb: np.ndarray) -> None:
        """Show a decoded frame and report the timestamp it actually carries.

        Every frame is painted: the decoder emits in decode order, so anything
        arriving here is newer than what is on screen and worth showing.

        Only the frame for the *newest* seek clears ``is_seeking``. Opening a
        pane issues a seek of its own (`_on_opened`), so a pane that has just
        reported ``has_media`` already has a decode in flight; with a bare
        boolean that first frame answered for whatever seek the caller made in
        the meantime, and `Seeker.is_settled` — which promises every pane has
        painted *the frame it was asked for* — could not tell the difference.
        """
        del index
        self.surface.set_frame(rgb)
        if request_id == self._seek_id:
            self.is_seeking = False
        self.time_pos = pts
        self.frame_presented.emit(pts)
        self._queue_osd_update(pts, self._displayed_rate(pts))

    def displayed_frame_rate_now(self) -> float:
        """Return the frame rate of the frame currently on screen."""
        return self._displayed_rate(self.time_pos)

    def _displayed_rate(self, source_time: float) -> float:
        return displayed_frame_rate(
            self._frame_times,
            source_time,
            self._is_vfr,
            self._nominal_fps,
            self._decoder_fps,
            self.time_map.rate_scale_at(self.time_map.to_master(source_time)),
        )

    def seek(self, t: float, exact: bool = True) -> None:
        """Show the frame whose presentation interval contains source time ``t``.

        ``exact`` is accepted and ignored.  Under libmpv a non-exact seek bought
        speed by landing on a keyframe; here the frame containing ``t`` costs a
        few milliseconds when it is anywhere near where the decoder already is,
        so there is nothing to trade away, and an inexact scrub position is
        exactly the misattribution D-075 exists to remove.
        """
        del exact
        if not self._media_loaded or self._worker is None:
            self._pending_seek = float(t)
            return
        self._seek_id += 1
        self.is_seeking = True
        self._last_source_time = float(t)
        self._worker.request(self._seek_id, float(t))
        QMetaObject.invokeMethod(self._worker, "decode_pending", Qt.ConnectionType.QueuedConnection)

    def play(self) -> None:
        """Note that the transport is running.

        The pane does not run a clock of its own: the player asks for the frame
        at each tick.  This exists so pane state still reflects the transport.
        """
        self._target_pause = False

    def pause(self) -> None:
        """Note that the transport is paused."""
        self._target_pause = True

    # ── geometry and chrome ──────────────────────────────────────────

    def set_source_bounds(self, bounds: tuple[float, float]) -> None:
        """Set the source-time interval that contains decodable media."""
        low, high = sorted(bounds)
        self._source_bounds = (low, high)

    def has_footage_at_master(self, t_master: float) -> bool:
        """Return whether this pane has media at the supplied master time."""
        if not bool(self.time_map.contains_master_time(t_master)):
            return False
        if self._source_bounds is None:
            return True
        t_source = self.time_map.to_source(t_master)
        start, end = self._source_bounds
        return bool(start <= t_source <= end)

    def set_tracking_readers(self, readers: list) -> None:
        self.paint_canvas.set_readers(readers)

    def set_overlay_tracks(self, tracks: list) -> None:
        """Draw named 2D prediction sources (ensemble + models) over this pane."""
        self.paint_canvas.set_tracks(tracks)

    def set_point_edits(self, edits: object) -> None:
        """Adopt the session's hand-correction store (D-099)."""
        self.paint_canvas.set_point_edits(edits)

    def set_point_edit_mode(self, enabled: bool) -> None:
        """Turn "Fix Tracker" on or off for this pane."""
        self.paint_canvas.set_edit_mode(enabled)

    @property
    def point_edit_mode(self) -> bool:
        """Whether this pane is currently accepting point corrections."""
        return bool(self.paint_canvas.edit_mode)

    def _queue_osd_update(self, t: float, fps: float) -> None:
        """Queue at most one UI-thread OSD/overlay update, retaining the newest frame."""
        with self._osd_lock:
            self._pending_osd = (t, fps)
            if self._osd_event_pending:
                return
            self._osd_event_pending = True
        self._osd_update.emit()

    @Slot()
    def _flush_osd_update(self) -> None:
        """Repaint the OSD and overlay, but never faster than a person can read.

        This runs once per *presented frame* per pane.  Six cameras at 120 fps
        would otherwise relayout six OSD labels and composite six translucent
        overlays 720 times a second on the UI thread, which is the whole tick
        budget.  The first frame after a quiet period paints immediately — a
        paused seek or a frame step must show its result at once — and a
        trailing timer guarantees the final frame of a burst is not dropped.
        """
        now = _elapsed()
        remaining = _OSD_MIN_INTERVAL_S - (now - self._last_osd_flush)
        # Anything this close to due is painted now.  Deferring it would arm a
        # timer for less than the clock's own resolution.
        if remaining > _OSD_DUE_EPSILON_S:
            # Leave _osd_event_pending set: newer frames keep overwriting
            # _pending_osd instead of queueing more events, so the timer paints
            # the newest frame exactly once.
            self._arm_osd_flush_timer(remaining)
            return

        with self._osd_lock:
            t, fps = self._pending_osd
            self._osd_event_pending = False
        self._last_osd_flush = now
        self._update_osd(t, fps)

    def _arm_osd_flush_timer(self, delay_s: float) -> None:
        """Schedule the deferred trailing OSD paint, at most one outstanding."""
        timer = self._osd_flush_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setTimerType(Qt.TimerType.CoarseTimer)
            timer.timeout.connect(self._flush_osd_update)
            self._osd_flush_timer = timer
        if not timer.isActive():
            timer.start(max(1, int(delay_s * 1000.0)))

    def eventFilter(self, obj, event):
        if obj is self.surface:
            try:
                # Compare integer values to avoid PySide6 EnumType.__call__ exceptions
                ev_type = int(event.type())
                if ev_type == 4:  # QEvent.Type.MouseButtonDblClick
                    self.double_clicked.emit(self)
                elif ev_type == 82:  # QEvent.Type.ContextMenu
                    self.right_clicked.emit(event.globalPos())
                    return True  # consume; MainWindow builds the menu
            except (AttributeError, RuntimeError, TypeError):
                logger.debug("Ignored invalid video-pane event", exc_info=True)
        return super().eventFilter(obj, event)

    def set_label(self, text: str) -> None:
        self._label_text = text
        if text and self._overlay_visible.get("camera.name", True):
            self.lbl_name.setText(text)
            self.lbl_name.setVisible(True)
        else:
            self.lbl_name.setVisible(False)

    def apply_overlay_visibility(self, visibility: dict[str, bool]) -> None:
        """Show or hide each registered overlay layer on this pane (D-090).

        Takes the already-resolved map rather than the registry itself: the
        global default and any per-camera override are combined once, by the
        window, so a pane never has to know which of the two it is following.
        """
        self._overlay_visible = dict(visibility)

        self.paint_canvas.set_points_visible(visibility.get("tracking.points", True))
        self.paint_canvas.set_point_labels_visible(visibility.get("tracking.point_labels", False))
        self.paint_canvas.set_corrections_visible(visibility.get("tracking.corrections", True))
        self.paint_canvas.set_legend_visible(visibility.get("tracking.legend", True))

        self.lbl_osd.setVisible(visibility.get("camera.osd", True))
        # Through set_label so an empty name stays hidden either way: a pane
        # with no label must not gain an empty box when the layer is enabled.
        self.set_label(self._label_text)

    def set_has_footage(self, has_footage: bool) -> None:
        if has_footage == self._master_has_footage:
            return
        self._master_has_footage = has_footage
        self.lbl_no_footage.setVisible(not has_footage)
        if not has_footage:
            # D-010: outside a source's bounds we show a dimmed placeholder,
            # never the last decoded frame frozen in place.
            self.surface.clear()

    @property
    def time_map(self):
        return self._time_map

    @time_map.setter
    def time_map(self, new_map):
        self._time_map = new_map

    @Slot()
    def _build_overlay_chrome(self) -> None:
        """Create the paint canvas, name/OSD labels, and placeholder overlay."""
        self.paint_canvas = PaintCanvas(self)
        self.paint_canvas.point_moved.connect(self.point_moved)
        self._grid.addWidget(self.paint_canvas, 0, 0)

        # Set up overlay
        self.overlay = QWidget()
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay.setStyleSheet("background: transparent;")
        olayout = QVBoxLayout(self.overlay)
        olayout.setContentsMargins(0, 0, 0, 0)

        self.lbl_name = QLabel("")
        self.lbl_name.setStyleSheet(
            "color: white; background-color: rgba(0,0,0,128); padding: 4px;"
        )
        self.lbl_name.setVisible(False)
        # The chrome labels are readouts, not controls. Their container is
        # already transparent to the mouse but the attribute is per widget, so
        # without this each label is its own dead zone: a click over the
        # timecode reached neither the video surface (no fullscreen on
        # double-click) nor the tracking overlay (no grabbing a marker that
        # happens to sit under it).
        self.lbl_name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.lbl_osd = QLabel(format_video_osd(0.0, 0.0, self._metadata))
        mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        self.lbl_osd.setStyleSheet("color: white; background-color: rgba(0,0,0,128); padding: 4px;")
        self.lbl_osd.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        set_font_family(self.lbl_osd, mono_font)

        top_layout = QHBoxLayout()
        _top = Qt.AlignmentFlag.AlignTop
        top_layout.addWidget(self.lbl_name, alignment=_top | Qt.AlignmentFlag.AlignLeft)
        top_layout.addStretch()
        top_layout.addWidget(self.lbl_osd, alignment=_top | Qt.AlignmentFlag.AlignRight)

        olayout.addLayout(top_layout)

        self.lbl_no_footage = QLabel("No Footage")
        self.lbl_no_footage.setStyleSheet("color: white; background-color: rgb(0,0,0);")
        self.lbl_no_footage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_no_footage.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lbl_no_footage.setVisible(False)
        olayout.addWidget(self.lbl_no_footage, 1)  # stretch

        self._grid.addWidget(self.overlay, 0, 0)

        self.zoom_controls = QWidget(self)
        zoom_layout = QHBoxLayout(self.zoom_controls)
        zoom_layout.setContentsMargins(4, 4, 4, 4)
        zoom_layout.setSpacing(0)

        self.zoom_in_button = QPushButton(self.zoom_controls)
        self.zoom_in_button.setText(tr("+"))
        self.zoom_in_button.setToolTip(tr("Zoom in"))
        self.zoom_in_button.clicked.connect(lambda: self.surface.zoom_by(1.25))

        self.zoom_out_button = QPushButton(self.zoom_controls)
        self.zoom_out_button.setText(tr("-"))
        self.zoom_out_button.setToolTip(tr("Zoom out"))
        self.zoom_out_button.clicked.connect(lambda: self.surface.zoom_by(1.0 / 1.25))

        self.reset_zoom_button = QPushButton(self.zoom_controls)
        self.reset_zoom_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.reset_zoom_button.setToolTip(tr("Reset zoom"))
        self.reset_zoom_button.clicked.connect(self.surface.reset_view)

        for button in (self.zoom_in_button, self.zoom_out_button, self.reset_zoom_button):
            button.setFlat(False)
            button.setFixedSize(24, 24)
            zoom_layout.addWidget(button)

        self._grid.addWidget(
            self.zoom_controls,
            0,
            0,
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
        )

    # ── teardown ─────────────────────────────────────────────────────

    def _shutdown_decoder(self) -> None:
        """Stop the decode thread and close its reader.

        Ownership is explicit, as it was for libmpv's event thread: the pane
        that started the thread stops it, rather than leaving it to garbage
        collection or Qt child destruction.
        """
        worker, self._worker = self._worker, None
        thread, self._thread = self._thread, None
        if worker is not None:
            # Blocking so the reader is closed on the thread that opened it,
            # before that thread goes away. Guarded on isRunning(): a blocking
            # invoke into a thread with no live event loop never returns, and
            # the worker's own slots never wait on the UI thread, so there is
            # no path back into a deadlock from here.
            if thread is not None and thread.isRunning():
                QMetaObject.invokeMethod(
                    worker, "shutdown", Qt.ConnectionType.BlockingQueuedConnection
                )
            else:
                worker.shutdown()
        if thread is not None:
            thread.quit()
            if not thread.wait(_DECODER_STOP_TIMEOUT_MS):
                logger.warning(
                    "Decode thread for %s did not stop within %d ms; detaching it so the "
                    "pane can be destroyed without taking a running thread with it",
                    getattr(worker, "path", "<unknown>"),
                    _DECODER_STOP_TIMEOUT_MS,
                )
                _abandon_decoder(thread, worker)
        self._media_loaded = False

    def _stop_everything(self) -> None:
        """Stop the deferred paint and the decode thread, in that order."""
        # Stop the deferred OSD paint before the widgets it touches go away:
        # a timer that fires during teardown paints into a half-destroyed pane.
        timer = self._osd_flush_timer
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                logger.debug("OSD flush timer was already destroyed", exc_info=True)
            self._osd_flush_timer = None
        self._shutdown_decoder()

    def close(self) -> bool:
        """Stop decoding before closing the widget.

        Returns whatever ``QWidget.close`` returns: this overrides a Qt method,
        and callers (and Qt itself) may act on the result.
        """
        self._stop_everything()
        return bool(super().close())

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stop the decode thread when Qt closes the pane by any other route.

        ``close()`` above only runs when something calls it; Qt closing a
        widget — an application quitting, a parent being destroyed — delivers
        this instead. Without it a ``QThread`` outlives its owner and Qt
        *aborts* the process with "QThread: Destroyed while thread is still
        running", which is a crash on exit rather than a leak.

        Explicit shutdown through ``VideoGrid.shutdown()`` remains the intended
        path and stays the documented one (AGENTS.md): this is the backstop for
        code that drops a window without closing it, not permission to rely on
        destruction.
        """
        self._stop_everything()
        super().closeEvent(event)
