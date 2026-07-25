"""Player orchestrator."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer

from avialview.core.timeline import MasterClock
from avialview.engine.seeker import SeekGroup
from avialview.ui.plot_pane import PlotPane
from avialview.ui.transport import Transport
from avialview.ui.video_grid import VideoGrid
from avialview.ui.video_pane import VideoPane

if TYPE_CHECKING:
    from avialview.ui.readout_panel import ReadoutPanel


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
        self._readout_panel: ReadoutPanel | None = None
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

        # Coalescing: newest pending keyframe-seek target during drag; flushed when seeker settles
        self._pending_scrub_t: float | None = None

    def start(self) -> None:
        self._last_tick_monotonic = time.monotonic()
        self._timer.start()

    def set_playing(self, playing: bool) -> None:
        if playing:
            # Wrap around to start if at the very end
            current_t = self.clock.state.t
            end_t = self.transport._bounds[1] if self._ab_out is None else self._ab_out
            start_t = self.transport._bounds[0] if self._ab_in is None else self._ab_in

            if current_t >= end_t - 0.05:
                self.seek(start_t, exact=True)

            self._last_tick_monotonic = time.monotonic()
            self.clock.play()
            for pane in self._update_pane_footage(self.clock.state.t):
                pane.play()
        else:
            self.clock.pause()
            for pane in self.video_grid.panes:
                pane.pause()
            # Force exact seek on pause to ensure frames align perfectly
            self.seeker.panes = self.video_grid.panes
            self.seeker.seek(self.clock.state.t, exact=True)

        self.transport.set_playing(playing)

    def play(self) -> None:
        """Start playback for programmatic callers such as the demo launcher."""
        self.set_playing(True)

    def seek(self, t: float, exact: bool = True) -> None:
        self._is_scrubbing = not exact
        self.clock.seek(t)

        # Coalesce fast keyframe seeks: if a seek is already in flight and this
        # is a non-exact (drag) seek, remember only the newest target and skip
        # dispatching a new SeekTask — _on_tick will flush it once seeker settles.
        self.seeker.panes = self._update_pane_footage(t)
        if not exact and not self.seeker.is_settled():
            self._pending_scrub_t = t
        else:
            self._pending_scrub_t = None
            self.seeker.seek(t, exact=exact)

        # Update UI instantly (cursor + readout follow live during drag)
        t_now = self.clock.state.t
        self.plot_pane.set_cursor(t_now)
        self.transport.set_time(t_now)
        if self._readout_panel:
            self._readout_panel.set_cursor(t_now)

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

        for pane in self._update_pane_footage(self.clock.state.t):
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

    def _update_pane_footage(self, t_master: float) -> list[VideoPane]:
        """Synchronize pane availability with master-time coverage before display or seek."""
        active_panes: list[VideoPane] = []
        for pane in self.video_grid.panes:
            has_footage = pane.has_footage_at_master(t_master)
            if getattr(pane, "_master_has_footage", None) != has_footage:
                pane.set_has_footage(has_footage)
                if not has_footage:
                    pane.pause()
            if has_footage:
                active_panes.append(pane)
        return active_panes

    def _on_tick(self) -> None:
        now = time.monotonic()

        # Flush a coalesced pending scrub seek as soon as the seeker is free
        if self._pending_scrub_t is not None:
            self.seeker.panes = self._update_pane_footage(self._pending_scrub_t)
            if self.seeker.is_settled():
                self.seeker.seek(self._pending_scrub_t, exact=False)
                self._pending_scrub_t = None

        if self.clock.state.playing and not self._is_scrubbing:
            # Advance clock
            self.clock.advance(now)
            t = self.clock.state.t

            # A/B loop enforcement
            if self._ab_in is not None and self._ab_out is not None and t >= self._ab_out:
                self.seek(self._ab_in, exact=True)
                t = self._ab_in

            # Drift correction (video following master clock)
            active_panes = self._update_pane_footage(t)
            self.seeker.panes = active_panes
            if self.seeker.is_settled() and active_panes:
                for idx, pane in enumerate(active_panes):
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
