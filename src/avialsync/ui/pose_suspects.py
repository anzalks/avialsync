"""Active-learning suspect-frame scanner and navigation for 2D/3D pose review.

Scans memory-mapped pose columns on a background worker (via ``MainWindow._run_job``)
to locate frames with low model likelihood, abrupt velocity spikes (teleports or
identity jumps), or tracking dropouts, then steps through them with
``Next / Previous Suspect Frame``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Slot

from avialsync.core.point_edits import PointKey
from avialsync.core.pyramid import PyramidReader
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread
from avialsync.ui.pose_overlay_extras import confidence_threshold

if TYPE_CHECKING:
    from avialsync.core.pose import PoseSchema
    from avialsync.core.timeline import TimeMap
    from avialsync.ui.main_window import MainWindow

__all__ = [
    "SuspectFrame",
    "find_suspects_in_cache",
    "jump_suspect_frame",
]

_MAX_SUSPECTS_PER_SOURCE = 250
_MIN_CLUSTER_GAP_FRAMES = 3


@dataclasses.dataclass(frozen=True)
class SuspectFrame:
    """One flagged instant worth human inspection in Fix Tracker."""

    t_master: float
    source_id: str
    point: str
    sample_index: int
    severity: float
    reason: str


@dataclasses.dataclass(frozen=True)
class _SourceSpec:
    source_id: str
    cache_dir: Path
    schema: PoseSchema
    time_map: TimeMap
    channel_dirs: dict[str, Path] = dataclasses.field(default_factory=dict)
    point_overrides: dict[tuple[str, int], tuple[float, float]] = dataclasses.field(
        default_factory=dict
    )


def _resolve_channel_dir(
    ch_name: str,
    cache_dir: Path,
    channel_dirs: dict[str, Path] | None,
) -> Path | None:
    """Return the directory containing *ch_name*'s pyramid files, or None if missing."""
    target = (channel_dirs or {}).get(ch_name, cache_dir)
    if (target / f"{ch_name}_v.npy").exists() or (target / f"{ch_name}_layout.json").exists():
        return target
    return None


def _low_likelihood_suspects(
    source_id: str,
    point_name: str,
    lik_dir: Path,
    lik_ch: str,
    times: np.ndarray,
    n: int,
    time_map: TimeMap,
    threshold: float,
    pt_overrides: list[tuple[int, float, float]],
) -> list[SuspectFrame]:
    """Flag contiguous runs where model likelihood drops below *threshold*."""
    rl = PyramidReader(lik_dir, lik_ch)
    try:
        _, lik, _ = rl.mapped_columns()
        m = min(n, len(lik))
        if m == 0:
            return []
        if pt_overrides:
            lik_arr = np.array(lik[:m], dtype=np.float64, copy=True)
            for idx, _, _ in pt_overrides:
                if 0 <= idx < m:
                    lik_arr[idx] = 1.0
        else:
            lik_arr = lik[:m]
        low_mask = np.isfinite(lik_arr) & (lik_arr < threshold)
        found: list[SuspectFrame] = []
        for idx in _cluster_peaks(low_mask, -np.asarray(lik_arr, dtype=np.float64)):
            val = float(lik_arr[idx])
            t_m = float(time_map.to_master(float(times[idx])))
            found.append(
                SuspectFrame(
                    t_master=t_m,
                    source_id=source_id,
                    point=point_name,
                    sample_index=idx,
                    severity=1.0 + (threshold - val),
                    reason=tr("{point}: low confidence ({val:.2f})").format(
                        point=point_name, val=val
                    ),
                )
            )
        return found
    finally:
        rl.close()


def _velocity_jump_suspects(
    source_id: str,
    point_name: str,
    is_3d: bool,
    times: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    gx: np.ndarray,
    gy: np.ndarray,
    n: int,
    time_map: TimeMap,
) -> list[SuspectFrame]:
    """Flag abrupt frame-to-frame velocity spikes (> median + 6 * MAD, floor 18)."""
    if n < 5:
        return []
    step = np.hypot(np.diff(xs[:n]), np.diff(ys[:n]))
    valid_steps = np.isfinite(step) & ~(gx[: n - 1] | gy[: n - 1])
    if np.count_nonzero(valid_steps) < 4:
        return []
    finite_vals = step[valid_steps]
    med = float(np.median(finite_vals))
    mad = float(np.median(np.abs(finite_vals - med))) * 1.4826
    cutoff = max(med + 6.0 * max(mad, 1.0), 18.0)
    spike_mask = valid_steps & (step > cutoff)
    found: list[SuspectFrame] = []
    for step_i in _cluster_peaks(spike_mask, step):
        idx = step_i + 1
        dist = float(step[step_i])
        t_m = float(time_map.to_master(float(times[idx])))
        reason = (
            tr("{point}: jump ({dist:.1f} units)").format(point=point_name, dist=dist)
            if is_3d
            else tr("{point}: jump ({dist:.1f} px)").format(point=point_name, dist=dist)
        )
        found.append(
            SuspectFrame(
                t_master=t_m,
                source_id=source_id,
                point=point_name,
                sample_index=idx,
                severity=dist / cutoff,
                reason=reason,
            )
        )
    return found


def _scan_point(
    source_id: str,
    point: Any,
    cache_dir: Path,
    time_map: TimeMap,
    threshold: float,
    channel_dirs: dict[str, Path] | None,
    pt_overrides: list[tuple[int, float, float]],
) -> list[SuspectFrame]:
    """Scan one bodypart's channels for low-confidence and velocity-jump frames."""
    if "x" not in point.axes or "y" not in point.axes:
        return []
    x_ch, y_ch = point.channel("x"), point.channel("y")
    x_dir = _resolve_channel_dir(x_ch, cache_dir, channel_dirs)
    y_dir = _resolve_channel_dir(y_ch, cache_dir, channel_dirs)
    if x_dir is None or y_dir is None:
        return []
    rx = PyramidReader(x_dir, x_ch)
    ry = PyramidReader(y_dir, y_ch)
    try:
        times, xs, gx = rx.mapped_columns()
        _, ys, gy = ry.mapped_columns()
        n = min(len(times), len(xs), len(ys))
        if n == 0:
            return []
        if pt_overrides:
            xs = np.array(xs[:n], dtype=np.float64, copy=True)
            ys = np.array(ys[:n], dtype=np.float64, copy=True)
            for idx, ox, oy in pt_overrides:
                if 0 <= idx < n:
                    xs[idx] = ox
                    ys[idx] = oy
        suspects: list[SuspectFrame] = []
        lik_ch = point.likelihood_channel
        lik_dir = _resolve_channel_dir(lik_ch, cache_dir, channel_dirs) if lik_ch else None
        if lik_ch and lik_dir is not None:
            suspects.extend(
                _low_likelihood_suspects(
                    source_id,
                    point.name,
                    lik_dir,
                    lik_ch,
                    times,
                    n,
                    time_map,
                    threshold,
                    pt_overrides,
                )
            )
        suspects.extend(
            _velocity_jump_suspects(
                source_id, point.name, "z" in point.axes, times, xs, ys, gx, gy, n, time_map
            )
        )
        return suspects
    finally:
        rx.close()
        ry.close()


def find_suspects_in_cache(
    source_id: str,
    cache_dir: Path,
    schema: PoseSchema,
    time_map: TimeMap,
    threshold: float,
    channel_dirs: dict[str, Path] | None = None,
    point_overrides: dict[tuple[str, int], tuple[float, float]] | None = None,
) -> list[SuspectFrame]:
    """Scan one pose cache off-thread for low likelihood, jumps, and dropouts."""
    overrides_by_point: dict[str, list[tuple[int, float, float]]] = {}
    if point_overrides:
        for (pt_name, idx), (ox, oy) in point_overrides.items():
            overrides_by_point.setdefault(pt_name, []).append((idx, float(ox), float(oy)))

    candidates: list[SuspectFrame] = []
    for point in schema.points:
        candidates.extend(
            _scan_point(
                source_id,
                point,
                cache_dir,
                time_map,
                threshold,
                channel_dirs,
                overrides_by_point.get(point.name, []),
            )
        )

    candidates.sort(key=lambda item: item.severity, reverse=True)
    trimmed = candidates[:_MAX_SUSPECTS_PER_SOURCE]
    trimmed.sort(key=lambda item: (item.t_master, -item.severity))
    return _deduplicate_nearby(trimmed)


def _cluster_peaks(mask: np.ndarray, score: np.ndarray) -> list[int]:
    """Pick the peak-scoring index from each contiguous run of True values."""
    indices = np.flatnonzero(mask)
    if len(indices) == 0:
        return []
    peaks: list[int] = []
    run_start = 0
    for pos in range(1, len(indices) + 1):
        if (
            pos == len(indices)
            or int(indices[pos]) - int(indices[pos - 1]) > _MIN_CLUSTER_GAP_FRAMES
        ):
            segment = indices[run_start:pos]
            best = int(segment[int(np.argmax(score[segment]))])
            peaks.append(best)
            run_start = pos
    return peaks


def _deduplicate_nearby(items: list[SuspectFrame], min_dt: float = 0.02) -> list[SuspectFrame]:
    """Collapse simultaneous suspects across body parts on the same frame."""
    deduped: list[SuspectFrame] = []
    for item in items:
        if deduped and abs(item.t_master - deduped[-1].t_master) <= min_dt:
            if item.severity > deduped[-1].severity:
                deduped[-1] = item
            continue
        deduped.append(item)
    return deduped


class _SuspectScanWorker(QObject):
    finished = Signal(object, object)  # signature, list[SuspectFrame]

    def __init__(self, signature: int, specs: list[_SourceSpec], threshold: float) -> None:
        super().__init__()
        self._signature = signature
        self._specs = specs
        self._threshold = threshold

    @Slot()
    def run(self) -> None:
        all_suspects: list[SuspectFrame] = []
        for spec in self._specs:
            all_suspects.extend(
                find_suspects_in_cache(
                    spec.source_id,
                    spec.cache_dir,
                    spec.schema,
                    spec.time_map,
                    self._threshold,
                    channel_dirs=spec.channel_dirs or None,
                    point_overrides=spec.point_overrides or None,
                )
            )
        all_suspects.sort(key=lambda item: item.t_master)
        self.finished.emit(self._signature, _deduplicate_nearby(all_suspects))


def _collect_specs(window: MainWindow) -> list[_SourceSpec]:
    show_original = bool(getattr(window, "_show_original_tracker", False))
    edited_gens = getattr(window, "_edited_generations", {})
    point_edits = getattr(window, "point_edits", None)
    specs: list[_SourceSpec] = []
    for source_id, schema in window._pose_schemas.items():
        cache_dir = window._pose_cache_dirs.get(source_id)
        if cache_dir is None or not cache_dir.exists():
            continue
        tmap = _time_map_for_pose(window, source_id)
        ch_dirs: dict[str, Path] = {}
        overrides: dict[tuple[str, int], tuple[float, float]] = {}
        if not show_original:
            gen = edited_gens.get(source_id)
            if gen is not None and hasattr(gen, "directories"):
                ch_dirs = dict(gen.directories)
            if point_edits is not None:
                overrides = {
                    (pk.point, pk.index): coords
                    for pk, coords in point_edits.items()
                    if pk.source_id == source_id
                }
        specs.append(
            _SourceSpec(
                source_id=source_id,
                cache_dir=cache_dir,
                schema=schema,
                time_map=tmap,
                channel_dirs=ch_dirs,
                point_overrides=overrides,
            )
        )
    return specs


def _time_map_for_pose(window: MainWindow, source_id: str) -> Any:
    from avialsync.core.timeline import TimeMap

    for sources in window._overlay_sources.values():
        entry = sources.get(source_id)
        if entry is None:
            continue
        for readers in (entry.get("points") or {}).values():
            return readers[0].time_map.copy()
    for reader in window._pose_3d_sources.get(source_id, ()):
        return reader.time_map.copy()
    return TimeMap()


def _signature_for(window: MainWindow, specs: list[_SourceSpec], threshold: float) -> int:
    show_original = bool(getattr(window, "_show_original_tracker", False))
    n_point_edits = len(getattr(window, "point_edits", ()))
    n_swaps = sum(1 for _ in getattr(window, "identity_swaps", ()))
    return hash(
        (
            round(threshold, 4),
            show_original,
            n_point_edits,
            n_swaps,
            tuple(
                (
                    s.source_id,
                    str(s.cache_dir),
                    round(s.time_map.offset, 6),
                    round(s.time_map.drift_ms_per_hour, 6),
                    len(getattr(s.time_map, "_exact_master", ()) or ()),
                    tuple(sorted((k, str(v)) for k, v in s.channel_dirs.items())),
                    tuple(sorted(s.point_overrides.items())),
                )
                for s in specs
            ),
        )
    )


def jump_suspect_frame(window: MainWindow, direction: int) -> None:
    """Jump to the next (``+1``) or previous (``-1``) suspect pose frame."""
    specs = _collect_specs(window)
    if not specs:
        return
    threshold = confidence_threshold()
    sig = _signature_for(window, specs, threshold)
    cached: tuple[int, list[SuspectFrame]] | None = getattr(window, "_suspect_cache", None)
    if cached is not None and cached[0] == sig:
        _apply_jump(window, cached[1], direction)
        return

    session_gen = window.session_runtime.generation
    worker = _SuspectScanWorker(sig, specs, threshold)

    def _on_done(done_sig: int, suspects: list[SuspectFrame]) -> None:
        if window.session_runtime.generation != session_gen:
            return
        window._suspect_cache = (done_sig, suspects)
        _apply_jump(window, suspects, direction)

    def _wire(thread: QThread) -> None:
        worker.finished.connect(on_ui_thread(_on_done, window))
        worker.finished.connect(thread.quit)

    window._run_job(worker, label=tr("Scanning pose for suspect frames"), configure=_wire)


def _apply_jump(window: MainWindow, suspects: list[SuspectFrame], direction: int) -> None:
    if not suspects:
        window.notifications.show_success(
            tr("No suspect pose frames found below the current threshold.")
        )
        return
    now = window.clock.state.t
    eps = 1e-4
    if direction > 0:
        chosen = next((s for s in suspects if s.t_master > now + eps), suspects[0])
    else:
        chosen = next((s for s in reversed(suspects) if s.t_master < now - eps), suspects[-1])
    bounds = window.clock.state.bounds
    target = (
        max(bounds[0], min(bounds[1], chosen.t_master))
        if bounds[1] > bounds[0]
        else chosen.t_master
    )
    window.player.seek(target, exact=True)
    window.video_grid.highlight_point(PointKey(chosen.source_id, chosen.point, chosen.sample_index))
    window._highlight_timer.start(2500)
    message = tr("Suspect frame — {reason} at {time:.3f} s").format(
        reason=chosen.reason, time=target
    )
    transport = getattr(window, "transport", None)
    if transport is not None and hasattr(transport, "set_status"):
        transport.set_status(message)
    else:
        window.statusBar().showMessage(message, 3500)
