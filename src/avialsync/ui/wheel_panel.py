"""The sidebar's Wheels section: review a wheel being placed, edit one placed (D-113).

**The one place a wheel's numbers are edited** (AGENTS rule 15). The Add Wheel
dialog asks for the first answers; after that the bar count, units, radius,
direction and ratio live here, beside the fit they produced -- the same shape as
a source's offset and drift in the panels above. The 3D view shows a wheel but
never edits one.

**Non-modal review.** While a wheel is being clicked the section shows what is
wanted next, the fit so far (click error, spacing, parallelism, the radius the
clicks imply), and Accept / Flip / Undo Click / Cancel. Nothing is committed
until Accept, and the videos stay usable the whole time (rule 11).

**Fields commit, keystrokes do not.** Every spin box has keyboard tracking off,
so typing ``120`` re-fits once rather than for 1, 12 and 120 -- each re-fit is
an undo step.

Widgets only: the section emits what the user asked for and shows what it is
given; :mod:`avialsync.ui.controllers.wheel_controller` does the work.
"""

from __future__ import annotations

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

from avialsync.core.wheel import Wheel, WheelFit, WheelSpec
from avialsync.ui.i18n import tr
from avialsync.ui.theme import set_bold
from avialsync.ui.wheel_dialogs import bar_count_spin, radius_spin, unit_items

__all__ = ["PlacementView", "WheelPanel", "describe_fit", "describe_encoder"]

#: Relative disagreement between a typed radius and the clicks' own, beyond
#: which the numbers say so in words: units, bar count, or calibration scale.
_RADIUS_WARNING = 0.07


@dataclass(frozen=True)
class PlacementView:
    """What the review section shows while a wheel is being clicked."""

    spec: WheelSpec
    frame: int
    #: What to click next, in the user's words.
    instruction: str
    #: The fit so far, or why there is none yet.
    summary: str
    can_undo: bool
    can_flip: bool
    can_accept: bool


def describe_fit(wheel_spec: WheelSpec, fit: WheelFit) -> str:
    """The fit in one paragraph: size, click error, and anything to check."""
    units = f" {wheel_spec.units}" if wheel_spec.units else ""
    geometry = fit.geometry
    parts = [
        tr("{bars} bars, radius {radius:.1f}{units}, width {width:.1f}{units}.").format(
            bars=geometry.bar_count,
            radius=geometry.radius,
            width=2 * geometry.half_width,
            units=units,
        ),
        tr("Clicks sit {median:.1f} px from the wheel (worst {worst:.1f} px).").format(
            median=fit.median_px, worst=fit.max_px
        ),
    ]
    if fit.spacing_deg:
        parts.append(
            tr("Bars within {spacing:.1f}° of their slots, {parallel:.1f}° of the axle.").format(
                spacing=max(abs(v) for v in fit.spacing_deg),
                parallel=max(fit.parallel_deg, default=0.0),
            )
        )
    if fit.implied_radius is not None and wheel_spec.radius:
        share = abs(fit.implied_radius - wheel_spec.radius) / wheel_spec.radius
        parts.append(
            tr("You entered {typed:.1f}{units}; the clicks imply {implied:.1f}{units}.").format(
                typed=wheel_spec.radius, implied=fit.implied_radius, units=units
            )
        )
        if share > _RADIUS_WARNING:
            parts.append(
                tr(
                    "That is {share:.0%} apart: check the 3D units, the bar count, and "
                    "the calibration's scale."
                ).format(share=share)
            )
    if fit.skipped:
        parts.append(
            tr(
                "The clicked bars are not neighbours ({slots}); check a bar was not stepped over."
            ).format(slots=", ".join(str(i) for i in sorted(fit.indices)))
        )
    if fit.ambiguous:
        parts.append(
            tr(
                "A mirrored wheel fits almost as well. Check the bars drawn over the "
                "video, and Flip if the wheel is on the wrong side."
            )
        )
    return " ".join(parts)


def describe_encoder(wheel: Wheel) -> str:
    """How the wheel turns, and how sure the direction is."""
    binding = wheel.binding
    if binding is None:
        return tr("Not turned by an encoder: drawn on frame {frame} only.").format(
            frame=wheel.frame
        )
    direction = tr("forward") if binding.sign > 0 else tr("reverse")
    if binding.measured:
        state = tr("direction {direction}, measured from {count} checks.").format(
            direction=direction, count=len(binding.checks)
        )
    else:
        state = tr(
            "direction {direction} is assumed. Verify on a frame a few turns away to measure it."
        ).format(direction=direction)
    return tr("Turned by {channel}; {state}").format(channel=binding.channel, state=state)


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
        form.addRow(tr("Direction"), self.direction)
        form.addRow(tr("Ratio"), self.ratio)
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

    def _spec_edited(self, panel: WheelPanel) -> None:
        bars, units, radius = self.spec.values()
        panel.spec_changed.emit(self.name, bars, units, radius)

    def _binding_edited(self, panel: WheelPanel) -> None:
        panel.binding_changed.emit(
            self.name, float(self.direction.currentData()), float(self.ratio.value())
        )

    def show_wheel(self, wheel: Wheel, checking: bool) -> None:
        self.spec.show(wheel.spec)
        self.fit.setText(describe_fit(wheel.spec, wheel.fit))
        self.encoder.setText(describe_encoder(wheel))
        binding = wheel.binding
        for widget in (self.direction, self.ratio, self.verify):
            widget.setEnabled(binding is not None)
        if binding is not None:
            _set_quietly(self.direction, "setCurrentIndex", 0 if binding.sign > 0 else 1)
            _set_quietly(self.ratio, "setValue", binding.ratio)
        self.verify.setText(tr("Click a Bar End…") if checking else tr("Verify Here"))


class WheelPanel(QGroupBox):
    """Every wheel in the session, and the one being placed."""

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
        form = QFormLayout()
        self._review_spec = _SpecFields(frame, form)
        review.addLayout(form)
        review.addWidget(self._summary)
        for spin in (self._review_spec.bars, self._review_spec.radius):
            spin.valueChanged.connect(lambda _v: self._placement_edited())
        self._review_spec.units.currentIndexChanged.connect(lambda _i: self._placement_edited())

        grid = QGridLayout()
        buttons: list[QPushButton] = []
        for text, description, signal in (
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
            (tr("Accept"), tr("Add this wheel; Undo removes it"), self.accept_requested),
            (
                tr("Cancel"),
                tr("Stop placing the wheel and discard the clicks"),
                self.cancel_requested,
            ),
        ):
            button = _button(text, description, frame)
            button.clicked.connect(signal)
            buttons.append(button)
        self._undo, self._flip, self._frame, self._accept, self._cancel = buttons
        grid.addWidget(self._undo, 0, 0)
        grid.addWidget(self._flip, 0, 1)
        grid.addWidget(self._frame, 1, 0, 1, 2)
        grid.addWidget(self._accept, 2, 0)
        grid.addWidget(self._cancel, 2, 1)
        review.addLayout(grid)
        return frame

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
            self._review_spec.show(view.spec)
            self._undo.setEnabled(view.can_undo)
            self._flip.setEnabled(view.can_flip)
            self._accept.setEnabled(view.can_accept)
            self._review.show()
        self._update_visibility()

    def set_wheels(self, wheels: list[Wheel], checking: str | None) -> None:
        """Show every placed wheel, rebuilding rows only when the set of names changed."""
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
            self._rows[wheel.name].show_wheel(wheel, checking == wheel.name)
        self._update_visibility()

    def _update_visibility(self) -> None:
        self.setVisible(bool(self._rows) or not self._review.isHidden())
