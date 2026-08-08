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

import numpy as np
from PySide6.QtCore import QMetaObject, QObject, QRectF, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QFontDatabase, QImage, QPainter, QPaintEvent
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from avialsync.core.errors import SourceOpenError
from avialsync.core.source import VideoMetadata
from avialsync.engine.pyav_reader import PyAVReader, to_rgb_array
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
#: rounding error's worth of time.
_OSD_DUE_EPSILON_S = 0.001

#: How long a decode thread gets to finish its current frame at teardown.
#: A worst-case cold jump is ~120 ms, so this is generous; it exists only so a
#: wedged decoder cannot hold the UI thread for the length of a job timeout.
_DECODER_STOP_TIMEOUT_MS = 3000


class DecodeWorker(QObject):
    """Owns one :class:`PyAVReader` on a decode thread.

    Requests coalesce: only the newest requested time is ever decoded.  The UI
    thread posts a time and an invocation; whichever invocation runs first takes
    the latest time and the rest find nothing to do.  That is what lets a 60 Hz
    tick drive a decoder that takes longer than a tick without ever queueing a
    backlog of frames nobody will see — sync correctness beats frame
    completeness (AGENTS.md rule 6).
    """

    opened = Signal(object, int, int, str)  # frame_times, width, height, codec
    failed = Signal(str)
    frame_ready = Signal(int, float, object)  # frame index, pts seconds, RGB array

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path
        self._reader: PyAVReader | None = None
        self._lock = threading.Lock()
        self._pending: float | None = None

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

    def request(self, source_time: float) -> None:
        """Record the newest wanted time. Safe to call from the UI thread."""
        with self._lock:
            self._pending = source_time

    @Slot()
    def decode_pending(self) -> None:
        """Decode the newest requested time, if one is still outstanding."""
        with self._lock:
            source_time = self._pending
            self._pending = None
        if source_time is None or self._reader is None:
            return
        try:
            index = self._reader.index_at_time(source_time)
            frame = self._reader.frame_at_index(index)
            rgb = to_rgb_array(frame)
        except Exception as error:
            # A decode failure is one lost frame, not a lost session: the next
            # request re-seeks from scratch. Swallowing it here keeps a damaged
            # region of a file from taking the pane down with it.
            logger.warning("Could not decode %s at %.6fs", self._path, source_time, exc_info=error)
            return
        self.frame_ready.emit(index, self._reader.time_at_index(index), rgb)

    @Slot()
    def shutdown(self) -> None:
        """Close the reader on its own thread, where it was opened."""
        with self._lock:
            self._pending = None
        if self._reader is not None:
            self._reader.close()
            self._reader = None


class VideoSurface(QWidget):
    """Paints the decoded frame, letterboxed.

    The geometry here must match :meth:`PaintCanvas._video_scale` exactly — the
    tracking overlay maps video pixels to widget pixels with the same formula,
    and any divergence would draw markers off the thing they mark.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._image: QImage | None = None
        #: The array the QImage borrows. QImage does not copy the buffer, so
        #: dropping this would leave it pointing at freed memory.
        self._buffer: np.ndarray | None = None

    def set_frame(self, rgb: np.ndarray) -> None:
        """Show a decoded ``(H, W, 3)`` uint8 RGB frame."""
        height, width, _ = rgb.shape
        self._buffer = rgb
        self._image = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888)
        self.update()

    def clear(self) -> None:
        """Drop the displayed frame."""
        self._image = None
        self._buffer = None
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Blit the frame centred, preserving aspect ratio."""
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        image = self._image
        if image is None or image.isNull():
            return
        scale = min(self.width() / image.width(), self.height() / image.height())
        width = image.width() * scale
        height = image.height() * scale
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(
            QRectF(
                (self.width() - width) / 2.0,
                (self.height() - height) / 2.0,
                width,
                height,
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
    file_loaded = Signal()
    open_failed = Signal(str)

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
        self._target_pause = True
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
        worker.moveToThread(thread)
        # The worker must be held for the thread's whole life: a QObject moved
        # to a QThread with no owning Python reference is collected out from
        # under it (HANDOUT.md trap 0a).
        self._worker = worker
        self._thread = thread

        worker.opened.connect(self._on_opened)
        worker.failed.connect(self._on_open_failed)
        worker.frame_ready.connect(self._on_frame_ready)
        thread.started.connect(worker.open)
        thread.start()

    @Slot(object, int, int, str)
    def _on_opened(self, frame_times: np.ndarray, width: int, height: int, codec: str) -> None:
        """Adopt the decoder's timestamp table and show the first wanted frame."""
        self._frame_times = frame_times
        self.video_size = (width, height)
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

    @Slot(int, float, object)
    def _on_frame_ready(self, index: int, pts: float, rgb: np.ndarray) -> None:
        """Show a decoded frame and report the timestamp it actually carries."""
        del index
        self.surface.set_frame(rgb)
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
        self.is_seeking = True
        self._worker.request(float(t))
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
        now = time.monotonic()
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
        if text:
            self.lbl_name.setText(text)
            self.lbl_name.setVisible(True)
        else:
            self.lbl_name.setVisible(False)

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

        self.lbl_osd = QLabel(format_video_osd(0.0, 0.0, self._metadata))
        mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        self.lbl_osd.setStyleSheet("color: white; background-color: rgba(0,0,0,128); padding: 4px;")
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
        self.lbl_no_footage.setVisible(False)
        olayout.addWidget(self.lbl_no_footage, 1)  # stretch

        self._grid.addWidget(self.overlay, 0, 0)

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
                logger.warning("Decode thread did not stop within %d ms", _DECODER_STOP_TIMEOUT_MS)
        self._media_loaded = False

    def close(self) -> bool:
        """Stop decoding before closing the widget.

        Returns whatever ``QWidget.close`` returns: this overrides a Qt method,
        and callers (and Qt itself) may act on the result.
        """
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
        return bool(super().close())
