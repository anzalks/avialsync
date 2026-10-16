"""Align, fit, review, and apply a wheel's periodic rotary transfer.

On any frame the user slides the drawn bars onto the video and saves that
frame; each save is one :class:`RotaryObservation` (encoder reading, cyclic
wheel angle).  Nothing about the alignment is wheel- or rig-specific beyond
drawing, so the fit stays the generic one any rotary prop can use.

A rig plugin may also supply its own calibrated wheel (D-226): geometry, the
absolute rotation model fitted on it, and the camera corrections it was fitted
through. :func:`adopt_rig` takes those declarations; :func:`use_rig_wheel`
builds the wheel from them, with no clicks.

This controller owns the later-frame rotation-calibration interaction only.
Wheel placement and the one-click direction check stay in
:mod:`avialsync.ui.controllers.wheel_controller`; the numerical fit is generic
and headless in :mod:`avialsync.core.rotary_calibration`.
"""

from __future__ import annotations

import dataclasses
import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread

from avialsync.core.calibration import Calibration, corrected
from avialsync.core.commands import SetWheelCommand
from avialsync.core.errors import RotaryCalibrationError
from avialsync.core.rotary_calibration import RotaryCalibrationProposal, RotaryObservation
from avialsync.core.source import RotaryHint
from avialsync.core.wheel import EncoderBinding, Wheel, WheelFit, WheelGeometry, WheelSpec
from avialsync.ui.controllers import wheel_display as display
from avialsync.ui.controllers.wheel_state import RotationPreview
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.controllers.calibration_controller import CalibrationState
    from avialsync.ui.main_window import MainWindow

__all__ = [
    "adjust",
    "adopt_rig",
    "apply",
    "fit",
    "offer_session_defaults",
    "offer_session_model",
    "save",
    "session_proposal",
    "start",
    "stop",
    "use_rig_wheel",
]


def _refresh_marker_place_mode(window: MainWindow) -> None:
    """Keep marker clicking live while a wheel interaction owns the panes."""
    state = window.wheel_state
    window.video_grid.set_marker_place_mode(
        state.placement is not None or state.checking is not None
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
    return RotaryCalibrationProposal(hint.motion_model, hint.motion_sign, source=hint.motion_source)


def _commit(window: MainWindow, before: Wheel | None, after: Wheel) -> None:
    """Replace *before* by *after* as one undo step."""
    window.document.execute(SetWheelCommand(after.name, before, after), window._mutations)


def _with_model(wheel: Wheel, proposal: RotaryCalibrationProposal) -> Wheel:
    """*wheel* turning by *proposal*'s transfer and direction."""
    assert wheel.binding is not None
    binding = dataclasses.replace(
        wheel.binding,
        sign=proposal.sign,
        ratio=proposal.motion_model.gain,
        # A fit can select a direction, but `measured` means the independent
        # Verify workflow has settled it. A plugin proposal must not claim a
        # local video verification merely by being accepted.
        measured=wheel.binding.measured and wheel.binding.sign == proposal.sign,
        motion_model=proposal.motion_model,
        motion_source=proposal.source,
    )
    return dataclasses.replace(wheel, binding=binding)


def adopt_rig(window: MainWindow, hint: RotaryHint | None) -> None:
    """Take a session's rig declarations: its wheel and model, and camera corrections.

    A calibration already in force gains the corrections now; one read later
    gains them as it is read (``calibration_controller``).
    """
    window.wheel_state.session_rotary = hint
    state = _calibration_state(window)
    if state is not None and window.session_runtime.camera_corrections:
        pairs = [(h.camera, h.correction) for h in window.session_runtime.camera_corrections]
        for video, camera in list(state.cameras.items()):
            state.cameras[video] = corrected(Calibration(cameras=(camera,)), pairs).cameras[0]
        display.refresh(window)
    offer_session_defaults(window)


def _calibration_state(window: MainWindow) -> CalibrationState | None:
    return window._calibration_state


def offer_session_defaults(window: MainWindow) -> None:
    """Offer the rig's default model to saved wheels that turn by something else.

    A saved wheel's model is the user's (or an older fit's), so the default is
    only proposed for review here, never applied: Apply Proposed Fit takes it.
    """
    hint = window.wheel_state.session_rotary
    if hint is None or not hint.motion_default:
        return
    offered = []
    for wheel in window.wheels:
        proposal = session_proposal(wheel, hint)
        if proposal is None or wheel.binding is None or wheel.source:
            continue
        if wheel.binding.motion_source == hint.motion_source:
            continue
        if wheel.name in window.wheel_state.motion_proposals:
            continue
        window.wheel_state.motion_proposals[wheel.name] = proposal
        offered.append(wheel.name)
    display.refresh(window)
    if hint.geometry is not None and not any(
        w.source == hint.geometry_source for w in window.wheels
    ):
        window.notifications.show_success(
            tr("This rig has a calibrated wheel: the {source}.").format(
                source=hint.geometry_source
            ),
            action_label=tr("Use Rig Wheel"),
            on_action=lambda: use_rig_wheel(window),
        )
    elif offered:
        window.notifications.show_success(
            tr("The {source} is ready to apply to {names}.").format(
                source=hint.motion_source, names=", ".join(offered)
            )
        )


def _turned(geometry: WheelGeometry, degrees: float) -> WheelGeometry:
    """*geometry* with bar 0 moved *degrees* round the axle."""
    x, y, _ = geometry.basis()
    angle = math.radians(degrees)
    zero = math.cos(angle) * x + math.sin(angle) * y
    return dataclasses.replace(geometry, zero=(float(zero[0]), float(zero[1]), float(zero[2])))


def use_rig_wheel(window: MainWindow, name: str | None = None) -> None:
    """Make *name* -- else the wheel the rig's encoder turns, else a new one -- the rig's wheel.

    One undo step. The rig's geometry has bar 0 at the model's absolute turn 0,
    so it is turned to the model's angle at the wheel's frame; every frame then
    draws at exactly that model's angle (D-226). No clicks are involved.
    """
    hint = window.wheel_state.session_rotary
    model = hint.motion_model if hint is not None else None
    if hint is None or hint.geometry is None or model is None or hint.source is None:
        return
    before = (
        window.wheels.get(name)
        if name
        else next((w for w in window.wheels if session_proposal(w, hint) is not None), None)
    )
    from avialsync.ui.controllers import calibration_controller

    calibration_controller.calibration_quietly(window)
    channel = (str(hint.source), hint.channel)
    frame = 0
    t = display.frame_master_time(window, frame)
    reading = display.sample(window, channel, t) if t is not None else None
    if reading is None:
        window.transport.set_status(
            tr("Load {channel} first: the rig's wheel is placed by its reading.").format(
                channel=hint.channel
            ),
            "warning",
        )
        return
    state = _calibration_state(window)
    after = _rig_wheel(hint, before, frame, reading, str(state.path) if state is not None else "")
    from avialsync.ui.prop_context import capture

    after = dataclasses.replace(after, context=capture(window, frame))
    if window.wheel_state.calibrating == after.name:
        stop(window)
    window.wheel_state.motion_proposals.pop(after.name, None)
    _commit(window, before, after)
    window.notifications.show_success(
        tr("{name} is now the {source}. Undo restores the earlier wheel.").format(
            name=after.name, source=hint.geometry_source
        )
    )


def _rig_wheel(
    hint: RotaryHint, before: Wheel | None, frame: int, reading: float, calibration: str
) -> Wheel:
    """The rig's wheel on *frame*, where the encoder reads *reading*; keeps *before*'s name."""
    assert hint.geometry is not None and hint.motion_model is not None and hint.source is not None
    model = hint.motion_model
    spec = WheelSpec(
        before.name if before is not None else "wheel",
        hint.geometry.bar_count,
        before.spec.radius if before is not None else (hint.radius or None),
        before.spec.units if before is not None else hint.units,
    )
    turn = hint.motion_sign * model.angle_degrees(reading)
    return Wheel(
        spec=spec,
        frame=frame,
        clicks=(),
        fit=WheelFit(_turned(hint.geometry, turn), (), (), (), ()),
        binding=EncoderBinding(
            str(hint.source),
            hint.channel,
            reading,
            sign=hint.motion_sign,
            ratio=model.gain,
            motion_model=model,
            motion_source=hint.motion_source,
        ),
        calibration=calibration,
        bar_diameter=before.bar_diameter if before is not None else None,
        source=hint.geometry_source,
    )


def offer_session_model(window: MainWindow, wheel: Wheel, hint: RotaryHint | None) -> None:
    """After placing *wheel*: apply the rig's default model, or offer a plugin's for review.

    A default is applied as its own undo step, so Undo leaves the placed wheel
    on its plain ratio. A wheel that already turns by a model (re-placed) keeps it.
    """
    proposal = session_proposal(wheel, hint)
    if proposal is None or wheel.binding is None:
        return
    if hint is not None and hint.motion_default:
        if wheel.binding.motion_model is not None:
            return
        _commit(window, wheel, _with_model(wheel, proposal))
        window.notifications.show_success(
            tr("{name} turns by the {source}. Undo returns it to the plain ratio.").format(
                name=wheel.name, source=proposal.source
            )
        )
        return
    window.wheel_state.motion_proposals[wheel.name] = proposal
    display.refresh(window)
    window.notifications.show_success(
        tr("A session-provided rotation model is ready to review for {name}.").format(
            name=wheel.name
        )
    )


def start(window: MainWindow, name: str) -> None:
    """Align the drawn bars to the video over multiple frames for one wheel."""
    if window.wheel_state.calibrating == name:
        stop(window)
        return
    wheel = window.wheels.get(name)
    if wheel is None or wheel.binding is None:
        return
    window._cancel_competing_placement("wheel")

    def ready() -> None:
        window.wheel_state.calibrating = name
        if not window.wheel_state.rotation_clock_subscribed:
            # The clock cannot unsubscribe; the observer is a no-op when idle.
            window.clock.subscribe(lambda t: display.show_rotation(window, t))
            window.wheel_state.rotation_clock_subscribed = True
        if window.clock.state.playing:
            window.transport.play_toggled.emit(False)
        _refresh_marker_place_mode(window)
        display.refresh(window)
        window.transport.set_status(
            tr(
                "Slide Visual rotation until the bars sit on the video, then Save Frame. "
                "Repeat on frames spread over the run, then choose Fit Rotation."
            ),
            "info",
        )

    from avialsync.ui.controllers import calibration_controller as calibration

    if wheel.context.cameras:
        ready()
    else:
        calibration.acquire_calibration(window, ready, lambda: None)


def stop(window: MainWindow) -> None:
    """Finish aligning without discarding the saved alignments."""
    if window.wheel_state.calibrating is None:
        return
    window.wheel_state.calibrating = None
    window.wheel_state.rotation_preview.clear()
    _refresh_marker_place_mode(window)
    display.refresh(window)


def adjust(window: MainWindow, name: str, degrees: float) -> None:
    """Draw *name*'s bars turned by *degrees* on this frame; record nothing."""
    wheel = window.wheels.get(name)
    if window.wheel_state.calibrating != name or wheel is None:
        return
    aligned = display.alignment(window, wheel, window.clock.state.t)
    if aligned is None:
        return
    window.wheel_state.rotation_preview[name] = RotationPreview(aligned[0], degrees)
    display.refresh(window)


def save(window: MainWindow, name: str) -> None:
    """Keep this frame's visual alignment as one rotary observation, as one undo step.

    Saving a frame again replaces its earlier alignment instead of weighting
    that frame twice.
    """
    wheel = window.wheels.get(name)
    if window.wheel_state.calibrating != name or wheel is None or wheel.binding is None:
        return
    aligned = display.alignment(window, wheel, window.clock.state.t)
    channel = (wheel.binding.source_id, wheel.binding.channel)
    reading = display.sample(window, channel, aligned[1]) if aligned is not None else None
    if aligned is None or reading is None:
        window.transport.set_status(tr("The encoder has no reading on this frame."), "warning")
        return
    frame, _t, turn, adjustment = aligned
    item = RotaryObservation(reading, (turn + adjustment) % wheel.spec.pitch, frame)
    kept = tuple(o for o in wheel.binding.rotation_observations if o.evidence_index != frame)
    binding = dataclasses.replace(wheel.binding, rotation_observations=(*kept, item))
    window.wheel_state.rotation_preview.pop(name, None)
    # A fit is a statement about this exact evidence. Retire it as soon as the
    # evidence changes; an applied fit remains undoable.
    window.wheel_state.motion_proposals.pop(name, None)
    _commit(window, wheel, dataclasses.replace(wheel, binding=binding))
    window.transport.set_status(
        tr(
            "Frame {frame} saved ({count} aligned). Move to another frame, or choose Fit Rotation."
        ).format(frame=frame, count=len(binding.rotation_observations)),
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
    observations: tuple[RotaryObservation, ...],
    proposal: RotaryCalibrationProposal | None,
    message: str = "",
) -> None:
    """Keep a result only when its exact evidence is still current."""
    window.wheel_state.motion_fitting.discard(name)
    current = window.wheels.get(name)
    if (
        current is None
        or current.binding is None
        or current.binding.rotation_observations != observations
    ):
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
                "Rotation proposal from {count} saved alignments: RMS {rms:.2f}°. "
                "Review and apply it to use it."
            ).format(count=proposal.observation_count, rms=proposal.rms_degrees or 0.0),
            "info",
        )
    display.refresh(window)


def _wire_fit(
    window: MainWindow,
    name: str,
    observations: tuple[RotaryObservation, ...],
    worker: object,
    thread: QThread,
) -> None:
    """Route worker outcomes to the UI and guarantee that its job terminates."""
    from avialsync.engine.rotary_calibration_worker import RotaryCalibrationWorker

    assert isinstance(worker, RotaryCalibrationWorker)
    worker.finished.connect(
        on_ui_thread(lambda proposal: _finish_fit(window, name, observations, proposal), window)
    )
    worker.error.connect(
        on_ui_thread(lambda message: _finish_fit(window, name, observations, None, message), window)
    )
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)


def fit(window: MainWindow, name: str) -> None:
    """Build a reviewable periodic transfer proposal on a registered worker."""
    from avialsync.engine.rotary_calibration_worker import RotaryCalibrationWorker

    wheel = window.wheels.get(name)
    if wheel is None or wheel.binding is None or name in window.wheel_state.motion_fitting:
        return
    observations = wheel.binding.rotation_observations
    if len(observations) < 3:
        window.transport.set_status(
            tr("Save an alignment on at least three different frames before fitting rotation."),
            "warning",
        )
        return
    stop(window)
    # The bars are drawn relative to the reference frame's reading through the
    # encoder's current mapping (`wheel_display._turn`); fit against the same
    # reading, or a re-aligned encoder leaves a constant bias the fit cannot hold.
    channel = (wheel.binding.source_id, wheel.binding.channel)
    from avialsync.ui import prop_context

    reference_time = prop_context.reference_time(window, wheel)
    reference = (
        display.sample(window, channel, reference_time) if reference_time is not None else None
    )
    binding = wheel.binding
    if reference is not None:
        binding = dataclasses.replace(binding, reference_angle=reference)
    worker = RotaryCalibrationWorker(
        binding,
        wheel.spec.bar_count,
        observations,
        _harmonic_orders(len(observations)),
    )
    window.wheel_state.motion_fitting.add(name)
    display.refresh(window)
    window._run_job(
        worker,
        label=tr("Fitting rotation for {name}").format(name=name),
        configure=lambda thread: _wire_fit(window, name, observations, worker, thread),
    )


def apply(window: MainWindow, name: str) -> None:
    """Accept the explicit transfer proposal as one undoable wheel change."""
    proposal = window.wheel_state.motion_proposals.get(name)
    wheel = window.wheels.get(name)
    if proposal is None or wheel is None or wheel.binding is None:
        return
    _commit(window, wheel, _with_model(wheel, proposal))
    del window.wheel_state.motion_proposals[name]
    display.refresh(window)
    window.transport.set_status(
        tr("Rotation calibration applied. Undo restores the earlier model."), "info"
    )
