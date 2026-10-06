"""Capture source identities before export jobs leave the UI thread."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def loaded_source_paths(window: MainWindow) -> tuple[Path, ...]:
    """Return every source path known to the current window."""
    names = set(window.video_grid.pane_paths())
    names.update(window._sensor_cache_dirs)
    names.update(window._overlay_sources)
    names.update(window._pose_3d_sources)
    names.update(window._trigger_configs)
    names.update(window.session_runtime.item_labels)
    for overlays in window._overlay_sources.values():
        names.update(overlays)
    return tuple(Path(name) for name in names)
