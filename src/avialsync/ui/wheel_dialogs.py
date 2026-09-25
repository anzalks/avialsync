"""The one question Add Wheel asks before the clicking starts (D-113).

A dialog the user explicitly asked for by choosing Add Wheel…, the case AGENTS
rule 11 allows a modal for. It collects what the clicks cannot supply:

* **the bar count**, without which two or three neighbouring bars cannot give
  the radius -- their curvature is about the size of the click error;
* **the units** the calibration's 3D coordinates are in, and optionally **the
  radius** measured on the rig in those units. anipose records no units, and a
  radius in centimetres against a calibration in millimetres is a wheel a tenth
  the size, so the radius field is only live once the units are declared;
* **the encoder channel** that turns the wheel, pre-selected when the session's
  plugin declared one (:class:`~avialsync.core.source.RotaryHint`), and
  "none" otherwise -- a wheel with no encoder is drawn on its own frame only.

Everything here can be changed afterwards in the Wheels inspector tab; this
is the first answer, not the only one.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.settings_schema import Setting, setting_for
from avialsync.core.source import RotaryHint
from avialsync.core.wheel import MIN_BAR_COUNT, UNITS, WheelSpec
from avialsync.ui.i18n import tr
from avialsync.ui.preferences_dialog import read_setting, write_setting

__all__ = [
    "WheelSetup",
    "ask_wheel_setup",
    "unit_items",
    "radius_spin",
    "bar_count_spin",
]

#: A wheel's name becomes a file name, ``<name>.wheel.toml``.
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")
_MAX_BARS = 720


def _setting(key: str) -> Setting:
    setting = setting_for(key)
    assert setting is not None
    return setting


_BAR_SETTING = _setting("wheel/bar_count")
_UNITS_SETTING = _setting("wheel/units")
_RADIUS_SETTING = _setting("wheel/radius")


def _saved_details() -> tuple[int, str, float] | None:
    """Return reusable setup only when its values are valid together."""
    bars = int(read_setting(_BAR_SETTING))
    units = str(read_setting(_UNITS_SETTING))
    radius = float(read_setting(_RADIUS_SETTING))
    if MIN_BAR_COUNT <= bars <= _MAX_BARS and units in ("", *UNITS):
        return bars, units, radius if units and radius > 0 else 0.0
    return None


def _write_details(bars: int, units: str, radius: float) -> None:
    """Save or forget the reusable values through the declared settings."""
    write_setting(_BAR_SETTING, bars)
    write_setting(_UNITS_SETTING, units)
    write_setting(_RADIUS_SETTING, radius)


@dataclass(frozen=True)
class WheelSetup:
    """What the dialog collected."""

    spec: WheelSpec
    #: ``(source id, channel id)`` of the encoder, or None for no encoder.
    channel: tuple[str, str] | None


def unit_items() -> list[tuple[str, str]]:
    """``(label, unit)`` for a units combo box, "not known" first."""
    return [(tr("Not known"), ""), *((unit, unit) for unit in UNITS)]


def bar_count_spin(parent: QWidget, value: int) -> QSpinBox:
    """A bar-count field; 0 shows as a prompt rather than as a number."""
    spin = QSpinBox(parent)
    spin.setRange(0, _MAX_BARS)
    spin.setSpecialValueText(tr("Enter the count"))
    spin.setValue(value)
    spin.setKeyboardTracking(False)
    spin.setAccessibleName(tr("Number of bars"))
    spin.setAccessibleDescription(tr("How many bars the whole wheel has, counted once on the rig"))
    return spin


def radius_spin(parent: QWidget, value: float, units: str) -> QDoubleSpinBox:
    """A radius field; 0 shows as "From the clicks", the default."""
    spin = QDoubleSpinBox(parent)
    spin.setDecimals(2)
    spin.setRange(0.0, 1.0e6)
    spin.setSpecialValueText(tr("From the clicks"))
    spin.setValue(value)
    spin.setKeyboardTracking(False)
    spin.setSuffix(f" {units}" if units else "")
    spin.setAccessibleName(tr("Radius to bar centres"))
    spin.setAccessibleDescription(
        tr(
            "Distance from the axle to the middle of a bar, measured on the rig. "
            "Leave it at From the clicks to have it measured from the bar spacing."
        )
    )
    return spin


class _WheelSetupDialog(QDialog):
    def __init__(
        self,
        taken: Collection[str],
        hint: RotaryHint | None,
        channels: Sequence[tuple[str, str, str]],
        parent: QWidget | None,
    ) -> None:
        super().__init__(parent)
        self._taken = {name.lower() for name in taken}
        self._hint = hint
        self._saved = _saved_details()
        self.setWindowTitle(tr("Add Wheel"))
        self.setAccessibleName(tr("Describe the wheel to place"))
        self.setAccessibleDescription(
            tr("Name, bar count, units, radius and encoder of the wheel you are about to click")
        )
        layout = QVBoxLayout(self)
        intro = QLabel(
            tr(
                "Click both ends of two or three neighbouring bars on the current frame. "
                "Each end needs clicks in at least two calibrated cameras; the third view "
                "can show a projected estimate. Use the point buttons to work across cameras "
                "or finish one camera first. Keep the same end as A on every bar. The rest "
                "of the wheel is generated from the clicks and the bar count."
            ),
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        layout.addLayout(self._build_form(hint, channels))
        self._build_saved_setup(layout, hint)

        self.problem = QLabel(self)
        self.problem.setWordWrap(True)
        self.problem.setAccessibleName(tr("Why the wheel cannot be placed yet"))
        layout.addWidget(self.problem)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setText(tr("Start Clicking"))
            ok.setAccessibleDescription(tr("Close this and click the bars in the videos"))
        cancel = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel is not None:
            cancel.setAccessibleDescription(tr("Do not add a wheel"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.name_edit.textChanged.connect(self._validate)
        self.bars.valueChanged.connect(self._validate)
        self.units.currentIndexChanged.connect(self._on_units)
        self._on_units()

    def _build_saved_setup(self, layout: QVBoxLayout, hint: RotaryHint | None) -> None:
        """Say where the values came from, and offer to remember or forget them."""
        self.saved_note = QLabel(self)
        self.saved_note.setWordWrap(True)
        self.saved_note.setText(
            tr("Saved setup loaded. Check its units against this recording.")
            if self._saved is not None and hint is None
            else tr("This recording supplied wheel details; check them before clicking.")
            if hint is not None
            else tr(
                "Only the bar count, units and radius can be remembered. "
                "Clicks stay with the recording."
            )
        )
        layout.addWidget(self.saved_note)
        self.remember = QCheckBox(
            tr("Update saved setup for future wheels")
            if self._saved is not None
            else tr("Remember this setup for future wheels"),
            self,
        )
        self.remember.setChecked(self._saved is None and hint is None)
        self.remember.setAccessibleDescription(
            tr("Save bar count, units and radius in AvialSync preferences after starting clicks")
        )
        layout.addWidget(self.remember)
        self.forget = QPushButton(tr("Forget saved setup"), self)
        self.forget.setAccessibleDescription(
            tr("Clear reusable wheel details; placed wheels in recordings are unaffected")
        )
        self.forget.setVisible(self._saved is not None)
        self.forget.clicked.connect(self._forget_saved)
        layout.addWidget(self.forget)

    def _build_form(
        self, hint: RotaryHint | None, channels: Sequence[tuple[str, str, str]]
    ) -> QFormLayout:
        form = QFormLayout()
        self.name_edit = QLineEdit(self._suggest_name(), self)
        self.name_edit.setAccessibleName(tr("Wheel name"))
        self.name_edit.setAccessibleDescription(
            tr("Letters, digits, underscore and hyphen; the wheel's file is named after it")
        )
        form.addRow(tr("Name"), self.name_edit)

        saved = self._saved if hint is None else None
        self.bars = bar_count_spin(
            self, hint.bar_count if hint is not None else saved[0] if saved else 0
        )
        form.addRow(tr("Bars on the wheel"), self.bars)

        self.units = QComboBox(self)
        for label, unit in unit_items():
            self.units.addItem(label, unit)
        self.units.setCurrentIndex(
            max(0, self.units.findData(hint.units if hint else saved[1] if saved else ""))
        )
        self.units.setAccessibleName(tr("3D units"))
        self.units.setAccessibleDescription(
            tr("The units the calibration's 3D coordinates are in; anipose does not record them")
        )
        form.addRow(tr("3D units"), self.units)

        self.radius = radius_spin(
            self, hint.radius if hint is not None else saved[2] if saved else 0.0, ""
        )
        form.addRow(tr("Radius to bar centres"), self.radius)

        form.addRow(tr("Turned by"), self._build_encoder(hint, channels))
        return form

    def _build_encoder(
        self, hint: RotaryHint | None, channels: Sequence[tuple[str, str, str]]
    ) -> QComboBox:
        """The encoder choice, pre-selected when the session declared its wheel."""
        self.encoder = QComboBox(self)
        self.encoder.addItem(tr("None: the wheel stays on the frame it was placed on"), None)
        for source, channel, label in channels:
            self.encoder.addItem(label, (source, channel))
        self.encoder.setAccessibleName(tr("Encoder channel"))
        self.encoder.setAccessibleDescription(
            tr("The cumulative angle, in degrees, that turns the wheel from frame to frame")
        )
        if hint is not None:
            for index in range(self.encoder.count()):
                data = self.encoder.itemData(index)
                if (
                    data is not None
                    and data[1] == hint.channel
                    and (hint.source is None or str(hint.source) == data[0])
                ):
                    self.encoder.setCurrentIndex(index)
                    break
        return self.encoder

    def _suggest_name(self) -> str:
        name, index = "wheel", 2
        while name.lower() in self._taken:
            name, index = f"wheel{index}", index + 1
        return name

    def _forget_saved(self) -> None:
        _write_details(0, "", 0.0)
        self._saved = None
        hint = self._hint
        self.bars.setValue(hint.bar_count if hint is not None else 0)
        self.units.setCurrentIndex(max(0, self.units.findData(hint.units if hint else "")))
        self.radius.setValue(hint.radius if hint is not None else 0.0)
        self.remember.setText(tr("Remember this setup for future wheels"))
        self.remember.setChecked(False)
        self.forget.hide()
        self.saved_note.setText(
            tr("Saved setup forgotten. Placed wheels in recordings are unaffected.")
        )

    def accept(self) -> None:
        """Commit the optional reusable setup when clicking starts."""
        if self.remember.isChecked() and self.bars.value() >= MIN_BAR_COUNT:
            units = str(self.units.currentData() or "")
            _write_details(self.bars.value(), units, self.radius.value() if units else 0.0)
        super().accept()

    def _on_units(self) -> None:
        units = str(self.units.currentData() or "")
        self.radius.setEnabled(bool(units))
        self.radius.setSuffix(f" {units}" if units else "")
        self.radius.setToolTip(
            ""
            if units
            else tr("Declare the 3D units first: a radius in the wrong units is silently wrong")
        )
        self._validate()

    def _validate(self) -> None:
        name = self.name_edit.text().strip()
        problem = ""
        if not name:
            problem = tr("Enter a name.")
        elif not _NAME_PATTERN.match(name):
            problem = tr("Use letters, digits, underscore or hyphen only.")
        elif name.lower() in self._taken:
            problem = tr("A wheel already uses this name.")
        elif self.bars.value() < MIN_BAR_COUNT:
            problem = tr("Enter how many bars the whole wheel has (at least 3).")
        self.problem.setText(problem)
        self.problem.setVisible(bool(problem))
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setEnabled(not problem)

    def setup(self) -> WheelSetup:
        units = str(self.units.currentData() or "")
        radius = self.radius.value() if units and self.radius.value() > 0 else None
        spec = WheelSpec(
            name=self.name_edit.text().strip(),
            bar_count=int(self.bars.value()),
            radius=radius,
            units=units,
        )
        data = self.encoder.currentData()
        channel = (str(data[0]), str(data[1])) if data is not None else None
        return WheelSetup(spec=spec, channel=channel)


def ask_wheel_setup(
    parent: QWidget | None,
    taken: Collection[str],
    hint: RotaryHint | None,
    channels: Sequence[tuple[str, str, str]],
) -> WheelSetup | None:
    """Ask what the wheel is; None when cancelled.

    *channels* lists ``(source id, channel id, label)`` for every loaded
    time-series channel the encoder could be.
    """
    dialog = _WheelSetupDialog(taken, hint, channels, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.setup()
