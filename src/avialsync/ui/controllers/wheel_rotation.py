"""Collect, fit, review, and apply a wheel's periodic rotary transfer.

This controller owns the later-frame rotation-calibration interaction only.
Wheel placement and the one-click direction check stay in
:mod:`avialsync.ui.controllers.wheel_controller`; the numerical fit is generic
and headless in :mod:`avialsync.core.rotary_calibration`.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread

from avialsync.core.commands import SetWheelCommand
from avialsync.core.errors import RotaryCalibrationError
from avialsync.core.rotary_calibration import RotaryCalibrationProposal
from avialsync.core.source import RotaryHint
from avialsync.core.wheel import Wheel, WheelCheck
from avialsync.ui.controllers import rig_paths
from avialsync.ui.controllers import wheel_display as display
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

__all__ = ["apply", "fit", "on_click", "session_proposal", "start", "stop"]


def _refresh_marker_place_mode(window: MainWindow) -> None:
    """Keep marker clicking live while a wheel interaction owns the panes."""
    state = window.wheel_state
    window.video_grid.set_marker_place_mode(
        state.placement is not None or state.checking is not None or state.calibrating is not None
    )


def session_proposal(wheel: Wheel, hint: RotaryHint | None) -> RotaryCalibrationProposal | None:
    """Expose a matching plugin hint as a reviewable proposal, never an edit."""
    binding = wheel.binding
    if binding is None or hint is None or hint.motion_model is None:
        return None
    if hint.channel != binding.channel:
        return None
    if hint.source is not None and str(hint.source) != binding.source_id:
        return None
    return RotaryCalibrationProposal(hint.motion_model, hint.motion_sign)


def start(window: MainWindow, name: str) -> None:
    """Collect bar-end observations over multiple frames for one wheel."""
    if window.wheel_state.calibrating == name:
        stop(window)
        return
    wheel = window.wheels.get(name)
    if wheel is None or wheel.binding is None:
        return
    window._cancel_competing_placement("wheel")

    def ready() -> None:
        window.wheel_state.calibrating = name
        if window.clock.state.playing:
            window.transport.play_toggled.emit(False)
        _refresh_marker_place_mode(window)
        display.refresh(window)
        window.transport.set_status(
            tr(
                "Click any bar end, then move to a different frame and click again. "
                "Choose Fit Rotation when you have enough coverage."
            ),
            "info",
        )

    from avialsync.ui.controllers import calibration_controller as calibration

    calibration.acquire_calibration(window, ready, lambda: None)


def stop(window: MainWindow) -> None:
    """Finish collecting rotation evidence without discarding its saved clicks."""
    if window.wheel_state.calibrating is None:
        return
    window.wheel_state.calibrating = None
    _refresh_marker_place_mode(window)
    display.refresh(window)


def on_click(window: MainWindow, video: str, x: float, y: float) -> None:
    """Persist one later-frame bar-end observation while collection remains active."""
    name = window.wheel_state.calibrating
    wheel = window.wheels.get(name) if name is not None else None
    state = window._calibration_state
    if wheel is None or wheel.binding is None or state is None or video not in state.cameras:
        return
    found = display.frame_and_time(window, window.clock.state.t)
    channel = (wheel.binding.source_id, wheel.binding.channel)
    angle = display.sample(window, channel, found[1]) if found is not None else None
    if found is None or angle is None:
        window.transport.set_status(tr("The encoder has no reading on this frame."), "warning")
        return
    item = WheelCheck(found[0], angle, rig_paths.camera_name(video), float(x), float(y))
    binding = dataclasses.replace(wheel.binding, checks=(*wheel.binding.checks, item))
    # A fit is a statement about this exact evidence collection. Retire it as
    # soon as another click is recorded; an applied fit remains undoable.
    window.wheel_state.motion_proposals.pop(wheel.name, None)
    window.document.execute(
        SetWheelCommand(wheel.name, wheel, dataclasses.replace(wheel, binding=binding)),
        window._mutations,
    )
    window.transport.set_status(
        tr(
            "Rotation click {count} recorded. Move to another frame, or choose Fit Rotation."
        ).format(count=len(binding.checks)),
        "info",
    )


def _harmonic_orders(observation_count: int) -> tuple[int, ...]:
    """Only ask evidence to support the correction complexity it can identify."""
    if observation_count >= 11:
        return (1, 2)
    if observation_count >= 7:
        return (1,)
    return ()


def _finish_fit(
    window: MainWindow,
    name: str,
    checks: tuple[WheelCheck, ...],
    proposal: RotaryCalibrationProposal | None,
    message: str = "",
) -> None:
    """Keep a result only when its exact click evidence is still current."""
    window.wheel_state.motion_fitting.discard(name)
    current = window.wheels.get(name)
    if current is None or current.binding is None or current.binding.checks != checks:
        display.refresh(window)
        return
    if proposal is None:
        window.report_failure(
            RotaryCalibrationError(message), doing=tr("Rotation calibration was not proposed")
        )
    else:
        window.wheel_state.motion_proposals[name] = proposal
        window.transport.set_status(
            tr(
                "Rotation proposal from {count} bar-end clicks: RMS {rms:.2f}°. "
                "Review and apply it to use it."
            ).format(count=proposal.observation_count, rms=proposal.rms_degrees or 0.0),
            "info",
        )
    display.refresh(window)


def _wire_fit(
    window: MainWindow, name: str, checks: tuple[WheelCheck, ...], worker: object, thread: QThread
) -> None:
    """Route worker outcomes to the UI and guarantee that its job terminates."""
    from avialsync.engine.rotary_calibration_worker import RotaryCalibrationWorker

    assert isinstance(worker, RotaryCalibrationWorker)
    worker.finished.connect(
        on_ui_thread(lambda proposal: _finish_fit(window, name, checks, proposal), window)
    )
    worker.error.connect(
        on_ui_thread(lambda message: _finish_fit(window, name, checks, None, message), window)
    )
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)


def fit(window: MainWindow, name: str) -> None:
    """Build a reviewable periodic transfer proposal on a registered worker."""
    from avialsync.engine.rotary_calibration_worker import RotaryCalibrationWorker

    wheel = window.wheels.get(name)
    if wheel is None or wheel.binding is None or name in window.wheel_state.motion_fitting:
        return
    checks = wheel.binding.checks
    if len(checks) < 3:
        window.transport.set_status(
            tr(
                "Collect at least three bar-end clicks on different frames before fitting rotation."
            ),
            "warning",
        )
        return
    stop(window)
    worker = RotaryCalibrationWorker(
        wheel.geometry,
        wheel.binding,
        display.camera_models(window),
        checks,
        _harmonic_orders(len(checks)),
    )
    window.wheel_state.motion_fitting.add(name)
    display.refresh(window)
    window._run_job(
        worker,
        label=tr("Fitting rotation for {name}").format(name=name),
        configure=lambda thread: _wire_fit(window, name, checks, worker, thread),
    )


def apply(window: MainWindow, name: str) -> None:
    """Accept the explicit transfer proposal as one undoable wheel change."""
    proposal = window.wheel_state.motion_proposals.get(name)
    wheel = window.wheels.get(name)
    if proposal is None or wheel is None or wheel.binding is None:
        return
    binding = dataclasses.replace(
        wheel.binding,
        sign=proposal.sign,
        ratio=proposal.motion_model.gain,
        # A fit can select a direction, but `measured` means the independent
        # Verify workflow has settled it. A plugin proposal must not claim a
        # local video verification merely by being accepted.
        measured=wheel.binding.measured and wheel.binding.sign == proposal.sign,
        motion_model=proposal.motion_model,
    )
    window.document.execute(
        SetWheelCommand(name, wheel, dataclasses.replace(wheel, binding=binding)),
        window._mutations,
    )
    del window.wheel_state.motion_proposals[name]
    display.refresh(window)
    window.transport.set_status(
        tr("Rotation calibration applied. Undo restores the earlier model."), "info"
    )
