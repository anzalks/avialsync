"""Compact shared controls for the time-series plot stack."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from avialsync.ui.action_button import ActionButton
from avialsync.ui.elided_label import ElidedLabel
from avialsync.ui.i18n import tr
from avialsync.ui.plot_sweep import PlotPresentation


class PlotHeader(QWidget):
    """Expose one live-style, page, Y-fit, row-height, and reset control strip."""

    presentation_changed = Signal(object)
    fit_all_requested = Signal()
    row_height_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)
        layout.addWidget(QLabel(tr("Live"), self))

        self.presentation_combo = QComboBox(self)
        self.presentation_combo.addItem(tr("Scope"), PlotPresentation.SCOPE)
        self.presentation_combo.setAccessibleName(tr("Live plot presentation"))
        self.presentation_combo.setToolTip(tr("Live plots clear and restart at each page"))
        self.presentation_combo.currentIndexChanged.connect(self._emit_presentation)
        layout.addWidget(self.presentation_combo)

        self.page_label = ElidedLabel("", self)
        self.page_label.setAccessibleName(tr("Visible plot page"))
        self.page_label.setMaximumWidth(125)
        layout.addWidget(self.page_label)

        self.fit_all_button = QPushButton(tr("Fit Y"), self)
        self.fit_all_button.setAccessibleName(tr("Fit Y ranges for visible channels"))
        self.fit_all_button.setToolTip(tr("Fit and freeze the visible Y range for every channel"))
        self.fit_all_button.clicked.connect(self.fit_all_requested.emit)
        layout.addWidget(self.fit_all_button)

        self.row_height_combo = QComboBox(self)
        self.row_height_combo.addItem(tr("Compact"), 72)
        self.row_height_combo.addItem(tr("Comfortable"), 110)
        self.row_height_combo.addItem(tr("Large"), 160)
        self.row_height_combo.setCurrentIndex(1)
        self.row_height_combo.setAccessibleName(tr("Plot row density"))
        self.row_height_combo.setToolTip(tr("Shared visible channel row height"))
        self.row_height_combo.currentIndexChanged.connect(self._emit_row_height)
        layout.addWidget(self.row_height_combo)

        # The plot pane's own Reset Plots action, which the View menu also
        # shows: it said "Reset plots" here and "Reset Plot Zoom" there for the
        # same Ctrl+0 command (rule 15, D-092).
        self.reset_button = ActionButton(self)
        self.reset_button.setAccessibleName(tr("Reset plot ranges and time span"))
        layout.addWidget(self.reset_button)

    def insert_span_control(self, control: QWidget) -> None:
        """Place the existing time-span editor in this one plots row (D-170)."""
        layout = self.layout()
        assert isinstance(layout, QHBoxLayout)
        layout.insertWidget(layout.indexOf(self.fit_all_button), control, 1)

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


class PlotControlStrip(QScrollArea):
    """One row at normal width, horizontally reachable at the compact floor."""

    def __init__(self, header: PlotHeader, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
        self.setWidget(header)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        """Reserve one control row and a scrollbar only when width needs it."""
        content = self.widget()
        row_height = content.sizeHint().height() if content is not None else 0
        bar_height = self.horizontalScrollBar().sizeHint().height()
        return QSize(1, row_height + bar_height + 2)

    def minimumSizeHint(self) -> QSize:
        """Keep the strip from widening the minimum window."""
        return self.sizeHint()
