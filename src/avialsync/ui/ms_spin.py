"""A time field held in seconds and shown in milliseconds.

Alignment results are read in milliseconds (residuals, precision, worst pair),
so a setting typed as "0.001000 s" beside them made the reader convert units
to compare two numbers on one screen. The value stays in seconds, which is
what the worker, settings and tests exchange; only the text changes.
"""

from __future__ import annotations

from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QDoubleSpinBox, QWidget

from avialsync.ui.i18n import tr

__all__ = ["MillisecondSpinBox"]


class MillisecondSpinBox(QDoubleSpinBox):
    """Seconds in `value()`, milliseconds on screen."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Microsecond resolution in seconds is three decimals of milliseconds.
        self.setDecimals(6)
        self.setSingleStep(0.0001)
        self.setSuffix(tr(" ms"))

    def textFromValue(self, value: float) -> str:  # noqa: N802 - Qt override
        return self.locale().toString(value * 1000.0, "f", 3)

    def valueFromText(self, text: str) -> float:  # noqa: N802 - Qt override
        number, ok = self.locale().toDouble(self._number(text))
        return number / 1000.0 if ok else self.value()

    def validate(self, text: str, pos: int) -> tuple[QValidator.State, str, int]:
        number = self._number(text)
        if text == self.specialValueText() or number in ("", "-", "+"):
            return QValidator.State.Intermediate, text, pos
        _value, ok = self.locale().toDouble(number)
        return (QValidator.State.Acceptable if ok else QValidator.State.Invalid), text, pos

    def _number(self, text: str) -> str:
        return text.removesuffix(self.suffix()).removeprefix(self.prefix()).strip()
