"""Build a proposed rotary transfer from saved wheel observations off the UI thread."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.errors import RotaryCalibrationError
from avialsync.core.rotary_calibration import RotaryObservation, fit_periodic_rotary
from avialsync.core.wheel import EncoderBinding

logger = logging.getLogger(__name__)

__all__ = ["RotaryCalibrationWorker"]


class RotaryCalibrationWorker(QObject):
    """Fit one rotation proposal from immutable wheel evidence."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        binding: EncoderBinding,
        bar_count: int,
        observations: Sequence[RotaryObservation],
        harmonic_orders: Sequence[int],
    ) -> None:
        super().__init__()
        self._binding = binding
        self._bar_count = int(bar_count)
        self._observations = tuple(observations)
        self._harmonic_orders = tuple(harmonic_orders)

    @Slot()
    def run(self) -> None:
        """Fit the generic transfer from saved visual alignments."""
        try:
            initial_model = self._binding.motion_model
            proposal = fit_periodic_rotary(
                self._observations,
                self._binding.reference_angle,
                360.0 / self._bar_count,
                initial_gain=self._binding.ratio,
                initial_sign=self._binding.sign,
                harmonic_orders=self._harmonic_orders,
                initial_model=initial_model,
            )
        except (RotaryCalibrationError, ValueError, ArithmeticError) as error:
            logger.warning("Rotary calibration fit failed", exc_info=True)
            self.error.emit(str(error))
            return
        self.finished.emit(proposal)
