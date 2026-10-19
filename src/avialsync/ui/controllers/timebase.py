"""Master zero, where each source sits against it, and how times are shown.

Master zero itself is ``SessionRuntimeState.start_time``; what was placed
against it lives in :class:`SessionTimebase`, a plain object the window holds as
``window.timebase``, so nothing here reads a private window field (D-148). The
window keeps one delegator per function for its existing callers (D-066). Calls
between functions in this module go directly: none of them is patched by a
test, and the two private delegators exist only for callers elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from avialsync.core.session_time import (
    placement_offset,
    reference_epoch,
    source_epoch_for,
    unix_start,
)
from avialsync.ui.time_format import TimeDisplayMode

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


@dataclass
class SessionTimebase:
    """What placed each source against master zero, and the time display mode."""

    #: What placed each source against the session zero, by path. Zero for
    #: any source whose own clock already starts at its recording.
    #:
    #: A source's TimeMap offset is this plus what the sidebar shows, and
    #: the split is the whole point: an `epoch_ms` file is placed at about
    #: 1.77e9, which no usable spin box can express, while the hand
    #: correction a user makes on top of it is a few frames. Keeping them
    #: in one number meant the offset control either clamped the placement
    #: (silently, to 86400) or was wiped by the first nudge.
    base_offsets: dict[str, float] = field(default_factory=dict)
    #: Unix epoch of each source's own t=0, where a session declared one.
    #: Keyed by path like the other per-item declarations a session makes.
    declared_epochs: dict[str, float] = field(default_factory=dict)
    #: The recording's trials as declared by its session, in Unix-epoch seconds;
    #: drawn against whatever master zero is in force (:func:`draw_trial_segments`).
    trial_epochs: list[tuple[float, float, str]] = field(default_factory=list)
    time_mode: TimeDisplayMode = TimeDisplayMode.RELATIVE

    def forget_placements(self) -> None:
        """Drop every placement and declared epoch.

        Placements belong to the session zero that produced them; carrying them
        into the next session would place its sources against an epoch it never
        declared.
        """
        self.base_offsets.clear()
        self.declared_epochs.clear()


def adopt_session_start(window: MainWindow, source_start: float) -> float:
    """Declare the session's zero from a source, if it has not been declared.

    Declared once and then kept (NWB): a reference that moved whenever an
    earlier source arrived would renumber every timestamp the user had
    already written down. Returns the reference in force afterwards.
    """
    reference = reference_epoch(window.session_runtime.start_time, source_start)
    if reference == window.session_runtime.start_time:
        return reference
    window.session_runtime.start_time = reference
    publish_session_epoch(window)
    return reference


def declare_base_offset(
    window: MainWindow, source_id: str, source_start: float, source_epoch: float | None
) -> float:
    """Place a source against the session zero and remember what that took.

    *source_epoch* is the Unix epoch of the source's own t=0, when the
    loader or the session knows it. Left out, it is guessed from the
    magnitude of *source_start*, which recognises timestamps that are
    already Unix time and nothing else -- see
    `core/session_time.source_epoch_for`.

    Returns the base offset: what this source's TimeMap needs before any
    hand correction, so that a file counting from midnight and one counting
    from its first frame both run from master zero.
    """
    if source_epoch is None:
        # Looked up rather than passed in, so that a caller cannot forget
        # it: every import path funnels through here, and a path that
        # silently skipped the declaration would place its source at the
        # wrong instant with nothing to show for it.
        source_epoch = window.timebase.declared_epochs.get(source_id)
    epoch = source_epoch_for(source_start, source_epoch)
    started = unix_start(source_start, epoch)
    if started is not None:
        window.adopt_session_start(started)
    base = placement_offset(epoch, window.session_start_time)
    window.timebase.base_offsets[source_id] = base
    return base


def effective_offset(window: MainWindow, source_id: str, user_offset: float) -> float:
    """The TimeMap offset for *source_id* given what the sidebar shows.

    The sidebar owns a residual and nothing else. Adding the placement here
    -- in one function, for video and time series alike -- is what stops a
    hand nudge from replacing a wall-clock source's placement with the
    nudge itself and throwing the source decades off the timeline.
    """
    return window.base_offset(source_id) + float(user_offset)


def user_offset(window: MainWindow, source_id: str, effective: float) -> float:
    """The residual to show in the sidebar for an absolute *effective* offset.

    The inverse of :func:`effective_offset`, for the paths that are handed
    a whole mapping: a restored session, and an accepted alignment fit.
    """
    return float(effective) - window.base_offset(source_id)


def publish_session_epoch(window: MainWindow) -> None:
    """Give every time-displaying surface the epoch of master zero.

    `format_time` has always taken this and falls back to elapsed time when
    it is zero. Nothing ever passed one, so the UTC and local time-of-day
    display modes silently could not work -- two of three options on a menu
    that has been there since the start.
    """
    epoch = window.session_runtime.start_time
    mode = window.timebase.time_mode
    window.transport.set_t_epoch(epoch)
    window.plot_pane.set_time_mode(mode, epoch)
    window.message_panel.set_time_mode(mode, epoch)
    window.changes_panel.set_time_mode(mode, epoch)
    draw_trial_segments(window)


def show_trial_segments(window: MainWindow, segments: list[tuple[float, float, str]]) -> None:
    """Show the recording's trials (Unix-epoch spans) in Data Streams and on the plots."""
    window.timebase.trial_epochs = list(segments)
    draw_trial_segments(window)


def draw_trial_segments(window: MainWindow) -> None:
    """Place the declared trials against master zero, or clear them without one."""
    zero = window.session_runtime.start_time
    trials = window.timebase.trial_epochs
    if not trials or zero <= 0.0:
        window.transport.set_trial_segments([])
        window.plot_pane.set_segment_boundaries([])
        return
    segments = [(start - zero, end - zero, name) for start, end, name in trials]
    window.transport.set_trial_segments(segments)
    # Both edges of every trial: between two trials there may be a gap (D-217).
    window.plot_pane.set_segment_boundaries(
        sorted({edge for start, end, _name in segments for edge in (start, end)})
    )


def forget_session_start(window: MainWindow) -> None:
    """Drop master zero and what was placed against it, the trials included."""
    window.session_runtime.start_time = 0.0
    window.show_trial_segments([])


def set_time_mode(window: MainWindow, mode: TimeDisplayMode) -> None:
    """Show every time in *mode* and announce the change."""
    window.timebase.time_mode = mode
    window.transport.set_time_mode(mode)
    # Through the one place that knows the epoch, so a mode change cannot
    # reset a surface to elapsed time by passing the default.
    publish_session_epoch(window)
    window.transport.set_time(window.clock.state.t)
    window.time_mode_changed.emit(mode)
