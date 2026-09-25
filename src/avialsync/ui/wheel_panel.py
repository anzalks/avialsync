"""The Wheels inspector tab: review a wheel being placed, edit one placed (D-113).

**The one place a wheel's numbers are edited** (AGENTS rule 15). The Add Wheel
dialog asks for the first answers; after that the bar count, units, radius,
direction and ratio live here, beside the fit they produced. The 3D view shows a wheel but
never edits one.

**Non-modal review.** While a wheel is being clicked the tab shows what is
wanted next, the fit so far (click error, spacing, parallelism, the radius the
clicks imply), and Done Labelling / Flip / Undo Click / Discard Clicks. Done
Labelling is available from the moment bars 1 and 2 are labelled (D-122);
nothing is committed until it is pressed, and the videos stay usable (rule 11).

**Fields commit, keystrokes do not.** Every spin box has keyboard tracking off,
so typing ``120`` re-fits once rather than for 1, 12 and 120 -- each re-fit is
an undo step.

Widgets only: the tab emits what the user asked for and shows what it is
given; :mod:`avialsync.ui.controllers.wheel_controller` does the work.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.wheel import Wheel, WheelSpec
from avialsync.ui.bar_diameter_field import BarDiameterField
from avialsync.ui.i18n import tr
from avialsync.ui.theme import set_bold
from avialsync.ui.wheel_dialogs import bar_count_spin, radius_spin, unit_items
from avialsync.ui.wheel_text import describe_encoder, describe_fit

__all__ = ["PlacementView", "WheelPanel"]


@dataclass(frozen=True)
class PlacementView:
    """What the review section shows while a wheel is being clicked."""

    spec: WheelSpec
    frame: int
    #: What to click next, in the user's words.
    instruction: str
    #: The fit so far, or why there is none yet.
    summary: str
    active_step: int
    point_counts: tuple[int, ...]
    camera_count: int
    estimated_count: int
    can_next: bool
    can_undo: bool
    can_flip: bool
    can_accept: bool


def _button(text: str, description: str, parent: QWidget) -> QPushButton:
    button = QPushButton(text, parent)
    button.setAccessibleDescription(description)
    return button


def _wrapped(parent: QWidget) -> QLabel:
    label = QLabel(parent)
    label.setWordWrap(True)
    return label


def _units_combo(parent: QWidget) -> QComboBox:
    combo = QComboBox(parent)
    for label, unit in unit_items():
        combo.addItem(label, unit)
    combo.setAccessibleName(tr("3D units"))
    combo.setAccessibleDescription(tr("The units the calibration's 3D coordinates are in"))
    return combo


def _set_quietly(widget: QWidget, setter: str, value: object) -> None:
    """Show a value the controller decided without echoing it back as an edit."""
    blocked = widget.blockSignals(True)
    try:
        getattr(widget, setter)(value)
    finally:
        widget.blockSignals(blocked)


class _SpecFields:
    """Bar count, units and radius: shared by the review and every placed wheel."""

    def __init__(self, parent: QWidget, form: QFormLayout) -> None:
        self.bars = bar_count_spin(parent, 0)
        self.units = _units_combo(parent)
        self.radius = radius_spin(parent, 0.0, "")
        form.addRow(tr("Bars"), self.bars)
        form.addRow(tr("3D units"), self.units)
        form.addRow(tr("Radius"), self.radius)

    def show(self, spec: WheelSpec) -> None:
        _set_quietly(self.bars, "setValue", spec.bar_count)
        _set_quietly(self.units, "setCurrentIndex", max(0, self.units.findData(spec.units)))
        _set_quietly(self.radius, "setValue", spec.radius or 0.0)
        self.radius.setEnabled(bool(spec.units))
        self.radius.setSuffix(f" {spec.units}" if spec.units else "")

    def values(self) -> tuple[int, str, float]:
        units = str(self.units.currentData() or "")
        return int(self.bars.value()), units, float(self.radius.value()) if units else 0.0


class _WheelRow(QFrame):
    """One placed wheel: what it is, how well it fits, and its fields."""

    def __init__(self, panel: WheelPanel, name: str) -> None:
        super().__init__(panel)
        self.name = name
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        title = QLabel(name, self)
        set_bold(title)
        layout.addWidget(title)
        self.fit = _wrapped(self)
        self.encoder = _wrapped(self)
        layout.addWidget(self.fit)
        layout.addWidget(self.encoder)

        form = QFormLayout()
        self.spec = _SpecFields(self, form)
        self._build_encoder_fields()
        form.addRow(tr("Direction"), self.direction)
        form.addRow(tr("Ratio"), self.ratio)
        form.addRow(tr("Encoder offset"), self.offset)
        self.diameter = BarDiameterField(self)
        form.addRow(tr("Bar diameter"), self.diameter)
        layout.addLayout(form)

        buttons = QGridLayout()
        self.verify = _button(
            tr("Verify Here"),
            tr("Click any bar end in any camera on this frame to test the encoder"),
            self,
        )
        self.replace = _button(
            tr("Re-place"), tr("Click this wheel's bars again, keeping its settings"), self
        )
        self.remove = _button(tr("Remove"), tr("Remove this wheel; Undo brings it back"), self)
        buttons.addWidget(self.verify, 0, 0, 1, 2)
        buttons.addWidget(self.replace, 1, 0)
        buttons.addWidget(self.remove, 1, 1)
        layout.addLayout(buttons)

        self.verify.clicked.connect(lambda: panel.verify_requested.emit(name))
        self.replace.clicked.connect(lambda: panel.replace_requested.emit(name))
        self.remove.clicked.connect(lambda: panel.remove_requested.emit(name))
        for widget in (self.spec.bars, self.spec.radius):
            widget.valueChanged.connect(lambda _v: self._spec_edited(panel))
        self.spec.units.currentIndexChanged.connect(lambda _i: self._spec_edited(panel))
        self.direction.currentIndexChanged.connect(lambda _i: self._binding_edited(panel))
        self.ratio.valueChanged.connect(lambda _v: self._binding_edited(panel))
        self.offset.valueChanged.connect(
            lambda value: panel.encoder_offset_changed.emit(name, float(value))
        )
        self.diameter.previewed.connect(lambda v: panel.bar_diameter_previewed.emit(name, v))
        self.diameter.committed.connect(lambda v: panel.bar_diameter_changed.emit(name, v))

    def _build_encoder_fields(self) -> None:
        """Direction, ratio and offset of the encoder that turns this wheel."""
        self.direction = QComboBox(self)
        self.direction.addItem(tr("Forward"), 1.0)
        self.direction.addItem(tr("Reverse"), -1.0)
        self.direction.setAccessibleName(tr("Encoder direction"))
        self.direction.setAccessibleDescription(
            tr("Which way the wheel turns as the encoder angle grows; Verify measures it")
        )
        self.ratio = QDoubleSpinBox(self)
        self.ratio.setDecimals(4)
        self.ratio.setRange(0.0001, 1000.0)
        self.ratio.setKeyboardTracking(False)
        self.ratio.setAccessibleName(tr("Encoder ratio"))
        self.ratio.setAccessibleDescription(
            tr("Wheel turns per encoder turn; 1 for an encoder on the axle")
        )
        # The encoder source's own offset, the one in its Sources row: a
        # constant encoder-to-camera latency is corrected there, so its plots
        # move with the wheel rather than disagreeing with it (rule 1).
        self.offset = QDoubleSpinBox(self)
        self.offset.setDecimals(3)
        self.offset.setRange(-3600.0, 3600.0)
        self.offset.setSingleStep(0.01)
        self.offset.setSuffix(" s")
        self.offset.setKeyboardTracking(False)
        self.offset.setAccessibleName(tr("Encoder offset"))
        self.offset.setAccessibleDescription(
            tr(
                "Shift the encoder against the video, for a constant encoder-to-camera "
                "latency. The same offset as the encoder's row in Sources, so its plots move too"
            )
        )
        self.offset.setToolTip(self.offset.accessibleDescription())

    def _spec_edited(self, panel: WheelPanel) -> None:
        bars, units, radius = self.spec.values()
        panel.spec_changed.emit(self.name, bars, units, radius)

    def _binding_edited(self, panel: WheelPanel) -> None:
        panel.binding_changed.emit(
            self.name, float(self.direction.currentData()), float(self.ratio.value())
        )

    def show_wheel(self, wheel: Wheel, checking: bool, offset: float | None) -> None:
        self.spec.show(wheel.spec)
        self.fit.setText(describe_fit(wheel.spec, wheel.fit, wheel.clicks))
        self.encoder.setText(describe_encoder(wheel))
        binding = wheel.binding
        for widget in (self.direction, self.ratio, self.verify):
            widget.setEnabled(binding is not None)
        self.verify.setToolTip(tr("Click a bar end to test the encoder direction"))
        self.offset.setEnabled(offset is not None)
        if offset is not None:
            _set_quietly(self.offset, "setValue", offset)
        if binding is not None:
            _set_quietly(self.direction, "setCurrentIndex", 0 if binding.sign > 0 else 1)
            _set_quietly(self.ratio, "setValue", binding.ratio)
        self.verify.setText(tr("Click a Bar End…") if checking else tr("Verify Here"))
        geometry = wheel.geometry
        # Up to the gap between neighbouring bar centres: bars thicker than
        # that would overlap, so no real wheel is past the end of the slider.
        spacing = 2.0 * geometry.radius * math.sin(math.pi / geometry.bar_count)
        self.diameter.show_value(wheel.bar_diameter, spacing, wheel.spec.units)


class WheelPanel(QGroupBox):
    """Every wheel in the session, and the one being placed."""

    point_requested = Signal(int)
    next_end_requested = Signal()
    undo_click_requested = Signal()
    flip_requested = Signal()
    go_to_frame_requested = Signal()
    accept_requested = Signal()
    cancel_requested = Signal()
    #: ``(bars, units, radius)`` of the wheel being placed; radius 0 is "from the clicks".
    placement_spec_changed = Signal(int, str, float)
    #: ``(name, bars, units, radius)`` of a placed wheel.
    spec_changed = Signal(str, int, str, float)
    #: ``(name, sign, ratio)``.
    binding_changed = Signal(str, float, float)
    #: ``(name, offset_s)`` for the encoder source that turns wheel *name*.
    encoder_offset_changed = Signal(str, float)
    #: ``(name, diameter)`` while its slider is dragged: draw it, record nothing.
    bar_diameter_previewed = Signal(str, float)
    #: ``(name, diameter)`` to keep; 0 is "not set".
    bar_diameter_changed = Signal(str, float)
    verify_requested = Signal(str)
    replace_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(tr("Wheels"), parent)
        self.setAccessibleName(tr("Wheels"))
        self.setAccessibleDescription(tr("Wheels placed with Add Wheel, and their settings"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self._review = self._build_review()
        layout.addWidget(self._review)

        self._rows_layout = QVBoxLayout()
        layout.addLayout(self._rows_layout)
        self._rows: dict[str, _WheelRow] = {}

        self._review.hide()
        self.hide()

    def _build_review(self) -> QFrame:
        """The review shown while a wheel is being clicked: what next, the fit, the choices."""
        frame = QFrame(self)
        frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)
        review = QVBoxLayout(frame)
        review.setContentsMargins(5, 5, 5, 5)
        self._review_title = QLabel(frame)
        set_bold(self._review_title)
        self._instruction = _wrapped(frame)
        self._summary = _wrapped(frame)
        review.addWidget(self._review_title)
        review.addWidget(self._instruction)
        review.addLayout(self._build_points(frame))
        review.addLayout(self._build_actions(frame))
        guide = _wrapped(frame)
        guide.setText(
            tr(
                "Select any point to work camera by camera. Two camera clicks locate it in 3D. "
                "Rings are clicks; dashed diamonds are projected estimates."
            )
        )
        review.addWidget(guide)
        self._evidence = _wrapped(frame)
        review.addWidget(self._evidence)
        form = QFormLayout()
        self._review_spec = _SpecFields(frame, form)
        for spin in (self._review_spec.bars, self._review_spec.radius):
            spin.valueChanged.connect(lambda _v: self._placement_edited())
        self._review_spec.units.currentIndexChanged.connect(lambda _i: self._placement_edited())
        review.addLayout(form)
        review.addWidget(self._summary)
        return frame

    def _build_points(self, frame: QFrame) -> QGridLayout:
        """1A…3B: pick which end the next camera click places, and see its count."""
        points = QGridLayout()
        self._point_buttons: list[QPushButton] = []
        for step in range(6):
            label = f"{step // 2 + 1}{'AB'[step % 2]}"
            description = tr("Select point {point} for the next camera click").format(point=label)
            button = _button(label, description, frame)
            button.setCheckable(True)
            button.setAccessibleName(tr("Select wheel point {point}").format(point=label))
            button.clicked.connect(lambda _checked, index=step: self.point_requested.emit(index))
            points.addWidget(button, step // 2, step % 2)
            self._point_buttons.append(button)
        return points

    def _build_actions(self, frame: QFrame) -> QGridLayout:
        """Next Point, Undo Click, Flip Side, Go to Frame, Done Labelling, Discard Clicks."""
        grid = QGridLayout()
        buttons: list[QPushButton] = []
        for text, description, signal in (
            (tr("Next Point"), tr("Select the next wheel bar endpoint"), self.next_end_requested),
            (tr("Undo Click"), tr("Take back the last click"), self.undo_click_requested),
            (
                tr("Flip Side"),
                tr("Use the mirrored wheel, with its axle on the other side"),
                self.flip_requested,
            ),
            (
                tr("Go to Frame"),
                tr("Return to the frame the bars are being clicked on"),
                self.go_to_frame_requested,
            ),
            (
                tr("Done Labelling"),
                tr("Save this wheel and finish labelling; Undo removes it"),
                self.accept_requested,
            ),
            (
                tr("Discard Clicks"),
                tr("Stop placing the wheel and discard the clicks"),
                self.cancel_requested,
            ),
        ):
            button = _button(text, description, frame)
            button.clicked.connect(signal)
            buttons.append(button)
        self._next, self._undo, self._flip, self._frame, self._accept, self._cancel = buttons
        grid.addWidget(self._next, 0, 0)
        grid.addWidget(self._undo, 0, 1)
        grid.addWidget(self._flip, 1, 0)
        grid.addWidget(self._frame, 1, 1)
        grid.addWidget(self._accept, 2, 0)
        grid.addWidget(self._cancel, 2, 1)
        return grid

    def _placement_edited(self) -> None:
        self.placement_spec_changed.emit(*self._review_spec.values())

    def show_placement(self, view: PlacementView | None) -> None:
        """Show the review for a wheel being placed, or hide it (None)."""
        if view is None:
            self._review.hide()
        else:
            self._review_title.setText(
                tr("Placing {name} on frame {frame}").format(name=view.spec.name, frame=view.frame)
            )
            self._instruction.setText(view.instruction)
            self._summary.setText(view.summary)
            self._evidence.setText(
                tr("{count} projected marks are estimates; only camera clicks are saved.").format(
                    count=view.estimated_count
                )
                if view.estimated_count
                else tr("A second camera click will project the point into missing views.")
            )
            for index, button in enumerate(self._point_buttons):
                label = f"{index // 2 + 1}{'AB'[index % 2]}"
                button.setText(f"{label}  {view.point_counts[index]}/{view.camera_count}")
                blocked = button.blockSignals(True)
                button.setChecked(index == view.active_step)
                button.blockSignals(blocked)
            self._next.setEnabled(view.can_next)
            self._review_spec.show(view.spec)
            self._undo.setEnabled(view.can_undo)
            self._flip.setEnabled(view.can_flip)
            self._accept.setEnabled(view.can_accept)
            self._accept.setToolTip(
                tr("Save this wheel and finish labelling as one undo step")
                if view.can_accept
                else view.summary
            )
            self._review.show()
        self._update_visibility()

    def set_wheels(
        self,
        wheels: list[Wheel],
        checking: str | None,
        offsets: Mapping[str, float] | None = None,
    ) -> None:
        """Show every placed wheel, rebuilding rows only when the set of names changed.

        *offsets* maps a wheel's name to its encoder source's offset, when that
        source is loaded; a wheel without one has its offset field greyed.
        """
        names = [wheel.name for wheel in wheels]
        if set(names) != set(self._rows):
            for row in self._rows.values():
                self._rows_layout.removeWidget(row)
                row.deleteLater()
            self._rows = {}
            for name in names:
                row = _WheelRow(self, name)
                self._rows_layout.addWidget(row)
                self._rows[name] = row
        for wheel in wheels:
            self._rows[wheel.name].show_wheel(
                wheel, checking == wheel.name, (offsets or {}).get(wheel.name)
            )
        self._update_visibility()

    def _update_visibility(self) -> None:
        self.setVisible(bool(self._rows) or not self._review.isHidden())
