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


def find_suspects_in_cache(
    source_id: str,
    cache_dir: Path,
    schema: PoseSchema,
    time_map: TimeMap,
    threshold: float,
) -> list[SuspectFrame]:
    """Scan one pose cache off-thread for low likelihood, jumps, and dropouts."""
    candidates: list[SuspectFrame] = []
    available = {p.stem[:-2] for p in cache_dir.glob("*_v.npy")} | {
        p.name[: -len("_layout.json")] for p in cache_dir.glob("*_layout.json")
    }
    for point in schema.points:
        if "x" not in point.axes or "y" not in point.axes:
            continue
        x_ch, y_ch = point.channel("x"), point.channel("y")
        if x_ch not in available or y_ch not in available:
            continue
        rx = PyramidReader(cache_dir, x_ch)
        ry = PyramidReader(cache_dir, y_ch)
        try:
            times, xs, gx = rx.mapped_columns()
            _, ys, gy = ry.mapped_columns()
            n = min(len(times), len(xs), len(ys))
            if n == 0:
                continue

            # 1. Likelihood below threshold
            lik_ch = point.likelihood_channel
            if lik_ch and lik_ch in available:
                rl = PyramidReader(cache_dir, lik_ch)
                try:
                    _, lik, _ = rl.mapped_columns()
                    m = min(n, len(lik))
                    low_mask = np.isfinite(lik[:m]) & (lik[:m] < threshold)
                    for idx in _cluster_peaks(low_mask, -np.asarray(lik[:m], dtype=np.float64)):
                        val = float(lik[idx])
                        t_m = float(time_map.to_master(float(times[idx])))
                        candidates.append(
                            SuspectFrame(
                                t_master=t_m,
                                source_id=source_id,
                                point=point.name,
                                sample_index=idx,
                                severity=1.0 + (threshold - val),
                                reason=f"{point.name}: low confidence ({val:.2f})",
                            )
                        )
                finally:
                    rl.close()

            # 2. Abrupt frame-to-frame velocity spikes (> median + 6 * MAD, floor 15 px)
            if n >= 5:
                dx = np.diff(xs[:n])
                dy = np.diff(ys[:n])
                step = np.hypot(dx, dy)
                valid_steps = np.isfinite(step) & ~(gx[: n - 1] | gy[: n - 1])
                if np.count_nonzero(valid_steps) >= 4:
                    finite_vals = step[valid_steps]
                    med = float(np.median(finite_vals))
                    mad = float(np.median(np.abs(finite_vals - med))) * 1.4826
                    cutoff = max(med + 6.0 * max(mad, 1.0), 18.0)
                    spike_mask = valid_steps & (step > cutoff)
                    for step_i in _cluster_peaks(spike_mask, step):
                        idx = step_i + 1
                        dist = float(step[step_i])
                        t_m = float(time_map.to_master(float(times[idx])))
                        candidates.append(
                            SuspectFrame(
                                t_master=t_m,
                                source_id=source_id,
                                point=point.name,
                                sample_index=idx,
                                severity=dist / cutoff,
                                reason=f"{point.name}: jump ({dist:.1f} px)",
                            )
                        )
        finally:
            rx.close()
            ry.close()

    # Keep top suspects bounded, then return sorted chronologically
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
                    spec.source_id, spec.cache_dir, spec.schema, spec.time_map, self._threshold
                )
            )
        all_suspects.sort(key=lambda item: item.t_master)
        self.finished.emit(self._signature, _deduplicate_nearby(all_suspects))


def _collect_specs(window: MainWindow) -> list[_SourceSpec]:
    specs: list[_SourceSpec] = []
    for source_id, schema in window._pose_schemas.items():
        cache_dir = window._pose_cache_dirs.get(source_id)
        if cache_dir is None or not cache_dir.exists():
            continue
        tmap = _time_map_for_pose(window, source_id)
        specs.append(
            _SourceSpec(source_id=source_id, cache_dir=cache_dir, schema=schema, time_map=tmap)
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


def _signature_for(specs: list[_SourceSpec], threshold: float) -> int:
    return hash(
        (
            round(threshold, 4),
            tuple(
                (
                    s.source_id,
                    str(s.cache_dir),
                    round(s.time_map.offset, 6),
                    round(s.time_map.drift_ms_per_hour, 6),
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
    sig = _signature_for(specs, threshold)
    cached: tuple[int, list[SuspectFrame]] | None = getattr(window, "_suspect_cache", None)
    if cached is not None and cached[0] == sig:
        _apply_jump(window, cached[1], direction)
        return

    worker = _SuspectScanWorker(sig, specs, threshold)

    def _on_done(done_sig: int, suspects: list[SuspectFrame]) -> None:
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
    window.statusBar().showMessage(
        tr("Suspect frame — {reason} at {time:.3f}s").format(reason=chosen.reason, time=target),
        3500,
    )
