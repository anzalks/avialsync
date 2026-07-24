"""Parallel seek coordinator."""

from PySide6.QtCore import QRunnable, QThreadPool

from kinochronix.ui.video_pane import VideoPane


class SeekTask(QRunnable):
    """Background task to seek a single video pane."""

    def __init__(self, pane: VideoPane, target_t: float, exact: bool):
        super().__init__()
        self.pane = pane
        self.target_t = target_t
        self.exact = exact

    def run(self) -> None:
        self.pane.seek(self.target_t, exact=self.exact)


class SeekGroup:
    """Manages parallel seeks across N video panes."""

    def __init__(self, panes: list[VideoPane]) -> None:
        self.panes = panes

    def seek_pane(self, pane: VideoPane, target_t: float, exact: bool = True) -> None:
        """Seek a single pane asynchronously."""
        if not pane.mpv:
            return
        pane.is_seeking = True  # Preemptively set to avoid double-triggering
        pool = QThreadPool.globalInstance()
        task = SeekTask(pane, target_t, exact)
        pool.start(task)

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
