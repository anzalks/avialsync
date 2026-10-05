"""Video grid layout manager."""

import logging
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QMargins, Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QWidget

from avialsync.ui.i18n import tr
from avialsync.ui.video_grid_overlays import GridOverlayMixin
from avialsync.ui.video_pane import VideoPane

logger = logging.getLogger(__name__)


class VideoGrid(GridOverlayMixin, QWidget):
    """Manages N VideoPanes in either a horizontal strip or an NxN grid.

    Uses a single QGridLayout and re-arranges children when the mode
    changes, avoiding the Qt limitation that prevents swapping layouts. What is
    drawn over the panes -- tracking, corrections, markers, reprojection, the
    wheel -- is routed by :class:`GridOverlayMixin`.
    """

    #: Floor for an empty grid: tall enough to read as a pane and as a drop
    #: target, low enough that it never dictates how window height is shared.
    #: A widget placed over the grid must survive it by degrading -- the
    #: placeholder label by eliding, the empty state by scrolling -- and never
    #: by raising this floor, which is the window's minimum height by proxy.
    BASE_MIN_HEIGHT = 72

    # Emitted when the user right-clicks inside any video pane.
    # path = the pane's video path; pos = QPoint (global screen position).
    pane_right_clicked = Signal(str, object)
    displayed_panes_changed = Signal()
    pane_attached = Signal(str)
    #: A pane has left the grid's model but its decoder is still being stopped.
    #:
    #: Tearing a libmpv client down could take the whole process with it on
    #: Windows (HANDOUT.md "Pending"). Stopping a decode thread is a far tamer
    #: operation, but this still happens mid-session, where losing the process
    #: would cost everything since the last autosave. Persisting here costs one
    #: small write and keeps that cheap insurance.
    pane_detached = Signal(str)
    #: A finished "Fix Tracker" drag in any pane, as a
    #: :class:`~avialsync.core.point_edits.PointMove`.
    point_moved = Signal(object)
    #: ``(path, x, y)``: a click placing a new 3D marker in one camera.
    marker_clicked = Signal(str, float, float)
    #: ``(path, name, frame, x, y)``: a hand-placed 3D marker was dragged.
    custom_point_moved = Signal(str, str, int, float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.panes: list[VideoPane] = []
        self._fullscreen_pane: VideoPane | None = None
        self._paths: list[str] = []
        self._pane_enabled: list[bool] = []
        self._grid_mode: bool = False
        self._batch_depth: int = 0
        self._init_grid_overlays()

        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)

        self.lbl_empty = QLabel(
            tr(
                "No videos loaded.\nDrag and drop videos or CSV "
                "files here.\nDouble-click a pane to maximise."
            )
        )
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # The placeholder asks for a drop-target's worth of height but must not
        # *demand* it: as a hard minimum it pinned the whole media row at 200 px,
        # so shrinking the window took every lost pixel out of the plot area
        # instead of scaling the two together.
        self.lbl_empty.setMinimumHeight(0)
        self.lbl_empty.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        self._layout.addWidget(self.lbl_empty, 0, 0)
        # Keep an empty grid readable as a pane and as a drop target, without
        # letting it dictate how the window's height is shared.
        self.setMinimumHeight(self.BASE_MIN_HEIGHT)

    # ── Public API ────────────────────────────────────────────────────

    def set_display_levels(self, path: str, levels) -> None:
        """Apply a display window to one camera (D-093)."""
        try:
            index = self._paths.index(path)
        except ValueError:
            return
        self.panes[index].set_display_levels(levels)

    def auto_display_levels(self, path: str):
        """Levels chosen from the frame that camera is currently showing."""
        try:
            index = self._paths.index(path)
        except ValueError:
            return None
        return self.panes[index].auto_display_levels()

    def set_overlay_visibility(self, resolver) -> None:
        """Apply overlay visibility to every pane (D-090).

        Takes a callable rather than a dict so a per-camera override is
        resolved against the path each pane actually holds; the grid does not
        need to know how that resolution works.
        """
        self._overlay_resolver = resolver
        for path, pane in zip(self._paths, self.panes, strict=False):
            pane.apply_overlay_visibility(resolver(path))

    def apply_overlays_to(self, path: str) -> None:
        """Apply the current overlay visibility to one pane.

        Called when a pane is built: a camera opened after the user set a layer
        must not come up showing it.
        """
        resolver = getattr(self, "_overlay_resolver", None)
        if resolver is None:
            return
        try:
            index = self._paths.index(path)
        except ValueError:
            return
        self.panes[index].apply_overlay_visibility(resolver(path))

    def reset_all_views(self) -> None:
        """Every pane back to its fitted, centred view: zoom 1.00x, no pan."""
        for pane in self.panes:
            pane.surface.reset_view()

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
        pane.point_moved.connect(self.point_moved)
        pane.marker_clicked.connect(lambda x, y, _p=path: self.marker_clicked.emit(_p, x, y))
        pane.custom_point_moved.connect(
            lambda name, frame, x, y, _p=path: self.custom_point_moved.emit(_p, name, frame, x, y)
        )
        # Forward right-click with path so MainWindow can build a context menu.
        if on_file_loaded is not None:
            pane.file_loaded.connect(on_file_loaded)
        pane.right_clicked.connect(lambda pos, _p=path: self.pane_right_clicked.emit(_p, pos))
        # Width by column stretch alone, so two cameras split the strip in
        # proportion to their pictures rather than to their name labels (D-174).
        policy = pane.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        pane.setSizePolicy(policy)
        surface = getattr(pane, "surface", None)  # test doubles have none
        if surface is not None:
            surface.view_changed.connect(self._fit_panes_to_picture)
        self.panes.append(pane)
        self._paths.append(path)
        self._pane_enabled.append(True)
        self._apply_held_overlays(pane, path)
        pane.open(media_path or path)
        if self._batch_depth == 0:
            self._relayout()
            self._update_labels()
        self.pane_attached.emit(path)
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
        # The held tracks own channel readers over mmap'd pyramids. A camera the
        # user removed is not coming back on its own, so holding them past this
        # point is retention with no reader.
        self._overlay_tracks.pop(path, None)

        if self._fullscreen_pane == pane:
            self._fullscreen_pane = None

        self._layout.removeWidget(pane)
        # After the model no longer lists this pane, so a listener persists the
        # session as it will be, and before `close()`, which is what terminates
        # the client and can fault.
        self.pane_detached.emit(path)
        pane.close()
        pane.deleteLater()
        if self._batch_depth == 0:
            self._relayout()
            self._update_labels()
            self.displayed_panes_changed.emit()

    def shutdown(self) -> None:
        """Stop every pane's decoder before their Qt parent is destroyed.

        Each pane is torn down independently. A pane owns a decode thread
        that outlives its widget, so letting one failure abort the loop leaves
        every later pane's thread running and the process never exits — the
        window appears to refuse to close (D-059).
        """
        for pane in self.panes:
            try:
                pane.close()
            except Exception:
                logger.exception("Ignoring a failure while closing a video pane")
            try:
                pane.deleteLater()
            except RuntimeError:
                logger.debug("Video pane was already destroyed", exc_info=True)
        self.panes.clear()
        self._paths.clear()
        self._fullscreen_pane = None
        self._pane_enabled.clear()
        self._overlay_tracks.clear()
        self._tracking_readers.clear()

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
                # Horizontal strip: all in row 0. One or two cameras are
                # sized to their pictures by _fit_panes_to_picture (D-174).
                for i, pane in enumerate(visible_panes):
                    self._layout.addWidget(pane, 0, i)
                    self._layout.setColumnStretch(i, 1)
                self._layout.setRowStretch(0, 1)
        finally:
            self._fit_panes_to_picture()
            self.setUpdatesEnabled(True)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_panes_to_picture()

    def _fit_panes_to_picture(self) -> None:
        """Size one or two strip panes to their pictures' aspect (D-174, F-11).

        A lone camera otherwise fills the whole cell and draws small inside a
        black letterbox, with its name and timecode in the letterbox corners.
        The grid's margins shrink the strip to the pictures' combined shape and
        the column stretches split it by each picture's aspect, so no pane gains
        a minimum size and the grid's own floor is unchanged. Three or more
        cameras, the NxN grid, and the fullscreen pane fill their cells as before.
        """
        if not hasattr(self, "_base_margins"):
            self._base_margins = self._layout.contentsMargins()
        base = self._base_margins
        # Widgets only: a test double standing in for a pane is not laid out.
        visible = [pane for pane in self.panes if isinstance(pane, QWidget) and pane.isVisible()]
        sizes = [getattr(pane, "video_size", None) for pane in visible]
        fit = 0 < len(visible) <= 2 and not self._grid_mode and self._fullscreen_pane is None
        if not fit or any(size is None or not all(size) for size in sizes):
            if self._layout.contentsMargins() != base:
                self._layout.setContentsMargins(base)
            return
        aspects = [size[0] / size[1] for size in sizes if size is not None]
        spacing = self._layout.horizontalSpacing() * (len(visible) - 1)
        width = self.width() - base.left() - base.right()
        height = self.height() - base.top() - base.bottom()
        if width <= spacing or height <= 0:
            return
        row_height = min(float(height), (width - spacing) / sum(aspects))
        spare_x = int((width - spacing - row_height * sum(aspects)) / 2)
        spare_y = int((height - row_height) / 2)
        margins = QMargins(
            base.left() + spare_x,
            base.top() + spare_y,
            base.right() + spare_x,
            base.bottom() + spare_y,
        )
        for column, aspect in enumerate(aspects):
            self._layout.setColumnStretch(column, max(1, round(aspect * 1000)))
        if self._layout.contentsMargins() != margins:
            self._layout.setContentsMargins(margins)

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
