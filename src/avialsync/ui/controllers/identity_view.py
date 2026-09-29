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

from typing import TYPE_CHECKING, Any

import numpy as np

from avialsync.core.identity_detect import Candidate, Trajectory
from avialsync.core.identity_swaps import SwapEvent, SwapGroup
from avialsync.core.pyramid import PyramidReader
from avialsync.engine.identity_worker import DetectionJob, DetectionWorker
from avialsync.ui.controllers import identity_controller
from avialsync.ui.i18n import tr
from avialsync.ui.identity_braid import BraidModel, BraidNode, build_model
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from pathlib import Path

    from avialsync.ui.main_window import MainWindow

__all__ = ["pose_sources", "model_for", "counts_for", "detect", "swap", "undo"]


def pose_sources(window: MainWindow) -> list[str]:
    """Every imported pose source that has lanes worth comparing."""
    return [
        source_id
        for source_id in window._pose_schemas
        if window.identity_swaps.groups_for(source_id)
    ]


def current_source(window: MainWindow) -> str:
    """The pose source the panel works on.

    The one overlaid on the selected camera, so choosing a camera chooses the
    tracking -- there is no third selector for it, and no hidden rule about
    which of several files a gesture lands on.
    """
    selected = window._selected_video_path
    if selected:
        for source_id in window._overlay_sources.get(selected, {}):
            if window.identity_swaps.groups_for(source_id):
                return source_id
    sources = pose_sources(window)
    return sources[0] if sources else ""


def groups_for(window: MainWindow, source_id: str) -> tuple[SwapGroup, ...]:
    return window.identity_swaps.groups_for(source_id)


# ── the picture ──────────────────────────────────────────────────────


def model_for(window: MainWindow, source_id: str, group_id: str, part: str) -> BraidModel | None:
    """Build the braid for one group and one part, or None when there is none."""
    group = window.identity_swaps.group(source_id, group_id)
    if group is None:
        return None

    times = _master_times(window, source_id)
    if times is None:
        return None

    tracks = {lane: _track(window, source_id, group, lane, part) for lane in group.lanes}
    boundaries = [
        event.index
        for event in window.identity_swaps.events_for(source_id)
        if event.group == group_id and event.moves(part)
    ]
    routing = [
        (index, window.identity_swaps.lane_map(source_id, group_id, part, index))
        for index in sorted(set(boundaries))
    ]
    return build_model(
        lanes=group.lanes,
        times=times,
        routing=routing,
        nodes=_nodes(window, source_id, group_id, part, times),
        tracks=tracks,
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


def _nodes(
    window: MainWindow, source_id: str, group_id: str, part: str, times: np.ndarray
) -> list[BraidNode]:
    """Accepted flips and proposed ones, on one list the braid can draw."""
    nodes: list[BraidNode] = []
    for event in window.identity_swaps.events_for(source_id):
        if event.group != group_id or not event.moves(part):
            continue
        nodes.append(
            BraidNode(
                index=event.index,
                at=_at(times, event.index),
                lanes=event.lanes,
                accepted=True,
                detail=tr("Accepted: {a} and {b} swap from frame {frame}.").format(
                    a=event.lanes[0],
                    b=event.lanes[1],
                    frame=_frame(window, source_id, event.index),
                ),
            )
        )
    accepted_at = {(node.index, frozenset(node.lanes)) for node in nodes}
    for candidate in window._swap_candidates.get((source_id, group_id, part), ()):
        if (candidate.index, frozenset(candidate.lanes)) in accepted_at:
            continue
        nodes.append(
            BraidNode(
                index=candidate.index,
                at=_at(times, candidate.index),
                lanes=candidate.lanes,
                accepted=False,
                detail=_candidate_detail(window, source_id, candidate),
            )
        )
    return nodes


def _candidate_detail(window: MainWindow, source_id: str, candidate: Candidate) -> str:
    """The evidence a proposal was made on, in the words a reviewer needs."""
    text = tr(
        "Candidate at frame {frame}: {a} and {b} came within {apart:.1f} px, and "
        "swapping them costs {ratio:.2f}x of keeping them."
    ).format(
        frame=_frame(window, source_id, candidate.index),
        a=candidate.lanes[0],
        b=candidate.lanes[1],
        apart=candidate.separation,
        ratio=candidate.cost_ratio,
    )
    if candidate.gap:
        text += " " + tr("{n} frame(s) had no position across it.").format(n=candidate.gap)
    return text


def _frame(window: MainWindow, source_id: str, index: int) -> int:
    from avialsync.ui.controllers import corrections_controller

    return corrections_controller.frame_for(window, source_id, index)


def _at(times: np.ndarray, index: int) -> float:
    if len(times) == 0:
        return 0.0
    return float(times[max(0, min(index, len(times) - 1))])


def _master_times(window: MainWindow, source_id: str) -> np.ndarray | None:
    """One master time per sample index, which is the braid's X axis."""
    for sources in window._overlay_sources.values():
        entry = sources.get(source_id)
        if entry is None:
            continue
        for readers in (entry.get("points") or {}).values():
            reader = readers[0]
            times = reader.source_reader.mapped_columns()[0]
            if len(times):
                return np.asarray(reader.time_map.to_master_array(np.asarray(times)))
    return None


def _track(
    window: MainWindow, source_id: str, group: SwapGroup, lane: str, part: str
) -> Trajectory:
    """One lane's trajectory for *part*, or its centroid across every part."""
    from avialsync.core.identity_detect import centroid

    parts = [part] if part else list(group.parts)
    tracks = [
        Trajectory(
            _values(window, source_id, f"{point}_x"), _values(window, source_id, f"{point}_y")
        )
        for point in (group.point(lane, name) for name in parts)
        if point is not None
    ]
    tracks = [track for track in tracks if len(track.x) and len(track.y)]
    if not tracks:
        return Trajectory(np.zeros(0), np.zeros(0))
    if len(tracks) == 1:
        return tracks[0]
    shortest = min(min(len(t.x), len(t.y)) for t in tracks)
    return centroid([Trajectory(t.x[:shortest], t.y[:shortest]) for t in tracks])


def _values(window: MainWindow, source_id: str, channel: str) -> np.ndarray:
    directory = identity_controller.directories_for(window, source_id).get(channel)
    if directory is None:
        return np.zeros(0)
    return PyramidReader(directory, channel).mapped_columns()[1]


# ── the gestures ─────────────────────────────────────────────────────


def swap(window: MainWindow, source_id: str, event: SwapEvent) -> None:
    """Accept one flip, through the command bus so it can be undone (rule 14)."""
    from avialsync.core.commands import SetIdentitySwapCommand

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


def detect(window: MainWindow, source_id: str, group_id: str, part: str) -> None:
    """Scan one group and part for flips, off the UI thread."""
    group = window.identity_swaps.group(source_id, group_id)
    if group is None:
        return
    parts = [part] if part else list(group.parts)
    directories = identity_controller.directories_for(window, source_id)
    lanes: dict[str, list[tuple[str, str]]] = {}
    for lane in group.lanes:
        pairs = [
            (f"{point}_x", f"{point}_y")
            for point in (group.point(lane, name) for name in parts)
            if point is not None
        ]
        if pairs:
            lanes[lane] = pairs
    if len(lanes) < 2:
        return

    job = DetectionJob(
        source_id=source_id,
        group=group_id,
        part=part,
        lanes=lanes,
        directories=_needed(directories, lanes),
    )
    worker = DetectionWorker(job)

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


def _needed(
    directories: dict[str, Path], lanes: dict[str, list[tuple[str, str]]]
) -> dict[str, Path]:
    wanted = {channel for pairs in lanes.values() for pair in pairs for channel in pair}
    return {channel: path for channel, path in directories.items() if channel in wanted}


def _adopt(window: MainWindow, job: DetectionJob, found: tuple[Candidate, ...]) -> None:
    """Keep what a scan proposed, and tell the user what it amounts to."""
    window._swap_candidates[(job.source_id, job.group, job.part)] = tuple(found)
    window._refresh_identity_panel()
    if found:
        window.notifications.show_success(
            tr("{n} possible identity swap(s) found. None have been applied.").format(n=len(found))
        )
    else:
        window.notifications.show_success(tr("No identity swaps found in what is selected."))
