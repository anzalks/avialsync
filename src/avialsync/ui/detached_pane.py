"""A workspace pane temporarily shown in its own window."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QSplitter, QVBoxLayout, QWidget

from avialsync.ui.i18n import tr


class DetachedPaneWindow(QDialog):
    """Move one pane out of a splitter and restore its exact slot on close."""

    returned = Signal()

    def __init__(
        self,
        title: str,
        pane: QWidget,
        splitter: QSplitter,
        index: int,
        parent: QWidget,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(title)
        self.setAccessibleName(tr("Detached {title} pane").format(title=title))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(900, 560)
        self._pane = pane
        self._splitter = splitter
        self._placeholder = QWidget()
        self._placeholder.setObjectName("detached_pane_placeholder")
        self._splitter.replaceWidget(index, self._placeholder)

        self._pane_layout = QVBoxLayout(self)
        self._pane_layout.setContentsMargins(0, 0, 0, 0)
        self._pane_layout.addWidget(pane, 1)
        controls = QHBoxLayout()
        controls.addStretch(1)
        self.return_button = QPushButton(tr("Return to main window"), self)
        self.return_button.setAccessibleDescription(
            tr("Put this pane back in its original place in the main workspace.")
        )
        self.return_button.clicked.connect(self.close)
        controls.addWidget(self.return_button)
        self._pane_layout.addLayout(controls)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Reinsert the pane before the detached window is destroyed."""
        index = self._splitter.indexOf(self._placeholder)
        if index >= 0:
            self._pane_layout.removeWidget(self._pane)
            self._splitter.replaceWidget(index, self._pane)
            self._placeholder.deleteLater()
            self.returned.emit()
        super().closeEvent(event)
