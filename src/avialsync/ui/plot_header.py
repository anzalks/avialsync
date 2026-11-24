"""Compact shared controls for the time-series plot stack."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.action_button import ActionButton
from avialsync.ui.design_tokens import spacing
from avialsync.ui.elided_label import ElidedLabel
from avialsync.ui.i18n import tr
from avialsync.ui.plot_sweep import PlotPresentation


class PlotHeader(QWidget):
    """Expose one live-style, page, Y-fit, row-height, and reset control strip."""

    presentation_changed = Signal(object)
    fit_all_requested = Signal()
    row_height_changed = Signal(int)
    view_mode_changed = Signal(str)

    _MIN_COMPACT_WIDTH = 220

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._compact_mode = False
        self._span_control: QWidget | None = None
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._root_layout.setContentsMargins(
            spacing("m"), spacing("xs"), spacing("m"), spacing("xs")
        )
        self._root_layout.setSpacing(spacing("xs"))
        self._primary_row = QHBoxLayout()
        self._primary_row.setContentsMargins(0, 0, 0, 0)
        self._primary_row.setSpacing(spacing("s"))
        self._secondary_row = QHBoxLayout()
        self._secondary_row.setContentsMargins(0, 0, 0, 0)
        self._secondary_row.setSpacing(spacing("s"))
        self._root_layout.addLayout(self._primary_row)
        # Scope is the only live presentation (D-057). The state stays on this
        # combo, which the pane reads, but a one-item selector is not shown: it
        # looked like a choice and did nothing.
        self.presentation_combo = QComboBox(self)
        self.presentation_combo.addItem(tr("Scope"), PlotPresentation.SCOPE)
        self.presentation_combo.setAccessibleName(tr("Live plot presentation"))
        self.presentation_combo.setToolTip(tr("Live plots clear and restart at each page"))
        self.presentation_combo.currentIndexChanged.connect(self._emit_presentation)
        self.presentation_combo.hide()

        self.page_label = ElidedLabel("", self)
        self.page_label.setAccessibleName(tr("Visible plot page"))
        self.page_label.setMaximumWidth(125)
        self._primary_row.addWidget(self.page_label)

        self.fit_all_button = QPushButton(tr("Fit Y"), self)
        self.fit_all_button.setAccessibleName(tr("Fit Y ranges for visible channels"))
        self.fit_all_button.setToolTip(tr("Fit and freeze the visible Y range for every channel"))
        self.fit_all_button.clicked.connect(self.fit_all_requested.emit)
        self._primary_row.addWidget(self.fit_all_button)

        self.row_height_combo = QComboBox(self)
        self.row_height_combo.addItem(tr("Compact"), 72)
        self.row_height_combo.addItem(tr("Comfortable"), 110)
        self.row_height_combo.addItem(tr("Large"), 160)
        # Compact by default, so a laptop shows more rows.
        self.row_height_combo.setCurrentIndex(0)
        self.row_height_combo.setAccessibleName(tr("Plot row density"))
        self.row_height_combo.setToolTip(tr("Shared visible channel row height"))
        self.row_height_combo.currentIndexChanged.connect(self._emit_row_height)
        self._primary_row.addWidget(self.row_height_combo)

        self.view_mode_combo = QComboBox(self)
        self.view_mode_combo.addItem(tr("Stacked"), "stacked")
        self.view_mode_combo.addItem(tr("Grouped"), "grouped")
        self.view_mode_combo.addItem(tr("Overlaid"), "overlay")
        self.view_mode_combo.addItem(tr("Heatmap"), "heatmap")
        self.view_mode_combo.setCurrentIndex(0)
        self.view_mode_combo.setAccessibleName(tr("Plot display mode"))
        self.view_mode_combo.setToolTip(
            tr(
                "Display visible channels as stacked rows, grouped signal bands, "
                "overlaid traces, or a 2D heatmap"
            )
        )
        self.view_mode_combo.currentIndexChanged.connect(self._emit_view_mode)
        self._primary_row.addWidget(self.view_mode_combo)

        # The plot pane's own Reset Plots action, which the View menu also
        # shows: it said "Reset plots" here and "Reset Plot Zoom" there for the
        # same Ctrl+0 command.
        self.reset_button = ActionButton(self)
        self.reset_button.setAccessibleName(tr("Reset plot ranges and time span"))
        self._primary_row.addWidget(self.reset_button)
        self._action_controls = (
            self.fit_all_button,
            self.row_height_combo,
            self.view_mode_combo,
            self.reset_button,
        )

    def insert_span_control(self, control: QWidget) -> None:
        """Place the existing time-span editor in this plots control bar."""
        self._span_control = control
        self._rebuild_rows(self._compact_mode)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = self._root_layout.minimumSize()
        return QSize(min(hint.width(), self._MIN_COMPACT_WIDTH), hint.height())

    def _single_row_min_width(self) -> int:
        margins = self._root_layout.contentsMargins()
        gap = max(0, self._primary_row.spacing())
        items: list[QWidget] = [
            *([self.page_label] if bool(self.page_label.text()) else []),
            *([self._span_control] if self._span_control is not None else []),
            *self._action_controls,
        ]
        controls_w = sum(max(w.minimumWidth(), w.minimumSizeHint().width()) for w in items)
        return margins.left() + margins.right() + controls_w + gap * max(0, len(items) - 1) + 12

    def _rebuild_rows(self, compact: bool) -> None:
        while self._primary_row.count():
            self._primary_row.takeAt(0)
        while self._secondary_row.count():
            self._secondary_row.takeAt(0)
        sec_idx = self._root_layout.indexOf(self._secondary_row)
        if sec_idx >= 0:
            self._root_layout.takeAt(sec_idx)
        self._primary_row.addWidget(self.page_label)
        if self._span_control is not None:
            self._primary_row.addWidget(self._span_control, 1)
        if compact:
            self._secondary_row.addStretch(1)
            for widget in self._action_controls:
                self._secondary_row.addWidget(widget)
            self._root_layout.addLayout(self._secondary_row)
        else:
            for widget in self._action_controls:
                self._primary_row.addWidget(widget)
        self._compact_mode = compact
        self.updateGeometry()
        self._root_layout.activate()

    def sync_width(self, available_width: int) -> bool:
        """Reflow between single-row and two-row layout; return True if mode changed."""
        want_compact = 0 < available_width < self._single_row_min_width()
        if want_compact == self._compact_mode:
            return False
        self._rebuild_rows(want_compact)
        return True

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.sync_width(self.width())

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

    def _emit_view_mode(self, _index: int) -> None:
        self.view_mode_changed.emit(str(self.view_mode_combo.currentData()))


class PlotControlStrip(QScrollArea):
    """One row at normal width, two rows when narrow, scrollable at ultra-compact floor."""

    def __init__(self, header: PlotHeader, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._header = header
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
        self.setWidget(header)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def _sync_header_mode(self, width: int) -> None:
        if self._header.sync_width(width):
            self.updateGeometry()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_header_mode(self.viewport().width() or self.width())

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_header_mode(self.viewport().width() or event.size().width())

    def sizeHint(self) -> QSize:
        """Reserve active row height plus scrollbar height only when visible."""
        content = self.widget()
        row_height = content.sizeHint().height() if content is not None else 0
        hbar = self.horizontalScrollBar()
        bar_height = hbar.sizeHint().height() if hbar.isVisible() else 0
        return QSize(1, row_height + bar_height + 2)

    def minimumSizeHint(self) -> QSize:
        """Keep the strip from widening the minimum window."""
        return self.sizeHint()
