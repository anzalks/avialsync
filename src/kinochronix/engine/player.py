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
        self._readout_panel = None
        self.seeker = SeekGroup(self.video_grid.panes)

        self._timer = QTimer(self)
        self._timer.setInterval(1000 // 60)  # 60 Hz
        self._timer.timeout.connect(self._on_tick)

        self._drift_counts: dict[int, int] = {}
        self._last_tick_monotonic = time.monotonic()

        # A/B loop state
        self._ab_in: float | None = None
        self._ab_out: float | None = None

        # Connect transport signals
        self.transport.play_toggled.connect(self.set_playing)
        self.transport.seek_requested.connect(self.seek)
        self.transport.rate_changed.connect(self.set_rate)
        self.transport.frame_step_requested.connect(self.step_frame)
        self.transport.ab_loop_changed.connect(self.set_ab_loop)

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
        self._drift_counts.clear()
        self._last_tick_monotonic = time.monotonic()

    def set_rate(self, rate: float) -> None:
        self.clock.set_rate(rate)
        for pane in self.video_grid.panes:
            pane.set_rate(rate)

    def step_frame(self, direction: int) -> None:
        """Step forward or backward by one frame across all video panes.

        Uses mpv's frame-step / frame-back-step so the step size is exact
        even for VFR content. After stepping, the master clock is snapped to
        the first pane's reported time_pos so plots stay in sync.
        """
        was_playing = self.clock.state.playing
        if was_playing:
            self.set_playing(False)

        for pane in self.video_grid.panes:
            if not pane.mpv:
                continue
            if direction > 0:
                pane.mpv.command("frame-step")
            else:
                pane.mpv.command("frame-back-step")

        # Snap master clock to first pane's position after a short delay
        # (mpv frame-step is async so we defer 50 ms)
        from PySide6.QtCore import QTimer

        QTimer.singleShot(50, self._snap_clock_to_first_pane)

    def _snap_clock_to_first_pane(self) -> None:
        """Read first pane's time_pos and seek master clock to match."""
        if not self.video_grid.panes:
            return
        pane = self.video_grid.panes[0]
        if pane.mpv is None:
            return
        t_pos = pane.time_map.to_master(pane.time_pos or self.clock.state.t)
        self.clock.seek(t_pos)
        self.plot_pane.set_cursor(t_pos)
        self.transport.set_time(t_pos)

    def set_ab_loop(self, t_in: float | None, t_out: float | None) -> None:
        """Set or clear the A/B loop region on the master clock."""
        self._ab_in = t_in
        self._ab_out = t_out

    def _on_tick(self) -> None:
        now = time.monotonic()

        if self.clock.state.playing and not self._is_scrubbing:
            # Advance clock
            self.clock.advance(now)
            t = self.clock.state.t

            # A/B loop enforcement
            if self._ab_in is not None and self._ab_out is not None and t >= self._ab_out:
                self.seek(self._ab_in, exact=True)
                t = self._ab_in

            # Drift correction (video following master clock)
            self.seeker.panes = self.video_grid.panes
            if self.seeker.is_settled() and len(self.video_grid.panes) > 0:
                for idx, pane in enumerate(self.video_grid.panes):
                    if not pane.mpv:
                        continue

                    vid_t = pane.time_pos
                    if vid_t is None:
                        continue

                    source_t = pane.time_map.to_source(t)
                    drift = vid_t - source_t

                    if abs(drift) > 0.040:
                        self._drift_counts[idx] = self._drift_counts.get(idx, 0) + 1
                        if self._drift_counts[idx] > 5:
                            self.seeker.seek_pane(pane, source_t, exact=True)
                            self._drift_counts[idx] = 0
                    else:
                        self._drift_counts[idx] = 0

            # Update UI
            self.plot_pane.set_cursor(t)
            self.transport.set_time(t)
            if self._readout_panel:
                self._readout_panel.set_cursor(t)

        self._last_tick_monotonic = now
