"""The drift field: milliseconds gained per hour, held and shown (D-184).

The value is the drift the mapping uses, in the same unit the session stores,
so what a person types is what is applied. Two decimals: 0.01 ms per hour is
finer than any clock pair a recording can measure.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDoubleSpinBox, QWidget

from avialsync.core.drift import describe_drift
from avialsync.ui.i18n import tr

__all__ = ["DriftSpinBox"]

#: Two seconds per hour either way: ten times what a free-running crystal does,
#: and still a bounded field.
DRIFT_LIMIT_MS_PER_HOUR = 360_000.0


class DriftSpinBox(QDoubleSpinBox):
    """A clock drift in ms/h, with the drift in frames or samples in its tooltip."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRange(-DRIFT_LIMIT_MS_PER_HOUR, DRIFT_LIMIT_MS_PER_HOUR)
        self.setDecimals(2)
        self.setSingleStep(1.0)
        self.setSuffix(tr(" ms/h"))
        self._rate_hz = 0.0
        self._samples = tr("samples")
        self._base_tip = ""
        self.valueChanged.connect(self._refresh_tip)

    def set_base_tooltip(self, text: str) -> None:
        """What the field is for; the current drift is appended to it."""
        self._base_tip = text
        self._refresh_tip()

    def set_sample_rate(self, rate_hz: float, samples: str) -> None:
        """Also give the drift in *samples* (``frames``) per hour at *rate_hz*."""
        self._rate_hz = max(0.0, float(rate_hz))
        self._samples = samples
        self._refresh_tip()

    def _refresh_tip(self, *_args: object) -> None:
        drift = describe_drift(self.value(), sample_rate_hz=self._rate_hz, samples=self._samples)
        tip = tr("Current drift: {drift}").format(drift=drift)
        self.setToolTip(f"{self._base_tip}\n{tip}" if self._base_tip else tip)
