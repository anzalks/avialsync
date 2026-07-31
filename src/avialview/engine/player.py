"""Player orchestrator."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QTimer

from avialview.core.timeline import MasterClock
from avialview.engine.seeker import SeekGroup

if TYPE_CHECKING:
    # ARCHITECTURE §1 layering: the engine must not depend on the UI at module
    # scope, or `engine` cannot be imported or tested headlessly.  These names
    # are used purely as annotations, so deferring them costs nothing.
    from avialview.ui.plot_pane import PlotPane
    from avialview.ui.readout_panel import ReadoutPanel
    from avialview.ui.tracking_3d_pane import Tracking3DPane
    from avialview.ui.transport import Transport
    from avialview.ui.video_grid import VideoGrid
    from avialview.ui.video_pane import VideoPane

logger = logging.getLogger(__name__)

#: Presentation refresh rate for text/pose consumers.  The master clock still
#: ticks at 60 Hz; only label formatting and pose resampling are throttled.
#: 20 Hz is above the rate at which a person can read a changing number and
#: leaves two thirds of every 60 Hz tick budget for decoding and painting.
_PRESENTATION_HZ = 20.0
_PRESENTATION_INTERVAL_S = 1.0 / _PRESENTATION_HZ


class Player(QObject):
    """Coordinates playback between UI and MasterClock."""

    def __init__(
        self,
        clock: MasterClock,
        video_grid: VideoGrid,
        plot_pane: PlotPane,
        transport: Transport,
        parent: QObject | None = None,
        *,
        tracking_3d_pane: Tracking3DPane | None = None,
    ):
        super().__init__(parent)
        self.clock = clock
        self.video_grid = video_grid
        self.plot_pane = plot_pane
        self.transport = transport
        self.tracking_3d_pane = tracking_3d_pane
        self._readout_panel: ReadoutPanel | None = None
        self.seeker = SeekGroup(self.video_grid.panes)

        self._timer = QTimer(self)
        self._timer.setInterval(1000 // 60)  # 60 Hz
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._on_tick)
        self.video_grid.displayed_panes_changed.connect(self._on_displayed_panes_changed)

        self._drift_counts: dict[int, int] = {}
        self._playing_pane_ids: set[int] = set()
        self._displayed_pane_ids = {id(pane) for pane in self.video_grid.visible_panes()}
        self._last_tick_monotonic = time.monotonic()
        # Presentation consumers are rate-limited independently of the clock.
        self._last_presentation_at = 0.0

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
        self._frame_step_reference: VideoPane | None = None
        self._queued_frame_steps = 0

    def start(self) -> None:
        self._last_tick_monotonic = time.monotonic()
        self._timer.start()

    def stop(self) -> None:
        """Stop UI ticks before the owning window tears down its panes."""
        self._timer.stop()
        self.clock.pause()
        self._pending_scrub_t = None
        self._queued_frame_steps = 0
        self._playing_pane_ids.clear()

    def set_playing(self, playing: bool) -> None:
        self.plot_pane.set_playing(playing)
        if playing:
            # Wrap around to start if at the very end
            current_t = self.clock.state.t
            bounds = self.transport.bounds
            end_t = bounds[1] if self._ab_out is None else self._ab_out
            start_t = bounds[0] if self._ab_in is None else self._ab_in

            if current_t >= end_t - 0.05:
                self.seek(start_t, exact=True)

            self._last_tick_monotonic = time.monotonic()
            self.clock.play()
            for pane in self._update_pane_footage(self.clock.state.t):
                pane.set_mapping_rate_at(self.clock.state.t)
        else:
            self.clock.pause()
            for pane in self.video_grid.panes:
                pane.pause()
            self._playing_pane_ids.clear()
            # Pause on accepted frame-trigger evidence, then decode that frame exactly.
            self.seek(self.clock.state.t, exact=True)

        self.transport.set_playing(playing)

    def play(self) -> None:
        """Start playback for programmatic callers such as the demo launcher."""
        self.set_playing(True)

    def seek(self, t: float, exact: bool = True) -> None:
        self._is_scrubbing = not exact
        self.plot_pane.set_scrubbing(not exact)
        if exact:
            t = self._snap_to_frame_evidence(t)
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
        now = time.monotonic()
        self._update_timeline_views(self.clock.state.t, now, force=True)

        # Reset drift hysteresis
        self._drift_counts.clear()
        self._last_tick_monotonic = now

    def _snap_to_frame_evidence(self, t_master: float) -> float:
        """Use the first active exact mapping as the reference frame clock."""
        for pane in self.video_grid.visible_panes():
            if not pane.has_footage_at_master(t_master):
                continue
            if getattr(pane.time_map, "has_exact_mapping", False) is True:
                return float(pane.time_map.snap_master_time(t_master))
        return t_master

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

        panes = self._update_pane_footage(self.clock.state.t)
        if not panes:
            return
        target = panes[0].frame_step_master_target(self.clock.state.t, direction)
        if target is not None:
            self.seek(target, exact=True)
            return
        reference = panes[0]
        if self._frame_step_reference is not None:
            self._queued_frame_steps += 1 if direction > 0 else -1
            return
        self._frame_step_reference = reference
        reference.frame_presented.connect(
            self._on_reference_frame_presented,
            Qt.ConnectionType.SingleShotConnection,
        )
        reference.frame_step(forward=direction > 0)

    def _on_reference_frame_presented(self, source_time: float) -> None:
        """Synchronize all panes after mpv steps a source without an index."""
        reference = self._frame_step_reference
        self._frame_step_reference = None
        if reference is None:
            return
        self.seek(reference.time_map.to_master(source_time), exact=True)

    def set_ab_loop(self, t_in: float | None, t_out: float | None) -> None:
        """Set or clear the A/B loop region on the master clock."""
        self._ab_in = t_in
        self._ab_out = t_out

    def _update_pane_footage(self, t_master: float) -> list[VideoPane]:
        """Synchronize pane availability with master-time coverage before display or seek."""
        active_panes: list[VideoPane] = []
        displayed_ids = {id(pane) for pane in self.video_grid.visible_panes()}
        for pane in self.video_grid.panes:
            pane_id = id(pane)
            if pane_id not in displayed_ids:
                if pane_id in self._playing_pane_ids:
                    pane.pause()
                    self._playing_pane_ids.discard(pane_id)
                self._drift_counts.pop(pane_id, None)
                continue
            has_footage = pane.has_footage_at_master(t_master)
            if getattr(pane, "_master_has_footage", None) != has_footage:
                pane.set_has_footage(has_footage)
                if not has_footage:
                    pane.pause()
                    self._playing_pane_ids.discard(pane_id)
            if has_footage:
                active_panes.append(pane)
                if self.clock.state.playing and pane_id not in self._playing_pane_ids:
                    pane.play()
                    self._playing_pane_ids.add(pane_id)
        self._displayed_pane_ids = displayed_ids
        return active_panes

    def _on_displayed_panes_changed(self) -> None:
        """Resynchronize newly displayed panes without stalling the master clock."""
        t_master = self.clock.state.t
        displayed_ids = {id(pane) for pane in self.video_grid.visible_panes()}
        newly_displayed = displayed_ids - self._displayed_pane_ids
        active_panes = self._update_pane_footage(t_master)
        self.seeker.panes = active_panes
        for pane in active_panes:
            if id(pane) in newly_displayed:
                source_t = pane.time_map.to_source(t_master)
                self.seeker.seek_pane(pane, source_t, exact=True)

    def _on_tick(self) -> None:
        now = time.monotonic()

        if (
            self._queued_frame_steps
            and self._frame_step_reference is None
            and self.seeker.is_settled()
        ):
            direction = 1 if self._queued_frame_steps > 0 else -1
            self._queued_frame_steps -= direction
            self.step_frame(direction)

        # Flush a coalesced pending scrub seek as soon as the seeker is free
        if self._pending_scrub_t is not None:
            self.seeker.panes = self._update_pane_footage(self._pending_scrub_t)
            if self.seeker.is_settled():
                self.seeker.seek(self._pending_scrub_t, exact=False)
                self._pending_scrub_t = None

        if self.clock.state.playing and not self._is_scrubbing:
            # The master timeline never waits for a decoder. A pane that is still
            # seeking drops frames and rejoins; plots/readout/3D keep moving.
            self.clock.advance(now)

            t = self.clock.state.t

            # A/B loop enforcement
            if self._ab_in is not None and self._ab_out is not None and t >= self._ab_out:
                self.seek(self._ab_in, exact=True)
                t = self._ab_in

            # Drift correction (video following master clock)
            active_panes = self._update_pane_footage(t)
            self.seeker.panes = active_panes
            if active_panes:
                for pane in active_panes:
                    if not pane.mpv:
                        continue
                    if pane.is_seeking:
                        continue

                    vid_t = pane.time_pos
                    if vid_t is None:
                        continue

                    source_t = pane.time_map.to_source(t)
                    drift = vid_t - source_t
                    pane_id = id(pane)
                    pane.set_mapping_rate_at(t)
                    tolerance = pane.sync_tolerance_at_master(t)
                    hard_threshold = max(0.25, tolerance * 8.0)

                    if abs(drift) > hard_threshold:
                        # Huge drift (e.g. delayed start), hard seek after brief hysteresis
                        self._drift_counts[pane_id] = self._drift_counts.get(pane_id, 0) + 1
                        if self._drift_counts[pane_id] > 5:
                            logger.debug(
                                "Correcting %.1f ms video drift with an exact seek",
                                drift * 1000,
                            )
                            self.seeker.seek_pane(pane, source_t, exact=True)
                            self._drift_counts[pane_id] = 0
                            pane.set_sync_correction(1.0)
                    elif abs(drift) > tolerance:
                        # Moderate drift: Soft PLL speed correction
                        self._drift_counts[pane_id] = 0
                        # If vid_t < source_t, drift is negative -> need to speed up
                        correction = 1.0 - (drift * 0.5)
                        correction = max(0.8, min(1.2, correction))
                        if abs(pane.sync_correction - correction) > 0.01:
                            pane.set_sync_correction(correction)
                    else:
                        # In sync
                        self._drift_counts[pane_id] = 0
                        if pane.sync_correction != 1.0:
                            pane.set_sync_correction(1.0)

            # Update UI
            self._update_timeline_views(t, now)

        self._last_tick_monotonic = now

    def _update_timeline_views(self, t_master: float, now: float, force: bool = False) -> None:
        """Move every timeline observer from one master-time value.

        Authoritative time still advances at 60 Hz — the clock, the plot cursor,
        and the seek bar all see every tick.  Text-formatting consumers are
        different: re-rendering 128 readout labels or resampling a 128-point pose
        sixty times a second costs more than a human can read, so they are
        rate-limited to :data:`_PRESENTATION_HZ` and skipped entirely while their
        panel is collapsed or hidden (P3.5 P1 hot path).

        ``now`` is the caller's already-sampled ``time.monotonic()`` value; this
        method never samples the clock itself, so it cannot perturb the tick's
        own timing.  ``force=True`` bypasses the rate limit for discrete events —
        a seek, a frame step, a pause — where a stale readout would be a lie
        rather than a dropped frame.
        """
        self.plot_pane.set_cursor(t_master)
        self.transport.set_time(t_master)

        if not force and (now - self._last_presentation_at) < _PRESENTATION_INTERVAL_S:
            return
        self._last_presentation_at = now

        if self.tracking_3d_pane is not None and self.tracking_3d_pane.isVisible():
            self.tracking_3d_pane.set_cursor(t_master)
        if self._readout_panel is not None and self._readout_panel.isVisible():
            self._readout_panel.set_cursor(t_master)
