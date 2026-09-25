"""Add Wheel end to end: declare, click, fit, review, accept, turn, verify (D-113).

1. **Declare.** Edit → Add Wheel… asks for a name, the bar count, the 3D units,
   an optional radius and the encoder channel (:mod:`avialsync.ui.wheel_dialogs`),
   pre-filled from the session plugin's :class:`~avialsync.core.source.RotaryHint`.
2. **Click.** With the calibration resolved (the same Import / Compute question
   as Add 3D Marker), every pane takes clicks: bar 1's first end, its second
   end, then bar 2's, each in every calibrated camera. An end clicked in
   every camera moves on by itself; two complete bars can be accepted, or a
   third can be clicked to check the fit.
3. **Review.** From two complete bars on, the wheel is fitted after every click
   (:func:`~avialsync.core.wheel.fit_wheel`, ~10 ms) and drawn dashed over
   every camera and the 3D view, with its numbers in the sidebar's Wheels
   section. Nothing is committed yet; Flip picks the mirrored wheel.
4. **Accept** runs one :class:`~avialsync.core.commands.SetWheelCommand`, so
   the wheel is one undo step and dirties the session (rule 14).
5. **Turn.** On any other frame the wheel is turned by the encoder, read at the
   presentation time of the frame on screen -- never the clock's raw time, which
   sits anywhere inside that frame's interval (rule 6) -- and with the encoder's
   *current* offset, so re-aligning the encoder moves the wheel with it.
6. **Verify.** A click on any bar end, in one camera, on a frame a few turns
   away tests the encoder's direction; two informative checks settle it
   (:mod:`avialsync.core.wheel_check`). Until then the panel says "assumed".

What each view draws, per frame, is :mod:`avialsync.ui.controllers.wheel_display`.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from avialsync.core.commands import SetWheelCommand
from avialsync.core.errors import WheelFitError
from avialsync.core.wheel import SIDES, EncoderBinding, EndClick, Wheel, WheelCheck, WheelSpec
from avialsync.core.wheel_check import settle_sign
from avialsync.core.wheel_fit import fit_wheel
from avialsync.ui.controllers import calibration_controller as calibration
from avialsync.ui.controllers import custom_marker_controller as markers
from avialsync.ui.controllers import rig_paths
from avialsync.ui.controllers import wheel_display as display
from avialsync.ui.i18n import tr
from avialsync.ui.wheel_dialogs import WheelSetup, ask_wheel_setup

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def _set_checked(window: MainWindow, checked: bool) -> None:
    action = window._act_add_wheel
    blocked = action.blockSignals(True)
    try:
        action.setChecked(checked)
    finally:
        action.blockSignals(blocked)


# ── placing ──────────────────────────────────────────────────────────


def _channels(window: MainWindow) -> list[tuple[str, str, str]]:
    """``(source, channel, label)`` for every loaded channel an encoder could be."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str]] = []
    for row in window.plot_pane.channels:
        key = (row.reader.source_id, row.reader.channel_id)
        if key[0] and key not in seen:
            seen.add(key)
            out.append((*key, f"{key[1]} · {Path(key[0]).name}"))
    return out


def toggled(window: MainWindow, checked: bool) -> None:
    """The Add Wheel action: start a placement, or cancel the one running."""
    if not checked:
        cancel(window, tr("Wheel not added."))
        return
    setup = ask_wheel_setup(
        window, window.wheels.names(), window._session_rotary, _channels(window)
    )
    if setup is None:
        _set_checked(window, False)
        return
    _start(window, setup)


def _start(window: MainWindow, setup: WheelSetup, replacing: str | None = None) -> None:
    markers.cancel(window)
    stop_checking(window)
    if window._act_fix_tracker.isChecked():
        window._act_fix_tracker.setChecked(False)
    calibration.acquire_calibration(
        window,
        lambda: _begin(window, setup, replacing),
        lambda: _set_checked(window, False),
    )


def _begin(window: MainWindow, setup: WheelSetup, replacing: str | None) -> None:
    frame = rig_paths.frame_at(window, window.clock.state.t)
    if frame is None:
        _set_checked(window, False)
        return
    if window.clock.state.playing:
        window.transport.play_toggled.emit(False)
    window._wheel_placement = display.Placement(
        setup.spec, setup.channel, frame, replacing=replacing
    )
    _set_checked(window, True)
    window.video_grid.set_marker_place_mode(True)
    display.refresh(window)


def cancel(window: MainWindow, message: str | None = None) -> None:
    """Abandon a placement in progress, if there is one."""
    had = window._wheel_placement is not None
    window._wheel_placement = None
    _set_checked(window, False)
    if had:
        window.video_grid.set_marker_place_mode(window._wheel_checking is not None)
        display.refresh(window)
        if message:
            window.transport.set_status(message, "info")


def on_clicked(window: MainWindow, video: str, x: float, y: float) -> bool:
    """A click in a pane: a wheel end or a check. False if no wheel wanted it."""
    if window._wheel_checking is not None:
        _check_click(window, video, x, y)
        return True
    placement = window._wheel_placement
    state = window._calibration_state
    if placement is None or state is None:
        return False
    if video not in state.cameras:
        window.transport.set_status(
            tr("{camera} is not in the calibration; click the bar in another camera.").format(
                camera=Path(video).stem
            ),
            "warning",
        )
        return True
    if rig_paths.frame_at(window, window.clock.state.t) != placement.frame:
        window.transport.set_status(
            tr("The wheel is being clicked on frame {frame}; use Go to Frame to return.").format(
                frame=placement.frame
            ),
            "warning",
        )
        return True
    camera = rig_paths.camera_name(video)
    if placement.step >= 6:
        window.transport.set_status(
            tr("Three bars are complete. Review the fit and Accept."), "info"
        )
        return True
    key = placement.end
    click = placement.clicks.get(key, EndClick(*key))
    previous = next(((vx, vy) for c, vx, vy in click.views if c == camera), None)
    placement.history.append((placement.step, camera, previous))
    placement.clicks[key] = click.with_view(camera, x, y)
    if len(placement.clicks[key].views) >= len(state.cameras):
        placement.step += 1
    _refit(window)
    return True


def undo_click(window: MainWindow) -> None:
    placement = window._wheel_placement
    if placement is None or not placement.history:
        return
    step, camera, previous = placement.history.pop()
    key = (step // 2, SIDES[step % 2])
    click = placement.clicks.get(key, EndClick(*key)).without_view(camera)
    if previous is not None:
        click = click.with_view(camera, *previous)
    if click.views:
        placement.clicks[key] = click
    else:
        placement.clicks.pop(key, None)
    placement.step = step
    _refit(window)


def flip(window: MainWindow) -> None:
    placement = window._wheel_placement
    if placement is not None:
        placement.flipped = not placement.flipped
        _refit(window)


def placement_spec_changed(window: MainWindow, bars: int, units: str, radius: float) -> None:
    placement = window._wheel_placement
    if placement is None:
        return
    placement.spec = _spec(placement.spec.name, bars, units, radius)
    _refit(window)


def _spec(name: str, bars: int, units: str, radius: float) -> WheelSpec:
    return WheelSpec(name, int(bars), radius if units and radius > 0 else None, units)


def _refit(window: MainWindow) -> None:
    placement = window._wheel_placement
    if placement is not None:
        try:
            placement.fit = fit_wheel(
                placement.spec,
                placement.ordered(),
                display.camera_models(window),
                flipped=placement.flipped,
            )
            placement.problem = ""
        except WheelFitError as error:
            placement.fit, placement.problem = None, str(error)
    display.refresh(window)


def go_to_frame(window: MainWindow) -> None:
    placement = window._wheel_placement
    t = display.frame_master_time(window, placement.frame) if placement is not None else None
    if t is not None:
        window.clock.seek(t)
        window.player.seek(t, exact=True)


def accept(window: MainWindow) -> None:
    """Commit the wheel being placed, as one undo step."""
    placement = window._wheel_placement
    if placement is None or placement.fit is None:
        return
    if not placement.ready(set(display.camera_models(window))):
        window.transport.set_status(
            tr("Click both ends of two or three bars in every calibrated camera first."),
            "warning",
        )
        return
    binding = None
    if placement.channel is not None:
        t = display.frame_master_time(window, placement.frame)
        angle = display.sample(window, placement.channel, t) if t is not None else None
        if angle is None:
            window.notifications.show_warning(
                tr("{channel} has no reading on frame {frame}, so the wheel will not turn.").format(
                    channel=placement.channel[1], frame=placement.frame
                )
            )
        else:
            binding = EncoderBinding(placement.channel[0], placement.channel[1], angle)
    previous = window.wheels.get(placement.replacing or placement.spec.name)
    if binding is not None and previous is not None and previous.binding is not None:
        # Re-placing keeps the ratio and the checks: they are observations of
        # the footage, still true of the new geometry, and re-settle against it.
        binding = dataclasses.replace(
            binding, ratio=previous.binding.ratio, checks=previous.binding.checks
        )
        binding = settle_sign(placement.fit.geometry, binding, display.camera_models(window))[0]
    state = window._calibration_state
    wheel = Wheel(
        spec=placement.spec,
        frame=placement.frame,
        clicks=placement.ordered(),
        fit=placement.fit,
        flipped=placement.flipped,
        binding=binding,
        calibration=str(state.path) if state is not None else "",
    )
    cancel(window)
    window.document.execute(SetWheelCommand(wheel.name, previous, wheel), window._mutations)
    window.transport.set_status(
        tr("Wheel {name} added: clicks sit {px:.1f} px from it.").format(
            name=wheel.name, px=wheel.fit.median_px
        ),
        "info",
    )
    if binding is not None and not binding.measured:
        window.notifications.show_warning(
            tr("The direction {name} turns is assumed until checked against the video.").format(
                name=wheel.name
            ),
            action_label=tr("How to Verify"),
            on_action=lambda: window.transport.set_status(
                tr(
                    "Go a few turns away, press Verify Here in the Wheels panel, and click "
                    "any bar end in any camera."
                ),
                "info",
            ),
        )


# ── checking the encoder ─────────────────────────────────────────────


def start_checking(window: MainWindow, name: str) -> None:
    """Take the next click as a check of *name*'s encoder; again to stop."""
    if window._wheel_checking == name:
        stop_checking(window)
        return
    wheel = window.wheels.get(name)
    if wheel is None or wheel.binding is None:
        return
    cancel(window)
    markers.cancel(window)

    def _ready() -> None:
        window._wheel_checking = name
        if window.clock.state.playing:
            window.transport.play_toggled.emit(False)
        window.video_grid.set_marker_place_mode(True)
        display.refresh(window)
        window.transport.set_status(
            tr("Click any end of a bar of {name}, in any one camera.").format(name=name), "info"
        )

    calibration.acquire_calibration(window, _ready, lambda: None)


def stop_checking(window: MainWindow) -> None:
    if window._wheel_checking is None:
        return
    window._wheel_checking = None
    window.video_grid.set_marker_place_mode(window._wheel_placement is not None)
    display.refresh(window)


def _check_click(window: MainWindow, video: str, x: float, y: float) -> None:
    name = window._wheel_checking
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
    cameras = display.camera_models(window)
    settled, results = settle_sign(
        wheel.geometry, wheel.binding, cameras, [*wheel.binding.checks, item]
    )
    stop_checking(window)
    window.document.execute(
        SetWheelCommand(wheel.name, wheel, dataclasses.replace(wheel, binding=settled)),
        window._mutations,
    )
    result = results[-1]
    if not result.informative:
        message = tr(
            "The wheel has turned less than one bar gap since frame {frame}, so this check "
            "cannot tell the directions apart. Try a frame further away."
        ).format(frame=wheel.frame)
    else:
        message = tr(
            "Check on frame {frame}: {deg:.1f}° ({px:.1f} px) from the encoder's wheel."
        ).format(frame=item.frame, deg=result.residual_deg, px=result.residual_px)
    window.transport.set_status(message, "info")


# ── editing a placed wheel ───────────────────────────────────────────


def edit_spec(window: MainWindow, name: str, bars: int, units: str, radius: float) -> None:
    """Re-fit *name* from its own clicks with a changed bar count, units or radius."""
    wheel = window.wheels.get(name)
    if wheel is None:
        return
    spec = _spec(name, bars, units, radius)
    if spec == wheel.spec:
        return
    calibration.calibration_quietly(window)
    cameras = display.camera_models(window)
    try:
        fit = fit_wheel(spec, wheel.clicks, cameras, flipped=wheel.flipped)
    except WheelFitError as error:
        window.report_failure(error, doing=tr("Wheel {name} was not re-fitted").format(name=name))
        display.refresh(window)
        return
    binding = wheel.binding
    if binding is not None and binding.checks:
        binding = settle_sign(fit.geometry, binding, cameras)[0]
    changed = dataclasses.replace(wheel, spec=spec, fit=fit, binding=binding)
    window.document.execute(SetWheelCommand(name, wheel, changed), window._mutations)


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


def remove(window: MainWindow, name: str) -> None:
    wheel = window.wheels.get(name)
    if wheel is not None:
        window.document.execute(SetWheelCommand(name, wheel, None), window._mutations)


def replace(window: MainWindow, name: str) -> None:
    """Click *name*'s bars again with its settings; Accept swaps it in, one undo step."""
    wheel = window.wheels.get(name)
    if wheel is None:
        return
    binding = wheel.binding
    channel = (binding.source_id, binding.channel) if binding is not None else None
    _start(window, WheelSetup(wheel.spec, channel), replacing=name)


def connect_panel(window: MainWindow) -> None:
    """Route the Wheels section's requests here."""
    panel = window.wheel_panel
    panel.undo_click_requested.connect(lambda: undo_click(window))
    panel.flip_requested.connect(lambda: flip(window))
    panel.go_to_frame_requested.connect(lambda: go_to_frame(window))
    panel.accept_requested.connect(lambda: accept(window))
    panel.cancel_requested.connect(lambda: cancel(window, tr("Wheel not added.")))
    panel.placement_spec_changed.connect(lambda b, u, r: placement_spec_changed(window, b, u, r))
    panel.spec_changed.connect(lambda n, b, u, r: edit_spec(window, n, b, u, r))
    panel.binding_changed.connect(lambda n, s, r: edit_binding(window, n, s, r))
    panel.verify_requested.connect(lambda n: start_checking(window, n))
    panel.replace_requested.connect(lambda n: replace(window, n))
    panel.remove_requested.connect(lambda n: remove(window, n))


# ── a new session ────────────────────────────────────────────────────


def reset(window: MainWindow) -> None:
    """Forget every wheel and any placement (a new session)."""
    cancel(window)
    window._wheel_checking = None
    window.wheels.clear()
    window._wheel_cache.clear()
    window._wheel_readers.clear()
    window._announced_wheel_files.clear()
    window._session_rotary = None
