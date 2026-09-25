"""Add Wheel end to end: declare, click, fit, review, accept, turn, verify (D-113).

1. **Declare.** Edit → Add Wheel… asks for a name, the bar count, the 3D units,
   an optional radius and the encoder channel (:mod:`avialsync.ui.wheel_dialogs`),
   pre-filled from the session plugin's :class:`~avialsync.core.source.RotaryHint`.
2. **Click.** With the calibration resolved, the Wheels tab names six ends
   (1A…3B), their real camera-click counts, and the selected point. Select
   any point or use Next Point to work camera by camera; an end seen in all
   cameras advances automatically. Two real views locate a point in 3D and
   project it into any missing view. Projections are not fit evidence
   (:mod:`avialsync.ui.controllers.wheel_placement`).
3. **Review.** From two complete bars on, the wheel is fitted after every click
   (:func:`~avialsync.core.wheel.fit_wheel`, ~10 ms) and drawn dashed over
   every camera and the 3D view, with its numbers in the Wheels tab.
   Nothing is committed yet; Flip picks the mirrored wheel.
4. **Done Labelling** is available from the moment bars 1 and 2 are labelled,
   and stays so through an optional third bar. It runs one
   :class:`~avialsync.core.commands.SetWheelCommand`, so the wheel is one undo
   step and dirties the session (rule 14). An unreliable fit is saved with its
   geometry hidden, never refused, so the clicks are not lost (D-122).
5. **Turn.** On any other frame the wheel is turned by the encoder, read at the
   presentation time of the frame on screen -- never the clock's raw time, which
   sits anywhere inside that frame's interval (rule 6) -- and with the encoder's
   *current* offset, so re-aligning the encoder moves the wheel with it.
6. **Verify.** A click on any bar end, in one camera, on a frame a few turns
   away tests the encoder's direction; two informative checks settle it
   (:mod:`avialsync.core.wheel_check`). Until then the panel says "assumed".

What each view draws, per frame, is :mod:`avialsync.ui.controllers.wheel_display`;
changing a placed wheel's numbers is :mod:`avialsync.ui.controllers.wheel_edits`.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from avialsync.core.commands import SetWheelCommand
from avialsync.core.wheel import (
    SIDES,
    EndClick,
    Wheel,
    WheelCheck,
    fit_issue,
)
from avialsync.core.wheel_check import settle_sign
from avialsync.ui.controllers import calibration_controller as calibration
from avialsync.ui.controllers import custom_marker_controller as markers
from avialsync.ui.controllers import rig_paths
from avialsync.ui.controllers import wheel_display as display
from avialsync.ui.controllers import wheel_edits as edits
from avialsync.ui.controllers import wheel_generation as generation
from avialsync.ui.controllers.wheel_placement import (
    POINTS,
    Placement,
)
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
    window._wheel_placement = Placement(setup.spec, setup.channel, frame, replacing=replacing)
    window._left_tabs.setCurrentWidget(window.wheel_tab)
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
    near = placement.step_near(camera, x, y, display.projected_hit_radius(window, video))
    if near is not None:
        placement.step = near
    if placement.step >= POINTS:
        window.transport.set_status(
            tr("Select a point in the Wheels tab to place or correct another click."), "info"
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


def select_end(window: MainWindow, step: int) -> None:
    """Choose a named endpoint, so camera-first and point-first orders both work."""
    placement = window._wheel_placement
    if placement is not None and 0 <= step < POINTS:
        placement.step = step
        display.refresh(window)


def next_end(window: MainWindow) -> None:
    """Advance to the next named point, even if this one needs another view later."""
    placement = window._wheel_placement
    if placement is not None and placement.step < POINTS - 1:
        placement.step += 1
        display.refresh(window)


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
    placement.spec = edits.spec_from(placement.spec.name, bars, units, radius)
    _refit(window)


def _refit(window: MainWindow) -> None:
    generation.refit(window)


def go_to_frame(window: MainWindow) -> None:
    placement = window._wheel_placement
    t = display.frame_master_time(window, placement.frame) if placement is not None else None
    if t is not None:
        window.clock.seek(t)
        window.player.seek(t, exact=True)


def accept(window: MainWindow) -> None:
    """Done Labelling: commit the wheel being placed, as one undo step.

    Available once bars 1 and 2 are labelled. A fit :func:`fit_issue` rejects
    is still saved and drawn -- the clicks are the user's work and the wheel
    is what they built -- with a warning and a Re-place offer (D-122, D-123).
    """
    placement = window._wheel_placement
    if placement is None or placement.fit is None:
        return
    if placement.fitting:
        window.transport.set_status(tr("The wheel is still being generated."), "info")
        return
    if not placement.ready(set(display.camera_models(window))):
        window.transport.set_status(
            tr("Click both ends of bars 1 and 2 in at least two calibrated cameras first."),
            "warning",
        )
        return
    previous = window.wheels.get(placement.replacing or placement.spec.name)
    state = window._calibration_state
    wheel = Wheel(
        spec=placement.spec,
        frame=placement.frame,
        clicks=placement.ordered(),
        fit=placement.fit,
        flipped=placement.flipped,
        binding=display.encoder_binding(window, placement, previous),
        calibration=str(state.path) if state is not None else "",
        # Re-placing re-fits the centre lines; the bars' thickness is unchanged.
        bar_diameter=previous.bar_diameter if previous is not None else None,
    )
    cancel(window)
    window.document.execute(SetWheelCommand(wheel.name, previous, wheel), window._mutations)
    _announce(window, wheel)


def _announce(window: MainWindow, wheel: Wheel) -> None:
    """Say what Done Labelling saved, and what is still to check."""
    if fit_issue(wheel.fit, wheel.clicks) is not None:
        window.notifications.show_warning(
            tr(
                "Wheel {name} is saved and drawn, but it fits your clicks poorly ({px:.1f} px, "
                "worst {worst:.1f} px). Re-place it to click its bar ends again."
            ).format(name=wheel.name, px=wheel.fit.median_px, worst=wheel.fit.max_px),
            action_label=tr("Re-place"),
            on_action=lambda: replace(window, wheel.name),
        )
    window.transport.set_status(
        tr("Wheel {name} added: clicks sit {px:.1f} px from it.").format(
            name=wheel.name, px=wheel.fit.median_px
        ),
        "info",
    )
    if wheel.binding is not None and not wheel.binding.measured:
        window.notifications.show_warning(
            tr("The direction {name} turns is assumed until checked against the video.").format(
                name=wheel.name
            ),
            action_label=tr("How to Verify"),
            on_action=lambda: window.transport.set_status(
                tr(
                    "Go a few turns away, press Verify Here in the Wheels tab, and click "
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


# ── re-placing a wheel (its other edits are wheel_edits) ─────────────


def replace(window: MainWindow, name: str) -> None:
    """Click *name*'s bars again; Done Labelling swaps it in as one undo step."""
    wheel = window.wheels.get(name)
    if wheel is None:
        return
    binding = wheel.binding
    channel = (binding.source_id, binding.channel) if binding is not None else None
    _start(window, WheelSetup(wheel.spec, channel), replacing=name)


def connect_panel(window: MainWindow) -> None:
    """Route the Wheels tab's requests here."""
    panel = window.wheel_panel
    panel.point_requested.connect(lambda step: select_end(window, step))
    panel.next_end_requested.connect(lambda: next_end(window))
    panel.undo_click_requested.connect(lambda: undo_click(window))
    panel.flip_requested.connect(lambda: flip(window))
    panel.go_to_frame_requested.connect(lambda: go_to_frame(window))
    panel.accept_requested.connect(lambda: accept(window))
    panel.cancel_requested.connect(lambda: cancel(window, tr("Wheel not added.")))
    panel.placement_spec_changed.connect(lambda b, u, r: placement_spec_changed(window, b, u, r))
    panel.spec_changed.connect(lambda n, b, u, r: edits.edit_spec(window, n, b, u, r))
    panel.binding_changed.connect(lambda n, s, r: edits.edit_binding(window, n, s, r))
    panel.encoder_offset_changed.connect(lambda n, o: edits.edit_encoder_offset(window, n, o))
    panel.bar_diameter_previewed.connect(lambda n, d: edits.preview_bar_diameter(window, n, d))
    panel.bar_diameter_changed.connect(lambda n, d: edits.edit_bar_diameter(window, n, d))
    panel.verify_requested.connect(lambda n: start_checking(window, n))
    panel.replace_requested.connect(lambda n: replace(window, n))
    panel.remove_requested.connect(lambda n: edits.remove(window, n))


# ── a new session ────────────────────────────────────────────────────


def reset(window: MainWindow) -> None:
    """Forget every wheel and any placement (a new session)."""
    cancel(window)
    window._wheel_checking = None
    window.wheels.clear()
    window._wheel_cache.clear()
    window._wheel_refits.clear()
    window._wheel_diameter_preview.clear()
    window._announced_wheel_files.clear()
    window._wheel_adopt_folders.clear()
    window._session_rotary = None
