"""Active-learning suspect-frame scanner and navigation for 2D/3D pose review.

Scans memory-mapped pose columns on a background worker (via ``MainWindow._run_job``)
to locate frames with low model likelihood, abrupt velocity spikes (teleports or
identity jumps), or tracking dropouts, then steps through them with
``Next / Previous Suspect Frame``.
"""

from __future__ import annotations

import dataclasses
import threading
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
_SCAN_CHUNK = 1_000_000
_STATS_SUBSAMPLE = 100_000


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


def _cluster_sparse_peaks(indices: np.ndarray, scores: np.ndarray) -> list[tuple[int, float]]:
    """Pick ``(index, peak_score)`` from each contiguous run of flagged indices."""
    if len(indices) == 0:
        return []
    peaks: list[tuple[int, float]] = []
    run_start = 0
    for pos in range(1, len(indices) + 1):
        if (
            pos == len(indices)
            or int(indices[pos]) - int(indices[pos - 1]) > _MIN_CLUSTER_GAP_FRAMES
        ):
            seg_scores = scores[run_start:pos]
            best_rel = int(np.argmax(seg_scores))
            peaks.append((int(indices[run_start + best_rel]), float(seg_scores[best_rel])))
            run_start = pos
    return peaks


def _low_likelihood_suspects(
    source_id: str,
    point_name: str,
    lik_dir: Path,
    lik_ch: str,
    times: Any,
    n: int,
    time_map: TimeMap,
    threshold: float,
    override_map: dict[int, tuple[float, float]],
    cancel_event: threading.Event | None = None,
) -> list[SuspectFrame]:
    """Flag contiguous runs where model likelihood drops below *threshold*."""
    rl = PyramidReader(lik_dir, lik_ch)
    try:
        _, lik, _ = rl.mapped_columns()
        m = min(n, len(lik))
        if m == 0:
            return []
        idx_parts: list[np.ndarray] = []
        val_parts: list[np.ndarray] = []
        for start in range(0, m, _SCAN_CHUNK):
            if cancel_event is not None and cancel_event.is_set():
                return []
            stop = min(start + _SCAN_CHUNK, m)
            chunk = np.asarray(lik[start:stop], dtype=np.float64)
            if override_map:
                chunk = chunk.copy()
                for idx in override_map:
                    if start <= idx < stop:
                        chunk[idx - start] = 1.0
            low_local = np.flatnonzero(np.isfinite(chunk) & (chunk < threshold))
            if len(low_local):
                idx_parts.append(low_local + start)
                val_parts.append(chunk[low_local])
        if not idx_parts:
            return []
        all_idx = np.concatenate(idx_parts)
        all_vals = np.concatenate(val_parts)
        found: list[SuspectFrame] = []
        for idx, neg_val in _cluster_sparse_peaks(all_idx, -all_vals):
            val = -neg_val
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


def _coord_slice(
    arr: Any, start: int, stop: int, override_map: dict[int, tuple[float, float]], axis: int | None
) -> np.ndarray:
    out = np.asarray(arr[start:stop], dtype=np.float64)
    if axis is not None and override_map:
        out = out.copy()
        for idx, coords in override_map.items():
            if start <= idx < stop:
                out[idx - start] = coords[axis]
    return out


def _step_cutoff(med: float, mad: float, span: float, *, is_3d: bool) -> float:
    if not is_3d:
        return max(med + 6.0 * max(mad, 1.0), 18.0)
    mad_floor = max(med * 0.25, span * 1e-3, 1e-6)
    step_floor = span * 0.05
    return max(med + 6.0 * max(mad, mad_floor), step_floor)


def _coordinate_span(arrays: tuple[np.ndarray, ...]) -> float:
    span = 1e-6
    for arr in arrays:
        fin = arr[np.isfinite(arr)]
        if len(fin) >= 2:
            span = max(span, float(np.max(fin) - np.min(fin)))
    return span


def _step_array(
    xs: np.ndarray,
    ys: np.ndarray,
    zs: np.ndarray | None,
    gx: np.ndarray,
    gy: np.ndarray,
    gz: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    dx = np.diff(xs)
    dy = np.diff(ys)
    if zs is not None and gz is not None:
        dz = np.diff(zs)
        step = np.sqrt(dx * dx + dy * dy + dz * dz)
        gapped = gx[:-1] | gy[:-1] | gz[:-1]
    else:
        step = np.hypot(dx, dy)
        gapped = gx[:-1] | gy[:-1]
    return step, np.isfinite(step) & ~gapped


def _velocity_jump_suspects(
    source_id: str,
    point_name: str,
    is_3d: bool,
    times: Any,
    xs: Any,
    ys: Any,
    zs: Any | None,
    gx: Any,
    gy: Any,
    gz: Any | None,
    n: int,
    time_map: TimeMap,
    override_map: dict[int, tuple[float, float]] | None = None,
    cancel_event: threading.Event | None = None,
) -> list[SuspectFrame]:
    """Flag abrupt frame-to-frame 2D/3D velocity spikes with scale-adaptive cutoffs."""
    if n < 5:
        return []
    ov = override_map or {}
    if n <= _SCAN_CHUNK:
        xc = _coord_slice(xs, 0, n, ov, 0)
        yc = _coord_slice(ys, 0, n, ov, 1)
        zc = _coord_slice(zs, 0, n, ov, None) if zs is not None else None
        gxc = np.asarray(gx[:n], dtype=bool)
        gyc = np.asarray(gy[:n], dtype=bool)
        gzc = np.asarray(gz[:n], dtype=bool) if gz is not None else None
        step, valid_steps = _step_array(xc, yc, zc, gxc, gyc, gzc)
        if int(np.count_nonzero(valid_steps)) < 4:
            return []
        finite_vals = step[valid_steps]
        med = float(np.median(finite_vals))
        mad = float(np.median(np.abs(finite_vals - med))) * 1.4826
        span = _coordinate_span((xc, yc) + ((zc,) if zc is not None else ())) if is_3d else 1.0
        cutoff = _step_cutoff(med, mad, span, is_3d=is_3d)
        spike_idx = np.flatnonzero(valid_steps & (step > cutoff))
        peaks = _cluster_sparse_peaks(spike_idx, step[spike_idx])
    else:
        peaks, cutoff = _chunked_velocity_peaks(is_3d, xs, ys, zs, gx, gy, gz, n, ov, cancel_event)
        if not peaks or cutoff <= 0.0:
            return []

    found: list[SuspectFrame] = []
    for step_i, dist in peaks:
        idx = step_i + 1
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


def _chunked_velocity_peaks(
    is_3d: bool,
    xs: Any,
    ys: Any,
    zs: Any | None,
    gx: Any,
    gy: Any,
    gz: Any | None,
    n: int,
    ov: dict[int, tuple[float, float]],
    cancel_event: threading.Event | None,
) -> tuple[list[tuple[int, float]], float]:
    """Estimate robust step cutoff from a bounded stride, then scan in 1M-sample chunks."""
    stride = max(1, (n - 1) // _STATS_SUBSAMPLE)
    s0 = np.arange(0, n - 1, stride, dtype=np.int64)
    s1 = s0 + 1
    x0, x1 = np.asarray(xs[s0], dtype=np.float64), np.asarray(xs[s1], dtype=np.float64)
    y0, y1 = np.asarray(ys[s0], dtype=np.float64), np.asarray(ys[s1], dtype=np.float64)
    gapped = np.asarray(gx[s0], dtype=bool) | np.asarray(gy[s0], dtype=bool)
    if zs is not None and gz is not None:
        z0, z1 = np.asarray(zs[s0], dtype=np.float64), np.asarray(zs[s1], dtype=np.float64)
        dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
        sub_step = np.sqrt(dx * dx + dy * dy + dz * dz)
        gapped |= np.asarray(gz[s0], dtype=bool)
        span = _coordinate_span((x0, y0, z0)) if is_3d else 1.0
    else:
        sub_step = np.hypot(x1 - x0, y1 - y0)
        span = _coordinate_span((x0, y0)) if is_3d else 1.0
    valid = np.isfinite(sub_step) & ~gapped
    if int(np.count_nonzero(valid)) < 4:
        return [], 0.0
    finite_vals = sub_step[valid]
    med = float(np.median(finite_vals))
    mad = float(np.median(np.abs(finite_vals - med))) * 1.4826
    cutoff = _step_cutoff(med, mad, span, is_3d=is_3d)

    idx_parts: list[np.ndarray] = []
    val_parts: list[np.ndarray] = []
    for start in range(0, n - 1, _SCAN_CHUNK):
        if cancel_event is not None and cancel_event.is_set():
            return [], 0.0
        stop = min(start + _SCAN_CHUNK + 1, n)
        xc = _coord_slice(xs, start, stop, ov, 0)
        yc = _coord_slice(ys, start, stop, ov, 1)
        zc = _coord_slice(zs, start, stop, ov, None) if zs is not None else None
        gxc = np.asarray(gx[start:stop], dtype=bool)
        gyc = np.asarray(gy[start:stop], dtype=bool)
        gzc = np.asarray(gz[start:stop], dtype=bool) if gz is not None else None
        step, valid_c = _step_array(xc, yc, zc, gxc, gyc, gzc)
        spikes = np.flatnonzero(valid_c & (step > cutoff))
        if len(spikes):
            idx_parts.append(spikes + start)
            val_parts.append(step[spikes])
    if not idx_parts:
        return [], cutoff
    return _cluster_sparse_peaks(np.concatenate(idx_parts), np.concatenate(val_parts)), cutoff


def _scan_point(
    source_id: str,
    point: Any,
    cache_dir: Path,
    time_map: TimeMap,
    threshold: float,
    channel_dirs: dict[str, Path] | None,
    pt_overrides: list[tuple[int, float, float]],
    cancel_event: threading.Event | None = None,
) -> list[SuspectFrame]:
    """Scan one bodypart's channels for low-confidence and velocity-jump frames."""
    if "x" not in point.axes or "y" not in point.axes:
        return []
    x_ch, y_ch = point.channel("x"), point.channel("y")
    x_dir = _resolve_channel_dir(x_ch, cache_dir, channel_dirs)
    y_dir = _resolve_channel_dir(y_ch, cache_dir, channel_dirs)
    if x_dir is None or y_dir is None:
        return []
    is_3d = "z" in point.axes
    rz: PyramidReader | None = None
    if is_3d:
        z_ch = point.channel("z")
        z_dir = _resolve_channel_dir(z_ch, cache_dir, channel_dirs)
        if z_dir is not None:
            rz = PyramidReader(z_dir, z_ch)
    rx = PyramidReader(x_dir, x_ch)
    ry = PyramidReader(y_dir, y_ch)
    try:
        times, xs, gx = rx.mapped_columns()
        _, ys, gy = ry.mapped_columns()
        zs: Any | None = None
        gz: Any | None = None
        n = min(len(times), len(xs), len(ys))
        if rz is not None:
            _, zs, gz = rz.mapped_columns()
            n = min(n, len(zs))
        if n == 0:
            return []
        override_map = {idx: (ox, oy) for idx, ox, oy in pt_overrides if 0 <= idx < n}
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
                    override_map,
                    cancel_event,
                )
            )
        if cancel_event is not None and cancel_event.is_set():
            return []
        suspects.extend(
            _velocity_jump_suspects(
                source_id,
                point.name,
                is_3d,
                times,
                xs,
                ys,
                zs,
                gx,
                gy,
                gz,
                n,
                time_map,
                override_map,
                cancel_event,
            )
        )
        return suspects
    finally:
        rx.close()
        ry.close()
        if rz is not None:
            rz.close()


def find_suspects_in_cache(
    source_id: str,
    cache_dir: Path,
    schema: PoseSchema,
    time_map: TimeMap,
    threshold: float,
    channel_dirs: dict[str, Path] | None = None,
    point_overrides: dict[tuple[str, int], tuple[float, float]] | None = None,
    *,
    cancel_event: threading.Event | None = None,
) -> list[SuspectFrame]:
    """Scan one pose cache off-thread for low likelihood, jumps, and dropouts."""
    overrides_by_point: dict[str, list[tuple[int, float, float]]] = {}
    if point_overrides:
        for (pt_name, idx), (ox, oy) in point_overrides.items():
            overrides_by_point.setdefault(pt_name, []).append((idx, float(ox), float(oy)))

    candidates: list[SuspectFrame] = []
    for point in schema.points:
        if cancel_event is not None and cancel_event.is_set():
            return []
        candidates.extend(
            _scan_point(
                source_id,
                point,
                cache_dir,
                time_map,
                threshold,
                channel_dirs,
                overrides_by_point.get(point.name, []),
                cancel_event,
            )
        )

    candidates.sort(key=lambda item: item.severity, reverse=True)
    trimmed = candidates[:_MAX_SUSPECTS_PER_SOURCE]
    trimmed.sort(key=lambda item: (item.t_master, -item.severity))
    return _deduplicate_nearby(trimmed)


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
    cancelled = Signal()
    progress = Signal(int)

    def __init__(self, signature: int, specs: list[_SourceSpec], threshold: float) -> None:
        super().__init__()
        self._signature = signature
        self._specs = specs
        self._threshold = threshold
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        total_points = max(1, sum(len(spec.schema.points) for spec in self._specs))
        done_points = 0
        all_suspects: list[SuspectFrame] = []
        for spec in self._specs:
            if self._cancel.is_set():
                self.cancelled.emit()
                return
            overrides_by_pt: dict[str, list[tuple[int, float, float]]] = {}
            for (pt_name, idx), (ox, oy) in spec.point_overrides.items():
                overrides_by_pt.setdefault(pt_name, []).append((idx, float(ox), float(oy)))
            src_candidates: list[SuspectFrame] = []
            for point in spec.schema.points:
                if self._cancel.is_set():
                    self.cancelled.emit()
                    return
                src_candidates.extend(
                    _scan_point(
                        spec.source_id,
                        point,
                        spec.cache_dir,
                        spec.time_map,
                        self._threshold,
                        spec.channel_dirs or None,
                        overrides_by_pt.get(point.name, []),
                        self._cancel,
                    )
                )
                done_points += 1
                self.progress.emit(min(100, int(done_points * 100 / total_points)))
            src_candidates.sort(key=lambda item: item.severity, reverse=True)
            trimmed = src_candidates[:_MAX_SUSPECTS_PER_SOURCE]
            trimmed.sort(key=lambda item: (item.t_master, -item.severity))
            all_suspects.extend(_deduplicate_nearby(trimmed))
        if self._cancel.is_set():
            self.cancelled.emit()
            return
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
        worker.cancelled.connect(thread.quit)

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
