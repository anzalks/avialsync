"""Asynchronous seek coordinator."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # ARCHITECTURE §1: engine must not depend on ui/ at module scope.
    from avialsync.ui.video_pane import VideoPane


class SeekGroup:
    """Fan out non-blocking libmpv seek commands across video panes.

    ``mpv.seek`` queues work in libmpv and returns immediately.  It must be
    called from the Qt thread that owns the embedded pane: dispatching it via
    ``QThreadPool`` can leave macOS property observers stuck in ``seeking``.
    """

    def __init__(self, panes: list[VideoPane]) -> None:
        self.panes = panes

    def seek_pane(self, pane: VideoPane, target_t: float, exact: bool = True) -> None:
        """Queue a seek on one pane without blocking the UI thread."""
        if not pane.mpv:
            return
        pane.seek(target_t, exact=exact)

    def seek(self, t: float, exact: bool = True) -> None:
        """Issue parallel seek commands to all active panes."""
        for pane in self.panes:
            source_t = pane.time_map.to_source(t)
            self.seek_pane(pane, source_t, exact)

    def is_settled(self) -> bool:
        """Return True if all panes have finished seeking."""
        for pane in self.panes:
            if pane.is_seeking:
                return False
        return True
