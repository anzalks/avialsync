"""Where each stream has no data between a session's parts, and the collapsed view (D-218).

A session made of parts -- trials, recordings -- keeps them on their own clock
(D-217), so the time between two parts is on the timeline. Each stream's lane in
Data Streams is empty wherever it recorded nothing between two parts: it shows
when that stream starts and stops. A dropout inside a part is not that; it stays
a data gap.

**Collapse Gaps Without Data** (View menu, and Preferences → Playback; on by
default) draws the time no stream has data in as a break of no width, so neither
the slider, the strip nor playback runs through minutes of nothing. It is a view:
master time, timestamps and readouts are unchanged.

Every stream answers "what do you have between *a* and *b*" from its own frames
or samples, so any plugin that declares its parts gets this without code of its
own. A stream that cannot answer is taken to have data -- nothing is hidden on
a guess.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QTimer

from avialsync.core.settings_schema import Setting, setting_for
from avialsync.core.timeline import TimeMap
from avialsync.core.trials import holes_between
from avialsync.ui.preferences_dialog import read_setting, write_setting

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

#: More samples than this between two parts is a stream that kept recording.
_CONTINUOUS = 100_000

#: The preference behind View → Collapse Gaps Without Data.
COLLAPSE_SETTING = "playback/collapse_gaps"


def install(window: MainWindow) -> None:
    """Follow the evidence: holes are found again whenever sources or parts change."""
    # Owned by the window, so it stops with it; a zero-delay single shot
    # coalesces a burst of evidence changes into one refresh.
    timer = QTimer(window)
    timer.setSingleShot(True)
    timer.setInterval(0)
    timer.timeout.connect(lambda: refresh_holes(window))
    window.transport.overview.evidence_changed.connect(timer.start)
    window.transport.set_collapse_gaps(collapse_enabled())


def _setting() -> Setting:
    setting = setting_for(COLLAPSE_SETTING)
    assert setting is not None  # declared in core.settings_schema
    return setting


def collapse_enabled() -> bool:
    return bool(read_setting(_setting()))


def set_collapse(window: MainWindow, collapse: bool) -> None:
    """Remember the choice and redraw the timeline with or without the gaps."""
    write_setting(_setting(), bool(collapse))
    window.transport.set_collapse_gaps(bool(collapse))
    window.plot_pane.set_time_warp(window.transport.warp)


def refresh_holes(window: MainWindow) -> None:
    """Find each source's holes between the session's parts, and publish them if changed.

    Publishing only a change is what lets this follow ``evidence_changed``,
    which publishing itself emits, without looping.
    """
    overview = window.transport.overview
    parts = [(start, end) for start, end, _name in overview._segments]
    holes: dict[str, list[tuple[float, float]]] = {}
    for source_id, (start, end, kind, _group) in overview._coverage.items():
        if len(parts) < 2:
            holes[source_id] = []
            continue
        holes[source_id] = holes_between(
            (start, end), parts, partial(samples_between, window, source_id, kind)
        )
    current = {source_id: list(overview._holes.get(source_id, ())) for source_id in holes}
    if holes != current:
        window.transport.set_coverage_holes(holes)
    # The plots draw the same collapsed time as the timeline, in every plugin's rows.
    window.plot_pane.set_time_warp(window.transport.warp)


def samples_between(
    window: MainWindow, source_id: str, kind: str, a: float, b: float
) -> tuple[np.ndarray, float] | None:
    """*source_id*'s sample or frame times between master *a* and *b*, and its spacing.

    ``None`` when it cannot tell yet -- not open, no rows -- which counts as data.
    """
    if kind == "video":
        return _video_samples(window, source_id, a, b)
    if kind == "imaging":
        return _imaging_samples(window, source_id, a, b)
    if kind == "data":
        return _data_samples(window, source_id, a, b)
    return None


def _frames(
    times: np.ndarray | None, mapping: TimeMap, a: float, b: float
) -> tuple[np.ndarray, float] | None:
    """Frames with source *times* under *mapping* that fall between master *a* and *b*."""
    if times is None or len(times) < 2:
        return None
    low, high = sorted((mapping.to_source(a), mapping.to_source(b)))
    first = int(np.searchsorted(times, low, side="right"))
    stop = int(np.searchsorted(times, high, side="left"))
    period = float(np.median(np.diff(times[: min(len(times), 1000)])))
    return mapping.to_master_array(np.asarray(times[first:stop])), period


def _video_samples(
    window: MainWindow, source_id: str, a: float, b: float
) -> tuple[np.ndarray, float] | None:
    grid = window.video_grid
    try:
        pane = grid.panes[grid.pane_paths().index(source_id)]
    except ValueError:
        return None
    # Not open yet: asked again when it is (``_on_video_pane_ready``).
    return _frames(pane._frame_times, pane.time_map, a, b)


def _imaging_samples(
    window: MainWindow, source_id: str, a: float, b: float
) -> tuple[np.ndarray, float] | None:
    pane = window.imaging_pane
    if source_id not in pane.source_paths():
        return None
    _loader, _config, mapping = pane.source_config(source_id)
    return _frames(pane.metadata_for(source_id).frame_times, mapping, a, b)


def _data_samples(
    window: MainWindow, source_id: str, a: float, b: float
) -> tuple[np.ndarray, float] | None:
    """The source's samples there, through its plot rows or, for a pose, its 3D readers."""
    readers = window.source_readers(source_id)
    if not readers:
        return None
    reader = readers[0]
    mapping = reader.time_map
    source = reader.source_reader.raw_slice(mapping.to_source(a), mapping.to_source(b))[0]
    if len(source) > _CONTINUOUS:
        # Recorded straight through: data, without mapping a million samples.
        return np.asarray([(a + b) / 2.0]), 0.0
    return mapping.to_master_array(np.asarray(source, dtype=np.float64)), 0.0
