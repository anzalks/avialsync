"""Compact shared controls for the time-series plot stack."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from avialview.ui.plot_sweep import PlotPresentation


class PlotHeader(QWidget):
    """Expose one live-style, page, Y-fit, row-height, and reset control strip."""

    presentation_changed = Signal(object)
    fit_all_requested = Signal()
    row_height_changed = Signal(int)
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)
        layout.addWidget(QLabel("Signals", self))
        layout.addWidget(QLabel("Live", self))

        self.presentation_combo = QComboBox(self)
        self.presentation_combo.addItem("Sweep", PlotPresentation.SWEEP)
        self.presentation_combo.addItem("Scope", PlotPresentation.SCOPE)
        self.presentation_combo.setAccessibleName("Live plot presentation")
        self.presentation_combo.setToolTip(
            "Sweep overwrites retained data; Scope clears and restarts"
        )
        self.presentation_combo.currentIndexChanged.connect(self._emit_presentation)
        layout.addWidget(self.presentation_combo)

        self.page_label = QLabel("", self)
        self.page_label.setAccessibleName("Visible plot page")
        layout.addWidget(self.page_label, 1)

        self.fit_all_button = QPushButton("Fit all", self)
        self.fit_all_button.setToolTip("Fit and freeze the visible Y range for every channel")
        self.fit_all_button.clicked.connect(self.fit_all_requested.emit)
        layout.addWidget(self.fit_all_button)

        layout.addWidget(QLabel("Rows", self))
        self.row_height_combo = QComboBox(self)
        self.row_height_combo.addItem("Compact", 72)
        self.row_height_combo.addItem("Comfortable", 110)
        self.row_height_combo.addItem("Large", 160)
        self.row_height_combo.setCurrentIndex(1)
        self.row_height_combo.setToolTip("Shared visible channel row height")
        self.row_height_combo.currentIndexChanged.connect(self._emit_row_height)
        layout.addWidget(self.row_height_combo)

        self.reset_button = QPushButton("Reset", self)
        self.reset_button.setToolTip("Reset shared time span and fit every visible plot (Ctrl+0)")
        self.reset_button.clicked.connect(self.reset_requested.emit)
        layout.addWidget(self.reset_button)

    def set_presentation(self, presentation: PlotPresentation) -> None:
        """Show a persisted live style without emitting a duplicate state transition."""
        index = self.presentation_combo.findData(presentation)
        self.presentation_combo.blockSignals(True)
        self.presentation_combo.setCurrentIndex(index)
        self.presentation_combo.blockSignals(False)

    def _emit_presentation(self, _index: int) -> None:
        self.presentation_changed.emit(self.presentation_combo.currentData())

    def _emit_row_height(self, _index: int) -> None:
        self.row_height_changed.emit(int(self.row_height_combo.currentData()))
