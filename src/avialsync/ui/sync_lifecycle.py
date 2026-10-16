"""Live clock ownership, dependency invalidation and nonlinear mapping restoration."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtWidgets import QWidget

from avialsync.core.timeline import TimeMap
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.core.session import SyncProvenance
    from avialsync.ui.coverage_lanes import SourceCoverage
    from avialsync.ui.main_window import MainWindow


def as_window(widget: QWidget | None) -> MainWindow | None:
    """Recognize the owning application window without accepting arbitrary widgets."""
    from avialsync.ui.main_window import MainWindow

    return widget if isinstance(widget, MainWindow) else None


def source_mapping(window: MainWindow, source_id: str) -> TimeMap | None:
    """Return the source's live authority, without reading files or copying arrays."""
    paths = window.video_grid.pane_paths()
    if source_id in paths:
        mapping = window.video_grid.panes[paths.index(source_id)].time_map
        return mapping if isinstance(mapping, TimeMap) else None
    if source_id in window.imaging_pane.source_paths():
        return window.imaging_pane.source_config(source_id)[2]
    cache = window._sensor_cache_dirs.get(source_id)
    if cache is not None:
        return window.plot_pane._source_time_maps.get(cache)
    if source_id in window._trigger_trains:
        return window.trigger_mapping(source_id)
    # Plot adapters can load a reader before its source card/cache registration.
    # The live reader still owns a valid clock; it is not a removed recording.
    for channel in window.plot_pane.channels:
        if channel.reader.source_id == source_id or str(channel.reader.cache_dir) == source_id:
            return channel.reader.time_map
    return None


def invalidate(window: MainWindow, source_id: str, moved: float = 0.0) -> None:
    """Annotate affected evidence, including every downstream clock dependency."""
    affected = {source_id}
    changed = True
    while changed:
        changed = False
        for index, entry in enumerate(window._sync_provenance):
            if entry.superseded_by:
                continue
            direct = entry.target_id == source_id
            reference = entry.reference_clock_id or entry.reference_id
            if not direct and reference not in affected:
                continue
            reason = (
                tr("moved {seconds:+.4f} s by hand after it was accepted").format(seconds=moved)
                if direct
                else tr("reference timing changed; review this alignment")
            )
            window._sync_provenance[index] = dataclasses.replace(entry, superseded_by=reason)
            affected.add(entry.target_id)
            changed = True
    wizard = getattr(window, "_sync_wizard", None)
    if wizard is not None:
        wizard.invalidate_sources()
    window.refresh_alignment_badges()


def restore_records(window: MainWindow, records: tuple[SyncProvenance, ...]) -> None:
    """Undo evidence annotations by identity, sharing their immutable arrays."""
    retained = {entry.target_id: entry for entry in records}
    window._sync_provenance = [
        retained.pop(entry.target_id, entry) for entry in window._sync_provenance
    ] + list(retained.values())
    window.refresh_alignment_badges()


def restore_adjustment(window: MainWindow, path: str) -> None:
    """Reapply saved scalar corrections against the original immutable evidence."""
    mapping = source_mapping(window, path)
    entry = next((e for e in window._sync_provenance if e.target_id == path), None)
    if mapping is None or entry is None or not len(entry.exact_master):
        return
    offset, drift = mapping.offset, mapping.drift_ms_per_hour
    mapping.set_mapping(
        entry.offset if entry.exact_offset_anchor is None else entry.exact_offset_anchor,
        entry.drift_ms_per_hour if entry.exact_drift_anchor is None else entry.exact_drift_anchor,
    )
    mapping.set_exact_mapping(
        np.asarray(entry.exact_master, dtype=np.float64),
        np.asarray(entry.exact_source, dtype=np.float64),
    )
    mapping.adjust_mapping(offset, drift)


def refresh_coverage(window: MainWindow, path: str) -> None:
    """Derive coverage from the evaluated mapping, including manual corrections."""
    mapping = source_mapping(window, path)
    if mapping is None:
        return
    if path in window._video_source_bounds:
        bounds = window._video_source_bounds[path]
        kind = "video"
    elif path in window.imaging_pane.source_paths():
        info = window.imaging_pane.metadata_for(path)
        bounds = (float(info.frame_times[0]), float(info.frame_times[-1]) + info.tail_duration)
        kind = "data"
    else:
        return
    window.transport.set_source_coverage(
        path,
        mapping.to_master(bounds[0]),
        mapping.to_master(bounds[1]),
        kind,
        window.coverage_group_for(path),
    )
    window._recompute_bounds()


def coverage_sources(window: MainWindow) -> list[SourceCoverage]:
    """Project coverage through each live mapping, including imaging and corrections."""
    from avialsync.ui.coverage_lanes import SourceCoverage

    coverage: list[SourceCoverage] = []
    for path, bounds in window._video_source_bounds.items():
        mapping = source_mapping(window, path) or TimeMap(
            *window._video_time_mappings.get(path, (0.0, 0.0))
        )
        coverage.append(
            SourceCoverage(
                label=Path(path).name,
                data=(mapping.to_master(bounds[0]), mapping.to_master(bounds[1])),
                evidence=window._evidence_span(path),
            )
        )
    for path, cache in window._sensor_cache_dirs.items():
        span = window.plot_pane.source_bounds(cache)
        if span is not None:
            coverage.append(
                SourceCoverage(
                    label=Path(path).name, data=span, evidence=window._evidence_span(path)
                )
            )
    for path in window.imaging_pane.source_paths():
        mapping = window.imaging_pane.source_config(path)[2]
        info = window.imaging_pane.metadata_for(path)
        coverage.append(
            SourceCoverage(
                label=Path(path).name,
                data=(
                    mapping.to_master(float(info.frame_times[0])),
                    mapping.to_master(float(info.frame_times[-1]) + info.tail_duration),
                ),
                evidence=window._evidence_span(path),
            )
        )
    return coverage
