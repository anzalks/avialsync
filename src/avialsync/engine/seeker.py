"""Asynchronous seek coordinator."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # ARCHITECTURE §1: engine must not depend on ui/ at module scope.
    from avialsync.ui.video_pane import VideoPane


class SeekGroup:
    """Fan out non-blocking frame requests across video panes.

    ``VideoPane.seek`` hands the wanted time to that pane's decode thread and
    returns immediately, so this never blocks the UI thread on decode work.
    Panes are driven in parallel because PyAV releases the GIL: three cameras
    genuinely decode on three cores rather than taking turns.
    """

    def __init__(self, panes: list[VideoPane]) -> None:
        self.panes = panes

    def seek_pane(self, pane: VideoPane, target_t: float, exact: bool = True) -> None:
        """Request one pane's frame at a source time, without blocking."""
        if not pane.has_media:
            return
        pane.seek(target_t, exact=exact)

    def seek(self, t: float, exact: bool = True) -> None:
        """Request every active pane's frame at master time ``t``."""
        for pane in self.panes:
            source_t = pane.time_map.to_source(t)
            self.seek_pane(pane, source_t, exact)

    def is_settled(self) -> bool:
        """Return True once every pane has painted the frame it was asked for."""
        for pane in self.panes:
            if pane.is_seeking:
                return False
        return True
