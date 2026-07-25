"""Master timeline and synchronization logic."""

import dataclasses
from collections.abc import Callable


@dataclasses.dataclass(frozen=True)
class PlaybackState:
    """Snapshot of current playback state."""

    playing: bool
    rate: float
    t: float
    bounds: tuple[float, float]


class MasterClock:
    """Single master clock for KinoChronix.

    Time is driven externally via advance(monotonic_now) to ensure exact monotonic sync
    without accumulating interval errors.
    """

    def __init__(self) -> None:
        self._playing: bool = False
        self._rate: float = 1.0
        self._t: float = 0.0
        self._bounds: tuple[float, float] = (0.0, 0.0)
        self._last_monotonic: float | None = None

        self._subscribers: list[Callable[[float], None]] = []

    def subscribe(self, callback: Callable[[float], None]) -> None:
        """Register a callback that is fired on seek or playback advance."""
        self._subscribers.append(callback)

    def _notify(self) -> None:
        for callback in self._subscribers:
            callback(self._t)

    @property
    def state(self) -> PlaybackState:
        return PlaybackState(playing=self._playing, rate=self._rate, t=self._t, bounds=self._bounds)

    def set_bounds(self, start: float, end: float) -> None:
        """Set the absolute limits of the master timeline."""
        if start > end:
            start, end = end, start
        self._bounds = (start, end)
        self._clamp_and_notify()

    def play(self) -> None:
        if not self._playing:
            self._playing = True
            self._last_monotonic = None  # Will be anchored on next advance

    def pause(self) -> None:
        if self._playing:
            self._playing = False
            self._last_monotonic = None

    def set_rate(self, rate: float) -> None:
        """Set playback rate, clamped between 0.01 and 10.0."""
        self._rate = max(0.01, min(10.0, float(rate)))
        self._last_monotonic = (
            None  # Re-anchor on next advance to prevent jump with old monotonic delta
        )

    def seek(self, t: float) -> None:
        """Seek to a specific master time."""
        self._t = float(t)
        self._last_monotonic = None
        self._clamp_and_notify()

    def advance(self, monotonic_now: float) -> None:
        """Advance time based on monotonic deltas."""
        monotonic_now = float(monotonic_now)
        if not self._playing:
            self._last_monotonic = monotonic_now
            return

        if self._last_monotonic is None:
            self._last_monotonic = monotonic_now
            return

        delta = monotonic_now - self._last_monotonic
        if delta < 0:
            delta = 0.0  # Monotonic clocks shouldn't go backwards, but just in case

        self._last_monotonic = monotonic_now

        if delta > 0:
            self._t += delta * self._rate
            self._clamp_and_notify()

    def _clamp_and_notify(self) -> None:
        # Clamp exactly to bounds
        if self._t < self._bounds[0]:
            self._t = self._bounds[0]
            self.pause()  # Stop at bounds
        elif self._t > self._bounds[1]:
            self._t = self._bounds[1]
            self.pause()  # Stop at bounds

        self._notify()


class TimeMap:
    """Maps master timeline to a specific source timeline.

    t_source = t_master + offset + drift_ppm * 1e-6 * (t_master - t_ref)
    """

    def __init__(self, offset: float = 0.0, drift_ppm: float = 0.0) -> None:
        self._offset: float = float(offset)
        self._drift_ppm: float = float(drift_ppm)
        self._t_ref: float = 0.0
        self._base_offset: float = self._offset  # The effective offset at t_ref

    @property
    def offset(self) -> float:
        return self._offset

    @offset.setter
    def offset(self, value: float) -> None:
        self._offset = float(value)
        self._base_offset = float(value)  # reset drift anchor too

    @property
    def drift_ppm(self) -> float:
        return self._drift_ppm

    def to_source(self, t_master: float) -> float:
        t_master = float(t_master)
        return t_master + self._base_offset + (self._drift_ppm * 1e-6) * (t_master - self._t_ref)

    def to_master(self, t_source: float) -> float:
        t_source = float(t_source)
        # to_source: ts = tm + offset + drift*(tm - t_ref)
        # ts = tm*(1 + drift) + offset - drift*t_ref
        # tm*(1 + drift) = ts - offset + drift*t_ref
        # tm = (ts - offset + drift*t_ref) / (1 + drift)
        drift_coeff = self._drift_ppm * 1e-6
        return (t_source - self._base_offset + drift_coeff * self._t_ref) / (1.0 + drift_coeff)

    def update(self, new_offset: float, new_drift_ppm: float, t_master_now: float) -> None:
        """
        Update mapping parameters dynamically, anchoring so that mapped time
        at t_master_now does not jump.
        """
        new_offset = float(new_offset)
        new_drift_ppm = float(new_drift_ppm)
        t_master_now = float(t_master_now)

        # Calculate current mapped time
        current_t_source = self.to_source(t_master_now)

        # We want the new mapping to equal current_t_source at t_master_now
        # current_t_source = t_master_now + new_base_offset +
        #                    (new_drift * 1e-6) * (t_master_now - t_master_now)
        # current_t_source = t_master_now + new_base_offset
        # => new_base_offset = current_t_source - t_master_now

        self._t_ref = t_master_now
        self._base_offset = current_t_source - t_master_now
        self._offset = new_offset
        self._drift_ppm = new_drift_ppm

    def set_mapping(self, offset: float, drift_ppm: float, t_ref: float = 0.0) -> None:
        """Replace this source mapping with an accepted, absolute calibration.

        Unlike :meth:`update`, this method intentionally does not preserve the
        current visual position.  It is only for a user-accepted alignment fit
        whose reference epoch is known and must be reproduced on session load.
        """
        self._offset = float(offset)
        self._base_offset = float(offset)
        self._drift_ppm = float(drift_ppm)
        self._t_ref = float(t_ref)
