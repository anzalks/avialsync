"""The Wheels tab's bar-diameter control: a slider to match by eye, a box to type (D-128).

A bar's diameter is not something the clicks measure -- they are on the bar's
centre line -- so it is set by sliding until the drawn bars are as thick as the
real ones in the video. Dragging only previews: the window draws the value
without recording anything, as Fix Tracker's drag does, so a drag is neither a
stream of undo steps nor a file write per pixel. Releasing the slider, or
typing a value, commits it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QSlider, QWidget

from avialsync.ui.i18n import tr

__all__ = ["BarDiameterField"]

#: Slider resolution across 0 .. the bar spacing.
_STEPS = 500


class BarDiameterField(QWidget):
    """A slider and a number for one wheel's bar diameter, in the calibration's units."""

    #: A value to draw while the slider is dragged; nothing is committed.
    previewed = Signal(float)
    #: A value to keep: slider released, arrow keys, or a typed number.
    committed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._maximum = 1.0
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, _STEPS)
        # Off, so valueChanged means a finished gesture; sliderMoved previews.
        self.slider.setTracking(False)
        self.slider.setAccessibleName(tr("Bar diameter slider"))
        self.slider.setAccessibleDescription(
            tr("Slide until the drawn bars are as thick as the real ones in the video")
        )
        self.spin = QDoubleSpinBox(self)
        self.spin.setDecimals(2)
        self.spin.setKeyboardTracking(False)
        self.spin.setSpecialValueText(tr("Not set"))
        self.spin.setAccessibleName(tr("Bar diameter"))
        self.spin.setAccessibleDescription(
            tr("Each bar's diameter in the 3D units; drawn over the video and in 3D")
        )
        row.addWidget(self.slider, 1)
        row.addWidget(self.spin)
        self.slider.sliderMoved.connect(self._preview)
        self.slider.valueChanged.connect(lambda step: self._commit(self._value_of(step)))
        self.spin.valueChanged.connect(self._commit)

    def show_value(self, value: float | None, maximum: float, units: str) -> None:
        """Show *value* on a scale up to *maximum*, the gap between bar centres.

        Ignored while the slider is held: the preview it drives redraws the
        tab, and resetting the slider under the pointer would commit 0 on
        release.
        """
        if self.slider.isSliderDown():
            return
        self._maximum = max(maximum, 1e-9)
        for widget in (self.slider, self.spin):
            widget.blockSignals(True)
        try:
            self.spin.setRange(0.0, self._maximum)
            self.spin.setSingleStep(self._maximum / 100.0)
            self.spin.setSuffix(f" {units}" if units else "")
            self.spin.setValue(value or 0.0)
            self.slider.setValue(round((value or 0.0) / self._maximum * _STEPS))
        finally:
            for widget in (self.slider, self.spin):
                widget.blockSignals(False)

    def _preview(self, step: int) -> None:
        value = self._value_of(step)
        blocked = self.spin.blockSignals(True)
        try:
            self.spin.setValue(value)
        finally:
            self.spin.blockSignals(blocked)
        self.previewed.emit(value)

    def _value_of(self, step: int) -> float:
        return step / _STEPS * self._maximum

    def _commit(self, value: float) -> None:
        self.committed.emit(float(value))
