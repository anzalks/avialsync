import sys

from PySide6.QtWidgets import QApplication

from avialsync.ui.main_window import MainWindow

app = QApplication.instance() or QApplication(sys.argv)
window = MainWindow()
window.resize(1024, 768)
window.show()

window.transport.set_status("This is a test status!", "busy")

app.processEvents()
print(f"Data Streams visible: {window.data_streams.isVisible()}")
print(f"Data Streams rect: {window.data_streams.geometry()}")
print(f"Status label visible: {window.data_streams._status_label.isVisible()}")
print(f"Status label rect: {window.data_streams._status_label.geometry()}")
print(f"Status label text: {window.data_streams._status_label.text()}")

# Also check how many panes are in the content splitter
print(f"Content splitter count: {window._content_splitter.count()}")
for i in range(window._content_splitter.count()):
    w = window._content_splitter.widget(i)
    print(f"  Widget {i}: {w.__class__.__name__}, visible: {w.isVisible()}, rect: {w.geometry()}")
