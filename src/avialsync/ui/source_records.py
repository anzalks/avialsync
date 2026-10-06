"""Describe loaded sources for the undoable document command bus."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from avialsync.core.document import SourceRecord
from avialsync.ui.imaging_integration import source_payload

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def anything_loaded(window: MainWindow) -> bool:
    """Whether any source contributes to the workspace."""
    return bool(
        window.video_grid.pane_paths()
        or window._sensor_cache_dirs
        or window.imaging_pane.source_paths()
    )


def source_record(window: MainWindow, source_id: str, kind: str) -> SourceRecord:
    """Capture a source's mapping and the import choices needed by undo."""
    offset, drift_ms_per_hour = window._recorded_mappings.get(source_id, (0.0, 0.0))
    payload: dict[str, Any] = {}
    if kind == "imaging" and source_id in window.imaging_pane.source_paths():
        payload, offset, drift_ms_per_hour = source_payload(window, source_id)
    return SourceRecord(
        source_id=source_id,
        path=source_id,
        kind=kind,
        offset=offset,
        drift_ms_per_hour=drift_ms_per_hour,
        payload=payload,
    )
