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
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import (
    QEvent,
    QMetaObject,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAccessible,
    QCloseEvent,
    QFontDatabase,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.errors import SourceOpenError
from avialsync.core.source import VideoMetadata
from avialsync.engine.display_pipeline import (
    DisplayLevels,
    SourceFormat,
    auto_levels_for_frame,
    probe_format,
    to_display_array,
)
from avialsync.engine.pyav_reader import PyAVReader
from avialsync.ui.accessible_views import register_painted
from avialsync.ui.design_tokens import spacing
from avialsync.ui.elided_label import ElidedLabel
from avialsync.ui.i18n import tr
from avialsync.ui.levels_panel import LevelsPanel
from avialsync.ui.theme import set_font_family
from avialsync.ui.video_overlay import PaintCanvas
from avialsync.ui.video_timing import VideoTimingMixin, displayed_frame_rate, format_video_osd
from avialsync.ui.wheel_overlay import WheelDrawing
from avialsync.ui.zoom_controls import ZOOM_STEP, ZoomControls

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
    # Released by polling, never by connecting to ``finished`` now: under
    # PySide6 6.12, connecting to a stopping thread can deadlock against its
    # teardown (see ``imaging_pane._release_finished_threads``).
    for held in list(_ABANDONED_DECODERS):
        try:
            finished = held[0].isFinished()
        except RuntimeError:
            finished = True
        if finished:
            _ABANDONED_DECODERS.discard(held)


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
    #: Levels chosen from the last decoded frame, before any levels (D-209).
    levels_measured = Signal(object)

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
        #: The last frame decoded, kept on this thread so Auto can measure the
        #: recording itself rather than a picture its levels already clipped.
        self._last_frame: Any = None
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
            self._last_frame = frame
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
    def measure_levels(self) -> None:
        """Choose levels from the last decoded frame, here on the decode thread."""
        frame = self._last_frame
        if frame is not None:
            self.levels_measured.emit(auto_levels_for_frame(frame))

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
        #: Off while a snapshot renders the picture: the readout is screen
        #: chrome, and a figure states the zoom in its caption instead.
        self.readout_shown = True

    @property
    def video_size(self) -> tuple[int, int] | None:
        """Decoded frame dimensions this surface is drawing, or None before one.

        The same numbers :meth:`frame_geometry` transforms, read from the widget
        that does the drawing — so anything cropping or overlaying a render is
        working from the geometry that produced it.
        """
        return self._video_size if all(self._video_size) else None

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

        *rgb* must be C-contiguous, because the ``QImage`` below borrows its
        buffer.  ``engine.display_pipeline.to_display_array`` guarantees that,
        on the decode thread where the copy is free of the UI budget; the check
        is not repeated here, so that the guarantee has one owner and not two.
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
        self._draw_view_readout(painter)

    def _draw_view_readout(self, painter: QPainter) -> None:
        """State the zoom and how far the view has been panned off centre.

        Only once either has been changed: a pane showing the whole frame
        unpanned is the default, and captioning that would put text on every
        video for no information. The same reasoning, and the same corner, as
        the 3D pane's orbit readout -- a view you arrived at by dragging is
        otherwise recorded only as a picture.
        """
        if not self.readout_shown or self.is_default_view:
            return
        readout = self.view_readout()
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.WindowText), 1))
        metrics = painter.fontMetrics()
        painter.drawText(
            max(6, self.width() - metrics.horizontalAdvance(readout) - 8),
            self.height() - 8,
            readout,
        )

    @property
    def is_default_view(self) -> bool:
        """Whether the whole frame is shown, fitted and centred."""
        return self._zoom == 1.0 and self._pan.isNull()

    def view_readout(self) -> str:
        """Zoom and pan offset as text. Separate from painting so it can be
        asserted on, as the 3D pane's readout is.

        The offset is in *displayed pixels* from centred, which is the frame the
        gesture happens in; expressing it in source pixels would change meaning
        with the zoom that produced it.
        """
        return f"{self._zoom:.2f}×  x {self._pan.x():+.0f}  y {self._pan.y():+.0f}"


_OSD_DETAILS = ("compact", "full")


def _saved_osd_detail() -> str:
    """The OSD detail level from Preferences, compact unless chosen otherwise."""
    from avialsync.core.settings_schema import setting_for
    from avialsync.ui.preferences_dialog import read_setting

    setting = setting_for("overlays/osd_detail")
    value = read_setting(setting) if setting is not None else "compact"
    return value if value in _OSD_DETAILS else "compact"


class _ChromeOsd(QLabel):
    """The timecode block: its natural width when it fits, wrapped when not (D-183).

    It used to keep its natural width at any pane size, so at three cameras the
    full block ran off the right edge. Now it takes the room the pane has left
    after the camera name's shortest form, and wraps at its spaces when that is
    less, so every word stays on screen.
    """

    def __init__(self, reserve: Callable[[], int]) -> None:
        super().__init__()
        self.setWordWrap(True)
        self._reserve = reserve
        self._longest = -1

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        longest = max((len(line) for line in text.splitlines()), default=0)
        if longest != self._longest:
            # Refitted only when the longest line changes length: the text is
            # rewritten every displayed frame, its width almost never.
            self._longest = longest
            self.fit()

    def fit(self) -> None:
        """Size to the longest line, or to the pane's free width if that is less."""
        host = self.parentWidget()
        if host is None or self._longest < 0:
            return
        margins = self.contentsMargins()
        natural = (
            self.fontMetrics().horizontalAdvance("0" * self._longest)
            + margins.left()
            + margins.right()
            + 2
        )
        free = max(48, host.width() - self._reserve())
        self.setFixedWidth(min(natural, free))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self.fit()


class _ChromeName(ElidedLabel):
    """The camera name: elides when the pane is narrow, never asks for more."""

    def __init__(self) -> None:
        super().__init__("", None, Qt.TextElideMode.ElideMiddle)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        """The full name's width, so a widened pane shows it again."""
        margins = self.contentsMargins()
        width = self.fontMetrics().horizontalAdvance(self.fullText())
        return QSize(width + margins.left() + margins.right() + 2, super().sizeHint().height())


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
    #: The user changed this camera's levels in its popover: (DisplayLevels).
    levels_requested = Signal(object)
    #: Auto measured levels from this camera's frame: (DisplayLevels).
    levels_measured = Signal(object)
    file_loaded = Signal()
    open_failed = Signal(str)
    #: A finished "Fix Tracker" drag, as a
    #: :class:`~avialsync.core.point_edits.PointMove`. Forwarded from the paint
    #: canvas so callers wire to the pane rather than reaching into its chrome.
    point_moved = Signal(object)
    #: ``(x, y)``: a click placing a new 3D marker (forwarded, as above).
    marker_clicked = Signal(float, float)
    #: ``(name, frame, x, y)``: a hand-placed 3D marker was dragged.
    custom_point_moved = Signal(str, int, float, float)

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
        self.media_path = ""
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
        register_painted(
            self, QAccessible.Role.Graphic, self.accessible_value, self.accessible_detail
        )
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
        #: What this pane decodes, which is not always what it is named after: a
        #: source played through a proxy (NWB imaging, D-188) is named by its
        #: recording and decoded from the proxy. Exports read this one.
        self.media_path = path

        worker = DecodeWorker(path)
        # A reopened file keeps the levels the camera is shown through.
        worker.set_levels(self._display_levels)
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
        worker.levels_measured.connect(self.levels_measured)
        thread.started.connect(worker.open)
        thread.start()

    @Slot(object)
    def _on_format_detected(self, source_format: object) -> None:
        """Publish what this recording actually is, once it has been decoded."""
        if isinstance(source_format, SourceFormat):
            self.source_format = source_format
            self.source_format_detected.emit(source_format)
            # The decoded depth replaces the one read from the pixel format.
            self.lbl_osd.setText(self.osd_text(self._osd_detail))

    def set_display_levels(self, levels: DisplayLevels) -> None:
        """Apply a display window to this camera.

        Handed to the decode worker, which converts with it: the table is built
        and applied on the decode thread, never here. The hand-over is a
        lock-guarded assignment rather than a queued call -- PySide6 cannot
        queue a plain Python object through ``invokeMethod`` (``Q_ARG(object,
        ...)`` raises "Unable to find a QMetaType for object"), which is how
        levels set in the inspector used to never reach the decoder at all.
        """
        self._display_levels = levels
        if hasattr(self, "levels_button"):
            self._show_levels_state()
        worker = self._worker
        if worker is not None:
            worker.set_levels(levels)
            # Re-request the frame on screen so the change is visible while
            # paused, which is when someone sets levels. The reader caches the
            # decoded frame, so this is a re-conversion, not a re-decode.
            if self._last_source_time is not None:
                self.seek(self._last_source_time)

    def display_levels(self) -> DisplayLevels:
        return self._display_levels

    def request_auto_levels(self) -> None:
        """Measure levels from the recording on the decode thread; they arrive as a change.

        Measured from the decoded frame, not the picture on screen: once levels
        clip the picture, what was clipped cannot be measured back from it.
        The answer comes back through :attr:`levels_measured` and is recorded
        and undoable like a slider's change, as a step of its own.
        """
        if self._worker is not None:
            QMetaObject.invokeMethod(
                self._worker, "measure_levels", Qt.ConnectionType.QueuedConnection
            )

    @Slot(object, int, int, str)
    def _on_opened(self, frame_times: np.ndarray, width: int, height: int, codec: str) -> None:
        """Adopt the decoder's timestamp table and show the first wanted frame."""
        self._frame_times = frame_times
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
        self.lbl_no_footage.setText(tr("Video unavailable") + "\n" + reason)
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

    def set_identity_resolver(self, resolver: object) -> None:
        """Adopt the window's map from a displayed point to its column (D-143)."""
        self.paint_canvas.set_identity_resolver(resolver)  # type: ignore[arg-type]

    def set_point_edit_mode(self, enabled: bool) -> None:
        """Turn "Fix Tracker" on or off for this pane."""
        self.paint_canvas.set_edit_mode(enabled)

    @property
    def point_edit_mode(self) -> bool:
        """Whether this pane is currently accepting point corrections."""
        return bool(self.paint_canvas.edit_mode)

    def set_highlighted_point(self, key: object) -> None:
        """Ring one tracked coordinate, or clear the ring when *key* is None."""
        self.paint_canvas.set_highlighted_point(key)

    def set_custom_markers(self, markers: dict[int, list[tuple[str, float, float]]]) -> None:
        """Hand-placed 3D markers seen by this camera, keyed by video frame."""
        self.paint_canvas.set_custom_markers(markers)

    def set_reprojection_source(
        self, source: Callable[[float], list[tuple[str, float, float]]] | None
    ) -> None:
        """Where this camera asks for 3D points projected into its pixels."""
        self.paint_canvas.set_reprojection_source(source)

    def set_wheel_source(self, source: Callable[[float], WheelDrawing | None] | None) -> None:
        """Where this camera asks for the wheel model, projected into its pixels."""
        self.paint_canvas.set_wheel_source(source)

    def set_prop_source(self, source: Callable[[float], list] | None) -> None:
        """Draw this camera's clicked physical props."""
        self.paint_canvas.set_prop_source(source)

    def set_marker_place_mode(self, enabled: bool) -> None:
        """Take the next left click as a new 3D marker's position in this camera."""
        self.paint_canvas.set_place_mode(enabled)

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
        self.lbl_osd.fit()

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
        self.paint_canvas.set_custom_markers_visible(
            visibility.get("tracking.custom_markers", True)
        )
        self.paint_canvas.set_reprojection_visible(visibility.get("tracking.reprojection", False))
        self.paint_canvas.set_wheel_visible(
            visibility.get("tracking.wheel", True), visibility.get("tracking.wheel_hidden", False)
        )
        self.paint_canvas.set_props_visible(visibility.get("tracking.props", True))

        self.lbl_osd.setVisible(visibility.get("camera.osd", True))
        # Through set_label so an empty name stays hidden either way: a pane
        # with no label must not gain an empty box when the layer is enabled.
        self.set_label(self._label_text)

    @property
    def video_size(self) -> tuple[int, int] | None:
        """Decoded video dimensions, or None before a frame has arrived.

        Delegated to the surface rather than mirrored here.  The surface is what
        draws the frame and what :meth:`VideoSurface.frame_geometry` transforms,
        so a second copy on the pane could only ever disagree with the geometry
        the overlay and the snapshot crop both project through (AGENTS rule 15).
        """
        return self.surface.video_size

    @property
    def shows_footage(self) -> bool:
        """Whether the pane is showing frames rather than the D-010 placeholder.

        Unknown counts as showing: a pane that has never been told otherwise is
        displaying whatever it decoded, not a placeholder.
        """
        return self._master_has_footage is not False

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
        self.paint_canvas.marker_clicked.connect(self.marker_clicked)
        self.paint_canvas.custom_point_moved.connect(self.custom_point_moved)
        self._grid.addWidget(self.paint_canvas, 0, 0)

        # Set up overlay
        self.overlay = QWidget()
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay.setStyleSheet("background: transparent;")
        olayout = QVBoxLayout(self.overlay)
        olayout.setContentsMargins(0, 0, 0, 0)

        # Chrome over the picture keeps fixed white-on-translucent colours: the
        # video behind it, not the theme, decides what is legible (D-174, F-35).
        chrome_style = "color: white; background-color: rgba(0,0,0,128);"
        self.lbl_name = _ChromeName()
        self.lbl_name.setStyleSheet(chrome_style)
        self.lbl_name.setContentsMargins(spacing("s"), spacing("s"), spacing("s"), spacing("s"))
        self.lbl_name.setVisible(False)
        # The chrome labels are readouts, not controls. Their container is
        # already transparent to the mouse but the attribute is per widget, so
        # without this each label is its own dead zone: a click over the
        # timecode reached neither the video surface (no fullscreen on
        # double-click) nor the tracking overlay (no grabbing a marker that
        # happens to sit under it).
        self.lbl_name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._osd_detail = _saved_osd_detail()
        self.lbl_osd = _ChromeOsd(self._osd_reserve)
        self.lbl_osd.setText(format_video_osd(0.0, 0.0, self._metadata, None, self._osd_detail))
        mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        self.lbl_osd.setStyleSheet(chrome_style)
        self.lbl_osd.setContentsMargins(spacing("s"), spacing("s"), spacing("s"), spacing("s"))
        self.lbl_osd.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        set_font_family(self.lbl_osd, mono_font)

        # One header row: the name elides first, the timecode keeps its width.
        top_layout = QHBoxLayout()
        _top = Qt.AlignmentFlag.AlignTop
        top_layout.addWidget(self.lbl_name, 0, _top)
        top_layout.addStretch(1)
        top_layout.addWidget(self.lbl_osd, 0, _top | Qt.AlignmentFlag.AlignRight)

        olayout.addLayout(top_layout)

        self.lbl_no_footage = QLabel(tr("No Footage"))
        self.lbl_no_footage.setStyleSheet("color: white; background-color: rgb(0,0,0);")
        self.lbl_no_footage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_no_footage.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lbl_no_footage.setVisible(False)
        olayout.addWidget(self.lbl_no_footage, 1)  # stretch

        self._grid.addWidget(self.overlay, 0, 0)

        self.zoom_controls = ZoomControls(self)
        self.zoom_in_button = self.zoom_controls.zoom_in_button
        self.zoom_out_button = self.zoom_controls.zoom_out_button
        self.reset_zoom_button = self.zoom_controls.reset_zoom_button
        self.zoom_controls.zoom_in_requested.connect(lambda: self.surface.zoom_by(ZOOM_STEP))
        self.zoom_controls.zoom_out_requested.connect(lambda: self.surface.zoom_by(1.0 / ZOOM_STEP))
        self.zoom_controls.reset_requested.connect(self.surface.reset_view)
        self._build_levels_popover()

        self._grid.addWidget(
            self.zoom_controls,
            0,
            0,
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
        )

    def _build_levels_popover(self) -> None:
        """A levels button beside zoom, opening this camera's own levels (D-209).

        Per camera, beside the zoom it belongs with: a toolbar acts on every
        pane at once and would need a hidden "which camera" rule. The button
        stays pressed while the camera is shown through anything but its full
        range, so an adjusted picture is never mistaken for the raw one.
        """
        name = tr("Display levels")
        self.levels_button = self.zoom_controls.add_glyph_button("levels", name)
        self.levels_button.setCheckable(True)
        self.levels_button.setAccessibleDescription(
            tr("Black point, white point and gamma for this camera's picture")
        )
        # A popup frame, not a QMenu: a widget embedded in a menu through a
        # QWidgetAction comes out disabled, and the menu sized itself to the
        # panel while it was still hidden -- a 0x0 popover with dead sliders.
        self.levels_popover = QFrame(self, Qt.WindowType.Popup)
        self.levels_popover.setFrameShape(QFrame.Shape.StyledPanel)
        self.levels_popover.setAccessibleName(name)
        box = QVBoxLayout(self.levels_popover)
        box.setContentsMargins(0, 0, 0, 0)
        self.levels_popover_panel = LevelsPanel(self.levels_popover)
        box.addWidget(self.levels_popover_panel)
        self.levels_popover_panel.levels_changed.connect(self.levels_requested)
        self.levels_popover_panel.auto_requested.connect(self.request_auto_levels)
        self.levels_button.clicked.connect(self._open_levels_popover)

    def _open_levels_popover(self) -> None:
        """Open this camera's levels above its button, inside the screen."""
        # A click toggles a checkable button; its state says "adjusted", not "open".
        self.levels_button.setChecked(not self._display_levels.is_identity)
        panel = self.levels_popover_panel
        panel.set_source_format(self.source_format)
        panel.setVisible(True)
        panel.set_levels(self._display_levels)
        popover = self.levels_popover
        popover.adjustSize()
        anchor = self.levels_button.mapToGlobal(QPoint(0, 0))
        position = QPoint(anchor.x(), anchor.y() - popover.height() - 4)
        screen = self.levels_button.screen()
        if screen is not None:
            bounds = screen.availableGeometry()
            if position.y() < bounds.top():
                position.setY(anchor.y() + self.levels_button.height() + 4)
            position.setX(min(max(position.x(), bounds.left()), bounds.right() - popover.width()))
        popover.move(position)
        popover.show()
        panel.setFocus()

    def _show_levels_state(self) -> None:
        adjusted = not self._display_levels.is_identity
        self.levels_button.setChecked(adjusted)
        self.levels_button.setToolTip(
            tr("Display levels (adjusted)") if adjusted else tr("Display levels")
        )
        self.levels_popover_panel.set_levels(self._display_levels)

    def accessible_value(self) -> str:
        """Time and frame on screen, read on query (D-179)."""
        return self.osd_text("compact")

    def accessible_detail(self) -> str:
        name = self._label_text or tr("Camera")
        full = " · ".join(line for line in self.osd_text("full").splitlines() if line)
        return f"{name}: {full}"

    def chrome_rects(self) -> tuple[QRect, ...]:
        """Rectangles, in pane coordinates, that labels drawn over video avoid.

        The explicit contract ``PaintCanvas`` reads (D-174), replacing a lookup
        of widgets by attribute name that a renamed widget broke silently. The
        zoom tools' rectangle is always reserved, shown or not, so labels never
        move when they appear.
        """
        rects = [
            label.geometry()
            for label in (self.lbl_name, self.lbl_osd)
            if label.isVisible() and label.width() > 0
        ]
        rects.append(QRect(self.zoom_controls.pos(), self.zoom_controls.sizeHint()))
        return tuple(rects)

    def _osd_reserve(self) -> int:
        """Width the timecode leaves for the camera name's shortest form."""
        if not self.lbl_name.isVisible():
            return 8
        return int(self.lbl_name.minimumSizeHint().width()) + 16

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "lbl_osd"):
            self.lbl_osd.fit()

    def set_osd_detail(self, detail: str) -> None:
        """Show the timecode as one compact line or the full block (D-174)."""
        self._osd_detail = detail if detail in _OSD_DETAILS else "compact"
        self._update_osd(self.time_pos, self._decoder_fps)

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
