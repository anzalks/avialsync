"""Non-modal editor for individually clicked physical-prop steps (D-149)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.physical_props import BallProp, BeltProp, Ladder, Point3, PropStore
from avialsync.ui.i18n import tr


class PropsPanel(QWidget):
    """Kind-specific controls for physical props in the shared inspector."""

    create_requested = Signal(str, bool)
    place_requested = Signal(str, str, bool)
    next_point_requested = Signal()
    save_step_requested = Signal()
    cancel_step_requested = Signal()
    remove_step_requested = Signal(str, str)
    reclick_step_requested = Signal(str, str)
    relabel_step_requested = Signal(str, str, str)
    move_step_requested = Signal(str, str, int)
    remove_ladder_requested = Signal(str)
    belt_save_requested = Signal()
    ball_save_requested = Signal()
    prop_selected = Signal(str, str)
    remove_prop_requested = Signal(str, str)

    def __init__(self, store: PropStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self.setAccessibleName(tr("Physical props inspector"))
        root_layout = QVBoxLayout(self)
        self.kind = QComboBox(self)
        self.kind.addItem(tr("Horizontal ladder"), "ladder")
        self.kind.addItem(tr("Wheel"), "wheel")
        self.kind.addItem(tr("Belt"), "belt")
        self.kind.addItem(tr("Ball"), "ball")
        self.kind.setAccessibleName(tr("Physical prop kind"))
        self.kind.setAccessibleDescription(tr("Choose the apparatus to add."))
        root_layout.addWidget(self.kind)
        self.name = QLineEdit(self)
        self.name.setPlaceholderText(tr("Prop name"))
        self.name.setAccessibleName(tr("Physical prop name"))
        self.name.setAccessibleDescription(tr("A unique name for this recording."))
        self.create_button = QPushButton(tr("Add ladder"), self)
        self.create_button.setAccessibleName(self.create_button.text())
        self.create_button.clicked.connect(
            lambda checked: self.create_requested.emit(self.name.text().strip(), checked)
        )
        self.name_row = QWidget(self)
        name_row = QHBoxLayout(self.name_row)
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.addWidget(self.name)
        name_row.addWidget(self.create_button)
        root_layout.addWidget(self.name_row)
        self.ladders = QComboBox(self)
        self.ladders.setAccessibleName(tr("Saved props of this kind"))
        self.ladders.setAccessibleDescription(tr("Select a saved prop of the selected kind."))
        self.ladders.currentIndexChanged.connect(self._selection_changed)
        root_layout.addWidget(self.ladders)
        self.editor_stack = QStackedWidget(self)
        root_layout.addWidget(self.editor_stack)
        self.ladder_editor = QWidget(self.editor_stack)
        layout = QVBoxLayout(self.ladder_editor)
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
        self.editor_stack.addWidget(self.ladder_editor)
        self._build_belt_editor()
        self._build_ball_editor()
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._kind_changed()
        self.refresh()

    @staticmethod
    def _coordinate(parent: QWidget, name: str) -> QDoubleSpinBox:
        field = QDoubleSpinBox(parent)
        field.setRange(-1_000_000_000.0, 1_000_000_000.0)
        field.setDecimals(4)
        field.setKeyboardTracking(False)
        field.setAccessibleName(name)
        return field

    @staticmethod
    def _units(parent: QWidget) -> QComboBox:
        combo = QComboBox(parent)
        combo.addItem(tr("Calibration units"), "")
        for unit in ("mm", "cm", "m"):
            combo.addItem(unit, unit)
        combo.setAccessibleName(tr("Prop geometry units"))
        return combo

    def _build_belt_editor(self) -> None:
        self.belt_editor = QWidget(self.editor_stack)
        layout = QVBoxLayout(self.belt_editor)
        form = QFormLayout()
        self.belt_units = self._units(self.belt_editor)
        self.belt_closed = QCheckBox(tr("Closed return path"), self.belt_editor)
        self.belt_closed.setAccessibleName(self.belt_closed.text())
        form.addRow(tr("Units"), self.belt_units)
        form.addRow(self.belt_closed)
        layout.addLayout(form)
        self.belt_vertices = QListWidget(self.belt_editor)
        self.belt_vertices.setAccessibleName(tr("Belt support path vertices"))
        self.belt_vertices.setAccessibleDescription(
            tr("Declared points in order along the fixed belt support path.")
        )
        self.belt_vertices.setMinimumHeight(72)
        layout.addWidget(self.belt_vertices)
        point_form = QFormLayout()
        self.belt_point_fields = [
            self._coordinate(self.belt_editor, tr("Belt point X")),
            self._coordinate(self.belt_editor, tr("Belt point Y")),
            self._coordinate(self.belt_editor, tr("Belt point Z")),
        ]
        for axis, field in zip(("X", "Y", "Z"), self.belt_point_fields, strict=True):
            point_form.addRow(tr("Point {axis}").format(axis=axis), field)
        layout.addLayout(point_form)
        point_buttons = QHBoxLayout()
        self.belt_add_vertex = QPushButton(tr("Add path point"), self.belt_editor)
        self.belt_update_vertex = QPushButton(tr("Update selected point"), self.belt_editor)
        self.belt_remove_vertex = QPushButton(tr("Remove selected point"), self.belt_editor)
        for button in (self.belt_add_vertex, self.belt_update_vertex, self.belt_remove_vertex):
            button.setAccessibleName(button.text())
            point_buttons.addWidget(button)
        layout.addLayout(point_buttons)
        direction_form = QFormLayout()
        self.belt_direction_fields = [
            self._coordinate(self.belt_editor, tr("Belt travel direction X")),
            self._coordinate(self.belt_editor, tr("Belt travel direction Y")),
            self._coordinate(self.belt_editor, tr("Belt travel direction Z")),
        ]
        for axis, field in zip(("X", "Y", "Z"), self.belt_direction_fields, strict=True):
            direction_form.addRow(tr("Travel direction {axis}").format(axis=axis), field)
        layout.addLayout(direction_form)
        self.belt_motion_status = QLabel(
            tr("Surface motion is unknown until displacement evidence is bound."),
            self.belt_editor,
        )
        self.belt_motion_status.setWordWrap(True)
        layout.addWidget(self.belt_motion_status)
        self.save_belt = QPushButton(tr("Save belt geometry"), self.belt_editor)
        self.save_belt.setAccessibleName(self.save_belt.text())
        self.save_belt.clicked.connect(self.belt_save_requested)
        layout.addWidget(self.save_belt)
        self.remove_belt = QPushButton(tr("Remove belt"), self.belt_editor)
        self.remove_belt.setAccessibleName(self.remove_belt.text())
        self.remove_belt.clicked.connect(
            lambda: self.remove_prop_requested.emit("belt", self.current_prop())
        )
        layout.addWidget(self.remove_belt)
        self.belt_add_vertex.clicked.connect(self._append_belt_vertex)
        self.belt_update_vertex.clicked.connect(self._replace_belt_vertex)
        self.belt_remove_vertex.clicked.connect(self._remove_belt_vertex)
        self.belt_vertices.currentRowChanged.connect(self._show_belt_vertex)
        self.editor_stack.addWidget(self.belt_editor)

    def _build_ball_editor(self) -> None:
        self.ball_editor = QWidget(self.editor_stack)
        layout = QVBoxLayout(self.ball_editor)
        form = QFormLayout()
        self.ball_units = self._units(self.ball_editor)
        self.ball_centre_fields = [
            self._coordinate(self.ball_editor, tr("Ball centre X")),
            self._coordinate(self.ball_editor, tr("Ball centre Y")),
            self._coordinate(self.ball_editor, tr("Ball centre Z")),
        ]
        for axis, field in zip(("X", "Y", "Z"), self.ball_centre_fields, strict=True):
            form.addRow(tr("Centre {axis}").format(axis=axis), field)
        self.ball_radius = QDoubleSpinBox(self.ball_editor)
        self.ball_radius.setRange(0.0001, 1_000_000_000.0)
        self.ball_radius.setDecimals(4)
        self.ball_radius.setKeyboardTracking(False)
        self.ball_radius.setAccessibleName(tr("Ball radius"))
        form.addRow(tr("Radius"), self.ball_radius)
        form.addRow(tr("Units"), self.ball_units)
        layout.addLayout(form)
        self.ball_motion_status = QLabel(
            tr("Orientation is unknown until surface landmarks or orientation evidence are bound."),
            self.ball_editor,
        )
        self.ball_motion_status.setWordWrap(True)
        layout.addWidget(self.ball_motion_status)
        self.save_ball = QPushButton(tr("Save ball geometry"), self.ball_editor)
        self.save_ball.setAccessibleName(self.save_ball.text())
        self.save_ball.clicked.connect(self.ball_save_requested)
        layout.addWidget(self.save_ball)
        self.remove_ball = QPushButton(tr("Remove ball"), self.ball_editor)
        self.remove_ball.setAccessibleName(self.remove_ball.text())
        self.remove_ball.clicked.connect(
            lambda: self.remove_prop_requested.emit("ball", self.current_prop())
        )
        layout.addWidget(self.remove_ball)
        self.editor_stack.addWidget(self.ball_editor)

    def _append_belt_vertex(self) -> None:
        point = tuple(float(field.value()) for field in self.belt_point_fields)
        self.belt_vertices.addItem(", ".join(f"{value:g}" for value in point))
        self.belt_vertices.setCurrentRow(self.belt_vertices.count() - 1)

    def _replace_belt_vertex(self) -> None:
        row = self.belt_vertices.currentRow()
        if row < 0:
            return
        point = tuple(float(field.value()) for field in self.belt_point_fields)
        self.belt_vertices.item(row).setText(", ".join(f"{value:g}" for value in point))

    def _remove_belt_vertex(self) -> None:
        row = self.belt_vertices.currentRow()
        if row >= 0:
            self.belt_vertices.takeItem(row)

    def _show_belt_vertex(self, row: int) -> None:
        if 0 <= row < self.belt_vertices.count():
            values = [float(value) for value in self.belt_vertices.item(row).text().split(", ")]
            for field, value in zip(self.belt_point_fields, values, strict=True):
                field.setValue(value)

    def belt_values(
        self,
    ) -> tuple[
        tuple[tuple[float, float, float], ...], bool, str, tuple[float, float, float] | None
    ]:
        vertices: tuple[Point3, ...] = tuple(
            (
                float(values[0]),
                float(values[1]),
                float(values[2]),
            )
            for row in range(self.belt_vertices.count())
            for values in (self.belt_vertices.item(row).text().split(", "),)
        )
        direction_values: Point3 = (
            float(self.belt_direction_fields[0].value()),
            float(self.belt_direction_fields[1].value()),
            float(self.belt_direction_fields[2].value()),
        )
        direction = None if all(value == 0.0 for value in direction_values) else direction_values
        return (
            vertices,
            self.belt_closed.isChecked(),
            str(self.belt_units.currentData() or ""),
            direction,
        )

    def set_belt_fields(self, belt: BeltProp) -> None:
        self.belt_vertices.clear()
        for vertex in belt.track.vertices:
            self.belt_vertices.addItem(", ".join(f"{value:g}" for value in vertex))
        self.belt_closed.setChecked(belt.track.closed)
        self.belt_units.setCurrentIndex(max(0, self.belt_units.findData(belt.units)))
        direction = belt.travel_direction or (0.0, 0.0, 0.0)
        for field, value in zip(self.belt_direction_fields, direction, strict=True):
            field.setValue(value)

    def ball_values(self) -> tuple[tuple[float, float, float], float, str]:
        centre = (
            float(self.ball_centre_fields[0].value()),
            float(self.ball_centre_fields[1].value()),
            float(self.ball_centre_fields[2].value()),
        )
        return centre, float(self.ball_radius.value()), str(self.ball_units.currentData() or "")

    def set_ball_fields(self, ball: BallProp) -> None:
        for field, value in zip(self.ball_centre_fields, ball.surface.centre, strict=True):
            field.setValue(value)
        self.ball_radius.setValue(ball.surface.radius)
        self.ball_units.setCurrentIndex(max(0, self.ball_units.findData(ball.units)))

    def set_wheel_placing(self, placing: bool) -> None:
        """Reflect wheel placement state on the kind-sensitive Add button."""
        blocked = self.create_button.blockSignals(True)
        try:
            self.create_button.setChecked(placing)
        finally:
            self.create_button.blockSignals(blocked)
        self.kind.setEnabled(not placing)
        self._update_create_button()

    def _update_create_button(self) -> None:
        kind = str(self.kind.currentData() or "ladder")
        if kind == "wheel":
            text = (
                tr("Cancel wheel placement") if self.create_button.isChecked() else tr("Add wheel")
            )
            description = tr("Start or cancel wheel placement in the video panes")
        else:
            text = tr("Add ladder")
            description = tr("Add a horizontal ladder to this recording")
        self.create_button.setText(text)
        self.create_button.setAccessibleName(text)
        self.create_button.setAccessibleDescription(description)

    def _kind_changed(self) -> None:
        kind = str(self.kind.currentData() or "ladder")
        self.name.clear()
        self.name.setVisible(kind != "wheel")
        self.ladders.setVisible(kind != "wheel")
        self.editor_stack.setVisible(kind != "wheel")
        self.create_button.setVisible(kind in {"ladder", "wheel"})
        self.create_button.setCheckable(kind == "wheel")
        self._update_create_button()
        page = {"ladder": self.ladder_editor, "belt": self.belt_editor, "ball": self.ball_editor}
        if kind in page:
            self.editor_stack.setCurrentWidget(page[kind])
        self.refresh()

    def _place(self, rung: bool) -> None:
        name = self.current_ladder()
        if name:
            self.place_requested.emit(name, self.step_label.text().strip(), rung)

    def current_ladder(self) -> str:
        """The selected ladder's stable name."""
        return self.current_prop()

    def current_prop(self) -> str:
        """The selected saved prop's stable name."""
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
        kind = str(self.kind.currentData() or "ladder")
        self.ladders.blockSignals(True)
        self.ladders.clear()
        for prop in self._store:
            prop_kind = (
                "ladder"
                if isinstance(prop, Ladder)
                else "belt"
                if isinstance(prop, BeltProp)
                else "ball"
                if isinstance(prop, BallProp)
                else ""
            )
            if prop_kind == kind:
                self.ladders.addItem(prop.name, prop.name)
        at = self.ladders.findData(selected)
        self.ladders.setCurrentIndex(at if at >= 0 else 0)
        self.ladders.blockSignals(False)
        has_selection = bool(self.ladders.currentData())
        self.remove_belt.setEnabled(kind == "belt" and has_selection)
        self.remove_ball.setEnabled(kind == "ball" and has_selection)
        self._refresh_steps()
        self._selection_changed()

    def select(self, name: str) -> None:
        """Select a saved prop in the current kind page."""
        index = self.ladders.findData(name)
        if index >= 0:
            self.ladders.setCurrentIndex(index)

    def select_prop(self, name: str, kind: str) -> None:
        """Switch to and select one newly accepted prop."""
        index = self.kind.findData(kind)
        if index >= 0 and index != self.kind.currentIndex():
            self.kind.setCurrentIndex(index)
        self.select(name)

    def _selection_changed(self) -> None:
        kind = str(self.kind.currentData() or "")
        name = str(self.ladders.currentData() or "")
        self.prop_selected.emit(kind, name)

    def _refresh_steps(self) -> None:
        selected = self._selected_step()
        prop = self._store.get(self.current_ladder())
        self.steps.clear()
        if not isinstance(prop, Ladder):
            return
        for step in prop.steps:
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

    def __init__(
        self,
        panel: PropsPanel,
        wheel_tab: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(panel)
        if wheel_tab is not None:
            layout.addWidget(wheel_tab)
            wheel_tab.setVisible(panel.kind.currentData() == "wheel")
            panel.kind.currentIndexChanged.connect(
                lambda _index: wheel_tab.setVisible(panel.kind.currentData() == "wheel")
            )
        self.setWidget(content)
        self.setAccessibleName(tr("Props"))
        self.setAccessibleDescription(tr("Inspect and edit physical apparatus in this recording."))
