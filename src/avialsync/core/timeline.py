"""Master timeline and synchronization logic."""

import dataclasses
import weakref
from collections.abc import Callable

import numpy as np

from avialsync.core.drift import MS_PER_HOUR

#: Arrays :meth:`PreparedExactMapping.prepare` validated and froze, by ``id``.
#: Weak, so a mapping nobody holds is not kept alive by having been checked.
_FROZEN: "weakref.WeakValueDictionary[int, np.ndarray]" = weakref.WeakValueDictionary()


@dataclasses.dataclass(frozen=True)
class PlaybackState:
    """Snapshot of current playback state."""

    playing: bool
    rate: float
    t: float
    bounds: tuple[float, float]


def _interp_scalar(x: float, xp: np.ndarray, fp: np.ndarray) -> float:
    """One lookup of :func:`_interp`, in plain floats: a seek or a clock tick."""
    if x < xp[0]:
        return float(fp[0])
    if x >= xp[-1]:
        return float(fp[-1])
    left = int(np.searchsorted(xp, x, side="right")) - 1
    x0 = float(xp[left])
    y0 = float(fp[left])
    if x == x0:
        return y0
    slope = (float(fp[left + 1]) - y0) / (float(xp[left + 1]) - x0)
    return slope * (x - x0) + y0


def _interp(x: np.ndarray, xp: np.ndarray, fp: np.ndarray) -> np.ndarray:
    """``np.interp``, without its copy of read-only ``xp`` and ``fp``.

    NumPy 2 copies a non-writeable array before interpolating, and exact
    mappings are frozen precisely so they can be shared: one scalar lookup on a
    million-frame mapping allocated 16 MB and took 1.6 ms, on every seek and
    playback tick. A binary search reads only the knots it needs. The formula,
    the exact value at a knot, and the clamping at both ends are NumPy's; the
    result agrees to a rounding step (NumPy's C may fuse the multiply-add).
    """
    values = np.asarray(x, dtype=np.float64)
    right = np.searchsorted(xp, values, side="right")
    left = np.clip(right - 1, 0, len(xp) - 2)
    x0 = xp[left]
    y0 = fp[left]
    slope = (fp[left + 1] - y0) / (xp[left + 1] - x0)
    result = np.where(values == x0, y0, slope * (values - x0) + y0)
    result = np.where(values < xp[0], fp[0], result)
    return np.asarray(np.where(values >= xp[-1], fp[-1], result), dtype=np.float64)


@dataclasses.dataclass(frozen=True, eq=False)
class PreparedExactMapping:
    """Validated, owned, immutable frame pairs ready for a short UI install.

    A million-frame mapping is scanned and copied once, on the worker that
    produced it. Every later holder -- each TimeMap, the provenance record, the
    undo stack, a saved session reopened -- shares those same two buffers.
    """

    master: np.ndarray
    source: np.ndarray

    @classmethod
    def adopt(cls, master_times: np.ndarray, source_times: np.ndarray) -> "PreparedExactMapping":
        """Reuse arrays an earlier :meth:`prepare` froze; prepare anything else.

        The check is identity against what :meth:`prepare` produced, not the
        writeable flag: a read-only view over memory someone else can still
        change is not frozen, and installing it unvalidated would let it change
        under a live mapping.
        """
        if (
            _FROZEN.get(id(master_times)) is master_times
            and _FROZEN.get(id(source_times)) is source_times
            and len(master_times) == len(source_times)
        ):
            return cls(master_times, source_times)
        return cls.prepare(master_times, source_times)

    @classmethod
    def prepare(cls, master_times: np.ndarray, source_times: np.ndarray) -> "PreparedExactMapping":
        """Validate and freeze arrays before crossing into the UI thread."""
        master = np.asarray(master_times, dtype=np.float64)
        source = np.asarray(source_times, dtype=np.float64)
        if (
            master.ndim != 1
            or source.ndim != 1
            or len(master) != len(source)
            or len(master) < 2
            or not np.all(np.isfinite(master))
            or not np.all(np.isfinite(source))
            or np.any(np.diff(master) <= 0)
            or np.any(np.diff(source) <= 0)
        ):
            raise ValueError(
                "Exact mapping timestamps must be equal-length, finite, strictly "
                "increasing one-dimensional arrays with at least two points."
            )
        # bytes owns storage that numpy cannot mark writable later. A readonly
        # ndarray over mutable owned memory is only advisory to its owner.
        mapping = cls(
            np.frombuffer(master.tobytes(), dtype=np.float64),
            np.frombuffer(source.tobytes(), dtype=np.float64),
        )
        _FROZEN[id(mapping.master)] = mapping.master
        _FROZEN[id(mapping.source)] = mapping.source
        return mapping


class MasterClock:
    """Single master clock for AvialSync.

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

    t_source = t_master + offset + drift_ms_per_hour / MS_PER_HOUR * (t_master - t_ref)
    """

    def __init__(self, offset: float = 0.0, drift_ms_per_hour: float = 0.0) -> None:
        self._offset: float = float(offset)
        self._drift_ms_per_hour: float = float(drift_ms_per_hour)
        self._t_ref: float = 0.0
        self._base_offset: float = self._offset  # The effective offset at t_ref
        self._exact_master: np.ndarray | None = None
        self._exact_source: np.ndarray | None = None

    @property
    def offset(self) -> float:
        return self._offset

    @offset.setter
    def offset(self, value: float) -> None:
        self._offset = float(value)
        self._base_offset = float(value)  # reset drift anchor too
        self._exact_master = None
        self._exact_source = None

    @property
    def drift_ms_per_hour(self) -> float:
        return self._drift_ms_per_hour

    @drift_ms_per_hour.setter
    def drift_ms_per_hour(self, value: float) -> None:
        self._drift_ms_per_hour = float(value)
        self._exact_master = None
        self._exact_source = None

    @property
    def rate_scale(self) -> float:
        """Return the source-time rate relative to master time."""
        if self._exact_master is not None and self._exact_source is not None:
            master_span = self._exact_master[-1] - self._exact_master[0]
            return float((self._exact_source[-1] - self._exact_source[0]) / master_span)
        return 1.0 + self._drift_ms_per_hour / MS_PER_HOUR

    @property
    def has_exact_mapping(self) -> bool:
        """Return whether accepted per-frame evidence owns this mapping."""
        return self._exact_master is not None and self._exact_source is not None

    def rate_scale_at(self, t_master: float) -> float:
        """Return the local source/master rate around ``t_master``.

        Exact frame-trigger mappings can be nonlinear, so their overall rate
        is insufficient for drift-free playback through VFR intervals.
        """
        if self._exact_master is None or self._exact_source is None:
            return 1.0 + self._drift_ms_per_hour / MS_PER_HOUR
        index = int(np.searchsorted(self._exact_master, float(t_master), side="right")) - 1
        index = max(0, min(index, len(self._exact_master) - 2))
        master_delta = self._exact_master[index + 1] - self._exact_master[index]
        source_delta = self._exact_source[index + 1] - self._exact_source[index]
        return float(source_delta / master_delta)

    def snap_master_time(self, t_master: float) -> float:
        """Snap to the nearest accepted frame-trigger timestamp, if available."""
        if self._exact_master is None:
            return float(t_master)
        value = float(t_master)
        right = int(np.searchsorted(self._exact_master, value, side="left"))
        if right <= 0:
            return float(self._exact_master[0])
        if right >= len(self._exact_master):
            return float(self._exact_master[-1])
        left = right - 1
        if value - self._exact_master[left] <= self._exact_master[right] - value:
            return float(self._exact_master[left])
        return float(self._exact_master[right])

    def contains_master_time(self, t_master: float) -> bool:
        """Return whether exact evidence covers ``t_master``.

        Affine mappings are unbounded; exact interpolation must not make its
        clamped endpoints look like footage beyond the accepted trigger range.
        """
        if self._exact_master is None:
            return True
        value = float(t_master)
        return bool(self._exact_master[0] <= value <= self._exact_master[-1])

    def to_source(self, t_master: float) -> float:
        t_master = float(t_master)
        if self._exact_master is not None and self._exact_source is not None:
            return _interp_scalar(t_master, self._exact_master, self._exact_source)
        return (
            t_master
            + self._base_offset
            + (self._drift_ms_per_hour / MS_PER_HOUR) * (t_master - self._t_ref)
        )

    def to_master(self, t_source: float) -> float:
        t_source = float(t_source)
        if self._exact_master is not None and self._exact_source is not None:
            return _interp_scalar(t_source, self._exact_source, self._exact_master)
        # to_source: ts = tm + offset + drift*(tm - t_ref)
        # ts = tm*(1 + drift) + offset - drift*t_ref
        # tm*(1 + drift) = ts - offset + drift*t_ref
        # tm = (ts - offset + drift*t_ref) / (1 + drift)
        drift_coeff = self._drift_ms_per_hour / MS_PER_HOUR
        return (t_source - self._base_offset + drift_coeff * self._t_ref) / (1.0 + drift_coeff)

    def to_master_array(self, t_source: np.ndarray) -> np.ndarray:
        """Vectorised :meth:`to_master` for an already-bounded array.

        Only ever call this on a slice or chunk.  Mapping a whole recording would
        allocate a second copy of it and defeat the mmap-backed sidecar.
        """
        source = np.asarray(t_source, dtype=np.float64)
        if self._exact_master is not None and self._exact_source is not None:
            return _interp(source, self._exact_source, self._exact_master)
        drift_coeff = self._drift_ms_per_hour / MS_PER_HOUR
        return (source - self._base_offset + drift_coeff * self._t_ref) / (1.0 + drift_coeff)

    def to_source_array(self, t_master: np.ndarray) -> np.ndarray:
        """Vectorised :meth:`to_source` for an already-bounded array."""
        master = np.asarray(t_master, dtype=np.float64)
        if self._exact_master is not None and self._exact_source is not None:
            return _interp(master, self._exact_master, self._exact_source)
        return (
            master
            + self._base_offset
            + (self._drift_ms_per_hour / MS_PER_HOUR) * (master - self._t_ref)
        )

    def update(self, new_offset: float, new_drift_ms_per_hour: float, t_master_now: float) -> None:
        """
        Update mapping parameters dynamically, anchoring so that mapped time
        at t_master_now does not jump.
        """
        new_offset = float(new_offset)
        new_drift_ms_per_hour = float(new_drift_ms_per_hour)
        t_master_now = float(t_master_now)

        # Calculate current mapped time
        current_t_source = self.to_source(t_master_now)

        # We want the new mapping to equal current_t_source at t_master_now
        # current_t_source = t_master_now + new_base_offset +
        #                    (new_drift / MS_PER_HOUR) * (t_master_now - t_master_now)
        # current_t_source = t_master_now + new_base_offset
        # => new_base_offset = current_t_source - t_master_now

        self._t_ref = t_master_now
        self._base_offset = current_t_source - t_master_now
        self._offset = new_offset
        self._drift_ms_per_hour = new_drift_ms_per_hour
        self._exact_master = None
        self._exact_source = None

    def set_mapping(self, offset: float, drift_ms_per_hour: float, t_ref: float = 0.0) -> None:
        """Replace this source mapping with an accepted, absolute calibration.

        Unlike :meth:`update`, this method intentionally does not preserve the
        current visual position.  It is only for a user-accepted alignment fit
        whose reference epoch is known and must be reproduced on session load.
        """
        self._offset = float(offset)
        self._base_offset = float(offset)
        self._drift_ms_per_hour = float(drift_ms_per_hour)
        self._t_ref = float(t_ref)
        self._exact_master = None
        self._exact_source = None

    def set_exact_mapping(self, master_times: np.ndarray, source_times: np.ndarray) -> None:
        """Set a piecewise interpolation array for exact non-affine mapping.

        This overrides offset/drift parameters during to_source and to_master evaluations.
        Arrays a worker already prepared are shared as they are; anything else is
        validated and frozen here.
        """
        self.install_prepared_exact_mapping(PreparedExactMapping.adopt(master_times, source_times))

    def install_prepared_exact_mapping(self, mapping: PreparedExactMapping) -> None:
        """Install worker-prepared frame pairs without scanning or copying them."""
        self._exact_master = mapping.master
        self._exact_source = mapping.source

    def copy(self) -> "TimeMap":
        """Snapshot settings while sharing immutable exact-evidence arrays."""
        copied = TimeMap(self._offset, self._drift_ms_per_hour)
        copied._t_ref = self._t_ref
        copied._base_offset = self._base_offset
        # Both arrays were frozen when they were installed. A later
        # mapping change replaces them, so copying millions of pairs for each
        # worker reference buys no isolation and can stall the UI.
        copied._exact_master = self._exact_master
        copied._exact_source = self._exact_source
        return copied
