import sys, os
os.environ["DYLD_LIBRARY_PATH"] = "/opt/homebrew/lib"
from PySide6.QtWidgets import QApplication
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import Qt, QMetaObject
import mpv

class MpvGLWidget(QOpenGLWidget):
    def __init__(self):
        super().__init__()
        self.ctx = None
        self.mpv = mpv.MPV(vo="libmpv", log_handler=print, loglevel="v")

    def initializeGL(self):
        ctx = self.context()
        def get_proc_address(_, name: bytes) -> int:
            addr = ctx.getProcAddress(name)
            return int(addr) if addr else 0
        
        wrapped = mpv.MpvGlGetProcAddressFn(get_proc_address)
        self.ctx = mpv.MpvRenderContext(
            self.mpv, "opengl", opengl_init_params={"get_proc_address": wrapped}
        )
        def on_update():
            QMetaObject.invokeMethod(self, "update", Qt.ConnectionType.QueuedConnection)
        self.ctx.update_cb = on_update

    def paintGL(self):
        if self.ctx:
            fbo = self.defaultFramebufferObject()
            w, h = self.width(), self.height()
            ratio = self.devicePixelRatio()
            self.ctx.render(flip_y=True, opengl_fbo={"w": int(w*ratio), "h": int(h*ratio), "fbo": fbo})

app = QApplication(sys.argv)
w = MpvGLWidget()
w.resize(640, 480)
# call play before show
w.mpv.play('examples/data/camera_1.mp4')
w.mpv.pause = True
w.show()

import time
time.sleep(1)
app.processEvents()
