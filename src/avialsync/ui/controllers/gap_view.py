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

import math
from functools import partial
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

import numpy as np
from PySide6.QtCore import QTimer

from avialsync.core.columns import RegularTimes
from avialsync.core.settings_schema import Setting, setting_for
from avialsync.core.timeline import TimeMap
from avialsync.core.trials import GAP_FACTOR, holes_between
from avialsync.ui.preferences_dialog import read_setting, write_setting

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

#: More samples than this between two parts is a stream that kept recording.
_CONTINUOUS = 100_000

#: The preference behind View → Collapse Gaps Without Data.
COLLAPSE_SETTING = "playback/collapse_gaps"
_HOLE_CACHE: WeakKeyDictionary[object, dict[str, tuple[object, list[tuple[float, float]]]]] = (
    WeakKeyDictionary()
)


def _mapping_signature(window: MainWindow, source_id: str, kind: str) -> object:
    """Compact cache key for a source's timing state without scanning its samples."""
    if kind == "video":
        grid = window.video_grid
        try:
            pane = grid.panes[grid.pane_paths().index(source_id)]
        except ValueError:
            return None
        ft = pane._frame_times
        tm = pane.time_map
        return (0 if ft is None else len(ft), tm.offset, tm.drift_ms_per_hour, id(tm._exact_master))
    if kind == "imaging":
        pane_i = window.imaging_pane
        if source_id not in pane_i.source_paths():
            return None
        _loader, _config, tm = pane_i.source_config(source_id)
        return (len(pane_i.metadata_for(source_id).frame_times), tm.offset, tm.drift_ms_per_hour)
    if kind == "data":
        readers = window.source_readers(source_id)
        if not readers:
            return None
        tm = readers[0].time_map
        return (id(readers[0].source_reader), tm.offset, tm.drift_ms_per_hour, id(tm._exact_master))
    return None


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
    parts_key = tuple(parts)
    per_source_cache = _HOLE_CACHE.setdefault(overview, {})
    holes: dict[str, list[tuple[float, float]]] = {}
    for source_id, (start, end, kind, _group) in overview._coverage.items():
        if len(parts) < 2:
            holes[source_id] = []
            continue
        sig = _mapping_signature(window, source_id, kind)
        cache_key: Any = (start, end, kind, parts_key, sig)
        cached_entry = per_source_cache.get(source_id)
        if cached_entry is not None and cached_entry[0] == cache_key and sig is not None:
            holes[source_id] = list(cached_entry[1])
            continue
        computed = holes_between(
            (start, end), parts, partial(samples_between, window, source_id, kind)
        )
        holes[source_id] = computed
        if sig is not None:
            per_source_cache[source_id] = (cache_key, list(computed))
    for stale in set(per_source_cache) - set(overview._coverage):
        per_source_cache.pop(stale, None)
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


def _regular_data_samples(
    t_base: RegularTimes, mapping: TimeMap, a: float, b: float
) -> tuple[np.ndarray, float] | None:
    """Resolve inter-part presence on a ``RegularTimes`` grid in O(1) without array allocation."""
    n = len(t_base)
    if n == 0:
        return None
    src_a, src_b = sorted((mapping.to_source(a), mapping.to_source(b)))
    dt_src = float(t_base.stride) / float(t_base.rate)
    period = abs(float(mapping.to_master(t_base.t0 + dt_src) - mapping.to_master(t_base.t0)))
    if period <= 0.0:
        period = dt_src
    lo_i = max(0, int(t_base.searchsorted(src_a, side="left")) - 1)
    hi_i = min(n, int(t_base.searchsorted(src_b, side="right")) + 1) - 1
    while lo_i <= hi_i and float(mapping.to_master(float(t_base[lo_i]))) <= a:
        lo_i += 1
    while hi_i >= lo_i and float(mapping.to_master(float(t_base[hi_i]))) >= b:
        hi_i -= 1
    if hi_i < lo_i:
        return np.empty(0, dtype=np.float64), period
    count = hi_i - lo_i + 1
    if count > _CONTINUOUS:
        return None
    t_first = float(mapping.to_master(float(t_base[lo_i])))
    t_last = float(mapping.to_master(float(t_base[hi_i])))
    tol = period * GAP_FACTOR
    if t_first - a <= tol and b - t_last <= tol:
        return None
    if count == 1 or t_last <= t_first:
        return np.asarray([t_first], dtype=np.float64), period
    step = max(tol * 0.5, 1e-12)
    n_bridge = max(2, int(math.ceil((t_last - t_first) / step)) + 1)
    return np.linspace(t_first, t_last, n_bridge, dtype=np.float64), period


def _irregular_data_samples(
    src_reader: Any, mapping: TimeMap, a: float, b: float
) -> tuple[np.ndarray, float] | None:
    """Resolve inter-part samples on stored timestamps, bounding slice size first."""
    t_base, _values, gap_base = src_reader.mapped_columns()
    if isinstance(t_base, RegularTimes):
        return _regular_data_samples(t_base, mapping, a, b)
    n = len(t_base)
    if n == 0:
        return None
    src_a, src_b = sorted((mapping.to_source(a), mapping.to_source(b)))
    i0 = int(np.searchsorted(t_base, src_a, side="left"))
    i1 = int(np.searchsorted(t_base, src_b, side="right"))
    if i1 - i0 > _CONTINUOUS:
        load_level = getattr(src_reader, "_load_level", None)
        if callable(load_level):
            try:
                _t4k, _, _, gap_4k = load_level(4096)
                if not bool(np.any(gap_4k[i0 // 4096 : (i1 // 4096) + 1])):
                    return None
                gap_idx = np.flatnonzero(gap_base[i0:i1]) + i0
                if 0 < len(gap_idx) <= 1024:
                    pts = sorted(
                        {i0, max(i0, i1 - 1)}
                        | {int(g) for g in gap_idx}
                        | {min(n - 1, int(g) + 1) for g in gap_idx}
                    )
                    head = mapping.to_master_array(
                        np.asarray(t_base[: min(n, 256)], dtype=np.float64)
                    )
                    per = float(np.median(np.diff(head))) if len(head) > 1 else 0.0
                    return mapping.to_master_array(np.asarray(t_base[pts], dtype=np.float64)), per
            except (OSError, ValueError, KeyError, IndexError):
                return None
        return None
    sub = np.asarray(t_base[i0:i1], dtype=np.float64)
    period = 0.0
    if len(sub) <= 1 and n > 1:
        head = mapping.to_master_array(np.asarray(t_base[: min(n, 256)], dtype=np.float64))
        period = float(np.median(np.diff(head)))
    return mapping.to_master_array(sub), period


def _data_samples(
    window: MainWindow, source_id: str, a: float, b: float
) -> tuple[np.ndarray, float] | None:
    """The source's samples there, through its plot rows or, for a pose, its 3D readers."""
    readers = window.source_readers(source_id)
    if not readers:
        return None
    reader = readers[0]
    mapping = reader.time_map
    src_reader = reader.source_reader
    if hasattr(src_reader, "mapped_columns"):
        return _irregular_data_samples(src_reader, mapping, a, b)
    source = src_reader.raw_slice(mapping.to_source(a), mapping.to_source(b))[0]
    if len(source) > _CONTINUOUS:
        return None
    return mapping.to_master_array(np.asarray(source, dtype=np.float64)), 0.0
