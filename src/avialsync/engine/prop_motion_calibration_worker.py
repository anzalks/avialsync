"""Fit a belt or ball motion correction from saved video checks off the UI thread."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.calibration import CameraModel
from avialsync.core.errors import PropMotionCalibrationError
from avialsync.core.physical_props import BallProp, BeltProp
from avialsync.core.prop_motion_calibration import fit_ball_motion, fit_belt_motion

logger = logging.getLogger(__name__)

__all__ = ["PropMotionCalibrationWorker"]


class PropMotionCalibrationWorker(QObject):
    """Build one reviewable moving-prop correction from frozen evidence."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, prop: BeltProp | BallProp, cameras: Mapping[str, CameraModel]) -> None:
        super().__init__()
        self._prop = prop
        self._cameras = dict(cameras)

    @Slot()
    def run(self) -> None:
        """Fit without touching Qt widgets or a mutable prop store."""
        try:
            proposal = (
                fit_belt_motion(self._prop, self._cameras)
                if isinstance(self._prop, BeltProp)
                else fit_ball_motion(self._prop, self._cameras)
            )
        except (PropMotionCalibrationError, ValueError, ArithmeticError) as error:
            logger.warning("Physical-prop motion calibration fit failed", exc_info=True)
            self.error.emit(str(error))
            return
        self.finished.emit(proposal)
