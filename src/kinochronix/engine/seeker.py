"""Parallel seek coordinator."""

from kinochronix.ui.video_pane import VideoPane


class SeekGroup:
    """Manages parallel seeks across N video panes."""

    def __init__(self, panes: list[VideoPane]) -> None:
        self.panes = panes

    def seek(self, t: float, exact: bool = True) -> None:
        """Issue parallel seek commands to all active panes."""
        for pane in self.panes:
            source_t = pane.time_map.to_source(t)
            pane.seek(source_t, exact=exact)

    def is_settled(self) -> bool:
        """Return True if all panes have finished seeking."""
        for pane in self.panes:
            if pane.is_seeking:
                return False
        return True
