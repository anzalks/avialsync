"""Generating a wheel from its clicked bar ends, off the UI thread (D-113, D-123).

One fit is 10-20 ms, but a labelled wheel may need several -- a third bar left
out, a typed radius in the wrong units -- which reached 55 ms, past the 30 ms a
UI-thread step may take (rule 3). So every fit runs here, registered through
``MainWindow._run_job`` like any other job (rule 11), and the Wheels tab says
"Generating wheel…" while it does.

It is handed frozen values only -- the spec, the clicks, the camera models --
so nothing the UI owns is touched from this thread.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.calibration import CameraModel
from avialsync.core.errors import CalibrationError, WheelFitError
from avialsync.core.wheel import EndClick, WheelSpec
from avialsync.core.wheel_fit import fit_labelled

logger = logging.getLogger(__name__)

__all__ = ["WheelFitWorker"]


class WheelFitWorker(QObject):
    """Fit one wheel from its clicks; emit the :class:`LabelledFit` or why none exists."""

    #: The :class:`~avialsync.core.wheel_fit.LabelledFit`.
    finished = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        spec: WheelSpec,
        clicks: Sequence[EndClick],
        cameras: Mapping[str, CameraModel],
        flipped: bool,
    ) -> None:
        super().__init__()
        self._spec = spec
        self._clicks = tuple(clicks)
        self._cameras = dict(cameras)
        self._flipped = flipped

    @Slot()
    def run(self) -> None:
        try:
            labelled = fit_labelled(self._spec, self._clicks, self._cameras, flipped=self._flipped)
        except WheelFitError as error:
            # The ordinary answer while too few ends are clicked yet.
            self.error.emit(str(error))
            return
        except (CalibrationError, ValueError, ArithmeticError) as error:
            # Anything else a fit can raise must still end the job with an
            # answer: a silent worker would leave the placement "generating".
            logger.warning("Wheel fit failed", exc_info=True)
            self.error.emit(str(error))
            return
        self.finished.emit(labelled)
