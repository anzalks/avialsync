import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QTreeWidget, QVBoxLayout, QWidget

class Win(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        w = QWidget()
        l = QVBoxLayout(w)
        self.t = QTreeWidget()
        # self.t.setAcceptDrops(True) by default?
        l.addWidget(self.t)
        self.setCentralWidget(w)
        print("Tree accepts drops?", self.t.acceptDrops())

    def dragEnterEvent(self, e):
        print("Win drag enter")
        e.accept()

app = QApplication(sys.argv)
win = Win()
