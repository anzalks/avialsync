"""Fix Tracker: the point-correction mode, and finding a correction again.

Moved from MainWindow (WINDOW_COMPOSITION_PLAN A6), which keeps one delegator
per function (D-066); the moved code keeps calling the window's own methods, and
its private accesses are in the boundary baseline under D-248. Persisting and
adopting corrections stay in :mod:`corrections_controller`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from avialsync.core.commands import SetTrackedPointCommand
from avialsync.core.point_edits import PointKey, PointMove
from avialsync.ui.changes_panel import ChangeRow
from avialsync.ui.controllers import (
    corrections_controller,
    custom_marker_controller,
    wheel_controller,
)
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

#: How long the revisit ring stays on a point the Changes panel navigated to.
#: Long enough to find it, short enough not to be mistaken for a state the
#: correction is in.
HIGHLIGHT_MS = 4000


def toggle_point_edit_mode(window: MainWindow, enabled: bool) -> None:
    """Turn point correction on or off across every video pane.

    Playback stops on the way in.  A moving frame makes the gesture
    impossible -- the marker being aimed at is somewhere else by the time
    the button goes down -- and stopping is what the user is about to do by
    hand anyway.  This is presentation state, not a document mutation, so
    it is deliberately not on the undo stack: undo reverses corrections,
    not the mode you made them in.
    """
    enabled = bool(enabled)
    if enabled and window._marker_placement is not None:
        custom_marker_controller.cancel(window, tr("3D marker not added."))
    if enabled:
        wheel_controller.cancel(window, tr("Wheel not added."))
        wheel_controller.stop_checking(window)
    if enabled and window.clock.state.playing:
        # Same route the K shortcut takes, so the transport button, the
        # player, and the clock stay in agreement.
        window.transport.play_toggled.emit(False)
    window.video_grid.set_point_edit_mode(enabled)
    if enabled:
        window.transport.set_status(
            tr("Fix Tracker on — drag a point to correct it. Playback paused."), "info"
        )
        return
    corrections = len(window.point_edits)
    window.transport.set_status(
        tr("Fix Tracker off — {n} corrected point(s) in this session.").format(n=corrections)
        if corrections
        else tr("Fix Tracker off."),
        "info",
    )


def on_tracked_point_moved(window: MainWindow, move: object) -> None:
    """Route a finished drag through the command bus so it can be undone."""
    if not isinstance(move, PointMove):
        return
    window.document.execute(
        SetTrackedPointCommand(
            source_id=move.key.source_id,
            point=move.key.point,
            index=move.key.index,
            before=move.before,
            after=move.after,
            display_frame=corrections_controller.frame_for(
                window, move.key.source_id, move.key.index
            ),
            shown_as=move.shown_as,
        ),
        window._mutations,
    )


def on_point_edits_changed(window: MainWindow) -> None:
    """Repaint every overlay after a correction is applied, undone, or loaded.

    The window observes the store, not each pane: a callback held by a
    widget outlives it, and a repaint scheduled onto a freed pane is a
    SIGSEGV with no traceback.  The window outlives them all.
    """
    # The first correction is what makes Export Changes available.
    window._refresh_action_availability()
    grid = getattr(window, "video_grid", None)
    if grid is not None:
        grid.refresh_point_edits()
    panel = getattr(window, "changes_panel", None)
    if panel is not None:
        panel.refresh()


def locate_correction(window: MainWindow, key: object) -> tuple[float, str, int] | None:
    """Place a correction on the master clock, a camera, and a frame.

    The Changes panel cannot work this out: it needs the pose source's own
    time column and the video that source overlays, and both live on the window.
    """
    if not isinstance(key, PointKey):
        return None
    for video, sources in window._overlay_sources.items():
        entry = sources.get(key.source_id)
        if entry is None:
            continue
        points = entry.get("points") or {}
        axes = points.get(key.point) or next(iter(points.values()), None)
        if axes is None:
            return None
        reader = axes[0]
        times = reader.source_reader.mapped_columns()[0]
        if not 0 <= key.index < len(times):
            return None
        t_master = float(reader.time_map.to_master(float(times[key.index])))
        frame = corrections_controller.frame_for(window, key.source_id, key.index)
        return t_master, video, frame
    return None


def revisit_change(window: MainWindow, row: object) -> None:
    """Go to a change the user selected in the panel.

    Seek, select the camera it belongs to, and -- for a correction -- ring
    the body part, because landing on the right frame with nine markers on
    screen is only half of "show me that again".
    """
    if not isinstance(row, ChangeRow):
        return
    if row.t_master is not None:
        window.player.seek(row.t_master, exact=True)
    if row.camera:
        window._select_video(row.camera)
    window.video_grid.highlight_point(row.point)
    if row.point is not None:
        window._highlight_timer.start(HIGHLIGHT_MS)


def restore_predicted_point(window: MainWindow, key: object) -> None:
    """Undo one correction from the panel, through the command bus."""
    if not isinstance(key, PointKey):
        return
    before = window.point_edits.get(key)
    if before is None:
        return
    window.document.execute(
        SetTrackedPointCommand(
            source_id=key.source_id,
            point=key.point,
            index=key.index,
            before=before,
            after=None,
            display_frame=corrections_controller.frame_for(window, key.source_id, key.index),
        ),
        window._mutations,
    )
