import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QSlider
from PySide6.QtCore import Qt

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        w = QWidget()
        l = QVBoxLayout(w)
        s = QSlider(Qt.Orientation.Horizontal)
        l.addWidget(s)
        self.setCentralWidget(w)
        
    def keyPressEvent(self, e):
        print("MainWindow received key:", e.key())
        super().keyPressEvent(e)

app = QApplication(sys.argv)
win = MainWindow()
win.show()
# Send key events to window
from PySide6.QtGui import QKeyEvent
QApplication.sendEvent(win, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier))
QApplication.sendEvent(win, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier))
app.processEvents()
