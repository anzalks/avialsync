"""Non-modal editor for individually clicked physical-prop steps (D-149)."""

from __future__ import annotations

import math

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
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.physical_props import (
    BallProp,
    BeltProp,
    Ladder,
    LadderSupport,
    Point3,
    PropStore,
    StepIrregularity,
)
from avialsync.ui.about import docs_url
from avialsync.ui.belt_placement_controls import BeltPlacementControls
from avialsync.ui.i18n import tr
from avialsync.ui.step_panel import StepPanel


def support_text(support: LadderSupport) -> str:
    """The translated name of a ladder support layout."""
    return {
        "none": tr("No support bars"),
        "side_rails": tr("Side rails at rung ends"),
        "centre_beam": tr("Centre beam under rungs"),
    }[support]


def irregular_text(tag: StepIrregularity) -> str:
    """The translated name of a step's irregularity tag; empty when regular."""
    return {
        "": "",
        "missing": tr("missing rung"),
        "raised": tr("raised"),
        "lowered": tr("lowered"),
        "shifted": tr("shifted sideways"),
        "other": tr("irregular"),
    }[tag]


class PropsPanel(QWidget):
    """Kind-specific controls for physical props in the shared inspector."""

    create_requested = Signal(str, bool)
    place_requested = Signal(str, str, bool)
    next_point_requested = Signal()
    save_step_requested = Signal()
    save_next_step_requested = Signal()
    ladder_support_requested = Signal(str, str)
    step_irregular_requested = Signal(str, str, str)
    belt_placement_requested = Signal(str)
    rung_count_requested = Signal(str, int)
    cancel_step_requested = Signal()
    remove_step_requested = Signal(str, str)
    reclick_step_requested = Signal(str, str)
    relabel_step_requested = Signal(str, str, str)
    move_step_requested = Signal(str, str, int)
    remove_ladder_requested = Signal(str)
    belt_save_requested = Signal()
    ball_save_requested = Signal()
    belt_bind_requested = Signal()
    ball_bind_requested = Signal()
    visual_track_requested = Signal(str, str)
    visual_clear_requested = Signal(str, str)
    visual_lap_requested = Signal(str)
    motion_check_requested = Signal(str, str)
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
        self.ladders = QComboBox(self)
        self.ladders.setAccessibleName(tr("Saved props of this kind"))
        self.ladders.setAccessibleDescription(tr("Select a saved prop of the selected kind."))
        self.ladders.currentIndexChanged.connect(self._selection_changed)
        # Labelled, in the order they are used: what kind, which saved one,
        # or a name for a new one (D-176, F-16).
        header = QFormLayout()
        header.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        header.addRow(tr("Kind"), self.kind)
        header.addRow(tr("Saved"), self.ladders)
        header.addRow(tr("New"), self.name_row)
        root_layout.addLayout(header)
        self.editor_stack = QStackedWidget(self)
        root_layout.addWidget(self.editor_stack)
        self.ladder_editor = QWidget(self.editor_stack)
        layout = QVBoxLayout(self.ladder_editor)
        # The panel already has the outer margin; a second one inside each page
        # put the belt and ball editors a few pixels past a 280 px sidebar.
        layout.setContentsMargins(0, 0, 0, 0)
        self.steps = QListWidget(self)
        self.steps.setAccessibleName(tr("Clicked ladder steps"))
        self.steps.setAccessibleDescription(
            tr("Steps stay in the order placed; each preserves its own camera clicks.")
        )
        layout.addWidget(self.steps)
        support_form = QFormLayout()
        self.ladder_support = QComboBox(self)
        for support in ("none", "side_rails", "centre_beam"):
            self.ladder_support.addItem(support_text(support), support)
        self.ladder_support.setAccessibleName(tr("Ladder support bars"))
        self.ladder_support.setAccessibleDescription(
            tr("Draw a rail through each rung end, or one beam under the rung middles.")
        )
        self.ladder_support.activated.connect(self._support_chosen)
        support_form.addRow(tr("Support"), self.ladder_support)
        self.rung_count = QSpinBox(self)
        self.rung_count.setRange(0, 10_000)
        self.rung_count.setSpecialValueText(tr("Off"))
        self.rung_count.setAccessibleName(tr("Rungs in the regular run"))
        self.rung_count.setAccessibleDescription(
            tr("Total rungs to extrapolate from the first two clicked rungs; Off to stop.")
        )
        support_form.addRow(tr("Rungs in total"), self.rung_count)
        layout.addLayout(support_form)
        self.extrapolate = QPushButton(tr("Extrapolate from first two rungs"), self)
        self.extrapolate.setAccessibleName(self.extrapolate.text())
        self.extrapolate.setAccessibleDescription(
            tr("Click two neighbouring rungs first; clicked rungs always replace estimates.")
        )
        self.extrapolate.clicked.connect(self._extrapolate_chosen)
        layout.addWidget(self.extrapolate)
        legend = QLabel(
            tr("Solid squares are your camera clicks; dashed marks are 3D projections."), self
        )
        legend.setWordWrap(True)
        form = QFormLayout()
        self.step_label = QLineEdit(self)
        self.step_label.setAccessibleName(tr("Step label"))
        self.step_label.setAccessibleDescription(tr("Name the next foothold, rung, or outline."))
        form.addRow(tr("Step label"), self.step_label)
        self.closed = QCheckBox(tr("Close outline"), self)
        self.closed.setAccessibleName(self.closed.text())
        self.closed.setAccessibleDescription(tr("Join the last clicked point to the first."))
        form.addRow(self.closed)
        self.step_irregular = QComboBox(self)
        self.step_irregular.addItem(tr("Regular"), "")
        for tag in ("missing", "raised", "lowered", "shifted", "other"):
            self.step_irregular.addItem(irregular_text(tag).capitalize(), tag)
        self.step_irregular.setAccessibleName(tr("Step regularity"))
        self.step_irregular.setAccessibleDescription(
            tr("Tag a place where the ladder departs from its regular pattern.")
        )
        form.addRow(tr("Regularity"), self.step_irregular)
        layout.addLayout(form)
        self.add_point = QPushButton(tr("Click foothold"), self)
        self.add_rung = QPushButton(tr("Click rung ends"), self)
        self.next_point = QPushButton(tr("Next point"), self)
        self.save_step = QPushButton(tr("Save step"), self)
        self.save_next_step = QPushButton(tr("Save and click next step"), self)
        self.save_next_step.setAccessibleDescription(
            tr("Save this step and start clicking the next one of the same kind.")
        )
        self.tag_step = QPushButton(tr("Set selected step's regularity"), self)
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
            self.save_next_step,
            self.cancel_step,
            self.reclick_step,
            self.relabel_step,
            self.tag_step,
            self.remove_step,
            self.up,
            self.down,
            self.remove_ladder,
        ):
            button.setAccessibleName(button.text())
        self.status = QLabel(tr("Click each point in the cameras where it is visible."), self)
        # One primary, four ordinary choices, the rest in the overflow (D-176).
        self.ladder_steps = StepPanel(tr("Ladder steps"), self.ladder_editor)
        self.ladder_steps.use_instruction_label(self.status)
        self.ladder_steps.set_primary(self.save_next_step)
        self.ladder_steps.add_secondary(
            [self.add_point, self.add_rung, self.next_point, self.save_step]
        )
        for button in (
            self.cancel_step,
            self.reclick_step,
            self.relabel_step,
            self.tag_step,
            self.up,
            self.down,
        ):
            self.ladder_steps.add_overflow(button)
        for button in (self.remove_step, self.remove_ladder):
            self.ladder_steps.add_overflow(button, destructive=True)
        self.ladder_steps.add_more(legend)
        self.ladder_steps.set_learn_more(docs_url("user-guide/index.html#physical-props"))
        layout.addWidget(self.ladder_steps)
        self.add_point.clicked.connect(lambda: self._place(False))
        self.add_rung.clicked.connect(lambda: self._place(True))
        self.next_point.clicked.connect(self.next_point_requested)
        self.save_step.clicked.connect(self.save_step_requested)
        self.save_next_step.clicked.connect(self.save_next_step_requested)
        self.tag_step.clicked.connect(self._tag_selected_step)
        self.steps.currentRowChanged.connect(self._show_step_tag)
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
        # Labels such as "Distance per reading unit" beside a six-decimal spin
        # box needed 327 px in a 280 px sidebar. A row that does not fit puts
        # its label above its field instead of forcing the panel wider.
        for form in self.findChildren(QFormLayout):
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
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
    def _point(fields: list[QDoubleSpinBox]) -> Point3:
        return (float(fields[0].value()), float(fields[1].value()), float(fields[2].value()))

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
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.belt_geometry_mode = QComboBox(self.belt_editor)
        self.belt_geometry_mode.addItem(tr("Two rollers placed in 3D"), "rollers")
        self.belt_geometry_mode.addItem(tr("Two rollers in one camera view"), "side")
        self.belt_geometry_mode.addItem(tr("Legacy point path"), "path")
        self.belt_geometry_mode.setAccessibleName(tr("Belt geometry model"))
        self.belt_geometry_mode.setAccessibleDescription(
            tr(
                "Place measured rollers from calibrated cameras, or in one camera's "
                "side view without calibration."
            )
        )
        form.addRow(tr("Geometry"), self.belt_geometry_mode)
        self.belt_units = self._units(self.belt_editor)
        self.belt_closed = QCheckBox(tr("Closed return path"), self.belt_editor)
        self.belt_closed.setAccessibleName(self.belt_closed.text())
        form.addRow(tr("Units"), self.belt_units)
        form.addRow(self.belt_closed)
        layout.addLayout(form)
        measure_form = QFormLayout()
        self.belt_centre_distance = QDoubleSpinBox(self.belt_editor)
        self.belt_centre_distance.setRange(0.0, 1_000_000_000.0)
        self.belt_centre_distance.setDecimals(4)
        self.belt_centre_distance.setSpecialValueText(tr("From clicks"))
        self.belt_centre_distance.setAccessibleName(tr("Measured roller centre distance"))
        self.belt_centre_distance.setAccessibleDescription(
            tr("Distance between the two roller axles, measured on the apparatus.")
        )
        measure_form.addRow(tr("Centre distance"), self.belt_centre_distance)
        self.belt_radius = QDoubleSpinBox(self.belt_editor)
        self.belt_radius.setRange(0.0, 1_000_000_000.0)
        self.belt_radius.setDecimals(4)
        self.belt_radius.setAccessibleName(tr("Measured roller radius"))
        measure_form.addRow(tr("Roller radius"), self.belt_radius)
        self.belt_measure_controls = QWidget(self.belt_editor)
        self.belt_measure_controls.setLayout(measure_form)
        layout.addWidget(self.belt_measure_controls)
        self.belt_placement = BeltPlacementControls(self.belt_editor)
        self.belt_placement.start.clicked.connect(
            lambda: self.belt_placement_requested.emit(
                str(self.belt_geometry_mode.currentData() or "")
            )
        )
        self.belt_placement.next_point.clicked.connect(self.next_point_requested)
        self.belt_placement.place.clicked.connect(self.save_step_requested)
        self.belt_placement.cancel.clicked.connect(self.cancel_step_requested)
        layout.addWidget(self.belt_placement)
        roller_form = QFormLayout()
        self.belt_first_fields = [
            self._coordinate(self.belt_editor, tr("First roller centre {axis}").format(axis=axis))
            for axis in ("X", "Y", "Z")
        ]
        self.belt_second_fields = [
            self._coordinate(self.belt_editor, tr("Second roller centre {axis}").format(axis=axis))
            for axis in ("X", "Y", "Z")
        ]
        for axis, first, second in zip(
            ("X", "Y", "Z"), self.belt_first_fields, self.belt_second_fields, strict=True
        ):
            roller_form.addRow(tr("First centre {axis}").format(axis=axis), first)
            roller_form.addRow(tr("Second centre {axis}").format(axis=axis), second)
        self.belt_roller_controls = QWidget(self.belt_editor)
        self.belt_roller_controls.setLayout(roller_form)
        layout.addWidget(self.belt_roller_controls)
        self.belt_geometry_mode.currentIndexChanged.connect(self._update_belt_geometry_mode)
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
        # One per line, as every other action in this panel: three of these
        # side by side needed 435 px in a 280 px sidebar.
        point_buttons = QVBoxLayout()
        self.belt_add_vertex = QPushButton(tr("Add path point"), self.belt_editor)
        self.belt_update_vertex = QPushButton(tr("Update selected point"), self.belt_editor)
        self.belt_remove_vertex = QPushButton(tr("Remove selected point"), self.belt_editor)
        for button in (self.belt_add_vertex, self.belt_update_vertex, self.belt_remove_vertex):
            button.setAccessibleName(button.text())
            point_buttons.addWidget(button)
        layout.addLayout(point_buttons)
        self.belt_path_controls = (
            self.belt_closed,
            self.belt_vertices,
            *self.belt_point_fields,
            self.belt_add_vertex,
            self.belt_update_vertex,
            self.belt_remove_vertex,
        )
        surface_form = QFormLayout()
        self.belt_width = QDoubleSpinBox(self.belt_editor)
        self.belt_width.setRange(0.0, 1_000_000_000.0)
        self.belt_width.setDecimals(4)
        self.belt_width.setSpecialValueText(tr("No surface mesh"))
        self.belt_width.setAccessibleName(tr("Measured belt surface width"))
        self.belt_width.setAccessibleDescription(
            tr("Width across the belt path, in the selected calibration units.")
        )
        surface_form.addRow(tr("Surface width"), self.belt_width)
        self.belt_normal_fields = [
            self._coordinate(self.belt_editor, tr("Belt surface normal X")),
            self._coordinate(self.belt_editor, tr("Belt surface normal Y")),
            self._coordinate(self.belt_editor, tr("Belt surface normal Z")),
        ]
        self.belt_normal_controls = QWidget(self.belt_editor)
        normal_form = QFormLayout(self.belt_normal_controls)
        normal_form.setContentsMargins(0, 0, 0, 0)
        for axis, field in zip(("X", "Y", "Z"), self.belt_normal_fields, strict=True):
            normal_form.addRow(tr("Surface normal {axis}").format(axis=axis), field)
        layout.addLayout(surface_form)
        layout.addWidget(self.belt_normal_controls)
        self._update_belt_geometry_mode()
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
        motion_form = QFormLayout()
        self.belt_channel = QComboBox(self.belt_editor)
        self.belt_channel.setAccessibleName(tr("Belt displacement channel"))
        self.belt_channel.setAccessibleDescription(
            tr("Choose the loaded channel that measures signed belt travel.")
        )
        motion_form.addRow(tr("Displacement channel"), self.belt_channel)
        self.belt_reference_distance = self._coordinate(
            self.belt_editor, tr("Belt mark distance along path on reference frame")
        )
        motion_form.addRow(tr("Mark distance along path"), self.belt_reference_distance)
        self.belt_scale = QDoubleSpinBox(self.belt_editor)
        self.belt_scale.setRange(0.000001, 1_000_000_000.0)
        self.belt_scale.setDecimals(6)
        self.belt_scale.setValue(1.0)
        self.belt_scale.setAccessibleName(tr("Belt distance per channel unit"))
        self.belt_scale.setAccessibleDescription(
            tr("Enter path distance moved for one unit of displacement reading.")
        )
        motion_form.addRow(tr("Distance per reading unit"), self.belt_scale)
        layout.addLayout(motion_form)
        self.bind_belt = QPushButton(tr("Bind displacement at current frame"), self.belt_editor)
        self.bind_belt.setAccessibleName(self.bind_belt.text())
        self.bind_belt.setAccessibleDescription(
            tr("Use the displayed frame as the reference for belt displacement.")
        )
        self.bind_belt.clicked.connect(self.belt_bind_requested)
        self.check_belt = QPushButton(tr("Check belt mark on later frame"), self.belt_editor)
        self.check_belt.setAccessibleName(self.check_belt.text())
        self.check_belt.setAccessibleDescription(
            tr("Click the identified mark on a later displayed frame to measure prediction error.")
        )
        self.check_belt.clicked.connect(
            lambda: self.motion_check_requested.emit("belt", self.current_prop())
        )
        self.track_belt = QPushButton(tr("Track belt mark from camera clicks"), self.belt_editor)
        self.track_belt.setAccessibleName(self.track_belt.text())
        self.track_belt.setAccessibleDescription(
            tr("Click the same material mark in two calibrated cameras on each observed frame.")
        )
        self.track_belt.clicked.connect(
            lambda: self.visual_track_requested.emit("belt", self.current_prop())
        )
        lap_form = QFormLayout()
        self.belt_lap = QSpinBox(self.belt_editor)
        self.belt_lap.setRange(-1_000_000, 1_000_000)
        self.belt_lap.setAccessibleName(tr("Belt visual lap count"))
        self.belt_lap.setAccessibleDescription(
            tr("Whole laps of the identified mark since the visual reference frame.")
        )
        self.set_belt_lap = QPushButton(tr("Set lap count on current frame"), self.belt_editor)
        self.set_belt_lap.setAccessibleName(self.set_belt_lap.text())
        self.set_belt_lap.clicked.connect(
            lambda: self.visual_lap_requested.emit(self.current_prop())
        )
        lap_form.addRow(tr("Laps"), self.belt_lap)
        layout.addLayout(lap_form)
        self.clear_belt_visual = QPushButton(tr("Clear belt visual track"), self.belt_editor)
        self.clear_belt_visual.setAccessibleName(self.clear_belt_visual.text())
        self.clear_belt_visual.clicked.connect(
            lambda: self.visual_clear_requested.emit("belt", self.current_prop())
        )
        self.save_belt = QPushButton(tr("Save belt geometry"), self.belt_editor)
        self.save_belt.setAccessibleName(self.save_belt.text())
        self.save_belt.clicked.connect(self.belt_save_requested)
        self.remove_belt = QPushButton(tr("Remove belt"), self.belt_editor)
        self.remove_belt.setAccessibleName(self.remove_belt.text())
        self.remove_belt.clicked.connect(
            lambda: self.remove_prop_requested.emit("belt", self.current_prop())
        )
        self.belt_steps = StepPanel(tr("Belt"), self.belt_editor)
        self.belt_steps.set_instruction(
            tr("Save the belt's path, then bind or track how its surface moves.")
        )
        self.belt_steps.set_primary(self.save_belt)
        self.belt_steps.add_secondary(
            [self.track_belt, self.bind_belt, self.check_belt, self.set_belt_lap]
        )
        self.belt_steps.add_overflow(self.clear_belt_visual, destructive=True)
        self.belt_steps.add_overflow(self.remove_belt, destructive=True)
        self.belt_steps.set_learn_more(docs_url("user-guide/index.html#physical-props"))
        layout.addWidget(self.belt_steps)
        self.belt_add_vertex.clicked.connect(self._append_belt_vertex)
        self.belt_update_vertex.clicked.connect(self._replace_belt_vertex)
        self.belt_remove_vertex.clicked.connect(self._remove_belt_vertex)
        self.belt_vertices.currentRowChanged.connect(self._show_belt_vertex)
        self.belt_channel.currentIndexChanged.connect(self._update_motion_enablement)
        self.editor_stack.addWidget(self.belt_editor)

    def _build_ball_editor(self) -> None:
        self.ball_editor = QWidget(self.editor_stack)
        layout = QVBoxLayout(self.ball_editor)
        layout.setContentsMargins(0, 0, 0, 0)
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
        motion_form = QFormLayout()
        self.ball_channels = [QComboBox(self.ball_editor) for _ in range(4)]
        for component, combo in zip(("w", "x", "y", "z"), self.ball_channels, strict=True):
            combo.setAccessibleName(
                tr("Ball quaternion {component} channel").format(component=component)
            )
            combo.setAccessibleDescription(
                tr("Choose one component of a synchronized orientation quaternion.")
            )
            motion_form.addRow(tr("Orientation {component}").format(component=component), combo)
        self.ball_mark_fields = [
            self._coordinate(self.ball_editor, tr("Ball surface mark {axis}").format(axis=axis))
            for axis in ("X", "Y", "Z")
        ]
        for field in self.ball_mark_fields:
            field.setAccessibleDescription(
                tr("World direction of the identified mark on the reference frame.")
            )
        self.ball_mark_fields[0].setValue(1.0)
        for axis, field in zip(("X", "Y", "Z"), self.ball_mark_fields, strict=True):
            motion_form.addRow(tr("Mark direction {axis}").format(axis=axis), field)
        layout.addLayout(motion_form)
        self.bind_ball = QPushButton(tr("Bind orientation at current frame"), self.ball_editor)
        self.bind_ball.setAccessibleName(self.bind_ball.text())
        self.bind_ball.setAccessibleDescription(
            tr("Use four synchronized orientation readings on the displayed frame.")
        )
        self.bind_ball.clicked.connect(self.ball_bind_requested)
        self.check_ball = QPushButton(tr("Check ball mark on later frame"), self.ball_editor)
        self.check_ball.setAccessibleName(self.check_ball.text())
        self.check_ball.setAccessibleDescription(
            tr("Click the identified ball mark on a later frame to measure prediction error.")
        )
        self.check_ball.clicked.connect(
            lambda: self.motion_check_requested.emit("ball", self.current_prop())
        )
        self.ball_visual_mark = QComboBox(self.ball_editor)
        for index, label in enumerate(("A", "B", "C")):
            self.ball_visual_mark.addItem(tr("Surface mark {label}").format(label=label), index)
        self.ball_visual_mark.setAccessibleName(tr("Ball visual landmark identity"))
        self.ball_visual_mark.setAccessibleDescription(
            tr("Choose the same surface mark identity at the reference and later frames.")
        )
        layout.addWidget(self.ball_visual_mark)
        self.track_ball = QPushButton(tr("Track ball mark from camera clicks"), self.ball_editor)
        self.track_ball.setAccessibleName(self.track_ball.text())
        self.track_ball.setAccessibleDescription(
            tr("Click each of three named marks in two calibrated cameras per observed frame.")
        )
        self.track_ball.clicked.connect(
            lambda: self.visual_track_requested.emit("ball", self.current_prop())
        )
        self.clear_ball_visual = QPushButton(tr("Clear ball visual track"), self.ball_editor)
        self.clear_ball_visual.setAccessibleName(self.clear_ball_visual.text())
        self.clear_ball_visual.clicked.connect(
            lambda: self.visual_clear_requested.emit("ball", self.current_prop())
        )
        self.save_ball = QPushButton(tr("Save ball geometry"), self.ball_editor)
        self.save_ball.setAccessibleName(self.save_ball.text())
        self.save_ball.clicked.connect(self.ball_save_requested)
        self.remove_ball = QPushButton(tr("Remove ball"), self.ball_editor)
        self.remove_ball.setAccessibleName(self.remove_ball.text())
        self.remove_ball.clicked.connect(
            lambda: self.remove_prop_requested.emit("ball", self.current_prop())
        )
        self.ball_steps = StepPanel(tr("Ball"), self.ball_editor)
        self.ball_steps.set_instruction(
            tr("Save the ball's geometry, then bind or track how it turns.")
        )
        self.ball_steps.set_primary(self.save_ball)
        self.ball_steps.add_secondary([self.track_ball, self.bind_ball, self.check_ball])
        self.ball_steps.add_overflow(self.clear_ball_visual, destructive=True)
        self.ball_steps.add_overflow(self.remove_ball, destructive=True)
        self.ball_steps.set_learn_more(docs_url("user-guide/index.html#physical-props"))
        layout.addWidget(self.ball_steps)
        # The stack is sized for the longer belt page. Keep the ball controls
        # together at the top instead of distributing the surplus between forms.
        layout.addStretch()
        self.editor_stack.addWidget(self.ball_editor)
        for combo in self.ball_channels:
            combo.currentIndexChanged.connect(self._update_motion_enablement)

    def _append_belt_vertex(self) -> None:
        point = tuple(float(field.value()) for field in self.belt_point_fields)
        self.belt_vertices.addItem(", ".join(f"{value:g}" for value in point))
        self.belt_vertices.setCurrentRow(self.belt_vertices.count() - 1)

    def _update_belt_geometry_mode(self) -> None:
        mode = self.belt_geometry_mode.currentData()
        self.belt_roller_controls.setVisible(mode == "rollers")
        self.belt_measure_controls.setVisible(mode in ("rollers", "side"))
        self.belt_placement.set_mode(str(mode))
        self.belt_normal_controls.setVisible(mode != "side")
        for widget in self.belt_path_controls:
            widget.setVisible(mode == "path")

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
        tuple[tuple[float, float, float], ...],
        bool,
        str,
        Point3 | None,
        float | None,
        Point3 | None,
        tuple[Point3, Point3, float] | None,
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
        width = float(self.belt_width.value()) or None
        normal = self._point(self.belt_normal_fields) if width else None
        mode = self.belt_geometry_mode.currentData()
        rollers: tuple[Point3, Point3, float] | None = None
        if mode == "rollers":
            rollers = (
                self._point(self.belt_first_fields),
                self._point(self.belt_second_fields),
                float(self.belt_radius.value()),
            )
        elif mode == "side":
            # A one-camera belt lives in its own side plane: x from hub 1 to
            # hub 2, y up. Only the measurements give it size.
            rollers = (
                (0.0, 0.0, 0.0),
                (float(self.belt_centre_distance.value()), 0.0, 0.0),
                float(self.belt_radius.value()),
            )
            normal = (0.0, 1.0, 0.0) if width else None
        return (
            vertices,
            self.belt_closed.isChecked(),
            str(self.belt_units.currentData() or ""),
            direction,
            width,
            normal,
            rollers,
        )

    def set_belt_fields(self, belt: BeltProp) -> None:
        mode = (
            "side"
            if belt.side_view is not None
            else "rollers"
            if belt.rollers is not None
            else "path"
        )
        self.belt_geometry_mode.setCurrentIndex(self.belt_geometry_mode.findData(mode))
        if belt.rollers is not None:
            self.belt_centre_distance.setValue(belt.rollers.run_length)
            for fields, values in (
                (self.belt_first_fields, belt.rollers.first),
                (self.belt_second_fields, belt.rollers.second),
            ):
                for field, value in zip(fields, values, strict=True):
                    field.setValue(value)
            self.belt_radius.setValue(belt.rollers.radius)
        self.belt_vertices.clear()
        for vertex in belt.track.vertices:
            self.belt_vertices.addItem(", ".join(f"{value:g}" for value in vertex))
        self.belt_closed.setChecked(belt.track.closed)
        self.belt_units.setCurrentIndex(max(0, self.belt_units.findData(belt.units)))
        direction = belt.travel_direction or (0.0, 0.0, 0.0)
        for field, value in zip(self.belt_direction_fields, direction, strict=True):
            field.setValue(value)
        self.belt_width.setValue(belt.surface_width or 0.0)
        self.belt_placement.show_saved(belt)
        for field, value in zip(
            self.belt_normal_fields, belt.surface_normal or (0.0, 0.0, 0.0), strict=True
        ):
            field.setValue(value)
        binding = belt.binding
        self.belt_reference_distance.setValue(binding.reference_distance if binding else 0.0)
        self.belt_scale.setValue(binding.units_per_reading if binding else 1.0)
        if binding is not None:
            self.select_channel(self.belt_channel, (binding.source_id, binding.channel))
        if belt.visual_frames:
            solved = sum(len(frame.point.clicks) >= 2 for frame in belt.visual_frames)
            self.belt_motion_status.setText(
                tr("Visual belt track: {solved}/{total} frames have two camera clicks.").format(
                    solved=solved, total=len(belt.visual_frames)
                )
            )
        elif binding and binding.checks:
            last = binding.checks[-1]
            self.belt_motion_status.setText(
                tr("Bound; {count} checks. Last: {residual:.1f} px (frame {frame}).").format(
                    count=len(binding.checks), residual=last.residual_px, frame=last.frame
                )
            )
        elif binding:
            self.belt_motion_status.setText(tr("Displacement bound; no later-frame checks yet."))
        else:
            self.belt_motion_status.setText(
                tr("Surface motion is unknown until displacement evidence is bound.")
            )
        self.check_belt.setEnabled(binding is not None)
        self.clear_belt_visual.setEnabled(bool(belt.visual_frames))
        self.set_belt_lap.setEnabled(belt.track.closed and bool(belt.visual_frames))
        self._update_motion_enablement()

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
        mark = ball.surface_marks[0] if ball.surface_marks else (1.0, 0.0, 0.0)
        for field, value in zip(self.ball_mark_fields, mark, strict=True):
            field.setValue(value)
        binding = ball.binding
        if binding is not None:
            for combo, channel in zip(self.ball_channels, binding.channels, strict=True):
                self.select_channel(combo, (binding.source_id, channel))
        if ball.visual_frames:
            solved = sum(
                all(len(mark.clicks) >= 2 for mark in frame.marks) for frame in ball.visual_frames
            )
            self.ball_motion_status.setText(
                tr("Visual ball track: {solved}/{total} frames have three stereo marks.").format(
                    solved=solved, total=len(ball.visual_frames)
                )
            )
        elif binding and binding.checks:
            last = binding.checks[-1]
            self.ball_motion_status.setText(
                tr("Bound; {count} checks. Last: {residual:.1f} px (frame {frame}).").format(
                    count=len(binding.checks), residual=last.residual_px, frame=last.frame
                )
            )
        elif binding:
            self.ball_motion_status.setText(tr("Orientation bound; no later-frame checks yet."))
        else:
            self.ball_motion_status.setText(
                tr("Orientation is unknown until four orientation channels are bound.")
            )
        self.check_ball.setEnabled(binding is not None)
        self.clear_ball_visual.setEnabled(bool(ball.visual_frames))
        self._update_motion_enablement()

    def set_motion_channels(self, channels: list[tuple[str, str, str]]) -> None:
        """Populate binding choices from live plot readers, retaining selections."""
        for combo in (self.belt_channel, *self.ball_channels):
            current = combo.currentData()
            combo.clear()
            combo.addItem(tr("Choose channel"), None)
            for source, channel, label in channels:
                combo.addItem(label, (source, channel))
            self.select_channel(combo, current)
        self._update_motion_enablement()

    def _update_motion_enablement(self) -> None:
        """Expose missing binding inputs before an unavailable gesture."""
        selected = self._store.get(self.current_prop())
        belt_ready = isinstance(selected, BeltProp) and self.belt_channel.currentData() is not None
        self.bind_belt.setEnabled(belt_ready)
        self.bind_belt.setToolTip(
            "" if belt_ready else tr("Save a belt and choose a displacement channel first.")
        )
        visual_belt_ready = isinstance(selected, BeltProp) and selected.travel_direction is not None
        if visual_belt_ready and isinstance(selected, BeltProp):
            assert selected.travel_direction is not None
            tangent = tuple(
                b - a
                for a, b in zip(selected.track.vertices[0], selected.track.vertices[1], strict=True)
            )
            alignment = sum(a * b for a, b in zip(tangent, selected.travel_direction, strict=True))
            visual_belt_ready = abs(alignment) >= 1e-9 * math.hypot(*tangent)
        self.track_belt.setEnabled(visual_belt_ready)
        self.track_belt.setToolTip(
            "" if visual_belt_ready else tr("Save a belt with a path travel direction first.")
        )
        belt_checked = isinstance(selected, BeltProp) and selected.binding is not None
        self.check_belt.setEnabled(belt_checked)
        self.check_belt.setToolTip(
            "" if belt_checked else tr("Bind belt displacement before checking a later frame.")
        )
        keys = [combo.currentData() for combo in self.ball_channels]
        chosen = [key for key in keys if key is not None]
        ball_ready = (
            isinstance(selected, BallProp)
            and len(chosen) == 4
            and len({key[0] for key in chosen}) == 1
            and len({key[1] for key in chosen}) == 4
        )
        self.bind_ball.setEnabled(ball_ready)
        self.bind_ball.setToolTip(
            "" if ball_ready else tr("Save a ball and choose four channels from one source first.")
        )
        self.track_ball.setEnabled(isinstance(selected, BallProp))
        ball_checked = isinstance(selected, BallProp) and selected.binding is not None
        self.check_ball.setEnabled(ball_checked)
        self.check_ball.setToolTip(
            "" if ball_checked else tr("Bind ball orientation before checking a later frame.")
        )

    @staticmethod
    def select_channel(combo: QComboBox, key: tuple[str, str] | None) -> None:
        """Select a tuple key without QVariant's unreliable tuple comparison."""
        for index in range(combo.count()):
            if combo.itemData(index) == key:
                combo.setCurrentIndex(index)
                return
        combo.setCurrentIndex(0)

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
            # A stack is as wide as its widest page, hidden ones included, so
            # the belt editor set the width of the ladder editor too. Only the
            # page on show takes part in layout.
            for widget in page.values():
                policy = (
                    QSizePolicy.Policy.Preferred
                    if widget is page[kind]
                    else QSizePolicy.Policy.Ignored
                )
                widget.setSizePolicy(policy, policy)
            self.editor_stack.adjustSize()
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

    def _tag_selected_step(self) -> None:
        if self.current_ladder() and self._selected_step():
            self.step_irregular_requested.emit(
                self.current_ladder(),
                self._selected_step(),
                str(self.step_irregular.currentData() or ""),
            )

    def _show_step_tag(self, _row: int) -> None:
        """Show the selected step's own tag so re-tagging starts from it."""
        prop = self._store.get(self.current_ladder())
        step_id = self._selected_step()
        if not isinstance(prop, Ladder) or not step_id:
            return
        step = next((item for item in prop.steps if item.step_id == step_id), None)
        if step is not None:
            self.step_irregular.setCurrentIndex(
                max(0, self.step_irregular.findData(step.irregular))
            )

    def _extrapolate_chosen(self) -> None:
        if self.current_ladder():
            self.rung_count_requested.emit(self.current_ladder(), int(self.rung_count.value()))

    def _support_chosen(self, _index: int) -> None:
        if self.current_ladder():
            self.ladder_support_requested.emit(
                self.current_ladder(), str(self.ladder_support.currentData() or "none")
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
        self._update_motion_enablement()

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
        for control in (self.ladder_support, self.rung_count, self.extrapolate):
            control.setEnabled(isinstance(prop, Ladder))
        if not isinstance(prop, Ladder):
            return
        blocked = self.ladder_support.blockSignals(True)
        self.ladder_support.setCurrentIndex(max(0, self.ladder_support.findData(prop.support)))
        self.ladder_support.blockSignals(blocked)
        self.rung_count.setValue(0 if prop.pattern is None else prop.pattern.count)
        for step in prop.steps:
            clicks = sum(len(point.clicks) for point in step.points)
            solved = sum(point.xyz is not None for point in step.points)
            text = tr("{label} — {clicks} clicks; {solved}/{points} points in 3D").format(
                label=step.label, clicks=clicks, solved=solved, points=len(step.points)
            )
            if step.irregular:
                text = tr("{step} · {tag}").format(step=text, tag=irregular_text(step.irregular))
            self.steps.addItem(text)
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
