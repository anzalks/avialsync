"""Build one identity braid from cache readers outside the UI thread.

The window snapshots paths, routing, and evidence before starting this worker.
Readers are opened here, so neither mmap lifetime nor a full centroid scan
belongs to a paint or selector callback.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.identity_detect import Candidate, Trajectory, centroid
from avialsync.core.identity_swaps import SwapEvent, SwapGroup
from avialsync.core.pyramid import PyramidReader
from avialsync.core.timeline import TimeMap
from avialsync.ui.i18n import tr
from avialsync.ui.identity_braid import BraidModel, BraidNode, build_model

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class BraidBuildJob:
    """Immutable source and edit state for one selected group and part."""

    source_id: str
    group: SwapGroup
    part: str
    directories: dict[str, Path]
    axis_channel: str
    time_map: TimeMap
    frame_rate: float
    routing: tuple[tuple[int, dict[str, str]], ...]
    events: tuple[SwapEvent, ...]
    candidates: tuple[Candidate, ...]
    #: The two lanes whose separation is drawn, and which a swap at the
    #: playhead exchanges. ``None`` for a group of two, where there is no choice.
    pair: tuple[str, str] | None = None


class BraidBuildWorker(QObject):
    """Read pose channels and decimate separation evidence in a registered job."""

    finished = Signal(object, object)
    error = Signal(str)

    def __init__(self, job: BraidBuildJob) -> None:
        super().__init__()
        self._job = job

    @Slot()
    def run(self) -> None:
        try:
            model = build_braid(self._job)
        except Exception as error:  # noqa: BLE001 - job failure is reported by the window
            logger.warning("Could not build identity braid", exc_info=error)
            self.error.emit(str(error))
            return
        self.finished.emit(self._job, model)


def build_braid(job: BraidBuildJob) -> BraidModel:
    """Build a model with this job's own readers and immutable time mapping."""
    directory = job.directories[job.axis_channel]
    source_times = PyramidReader(directory, job.axis_channel).mapped_columns()[0]
    times = np.asarray(job.time_map.to_master_array(source_times), dtype=float)
    frames = (
        np.rint(source_times * job.frame_rate).astype(np.int64)
        if job.frame_rate > 0.0
        else np.arange(len(source_times), dtype=np.int64)
    )
    tracks = {lane: _trajectory(job, lane) for lane in job.group.lanes}
    return build_model(
        lanes=job.group.lanes,
        times=times,
        routing=job.routing,
        nodes=_nodes(job, source_times, times),
        tracks=tracks,
        pair=job.pair,
        frame_numbers=frames,
    )


def _trajectory(job: BraidBuildJob, lane: str) -> Trajectory:
    parts = (job.part,) if job.part else job.group.parts
    tracks = [
        Trajectory(_values(job, f"{point}_x"), _values(job, f"{point}_y"))
        for point in (job.group.point(lane, part) for part in parts)
        if point is not None
    ]
    tracks = [track for track in tracks if len(track.x) and len(track.y)]
    if not tracks:
        return Trajectory(np.zeros(0), np.zeros(0))
    if len(tracks) == 1:
        return tracks[0]
    shortest = min(min(len(track.x), len(track.y)) for track in tracks)
    return centroid([Trajectory(track.x[:shortest], track.y[:shortest]) for track in tracks])


def _values(job: BraidBuildJob, channel: str) -> np.ndarray:
    """One channel's values, or nothing when they are no longer there.

    A job reads a directory it was handed when it was queued. Behind the keep
    window in :mod:`avialsync.core.edit_cache` that directory is still on disk;
    this is the belt to that braces, because a braid that cannot draw one lane
    is worth more than a traceback and an empty panel.
    """
    directory = job.directories.get(channel)
    if directory is None:
        return _empty()
    try:
        return PyramidReader(directory, channel).mapped_columns()[1]
    except (FileNotFoundError, ValueError):
        logger.warning("Identity braid: %s is no longer in %s", channel, directory)
        return _empty()


def _empty() -> np.ndarray:
    return np.zeros(0, dtype=float)


def _nodes(job: BraidBuildJob, source_times: np.ndarray, times: np.ndarray) -> list[BraidNode]:
    nodes: list[BraidNode] = []
    for event in job.events:
        frame = _frame(source_times, job.frame_rate, event.index)
        nodes.append(
            BraidNode(
                index=event.index,
                at=_at(times, event.index),
                lanes=event.lanes,
                accepted=True,
                parts=event.parts,
                display_frame=frame,
                detail=tr("Accepted: {a} and {b} swap from frame {frame}.").format(
                    a=event.lanes[0], b=event.lanes[1], frame=frame
                ),
            )
        )
    accepted_at = {(node.index, frozenset(node.lanes)) for node in nodes}
    for candidate in job.candidates:
        if (candidate.index, frozenset(candidate.lanes)) in accepted_at:
            continue
        detail = tr(
            "Candidate at frame {frame}: {a} and {b} came within {apart:.1f} px, "
            "and swapping them costs {ratio:.2f}x of keeping them."
        ).format(
            frame=_frame(source_times, job.frame_rate, candidate.index),
            a=candidate.lanes[0],
            b=candidate.lanes[1],
            apart=candidate.separation,
            ratio=candidate.cost_ratio,
        )
        if candidate.gap:
            detail += " " + tr("{n} frame(s) had no position across it.").format(n=candidate.gap)
        nodes.append(
            BraidNode(
                index=candidate.index,
                at=_at(times, candidate.index),
                lanes=candidate.lanes,
                accepted=False,
                display_frame=_frame(source_times, job.frame_rate, candidate.index),
                detail=detail,
            )
        )
    return sorted(nodes, key=lambda node: (node.index, node.accepted))


def _frame(times: np.ndarray, rate: float, index: int) -> int:
    if rate <= 0.0 or not 0 <= index < len(times):
        return index
    return int(round(float(times[index]) * rate))


def _at(times: np.ndarray, index: int) -> float:
    if len(times) == 0:
        return 0.0
    return float(times[max(0, min(index, len(times) - 1))])
