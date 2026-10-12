"""Build a proposed rotary transfer from saved wheel observations off the UI thread."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.calibration import CameraModel
from avialsync.core.errors import CalibrationError, RotaryCalibrationError
from avialsync.core.rotary_calibration import fit_periodic_rotary
from avialsync.core.wheel import EncoderBinding, WheelCheck, WheelGeometry
from avialsync.core.wheel_check import motion_observations

logger = logging.getLogger(__name__)

__all__ = ["RotaryCalibrationWorker"]


class RotaryCalibrationWorker(QObject):
    """Fit one rotation proposal from immutable wheel evidence."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        geometry: WheelGeometry,
        binding: EncoderBinding,
        cameras: Mapping[str, CameraModel],
        checks: Sequence[WheelCheck],
        harmonic_orders: Sequence[int],
    ) -> None:
        super().__init__()
        self._geometry = geometry
        self._binding = binding
        self._cameras = dict(cameras)
        self._checks = tuple(checks)
        self._harmonic_orders = tuple(harmonic_orders)

    @Slot()
    def run(self) -> None:
        """Turn visible-wheel clicks into a generic proposed transfer."""
        try:
            observations = motion_observations(self._geometry, self._cameras, self._checks)
            initial_model = self._binding.motion_model
            proposal = fit_periodic_rotary(
                observations,
                self._binding.reference_angle,
                360.0 / self._geometry.bar_count,
                initial_gain=self._binding.ratio,
                initial_sign=self._binding.sign,
                harmonic_orders=self._harmonic_orders,
                initial_model=initial_model,
            )
        except (CalibrationError, RotaryCalibrationError, ValueError, ArithmeticError) as error:
            logger.warning("Rotary calibration fit failed", exc_info=True)
            self.error.emit(str(error))
            return
        self.finished.emit(proposal)
