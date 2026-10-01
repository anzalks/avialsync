"""Non-modal editor for individually clicked physical-prop steps (D-149)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.physical_props import Ladder, PropStore
from avialsync.ui.i18n import tr


class PropsPanel(QWidget):
    """Controls for declared ladders and their exact clicked step geometry."""

    create_requested = Signal(str)
    place_requested = Signal(str, str, bool)
    next_point_requested = Signal()
    save_step_requested = Signal()
    cancel_step_requested = Signal()
    remove_step_requested = Signal(str, str)
    reclick_step_requested = Signal(str, str)
    relabel_step_requested = Signal(str, str, str)
    move_step_requested = Signal(str, str, int)
    remove_ladder_requested = Signal(str)

    def __init__(self, store: PropStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self.setAccessibleName(tr("Physical props inspector"))
        layout = QVBoxLayout(self)
        self.kind = QComboBox(self)
        self.kind.addItem(tr("Horizontal ladder"), "ladder")
        self.kind.addItem(tr("Wheel (open Wheels tab)"), "wheel")
        self.kind.setAccessibleName(tr("Physical prop kind"))
        self.kind.setAccessibleDescription(tr("Choose the apparatus to add."))
        layout.addWidget(self.kind)
        self.name = QLineEdit(self)
        self.name.setPlaceholderText(tr("Ladder name"))
        self.name.setAccessibleName(tr("New ladder name"))
        self.name.setAccessibleDescription(tr("A unique name for this recording."))
        self.create_button = QPushButton(tr("Add ladder"), self)
        self.create_button.setAccessibleName(self.create_button.text())
        self.create_button.clicked.connect(
            lambda: self.create_requested.emit(self.name.text().strip())
        )
        name_row = QHBoxLayout()
        name_row.addWidget(self.name)
        name_row.addWidget(self.create_button)
        layout.addLayout(name_row)
        self.ladders = QComboBox(self)
        self.ladders.setAccessibleName(tr("Saved ladders"))
        self.ladders.setAccessibleDescription(tr("Select a ladder to inspect or edit."))
        self.ladders.currentIndexChanged.connect(self._refresh_steps)
        layout.addWidget(self.ladders)
        self.steps = QListWidget(self)
        self.steps.setAccessibleName(tr("Clicked ladder steps"))
        self.steps.setAccessibleDescription(
            tr("Steps stay in the order placed; each preserves its own camera clicks.")
        )
        layout.addWidget(self.steps)
        legend = QLabel(
            tr("Solid squares are your camera clicks; dashed marks are 3D projections."), self
        )
        legend.setWordWrap(True)
        layout.addWidget(legend)
        form = QFormLayout()
        self.step_label = QLineEdit(self)
        self.step_label.setAccessibleName(tr("Step label"))
        self.step_label.setAccessibleDescription(tr("Name the next foothold, rung, or outline."))
        form.addRow(tr("Step label"), self.step_label)
        self.closed = QCheckBox(tr("Close outline"), self)
        self.closed.setAccessibleName(self.closed.text())
        self.closed.setAccessibleDescription(tr("Join the last clicked point to the first."))
        form.addRow(self.closed)
        layout.addLayout(form)
        self.add_point = QPushButton(tr("Click foothold"), self)
        self.add_rung = QPushButton(tr("Click rung ends"), self)
        self.next_point = QPushButton(tr("Next point"), self)
        self.save_step = QPushButton(tr("Save step"), self)
        self.cancel_step = QPushButton(tr("Cancel clicks"), self)
        self.remove_step = QPushButton(tr("Remove step"), self)
        self.reclick_step = QPushButton(tr("Re-click selected step"), self)
        self.relabel_step = QPushButton(tr("Rename selected step"), self)
        self.up = QPushButton(tr("Move step up"), self)
        self.down = QPushButton(tr("Move step down"), self)
        self.remove_ladder = QPushButton(tr("Remove ladder"), self)
        for button in (
            self.add_point,
            self.add_rung,
            self.next_point,
            self.save_step,
            self.cancel_step,
            self.reclick_step,
            self.relabel_step,
            self.remove_step,
            self.up,
            self.down,
            self.remove_ladder,
        ):
            button.setAccessibleName(button.text())
            layout.addWidget(button)
        self.status = QLabel(tr("Click each point in the cameras where it is visible."), self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.add_point.clicked.connect(lambda: self._place(False))
        self.add_rung.clicked.connect(lambda: self._place(True))
        self.next_point.clicked.connect(self.next_point_requested)
        self.save_step.clicked.connect(self.save_step_requested)
        self.cancel_step.clicked.connect(self.cancel_step_requested)
        self.remove_step.clicked.connect(self._remove_selected_step)
        self.reclick_step.clicked.connect(self._reclick_selected_step)
        self.relabel_step.clicked.connect(self._relabel_selected_step)
        self.up.clicked.connect(lambda: self._move_selected_step(-1))
        self.down.clicked.connect(lambda: self._move_selected_step(1))
        self.remove_ladder.clicked.connect(self._remove_selected_ladder)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._kind_changed()
        self.refresh()

    def _kind_changed(self) -> None:
        ladder = self.kind.currentData() == "ladder"
        self.create_button.setText(tr("Add ladder") if ladder else tr("Open Wheels tab"))
        self.create_button.setAccessibleName(self.create_button.text())
        for widget in (
            self.name,
            self.ladders,
            self.steps,
            self.step_label,
            self.closed,
            self.add_point,
            self.add_rung,
            self.next_point,
            self.save_step,
            self.cancel_step,
            self.reclick_step,
            self.relabel_step,
            self.remove_step,
            self.up,
            self.down,
            self.remove_ladder,
        ):
            widget.setEnabled(ladder)

    def _place(self, rung: bool) -> None:
        name = self.current_ladder()
        if name:
            self.place_requested.emit(name, self.step_label.text().strip(), rung)

    def current_ladder(self) -> str:
        """The selected ladder's stable name."""
        return str(self.ladders.currentData() or "")

    def _selected_step(self) -> str:
        item = self.steps.currentItem()
        return str(item.data(0x0100) or "") if item is not None else ""

    def _remove_selected_step(self) -> None:
        if self.current_ladder() and self._selected_step():
            self.remove_step_requested.emit(self.current_ladder(), self._selected_step())

    def _reclick_selected_step(self) -> None:
        if self.current_ladder() and self._selected_step():
            self.reclick_step_requested.emit(self.current_ladder(), self._selected_step())

    def _relabel_selected_step(self) -> None:
        if self.current_ladder() and self._selected_step() and self.step_label.text().strip():
            self.relabel_step_requested.emit(
                self.current_ladder(), self._selected_step(), self.step_label.text().strip()
            )

    def _move_selected_step(self, offset: int) -> None:
        if self.current_ladder() and self._selected_step():
            self.move_step_requested.emit(self.current_ladder(), self._selected_step(), offset)

    def _remove_selected_ladder(self) -> None:
        if self.current_ladder():
            self.remove_ladder_requested.emit(self.current_ladder())

    def refresh(self) -> None:
        """Reflect the accepted store, preserving the current selection."""
        selected = self.current_ladder()
        self.ladders.blockSignals(True)
        self.ladders.clear()
        for ladder in self._store:
            self.ladders.addItem(ladder.name, ladder.name)
        at = self.ladders.findData(selected)
        self.ladders.setCurrentIndex(at if at >= 0 else 0)
        self.ladders.blockSignals(False)
        self._refresh_steps()

    def select(self, name: str) -> None:
        """Show the newly added ladder."""
        index = self.ladders.findData(name)
        if index >= 0:
            self.ladders.setCurrentIndex(index)

    def _refresh_steps(self) -> None:
        selected = self._selected_step()
        ladder: Ladder | None = self._store.get(self.current_ladder())
        self.steps.clear()
        if ladder is None:
            return
        for step in ladder.steps:
            clicks = sum(len(point.clicks) for point in step.points)
            solved = sum(point.xyz is not None for point in step.points)
            self.steps.addItem(
                tr("{label} — {clicks} clicks; {solved}/{points} points in 3D").format(
                    label=step.label, clicks=clicks, solved=solved, points=len(step.points)
                )
            )
            item = self.steps.item(self.steps.count() - 1)
            item.setData(0x0100, step.step_id)
            if solved < len(step.points):
                item.setToolTip(
                    tr(
                        "Unsolved points stay in their clicked cameras until more "
                        "calibrated views are clicked."
                    )
                )
            else:
                worst = max(point.error_px or 0.0 for point in step.points)
                item.setToolTip(
                    tr(
                        "All points located in 3D; largest reprojection error {error:.1f} px."
                    ).format(error=worst)
                )
        for index in range(self.steps.count()):
            if self.steps.item(index).data(0x0100) == selected:
                self.steps.setCurrentRow(index)
                break


class PropsTab(QScrollArea):
    """Keep the inspector usable in the compact 640×480 workspace."""

    def __init__(self, panel: PropsPanel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setWidget(panel)
        self.setAccessibleName(tr("Props"))
        self.setAccessibleDescription(tr("Inspect and edit physical apparatus in this recording."))
