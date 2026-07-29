"""Video rendering pane using libmpv."""

import logging
import sys
import threading
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from avialview.core.source import VideoMetadata
from avialview.ui.diagnostics import probe_libmpv
from avialview.ui.theme import set_font_family
from avialview.ui.video_overlay import PaintCanvas
from avialview.ui.video_timing import VideoTimingMixin, format_video_osd

logger = logging.getLogger(__name__)


def _release_mpv_render_context(widget: object) -> None:
    """Free a libmpv OpenGL render context before its client is terminated."""
    context = getattr(widget, "ctx", None)
    if context is None:
        return
    widget.makeCurrent()
    try:
        context.free()
    finally:
        widget.ctx = None
        widget.doneCurrent()


def _shutdown_mpv_client(player: Any, gl_widget: Any | None = None) -> None:
    """Release a Qt OpenGL render client, then terminate its libmpv handle once."""
    if gl_widget is not None:
        try:
            _release_mpv_render_context(gl_widget)
        except RuntimeError:
            # A failed GL cleanup must not leave libmpv's event thread alive.
            logger.warning("Could not release the mpv render context", exc_info=True)
    try:
        player.terminate()
    except Exception:
        logger.warning("Could not terminate the mpv client", exc_info=True)
    if gl_widget is not None:
        gl_widget.mpv = None


class VideoPane(VideoTimingMixin, QWidget):
    """
    Video rendering pane.

    Uses libmpv's Qt OpenGL render API on Windows/macOS and native
    window embedding (wid) on Linux.
    """

    double_clicked = Signal(object)
    right_clicked = Signal(object)  # emits QPoint (global position)
    _osd_update = Signal()
    frame_presented = Signal(float)  # delivered source timestamp
    file_loaded = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.time_pos = 0.0
        self._is_vfr = False
        self._frame_times: np.ndarray | None = None
        self._nominal_fps = 0.0
        self._decoder_fps = 0.0
        self._metadata = VideoMetadata()
        self.is_seeking = False
        self._mpv_seeking = False
        self._seek_pending = False
        self._seek_target = 0.0
        self._seek_exact = True
        self.mpv = None
        self._video_widget = None
        self._media_loaded = False
        self._pending_seek: tuple[float, bool] | None = None
        self._target_pause = True
        self._current_rate = 1.0
        self._mapping_rate_scale = 1.0
        self._sync_correction = 1.0
        self._osd_lock = threading.Lock()
        self._pending_osd: tuple[float, float] = (0.0, 0.0)
        self._osd_event_pending = False

        from avialview.core.timeline import TimeMap

        self.time_map = TimeMap()
        self._source_bounds: tuple[float, float] | None = None
        self._master_has_footage: bool | None = None

        self.setLayout(QGridLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        if not probe_libmpv(self):
            return

        import os

        import mpv

        is_offscreen = os.environ.get("QT_QPA_PLATFORM") == "offscreen"

        if sys.platform in ("darwin", "win32") and not is_offscreen:
            from PySide6.QtGui import QOpenGLContext
            from PySide6.QtOpenGLWidgets import QOpenGLWidget

            class MpvGLWidget(QOpenGLWidget):
                def __init__(self, parent_pane: "VideoPane"):
                    # A Windows QOpenGLWidget must be parented before its native
                    # surface/context is created.  Relying on QGridLayout to
                    # reparent it later can leave libmpv with no render target.
                    super().__init__(parent_pane)
                    self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                    self.parent_pane = parent_pane
                    self.ctx = None
                    self._render_update_lock = threading.Lock()
                    self._render_update_pending = False
                    # Use vo="libmpv" so it renders via the API instead of a standalone window
                    self.mpv = mpv.MPV(
                        hwdec="auto-safe",
                        hr_seek_framedrop=False,
                        keep_open="yes",
                        vo="libmpv",
                        input_default_bindings="no",
                        input_vo_keyboard="no",
                    )

                    @self.mpv.property_observer("time-pos")
                    def time_observer(_name: str, value: float) -> None:
                        if value is not None:
                            self.parent_pane._observe_time(float(value))

                    @self.mpv.property_observer("estimated-vf-fps")
                    def fps_observer(_name: str, value: float) -> None:
                        if value is not None:
                            self.parent_pane._decoder_fps = float(value)

                    @self.mpv.property_observer("seeking")
                    def seeking_observer(_name: str, value: bool) -> None:
                        if value is not None:
                            self.parent_pane._observe_seeking(bool(value))

                def initializeGL(self) -> None:
                    ctx = QOpenGLContext.currentContext()

                    def get_proc_address(_ctx, name: bytes) -> int:
                        addr = ctx.getProcAddress(name)
                        return int(addr) if addr else 0

                    # Wrap using the EXACT ctypes function signature defined in python-mpv
                    wrapped_get_proc_address = mpv.MpvGlGetProcAddressFn(get_proc_address)

                    self.ctx = mpv.MpvRenderContext(
                        self.mpv,
                        "opengl",
                        opengl_init_params={"get_proc_address": wrapped_get_proc_address},
                    )

                    def on_mpv_update():
                        from PySide6.QtCore import QMetaObject, Qt

                        with self._render_update_lock:
                            if self._render_update_pending:
                                return
                            self._render_update_pending = True
                        try:
                            QMetaObject.invokeMethod(
                                self,
                                "_consume_mpv_update",
                                Qt.ConnectionType.QueuedConnection,
                            )
                        except RuntimeError:
                            with self._render_update_lock:
                                self._render_update_pending = False

                    self.ctx.update_cb = on_mpv_update

                    # If open() was called before we had a context, play it now
                    if hasattr(self.parent_pane, "_pending_play"):
                        self.mpv.play(self.parent_pane._pending_play)
                        self.mpv.pause = getattr(self.parent_pane, "_target_pause", True)
                        delattr(self.parent_pane, "_pending_play")

                @Slot()
                def _consume_mpv_update(self) -> None:
                    with self._render_update_lock:
                        self._render_update_pending = False
                    self.update()

                def paintGL(self) -> None:
                    if self.ctx:
                        fbo = self.defaultFramebufferObject()
                        w, h = self.width(), self.height()
                        ratio = self.devicePixelRatio()
                        self.ctx.render(
                            flip_y=True,
                            opengl_fbo={"w": int(w * ratio), "h": int(h * ratio), "fbo": fbo},
                        )

            self.gl_widget = MpvGLWidget(self)
            self.gl_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
            self._video_widget = self.gl_widget
            self.layout().addWidget(self.gl_widget, 0, 0)
            self.mpv = self.gl_widget.mpv

        else:
            self.video_container = QWidget()
            self._video_widget = self.video_container
            self.video_container.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
            self.video_container.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
            self.video_container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.layout().addWidget(self.video_container, 0, 0)

            if is_offscreen:
                self.mpv = mpv.MPV(
                    vo="null",
                    hwdec="auto-safe",
                    hr_seek_framedrop=False,
                    keep_open="yes",
                    input_default_bindings="no",
                    input_vo_keyboard="no",
                )
            else:
                wid = int(self.video_container.winId())
                if sys.platform == "win32":
                    # libmpv's Win32 embedding API expects an unsigned 32-bit HWND.
                    wid &= 0xFFFFFFFF
                self.mpv = mpv.MPV(
                    wid=wid,
                    hwdec="auto-safe",
                    hr_seek_framedrop=False,
                    keep_open="yes",
                    input_default_bindings="no",
                    input_vo_keyboard="no",
                )

            @self.mpv.property_observer("time-pos")
            def time_observer(_name: str, value: float) -> None:
                if value is not None:
                    self._observe_time(float(value))

            @self.mpv.property_observer("estimated-vf-fps")
            def fps_observer(_name: str, value: float) -> None:
                if value is not None:
                    self._decoder_fps = float(value)

            @self.mpv.property_observer("seeking")
            def seeking_observer(_name: str, value: bool) -> None:
                if value is not None:
                    self._observe_seeking(bool(value))

        # Set up PaintCanvas for tracking
        @self.mpv.event_callback("file-loaded")
        def file_loaded(_event: object) -> None:
            self.file_loaded.emit()

        self.paint_canvas = PaintCanvas(self)
        self.layout().addWidget(self.paint_canvas, 0, 0)

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

        self.layout().addWidget(self.overlay, 0, 0)

        self._osd_update.connect(self._flush_osd_update)

        if self._video_widget:
            self.file_loaded.connect(self._on_file_loaded)
            self._video_widget.installEventFilter(self)

    def set_source_bounds(self, bounds: tuple[float, float]) -> None:
        """Set the source-time interval that contains decodable media."""
        self._source_bounds = tuple(sorted(bounds))

    def has_footage_at_master(self, t_master: float) -> bool:
        """Return whether this pane has media at the supplied master time."""
        if not self.time_map.contains_master_time(t_master):
            return False
        if self._source_bounds is None:
            return True
        t_source = self.time_map.to_source(t_master)
        start, end = self._source_bounds
        return start <= t_source <= end

    def set_tracking_readers(self, readers: list) -> None:
        self.paint_canvas.set_readers(readers)

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
        with self._osd_lock:
            t, fps = self._pending_osd
            self._osd_event_pending = False
        self._update_osd(t, fps)

    def eventFilter(self, obj, event):
        if obj == self._video_widget:
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

    def open(self, path: str) -> None:
        """Open a video file."""
        if self.mpv:
            self._media_loaded = False
            if hasattr(self, "gl_widget") and self.gl_widget.ctx is None:
                self._pending_play = path
            else:
                self.mpv.play(path)
                self.mpv.pause = True

    def play(self) -> None:
        """Unpause the video."""
        self._target_pause = False
        if self.mpv:
            self.mpv.pause = False

    def pause(self) -> None:
        """Pause the video."""
        self._target_pause = True
        if self.mpv:
            self.mpv.pause = True

    def set_rate(self, rate: float) -> None:
        """Set playback rate."""
        self._current_rate = rate
        self._apply_rate()

    def set_sync_correction(self, correction: float) -> None:
        """Apply Player's bounded drift correction to the effective mpv rate."""
        self._sync_correction = correction
        self._apply_rate()

    @property
    def sync_correction(self) -> float:
        """Return the currently applied drift-correction multiplier."""
        return self._sync_correction

    def _apply_rate(self) -> None:
        if self.mpv:
            self.mpv.speed = self._current_rate * self._mapping_rate_scale * self._sync_correction

    @property
    def time_map(self):
        return self._time_map

    @time_map.setter
    def time_map(self, new_map):
        self._time_map = new_map
        self._mapping_rate_scale = new_map.rate_scale
        self._apply_rate()

    @Slot()
    def _on_file_loaded(self) -> None:
        """Dispatch a seek only after libmpv confirms that commands are accepted."""
        self._media_loaded = True
        pending = self._pending_seek
        self._pending_seek = None
        if pending is not None:
            target, exact = pending
            self.seek(target, exact=exact)

    def seek(self, t: float, exact: bool = True) -> None:
        """Seek to a specific time. Exact seek or keyframe."""
        if not self.mpv:
            return
        if not self._media_loaded:
            self._pending_seek = (t, exact)
            return
        precision = "exact" if exact else "keyframes"
        try:
            self._seek_target = float(t)
            self._seek_exact = exact
            self._seek_pending = True
            self._mpv_seeking = True
            self.is_seeking = True
            self.mpv.seek(t, reference="absolute", precision=precision)
        except Exception:
            # mpv may raise SystemError -12 if we seek before it has finished loading the file
            self._seek_pending = False
            self._mpv_seeking = False
            self.is_seeking = False
            logger.warning("Video seek failed at %.6f seconds", t, exc_info=True)

    def frame_step(self, forward: bool = True) -> None:
        """Step one frame forward or backward."""
        if not self.mpv:
            return
        try:
            if forward:
                self.mpv.command("frame-step")
            else:
                self.mpv.command("frame-back-step")
        except Exception:
            logger.warning("Video frame step failed", exc_info=True)

    def close(self) -> None:
        """Terminate mpv before closing the widget."""
        player = self.mpv
        if player:
            gl_widget = getattr(self, "gl_widget", None)
            _shutdown_mpv_client(player, gl_widget)
            self.mpv = None
        super().close()
