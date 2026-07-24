"""Video rendering pane using libmpv."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from kinochronix.ui.diagnostics import probe_libmpv


class VideoPane(QWidget):
    """
    Video rendering pane.

    Uses macOS Render API via QOpenGLWidget on Darwin,
    and native window embedding (wid) on Windows/Linux.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.time_pos = 0.0
        self.is_seeking = False
        self.mpv = None

        if not probe_libmpv(self):
            return

        import mpv

        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)

        import os
        is_offscreen = os.environ.get("QT_QPA_PLATFORM") == "offscreen"

        if sys.platform == "darwin" and not is_offscreen:
            from PySide6.QtGui import QOpenGLContext
            from PySide6.QtOpenGLWidgets import QOpenGLWidget

            class MpvGLWidget(QOpenGLWidget):
                def __init__(self, parent_pane: "VideoPane"):
                    super().__init__()
                    self.parent_pane = parent_pane
                    self.ctx = None
                    self.mpv = mpv.MPV(hwdec="auto-safe", keep_open="yes")

                    @self.mpv.property_observer("time-pos")
                    def time_observer(_name: str, value: float) -> None:
                        if value is not None:
                            self.parent_pane.time_pos = value

                    @self.mpv.property_observer("seeking")
                    def seeking_observer(_name: str, value: bool) -> None:
                        if value is not None:
                            self.parent_pane.is_seeking = value

                def initializeGL(self) -> None:
                    ctx = QOpenGLContext.currentContext()
                    def get_proc_address(name: bytes) -> int:
                        addr = ctx.getProcAddress(name)
                        return int(addr) if addr else 0

                    self.ctx = mpv.MpvRenderContext(
                        self.mpv,
                        "opengl",
                        opengl_init_params={"get_proc_address": get_proc_address}
                    )
                    self.ctx.update_cb = self.update

                def paintGL(self) -> None:
                    if self.ctx:
                        fbo = self.defaultFramebufferObject()
                        w, h = self.width(), self.height()
                        ratio = self.devicePixelRatio()
                        self.ctx.render(
                            flip_y=True,
                            opengl_fbo={"w": int(w * ratio), "h": int(h * ratio), "fbo": fbo}
                        )

            self.gl_widget = MpvGLWidget(self)
            self.layout().addWidget(self.gl_widget)
            self.mpv = self.gl_widget.mpv

        else:
            self.video_container = QWidget()
            self.video_container.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
            self.video_container.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
            self.layout().addWidget(self.video_container)

            if is_offscreen:
                self.mpv = mpv.MPV(vo="null", hwdec="auto-safe", keep_open="yes")
            else:
                wid = int(self.video_container.winId())
                self.mpv = mpv.MPV(wid=wid, hwdec="auto-safe", keep_open="yes")

            @self.mpv.property_observer("time-pos")
            def time_observer(_name: str, value: float) -> None:
                if value is not None:
                    self.time_pos = value

            @self.mpv.property_observer("seeking")
            def seeking_observer(_name: str, value: bool) -> None:
                if value is not None:
                    self.is_seeking = value

    def open(self, path: str) -> None:
        """Open a video file."""
        if self.mpv:
            self.mpv.play(path)
            self.mpv.pause = True

    def play(self) -> None:
        """Unpause the video."""
        if self.mpv:
            self.mpv.pause = False

    def pause(self) -> None:
        """Pause the video."""
        if self.mpv:
            self.mpv.pause = True

    def set_rate(self, rate: float) -> None:
        """Set playback rate."""
        if self.mpv:
            self.mpv.speed = rate

    def seek(self, t: float, exact: bool = True) -> None:
        """Seek to a specific time. Exact seek or keyframe."""
        if not self.mpv:
            return
        precision = "exact" if exact else "keyframes"
        self.mpv.seek(t, reference="absolute", precision=precision)

    def frame_step(self, forward: bool = True) -> None:
        """Step one frame forward or backward."""
        if not self.mpv:
            return
        if forward:
            self.mpv.command("frame-step")
        else:
            self.mpv.command("frame-back-step")
