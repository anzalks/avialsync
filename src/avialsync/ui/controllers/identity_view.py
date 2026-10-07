"""What the Fix Identities panel shows, and what its gestures turn into.

Split from :mod:`avialsync.ui.controllers.identity_controller`, which owns
persistence and the edited cache: this owns the *view* -- which source, which
group, which part, what the braid is drawn from, and what a drag becomes.

Two things are worth stating where the code is.

**The routing comes from the store.**  The braid asks
:meth:`~avialsync.core.identity_swaps.SwapStore.lane_map` for who displays whom
at each boundary rather than replaying the events itself, so the picture cannot
drift from the data it is a picture of (rule 15).  The empty part -- "All
parts" in the selector -- falls out of the same call: an event that names no
parts moves the whole group, and ``moves("")`` is true for exactly those.

**The trajectories are the edited ones.**  A scan reads through whatever
generation the source's readers are on, so an accepted flip is not proposed a
second time and the separation trace shows the identities as they now stand.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

import numpy as np

from avialsync.core.identity_detect import Candidate
from avialsync.core.identity_swaps import SwapEvent, SwapGroup
from avialsync.engine.identity_worker import GroupDetectionJob, GroupDetectionWorker
from avialsync.ui.controllers import identity_controller
from avialsync.ui.i18n import tr
from avialsync.ui.identity_model_worker import BraidBuildJob
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

__all__ = ["pose_sources", "job_for", "counts_for", "detect", "swap", "undo"]


def pose_sources(window: MainWindow) -> list[str]:
    """Every imported 2D pose source identity repair can work on.

    Deliberately *not* "every source with a derivable group". Animals and
    left-against-right are the two a schema can state for itself; a wrist that
    the tracker confuses with an ankle is just as real and no naming convention
    reveals it, so the user declares that pair — inside the panel. Gating the
    panel on a derived group put the one affordance that creates a group behind
    a door that only a group could open, and left the recordings that need it
    most with a greyed-out menu item telling them to import different data.
    """
    return list(window._pose_schemas)


def current_source(window: MainWindow) -> str:
    """The pose source the panel works on.

    The one overlaid on the selected camera, so choosing a camera chooses the
    tracking -- there is no third selector for it, and no hidden rule about
    which of several files a gesture lands on.
    """
    selected = window._selected_video_path
    if selected:
        for source_id in window._overlay_sources.get(selected, {}):
            if source_id in window._pose_schemas:
                return source_id
    sources = pose_sources(window)
    return sources[0] if sources else ""


def index_at_time(window: MainWindow, source_id: str, at: float) -> int | None:
    """The sample of *source_id* showing at master time *at*.

    Asked of the source, not of the braid: a rebuild clears the braid while it
    runs, and accepting a swap starts one. Reading the frame from the plot
    meant a second Apply during that window was silently dropped -- which is
    the moment a person watching for flips is most likely to press it.

    The same rule the video pane uses (rule 6): the last sample at or before
    *at*, so the frame on screen is the frame the swap starts on.
    """
    for sources in window._overlay_sources.values():
        entry = sources.get(source_id)
        if entry is None:
            continue
        for readers in (entry.get("points") or {}).values():
            reader = readers[0]
            times = reader.source_reader.mapped_columns()[0]
            if not len(times):
                return None
            position = int(np.searchsorted(times, reader.time_map.to_source(at), side="right")) - 1
            return max(0, min(position, len(times) - 1))
    return None


def groups_for(window: MainWindow, source_id: str) -> tuple[SwapGroup, ...]:
    return window.identity_swaps.groups_for(source_id)


# ── the picture ──────────────────────────────────────────────────────


def job_for(
    window: MainWindow,
    source_id: str,
    group_id: str,
    part: str,
    pair: tuple[str, str] | None = None,
) -> BraidBuildJob | None:
    """Snapshot UI-owned state; the returned job opens its own cache readers."""
    group = window.identity_swaps.group(source_id, group_id)
    if group is None:
        return None
    entry = next(
        (
            sources[source_id]
            for sources in window._overlay_sources.values()
            if source_id in sources
        ),
        None,
    )
    if entry is None:
        return None
    readers = next(iter((entry.get("points") or {}).values()), None)
    if not readers:
        return None
    directories = identity_controller.directories_for(window, source_id)
    axis_channel = readers[0].channel_id
    if axis_channel not in directories:
        return None
    boundaries = [
        event.index
        for event in window.identity_swaps.events_for(source_id)
        if event.group == group_id and event.moves(part)
    ]
    routing = [
        (index, window.identity_swaps.lane_map(source_id, group_id, part, index))
        for index in sorted(set(boundaries))
    ]
    return BraidBuildJob(
        source_id=source_id,
        group=group,
        part=part,
        directories=directories,
        axis_channel=axis_channel,
        # Exact mapping arrays are immutable; a shallow copy freezes which
        # arrays this job sees if alignment changes while it is running.
        time_map=copy.copy(readers[0].time_map),
        frame_rate=float(entry.get("frame_rate", 0.0)),
        routing=tuple((index, dict(mapping)) for index, mapping in routing),
        events=tuple(
            event
            for event in window.identity_swaps.events_for(source_id)
            if event.group == group_id and event.moves(part)
        ),
        candidates=window._swap_candidates.get((source_id, group_id, part), ()),
        pair=pair,
    )


def counts_for(
    window: MainWindow, source_id: str, group: SwapGroup
) -> dict[tuple[str, str], tuple[int, int]]:
    """``(candidates, accepted)`` per part, for the part selector's own menu."""
    counts: dict[tuple[str, str], tuple[int, int]] = {}
    for part in ("", *group.parts):
        candidates = len(window._swap_candidates.get((source_id, group.name, part), ()))
        accepted = sum(
            1
            for event in window.identity_swaps.events_for(source_id)
            if event.group == group.name and event.moves(part)
        )
        counts[(group.name, part)] = (candidates, accepted)
    return counts


def _frame(window: MainWindow, source_id: str, index: int) -> int:
    from avialsync.ui.controllers import corrections_controller

    return corrections_controller.frame_for(window, source_id, index)


# ── the gestures ─────────────────────────────────────────────────────


def swap(window: MainWindow, source_id: str, event: SwapEvent) -> None:
    """Accept one flip, through the command bus so it can be undone (rule 14)."""
    from avialsync.core.commands import SetIdentitySwapCommand

    if event in window.identity_swaps.events_for(source_id):
        # Already in force. Pressing Apply again on the same frame is a no-op,
        # and a no-op does not deserve an undo step of its own.
        return

    window.document.execute(
        SetIdentitySwapCommand(
            source_id=source_id,
            event=event,
            accepted=True,
            display_frame=_frame(window, source_id, event.index),
        ),
        window._mutations,
    )


def undo(window: MainWindow, source_id: str, event: SwapEvent) -> None:
    """Undo one accepted flip, by the same route."""
    from avialsync.core.commands import SetIdentitySwapCommand

    held = next(
        (
            candidate
            for candidate in window.identity_swaps.events_for(source_id)
            if candidate.index == event.index
            and candidate.group == event.group
            and set(candidate.lanes) == set(event.lanes)
            # Scope included: two events can share a frame and a pair and mean
            # different things -- one for the whole animal, one for a wrist.
            and candidate.parts == event.parts
        ),
        None,
    )
    if held is None:
        return
    window.document.execute(
        SetIdentitySwapCommand(
            source_id=source_id,
            event=held,
            accepted=False,
            display_frame=_frame(window, source_id, held.index),
        ),
        window._mutations,
    )


def accepted_at(
    window: MainWindow,
    source_id: str,
    group_id: str,
    part: str,
    index: int,
    pair: tuple[str, str] | None = None,
) -> SwapEvent | None:
    """The accepted flip in force at *index*: the last one at or before it.

    Which is what "remove this swap" means to somebody watching the video. The
    alternative -- acting on whichever row the list had selected -- removed a
    swap from earlier in the recording while they were looking at a later
    frame, and the identities before the playhead changed under them.
    """
    wanted = set(pair) if pair else None
    candidates = [
        event
        for event in window.identity_swaps.events_for(source_id)
        if event.group == group_id
        and event.index <= index
        and event.moves(part)
        and (wanted is None or set(event.lanes) == wanted)
    ]
    return max(candidates, key=lambda event: event.index, default=None)


def remove_all(window: MainWindow, source_id: str) -> None:
    """Undo every accepted flip on one source, as a single step.

    One command rather than one per event: a person clearing a source is
    performing one act and expects one Ctrl+Z to put it back, not eleven.
    """
    from avialsync.core.commands import ClearIdentitySwapsCommand

    held = window.identity_swaps.events_for(source_id)
    if not held:
        return
    window.document.execute(
        ClearIdentitySwapsCommand(source_id=source_id, events=held), window._mutations
    )


def detect(window: MainWindow, source_id: str, group_id: str, part: str) -> None:
    """Scan every part of the selected group, including its centroid."""
    group = window.identity_swaps.group(source_id, group_id)
    if group is None:
        return
    directories = identity_controller.directories_for(window, source_id)
    selections: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for selected in ("", *group.parts):
        parts = (selected,) if selected else group.parts
        lanes: dict[str, list[tuple[str, str]]] = {}
        for lane in group.lanes:
            pairs = [
                (f"{point}_x", f"{point}_y")
                for point in (group.point(lane, name) for name in parts)
                if point is not None
            ]
            if pairs:
                lanes[lane] = pairs
        if len(lanes) >= 2:
            selections[selected] = lanes
    if not selections:
        return
    wanted = {
        channel
        for lanes in selections.values()
        for pairs in lanes.values()
        for pair in pairs
        for channel in pair
    }
    job = GroupDetectionJob(
        source_id=source_id,
        group=group_id,
        parts=selections,
        directories={channel: path for channel, path in directories.items() if channel in wanted},
    )
    worker = GroupDetectionWorker(job)

    def _wire(_thread: Any) -> None:
        worker.finished.connect(on_ui_thread(lambda j, found: _adopt(window, j, found), window))
        worker.error.connect(
            on_ui_thread(
                lambda message: window.notifications.show_warning(
                    tr("The identity scan could not be run."), details=message
                ),
                window,
            )
        )

    window._run_job(worker, label=tr("Looking for identity swaps"), configure=_wire)


def _adopt(
    window: MainWindow, job: GroupDetectionJob, found: dict[str, tuple[Candidate, ...]]
) -> None:
    """Keep all part counts; show only the selected slice in the braid."""
    for part, candidates in found.items():
        window._swap_candidates[(job.source_id, job.group, part)] = candidates
    window._refresh_identity_panel()
    total = sum(len(candidates) for candidates in found.values())
    if total:
        window.notifications.show_success(
            tr(
                "{n} possible identity swap(s) found across the group. None have been applied."
            ).format(n=total)
        )
    else:
        window.notifications.show_success(tr("No identity swaps found in what is selected."))
