"""Player orchestrator."""

import time

from PySide6.QtCore import QObject, QTimer

from kinochronix.core.timeline import MasterClock
from kinochronix.engine.seeker import SeekGroup
from kinochronix.ui.plot_pane import PlotPane
from kinochronix.ui.transport import Transport
from kinochronix.ui.video_grid import VideoGrid


class Player(QObject):
    """Coordinates playback between UI and MasterClock."""

    def __init__(
        self,
        clock: MasterClock,
        video_grid: VideoGrid,
        plot_pane: PlotPane,
        transport: Transport,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.clock = clock
        self.video_grid = video_grid
        self.plot_pane = plot_pane
        self.transport = transport
        self.seeker = SeekGroup(self.video_grid.panes)

        self._timer = QTimer(self)
        self._timer.setInterval(1000 // 60)  # 60 Hz
        self._timer.timeout.connect(self._on_tick)

        self._drift_count = 0
        self._last_tick_monotonic = time.monotonic()

        # Connect transport signals
        self.transport.play_toggled.connect(self.set_playing)
        self.transport.seek_requested.connect(self.seek)
        self.transport.rate_changed.connect(self.set_rate)

        # We keep track of manual scrubbing state so the clock doesn't advance
        self._is_scrubbing = False

    def start(self) -> None:
        self._last_tick_monotonic = time.monotonic()
        self._timer.start()

    def set_playing(self, playing: bool) -> None:
        if playing:
            self._last_tick_monotonic = time.monotonic()
            self.clock.play()
            for pane in self.video_grid.panes:
                pane.play()
        else:
            self.clock.pause()
            for pane in self.video_grid.panes:
                pane.pause()
            # Force exact seek on pause to ensure frames align perfectly
            self.seeker.panes = self.video_grid.panes
            self.seeker.seek(self.clock.state.t, exact=True)

        self.transport.set_playing(playing)

    def seek(self, t: float, exact: bool = True) -> None:
        self._is_scrubbing = not exact
        self.clock.seek(t)
        self.seeker.panes = self.video_grid.panes
        self.seeker.seek(t, exact=exact)

        # update UI instantly
        self.plot_pane.set_cursor(self.clock.state.t)
        self.transport.set_time(self.clock.state.t)

        # Reset drift hysteresis
        self._drift_count = 0
        self._last_tick_monotonic = time.monotonic()

    def set_rate(self, rate: float) -> None:
        self.clock.set_rate(rate)
        for pane in self.video_grid.panes:
            pane.set_rate(rate)

    def _on_tick(self) -> None:
        now = time.monotonic()

        if self.clock.state.playing and not self._is_scrubbing:
            # Advance clock
            self.clock.advance(now)
            t = self.clock.state.t

            # Drift correction (video following master clock)
            # Only if grid is settled (no panes are actively seeking)
            self.seeker.panes = self.video_grid.panes
            if self.seeker.is_settled() and len(self.video_grid.panes) > 0:
                drifting = False
                for pane in self.video_grid.panes:
                    source_t = pane.time_map.to_source(t)
                    if abs(pane.time_pos - source_t) > 0.040:
                        drifting = True
                        break

                if drifting:
                    self._drift_count += 1
                    if self._drift_count > 5:
                        self.seeker.seek(t, exact=False)
                        self._drift_count = 0
                else:
                    self._drift_count = 0

            # Update UI
            self.plot_pane.set_cursor(t)
            self.transport.set_time(t)

        self._last_tick_monotonic = now
