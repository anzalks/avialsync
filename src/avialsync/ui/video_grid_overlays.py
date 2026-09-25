"""Routing what is drawn over the video to the right panes, now and later.

Split from :mod:`avialsync.ui.video_grid`, which lays panes out; this decides
what each pane draws over its frame -- tracking readers and tracks, hand
corrections and the Fix Tracker mode (D-099), hand-placed markers and their
placement mode (D-112), reprojection, and the wheel (D-113).

**Everything is held, not just forwarded.** Panes are built one at a time and
each demuxes its whole file first, so overlay state routinely resolves while a
later camera has no pane yet. :meth:`_apply_held_overlays` gives a pane built
later exactly the state the rest of the grid is in, before its first paint.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from avialsync.ui.video_pane import VideoPane

logger = logging.getLogger(__name__)

__all__ = ["GridOverlayMixin"]


class GridOverlayMixin:
    """Overlay routing for :class:`~avialsync.ui.video_grid.VideoGrid`."""

    # ── supplied by the host grid ────────────────────────────────────
    panes: list[VideoPane]
    _paths: list[str]

    def _init_grid_overlays(self) -> None:
        #: Overlay state that arrived before the pane it belongs to. Panes are
        #: built one at a time and each one demuxes its whole file first, so
        #: tracking data routinely resolves while later cameras have no pane.
        self._overlay_tracks: dict[str, list] = {}
        self._tracking_readers: list = []
        #: The session's hand-correction store, and whether the panes are
        #: currently accepting corrections. Held here for the same reason the
        #: overlay tracks are: a pane built later must open already in the
        #: state the rest of the grid is in, not in the default one.
        self._point_edits: object | None = None
        self._point_edit_mode = False
        #: Hand-placed 3D markers per camera path, and whether a new one is
        #: being placed; held for a pane built later, as above.
        self._custom_markers: dict[str, dict[int, list[tuple[str, float, float]]]] = {}
        self._marker_place_mode = False
        #: ``(path, t_master) -> [(name, x, y)]``: 3D points projected into a camera.
        self._reprojection: Callable[[str, float], list] | None = None
        #: ``(path, t_master) -> WheelDrawing``: the wheel model in a camera (D-113).
        self._wheel: Callable[[str, float], object] | None = None

    def _apply_held_overlays(self, pane: VideoPane, path: str) -> None:
        """Give a pane built now whatever already resolved for its camera."""
        # Whatever already resolved for this camera while it had no pane. Applied
        # before `open`, so the pane's first paint is already correct.
        if self._tracking_readers:
            pane.set_tracking_readers(list(self._tracking_readers))
        held = self._overlay_tracks.get(path)
        if held:
            pane.set_overlay_tracks(list(held))
        if self._point_edits is not None:
            pane.set_point_edits(self._point_edits)
        if self._point_edit_mode:
            pane.set_point_edit_mode(True)
        if path in self._custom_markers:
            pane.set_custom_markers(self._custom_markers[path])
        if self._marker_place_mode:
            pane.set_marker_place_mode(True)
        if self._reprojection is not None:
            pane.set_reprojection_source(self._reprojection_for(path))
        if self._wheel is not None:
            pane.set_wheel_source(self._wheel_for(path))

    def set_tracking_readers(self, readers: list) -> None:
        """Pass tracking data readers to all video panes for overlay rendering.

        Retained, for the same reason :meth:`set_overlay_tracks` retains: a pane
        built after this call would otherwise show nothing until the plot's
        source list next changed.
        """
        self._tracking_readers = list(readers)
        for pane in self.panes:
            pane.set_tracking_readers(list(self._tracking_readers))

    def set_overlay_tracks(self, path: str, tracks: list) -> None:
        """Attach named 2D prediction tracks to the pane showing *path* only.

        2D pose data is camera-specific: a track extracted from SideCam must
        never be painted over FaceCam, so this routes by exact video path
        instead of broadcasting like :meth:`set_tracking_readers`.

        The tracks are kept against the path because they routinely arrive
        before their pane exists, and the arrival is a one-shot event nobody
        repeats. Opening a pane demuxes the whole file to build its timestamp
        table, and panes are built strictly one at a time (D-040), while the
        pose CSVs import concurrently beside them. On a multi-camera session
        that means every camera after the first had its overlay resolved while
        it still had no pane to land on — dropped here, and never asked for
        again, so only the first camera was ever painted.
        """
        self._overlay_tracks[path] = list(tracks)
        try:
            index = self._paths.index(path)
        except ValueError:
            logger.debug(
                "Holding %d overlay track(s) for %s until its pane is built.", len(tracks), path
            )
            return
        self.panes[index].set_overlay_tracks(self._overlay_tracks[path])

    def set_point_edits(self, edits: object) -> None:
        """Share one hand-correction store with every pane, now and later."""
        self._point_edits = edits
        for pane in self.panes:
            pane.set_point_edits(edits)

    def set_point_edit_mode(self, enabled: bool) -> None:
        """Turn "Fix Tracker" on or off across every video pane at once.

        The mode is the grid's, not a pane's: a correction made on one camera
        while another is still read-only would make the interaction depend on
        which pane happened to be focused.
        """
        enabled = bool(enabled)
        self._point_edit_mode = enabled
        for pane in self.panes:
            pane.set_point_edit_mode(enabled)

    @property
    def point_edit_mode(self) -> bool:
        """Whether the panes are currently accepting point corrections."""
        return self._point_edit_mode

    def refresh_point_edits(self) -> None:
        """Repaint every overlay after the correction store changed."""
        for pane in self.panes:
            pane.paint_canvas.update()

    def set_custom_markers(
        self, path: str, markers: dict[int, list[tuple[str, float, float]]]
    ) -> None:
        """Hand-placed 3D markers for the pane showing *path* only."""
        self._custom_markers[path] = markers
        if path in self._paths:
            self.panes[self._paths.index(path)].set_custom_markers(markers)

    def set_reprojection_source(self, source: Callable[[str, float], list] | None) -> None:
        """One projection function for every pane, each asking for its own camera."""
        self._reprojection = source
        for path, pane in zip(self._paths, self.panes, strict=False):
            pane.set_reprojection_source(self._reprojection_for(path))

    def set_wheel_source(self, source: Callable[[str, float], object] | None) -> None:
        """One function for every pane, each asking for the wheel in its own camera.

        None while there is no wheel, so a pane with nothing to draw is not
        repainted on every tick for the sake of asking.
        """
        if source is self._wheel:
            return
        self._wheel = source
        for path, pane in zip(self._paths, self.panes, strict=False):
            pane.set_wheel_source(self._wheel_for(path))

    def _wheel_for(self, path: str) -> Callable[[float], Any] | None:
        source = self._wheel
        if source is None:
            return None
        return lambda t: source(path, t)

    def _reprojection_for(self, path: str) -> Callable[[float], list] | None:
        source = self._reprojection
        if source is None:
            return None
        return lambda t: source(path, t)

    def set_marker_place_mode(self, enabled: bool) -> None:
        """Turn 3D-marker placement on or off in every pane at once."""
        self._marker_place_mode = bool(enabled)
        for pane in self.panes:
            pane.set_marker_place_mode(self._marker_place_mode)

    def custom_marker_at(self, path: str, global_pos: object) -> tuple[str, int] | None:
        """``(name, frame)`` of the hand-placed marker under a screen position."""
        if path not in self._paths:
            return None
        canvas = self.panes[self._paths.index(path)].paint_canvas
        local = canvas.mapFromGlobal(global_pos)
        point = canvas.custom_marker_at(float(local.x()), float(local.y()))
        if point is None or point.key is None:
            return None
        return point.key.point, point.key.index

    def highlight_point(self, key: object) -> None:
        """Ring one coordinate on whichever pane holds it, clearing the rest."""
        for pane in self.panes:
            pane.set_highlighted_point(key)
