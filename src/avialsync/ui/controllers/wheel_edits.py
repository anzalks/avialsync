"""Changing a placed wheel from the Wheels tab: its numbers, its encoder, or removing it (D-113).

Split from :mod:`avialsync.ui.controllers.wheel_controller`, which places and
verifies wheels. Every change here is one
:class:`~avialsync.core.commands.SetWheelCommand` (rule 14), and a changed bar
count, unit or radius re-fits from the wheel's own clicks -- never new ones --
in the background, like placing one.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread

from avialsync.core.commands import SetWheelCommand
from avialsync.core.errors import WheelFitError
from avialsync.core.wheel import WheelSpec
from avialsync.core.wheel_check import settle_sign
from avialsync.core.wheel_fit import LabelledFit
from avialsync.engine.wheel_fit_worker import WheelFitWorker
from avialsync.ui.controllers import calibration_controller as calibration
from avialsync.ui.controllers import wheel_display as display
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

__all__ = ["edit_binding", "edit_encoder_offset", "edit_spec", "remove", "spec_from"]


def spec_from(name: str, bars: int, units: str, radius: float) -> WheelSpec:
    """The spec the tab's fields describe; a radius without units is "from the clicks"."""
    return WheelSpec(name, int(bars), radius if units and radius > 0 else None, units)


def edit_spec(window: MainWindow, name: str, bars: int, units: str, radius: float) -> None:
    """Re-fit *name* from its own clicks with a changed bar count, units or radius.

    The fit runs in the background (rule 3, D-123). Edits faster than the fit
    are not queued: the latest spec asked for is the one applied.
    """
    wheel = window.wheels.get(name)
    if wheel is None:
        return
    spec = spec_from(name, bars, units, radius)
    if spec == wheel.spec:
        return
    calibration.calibration_quietly(window)
    cameras = display.camera_models(window)
    window._wheel_refits[name] = spec
    worker = WheelFitWorker(spec, wheel.clicks, cameras, wheel.flipped)

    def done(labelled: LabelledFit | None, problem: str = "") -> None:
        if window._wheel_refits.get(name) != spec:
            return
        del window._wheel_refits[name]
        current = window.wheels.get(name)
        if current is None:
            return
        if labelled is None:
            window.report_failure(
                WheelFitError(problem), doing=tr("Wheel {name} was not re-fitted").format(name=name)
            )
            display.refresh(window)
            return
        binding = current.binding
        if binding is not None and binding.checks:
            binding = settle_sign(labelled.fit.geometry, binding, cameras)[0]
        changed = dataclasses.replace(current, spec=spec, fit=labelled.fit, binding=binding)
        window.document.execute(SetWheelCommand(name, current, changed), window._mutations)

    def wire(thread: QThread) -> None:
        worker.finished.connect(on_ui_thread(done, window))
        worker.error.connect(on_ui_thread(lambda message: done(None, message), window))
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)

    window._run_job(worker, label=tr("Re-fitting wheel {name}").format(name=name), configure=wire)


def edit_binding(window: MainWindow, name: str, sign: float, ratio: float) -> None:
    """A direction or ratio typed by hand: used as given, and no longer "measured"."""
    wheel = window.wheels.get(name)
    if wheel is None or wheel.binding is None:
        return
    binding = wheel.binding
    if (sign, ratio) == (binding.sign, binding.ratio):
        return
    changed = dataclasses.replace(binding, sign=sign, ratio=ratio, measured=False)
    window.document.execute(
        SetWheelCommand(name, wheel, dataclasses.replace(wheel, binding=changed)),
        window._mutations,
    )


def edit_encoder_offset(window: MainWindow, name: str, offset: float) -> None:
    """Move *name*'s encoder source against the video, exactly as its Sources row does.

    One authority for a source's timing (rule 1): the offset typed here is the
    encoder's own, applied and undone through the same path, so the encoder's
    plots and the wheel it turns cannot disagree about the latency.
    """
    wheel = window.wheels.get(name)
    binding = wheel.binding if wheel is not None else None
    if binding is None or window.sidebar.sensor_widget(binding.source_id) is None:
        return
    current, drift = window.sidebar.sensor_mapping(binding.source_id)
    if offset == current:
        return
    window.sidebar.set_sensor_mapping(binding.source_id, offset, drift)
    window._on_sensor_mapping_changed(binding.source_id, offset, drift)


def remove(window: MainWindow, name: str) -> None:
    """Take *name* out of the session; its file is marked removed, never deleted."""
    wheel = window.wheels.get(name)
    if wheel is not None:
        window.document.execute(SetWheelCommand(name, wheel, None), window._mutations)
