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

Every stream answers "do you have data between *a* and *b*" from its own frames
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
from avialsync.core.trials import holes_between
from avialsync.ui.preferences_dialog import read_setting, write_setting

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

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
            (start, end), parts, partial(has_data_between, window, source_id, kind)
        )
    current = {source_id: list(overview._holes.get(source_id, ())) for source_id in holes}
    if holes != current:
        window.transport.set_coverage_holes(holes)


def has_data_between(window: MainWindow, source_id: str, kind: str, a: float, b: float) -> bool:
    """Whether *source_id* has a frame or sample strictly between master *a* and *b*."""
    if kind == "video":
        return _video_has(window, source_id, a, b)
    if kind == "imaging":
        return _imaging_has(window, source_id, a, b)
    if kind == "data":
        return _data_has(window, source_id, a, b)
    return True


def _between(times: np.ndarray | None, low: float, high: float) -> bool:
    if times is None or not len(times):
        return True
    first = int(np.searchsorted(times, low, side="right"))
    return first < len(times) and float(times[first]) < high


def _video_has(window: MainWindow, source_id: str, a: float, b: float) -> bool:
    grid = window.video_grid
    try:
        pane = grid.panes[grid.pane_paths().index(source_id)]
    except ValueError:
        return True
    mapping = pane.time_map
    return _between(pane._frame_times, mapping.to_source(a), mapping.to_source(b))


def _imaging_has(window: MainWindow, source_id: str, a: float, b: float) -> bool:
    pane = window.imaging_pane
    if source_id not in pane.source_paths():
        return True
    _loader, _config, mapping = pane.source_config(source_id)
    times = pane.metadata_for(source_id).frame_times
    return _between(times, mapping.to_source(a), mapping.to_source(b))


def _data_has(window: MainWindow, source_id: str, a: float, b: float) -> bool:
    readers = [
        channel.reader
        for channel in window.plot_pane.channels
        if channel.reader.source_id == source_id
    ]
    if not readers:
        return True
    for reader in readers:
        following = reader.neighbour_sample_time(a, 1)
        if following is None or following >= b:
            continue
        return True
    return False
