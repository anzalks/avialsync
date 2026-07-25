"""Keyboard shortcuts reference dialog."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_SHORTCUTS = [
    ("Space", "Play / Pause"),
    ("←", "Step back 1 frame"),
    ("→", "Step forward 1 frame"),
    ("Shift + ←", "Jump back 1 second"),
    ("Shift + →", "Jump forward 1 second"),
    ("Home", "Jump to start"),
    ("End", "Jump to end"),
    ("[", "Set A/B loop in-point"),
    ("]", "Set A/B loop out-point"),
    ("M", "Add point marker at playhead"),
    ("Ctrl + S", "Save session"),
    ("Ctrl + O", "Open session"),
    ("Ctrl + E", "Export snapshot (plot + frame)"),
    ("Ctrl + T", "Cycle theme (System → Dark → Light)"),
    ("Ctrl + 0", "Reset plot zoom to full data extent"),
    ("?", "Show this shortcuts dialog"),
]


class ShortcutsDialog(QDialog):
    """Modal dialog listing all keyboard shortcuts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        table = QTableWidget(len(_SHORTCUTS), 2)
        table.setHorizontalHeaderLabels(["Key", "Action"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        for row, (key, action) in enumerate(_SHORTCUTS):
            key_item = QTableWidgetItem(key)
            key_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 0, key_item)
            table.setItem(row, 1, QTableWidgetItem(action))

        layout.addWidget(table)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.close)
        layout.addWidget(btn_box)
