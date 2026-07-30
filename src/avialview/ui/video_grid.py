"""Video grid layout manager."""

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from avialview.ui.video_pane import VideoPane


class VideoGrid(QWidget):
    """Manages N VideoPanes in either a horizontal strip or an NxN grid.

    Uses a single QGridLayout and re-arranges children when the mode
    changes, avoiding the Qt limitation that prevents swapping layouts.
    """

    # Emitted when the user right-clicks inside any video pane.
    # path = the pane's video path; pos = QPoint (global screen position).
    pane_right_clicked = Signal(str, object)
    displayed_panes_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.panes: list[VideoPane] = []
        self._fullscreen_pane: VideoPane | None = None
        self._paths: list[str] = []
        self._pane_enabled: list[bool] = []
        self._grid_mode: bool = False
        self._batch_depth: int = 0

        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)

        self.lbl_empty = QLabel(
            "No videos loaded.\nDrag and drop videos or CSV "
            "files here.\nDouble-click a pane to maximise."
        )
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setMinimumHeight(200)
        self._layout.addWidget(self.lbl_empty, 0, 0)

    # ── Public API ────────────────────────────────────────────────────

    def pane_paths(self) -> list[str]:
        """Return a copy of the loaded video paths, parallel to self.panes."""
        return list(self._paths)

    def visible_panes(self) -> list[VideoPane]:
        """Return panes currently selected and displayed by the grid."""
        if self._fullscreen_pane is not None:
            try:
                index = self.panes.index(self._fullscreen_pane)
            except ValueError:
                return []
            return [self._fullscreen_pane] if self._is_pane_enabled(index) else []
        return [pane for index, pane in enumerate(self.panes) if self._is_pane_enabled(index)]

    def _is_pane_enabled(self, index: int) -> bool:
        """Treat legacy directly-injected test panes as visible."""
        return index >= len(self._pane_enabled) or self._pane_enabled[index]

    def frame_records_at(self, t_master: float) -> list[dict[str, Any]]:
        """Return per-video frame records at *t_master* for annotation storage.

        Each record: {"path": str, "frame_index": int, "media_timestamp": float}.
        This is the single authority for frame computation — main_window and
        tests must call this rather than replicating the fps/time_map logic.
        """
        records: list[dict[str, Any]] = []
        for path, pane in zip(self._paths, self.panes, strict=False):
            frame_index, media_timestamp = pane.frame_record_at(t_master)
            records.append(
                {
                    "path": path,
                    "frame_index": frame_index,
                    "media_timestamp": media_timestamp,
                }
            )
        return records

    def set_tracking_readers(self, readers: list) -> None:
        """Pass tracking data readers to all video panes for overlay rendering."""
        for pane in self.panes:
            pane.set_tracking_readers(readers)

    def set_overlay_tracks(self, path: str, tracks: list) -> None:
        """Attach named 2D prediction tracks to the pane showing *path* only.

        2D pose data is camera-specific: a track extracted from SideCam must
        never be painted over FaceCam, so this routes by exact video path
        instead of broadcasting like :meth:`set_tracking_readers`.
        """
        try:
            index = self._paths.index(path)
        except ValueError:
            return
        self.panes[index].set_overlay_tracks(tracks)

    def set_grid_mode(self, enabled: bool) -> None:
        """Switch between horizontal-strip and NxN grid layout."""
        if enabled == self._grid_mode:
            return
        self._grid_mode = enabled
        self._relayout()

    def add_pane(
        self,
        path: str,
        *,
        media_path: str | None = None,
        on_file_loaded: Callable[[], None] | None = None,
    ) -> VideoPane:
        """Add a pane identified by original *path*, playing *media_path* if supplied."""
        pane = VideoPane(self)
        pane.double_clicked.connect(self._on_pane_double_clicked)
        # Forward right-click with path so MainWindow can build a context menu.
        if on_file_loaded is not None:
            pane.file_loaded.connect(on_file_loaded)
        pane.right_clicked.connect(lambda pos, _p=path: self.pane_right_clicked.emit(_p, pos))
        self.panes.append(pane)
        self._paths.append(path)
        self._pane_enabled.append(True)
        pane.open(media_path or path)
        if self._batch_depth == 0:
            self._relayout()
            self._update_labels()
        return pane

    def remove_pane(self, path: str) -> None:
        """Remove a video pane by path."""
        try:
            idx = self._paths.index(path)
        except ValueError:
            return

        pane = self.panes.pop(idx)
        self._paths.pop(idx)
        if idx < len(self._pane_enabled):
            self._pane_enabled.pop(idx)

        if self._fullscreen_pane == pane:
            self._fullscreen_pane = None

        self._layout.removeWidget(pane)
        pane.close()
        pane.deleteLater()
        if self._batch_depth == 0:
            self._relayout()
            self._update_labels()
            self.displayed_panes_changed.emit()

    def shutdown(self) -> None:
        """Terminate all libmpv panes before their Qt parent is destroyed."""
        for pane in self.panes:
            pane.close()
            pane.deleteLater()
        self.panes.clear()
        self._paths.clear()
        self._fullscreen_pane = None
        self._pane_enabled.clear()

    def set_offset(self, path: str, offset: float) -> None:
        """Update the time offset for a specific video."""
        try:
            idx = self._paths.index(path)
            self.panes[idx].time_map.offset = offset
        except ValueError:
            pass

    def set_sync_mapping(
        self,
        path: str,
        offset: float,
        drift_ppm: float,
        exact_master: np.ndarray | None = None,
        exact_source: np.ndarray | None = None,
    ) -> None:
        """Apply a user-accepted absolute synchronization mapping to one video."""
        try:
            idx = self._paths.index(path)
            pane = self.panes[idx]
            pane.time_map.set_mapping(offset, drift_ppm)
            if exact_master is not None and exact_source is not None:
                pane.time_map.set_exact_mapping(exact_master, exact_source)
            # Reassign to trigger property setter and re-apply libmpv speed
            pane.time_map = pane.time_map
        except ValueError:
            pass

    def set_pane_visible(self, path: str, visible: bool) -> None:
        """Show or hide a video pane without unloading it."""
        try:
            idx = self._paths.index(path)
        except ValueError:
            return
        while len(self._pane_enabled) < len(self.panes):
            self._pane_enabled.append(True)
        if self._pane_enabled[idx] == visible:
            return
        self._pane_enabled[idx] = visible
        if not visible and self._fullscreen_pane is self.panes[idx]:
            self._fullscreen_pane = None
        self._relayout()
        self.displayed_panes_changed.emit()

    # ── Internal ──────────────────────────────────────────────────────

    def begin_batch_add(self) -> None:
        """Defer relayout until end_batch_add(). Use for multi-file drops."""
        self._batch_depth += 1

    def end_batch_add(self) -> None:
        """Resume relayout after a batch add sequence."""
        self._batch_depth = max(0, self._batch_depth - 1)
        if self._batch_depth == 0:
            self._relayout()
            self._update_labels()
            self.displayed_panes_changed.emit()

    def _relayout(self) -> None:
        """Remove all widgets from the grid and re-add them in the
        current arrangement (strip or NxN).  Widgets stay parented to
        *self* the whole time — only their grid position changes."""

        self.setUpdatesEnabled(False)
        try:
            # Remove every widget from the layout without unparenting
            while self._layout.count():
                self._layout.takeAt(0)

            # Reset stretches
            for c in range(self._layout.columnCount()):
                self._layout.setColumnStretch(c, 0)
            for r in range(self._layout.rowCount()):
                self._layout.setRowStretch(r, 0)

            for pane in self.panes:
                pane.setVisible(False)
            visible_panes = self.visible_panes()
            n = len(visible_panes)

            # ── Empty state ──────────────────────────────────────────
            if n == 0:
                self.lbl_empty.setVisible(True)
                self._layout.addWidget(self.lbl_empty, 0, 0)
                return

            self.lbl_empty.setVisible(False)

            # ── Fullscreen override ──────────────────────────────────
            if self._fullscreen_pane and self._fullscreen_pane in visible_panes:
                self._fullscreen_pane.setVisible(True)
                self._layout.addWidget(self._fullscreen_pane, 0, 0)
                self._layout.setColumnStretch(0, 1)
                self._layout.setRowStretch(0, 1)
                return

            # ── Normal: only user-enabled panes visible ──────────────
            for pane in visible_panes:
                pane.setVisible(True)

            if self._grid_mode:
                cols = math.ceil(math.sqrt(n))
                for i, pane in enumerate(visible_panes):
                    row, col = divmod(i, cols)
                    self._layout.addWidget(pane, row, col)
                for c in range(cols):
                    self._layout.setColumnStretch(c, 1)
                rows = math.ceil(n / cols)
                for r in range(rows):
                    self._layout.setRowStretch(r, 1)
            else:
                # Horizontal strip: all in row 0
                for i, pane in enumerate(visible_panes):
                    self._layout.addWidget(pane, 0, i)
                    self._layout.setColumnStretch(i, 1)
                self._layout.setRowStretch(0, 1)
        finally:
            self.setUpdatesEnabled(True)

    def _update_labels(self) -> None:
        """Update camera labels, disambiguating duplicate filenames."""
        from collections import defaultdict

        name_counts: dict[str, list[int]] = defaultdict(list)
        for i, p in enumerate(self._paths):
            name_counts[Path(p).name].append(i)

        for i, p in enumerate(self._paths):
            path = Path(p)
            if len(name_counts[path.name]) > 1:
                label = f"{path.parent.name}/{path.name}"
            else:
                label = path.name

            if len(self.panes) == 1:
                self.panes[i].set_label("")
            else:
                self.panes[i].set_label(label)

    def toggle_fullscreen(self, path: str | None = None) -> None:
        """Toggle fullscreen for the pane identified by *path*.

        If *path* is None, the first pane is used (for toolbar/shortcut use).
        """
        if not self.panes:
            return
        if path is not None:
            try:
                pane = self.panes[self._paths.index(path)]
            except ValueError:
                return
        else:
            pane = self.panes[0]
        self._on_pane_double_clicked(pane)

    def _on_pane_double_clicked(self, pane: VideoPane) -> None:
        """Toggle fullscreen for the clicked pane."""
        if self._fullscreen_pane is pane:
            self._fullscreen_pane = None
        else:
            self._fullscreen_pane = pane
        self._relayout()
        self.displayed_panes_changed.emit()
