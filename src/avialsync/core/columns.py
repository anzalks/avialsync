"""Columns a cache entry describes instead of storing.

A channel's level-1 columns used to be three files of one element per sample:
float64 times, the values, and a boolean gap mask. Most of that is redundant:

* A regularly sampled stream's times are ``t0 + i / rate``. Stored, they are
  8 bytes per sample -- more than the value itself. :class:`RegularTimes`
  computes them, and only after every stored sample has been checked to equal
  the formula exactly (:func:`fit_regular`), so a header that claims a rate
  the data does not keep never replaces the data's own timestamps.
* A channel without a gap has an all-false mask. :func:`no_gaps` is a
  zero-stride read-only view: a real ``ndarray`` that occupies no memory.
* Integer samples (ADC counts, digital lines) fit 16 bits; a binary source's
  samples can be read where they already are, with the format's scale applied
  on read. :class:`ScaledColumn` does both.

Consumers keep indexing, slicing and calling NumPy on these as before.
``np.searchsorted`` dispatches to :meth:`RegularTimes.searchsorted`, which is
arithmetic rather than a search. A whole-column NumPy operation materialises
the column, as reading a whole mmap always did, so it belongs only on short
columns or bounded slices, as for an mmap.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from numpy.lib.mixins import NDArrayOperatorsMixin

__all__ = [
    "LazyColumn",
    "RegularTimes",
    "ScaledColumn",
    "fit_regular",
    "no_gaps",
]

#: Samples checked per pass when verifying regularity over an mmap.
_VERIFY_CHUNK = 1_000_000


def no_gaps(length: int) -> np.ndarray:
    """An all-false gap mask of *length* that occupies no memory."""
    return np.broadcast_to(np.zeros(1, dtype=bool), (int(length),))


def _index_array(key: Any, length: int) -> np.ndarray:
    """Positions selected by *key* (an integer array or a boolean mask)."""
    selection = np.asarray(key)
    if selection.dtype == np.bool_:
        if selection.shape != (length,):
            raise IndexError("boolean index does not match the column length")
        return np.flatnonzero(selection)
    positions = selection.astype(np.int64, copy=False)
    positions = np.where(positions < 0, positions + length, positions)
    if positions.size and (positions.min() < 0 or positions.max() >= length):
        raise IndexError("index out of range for column")
    return positions


class LazyColumn(NDArrayOperatorsMixin):
    """A read-only 1-D column computed on access; looks like an ``ndarray`` to NumPy."""

    dtype: np.dtype[Any]

    def __len__(self) -> int:
        raise NotImplementedError

    @property
    def shape(self) -> tuple[int]:
        return (len(self),)

    @property
    def ndim(self) -> int:
        return 1

    @property
    def size(self) -> int:
        return len(self)

    def _take(self, positions: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def _range(self, start: int, stop: int, step: int) -> np.ndarray:
        return self._take(np.arange(start, stop, step, dtype=np.int64))

    def __getitem__(self, key: Any) -> Any:
        length = len(self)
        if isinstance(key, (int, np.integer)):
            index = int(key)
            if index < 0:
                index += length
            if not 0 <= index < length:
                raise IndexError("index out of range for column")
            return self._take(np.array([index], dtype=np.int64))[0]
        if isinstance(key, slice):
            return self._range(*key.indices(length))
        if isinstance(key, tuple) and len(key) == 1:
            return self[key[0]]
        return self._take(_index_array(key, length))

    def __iter__(self) -> Any:
        return iter(self[:])

    def __array__(self, dtype: Any = None, copy: Any = None) -> np.ndarray:
        values: np.ndarray = self[:]
        return values if dtype is None else values.astype(dtype, copy=False)

    def __array_ufunc__(self, ufunc: Any, method: str, *inputs: Any, **kwargs: Any) -> Any:
        unwrapped = tuple(np.asarray(x) if isinstance(x, LazyColumn) else x for x in inputs)
        return getattr(ufunc, method)(*unwrapped, **kwargs)

    def astype(self, dtype: Any, copy: bool = True) -> np.ndarray:
        values: np.ndarray = self[:]
        return values.astype(dtype, copy=copy)


class RegularTimes(LazyColumn):
    """Times on a regular clock, for ``k < length``, in one of three forms.

    * ``t0 + (k * stride) / rate`` -- a loader dividing a sample index by a rate;
    * ``t0 + (k * stride) * step`` -- one multiplying by an interval;
    * ``(ticks + k * stride) / rate`` -- whole clock ticks, which is what a time
      written in decimals at an exact rate parses to (``10.01`` is ``1001 / 100``).

    They differ in the last bit, and the grid must reproduce the stored times
    exactly, so it keeps whichever form did. *stride* lets a pyramid level name
    every 16th sample of level 1 with the same formula, so a level's times are
    bit-for-bit level 1's.
    """

    dtype = np.dtype(np.float64)

    def __init__(
        self,
        t0: float,
        rate: float,
        length: int,
        stride: int = 1,
        *,
        step: float | None = None,
        ticks: float | None = None,
    ) -> None:
        if step is not None:
            if not step > 0 or not math.isfinite(step):
                raise ValueError("a regular time axis needs a positive finite step")
            rate = 1.0 / step
        if not rate > 0 or not math.isfinite(rate):
            raise ValueError("a regular time axis needs a positive finite rate")
        self.t0 = float(t0)
        self.rate = float(rate)
        self.step = None if step is None else float(step)
        self.ticks = None if ticks is None else float(ticks)
        self.length = int(length)
        self.stride = int(stride)

    def __len__(self) -> int:
        return self.length

    def __repr__(self) -> str:
        form = f"step={self.step!r}" if self.step is not None else f"rate={self.rate!r}"
        return f"RegularTimes(t0={self.t0!r}, {form}, length={self.length}, stride={self.stride})"

    def _take(self, positions: np.ndarray) -> np.ndarray:
        ticks = (positions * self.stride).astype(np.float64)
        if self.step is not None:
            return self.t0 + ticks * self.step
        if self.ticks is not None:
            return (self.ticks + ticks) / self.rate
        return self.t0 + ticks / self.rate

    def _with(self, length: int, stride: int) -> RegularTimes:
        return RegularTimes(self.t0, self.rate, length, stride, step=self.step, ticks=self.ticks)

    def level(self, factor: int) -> RegularTimes:
        """Every *factor*-th time, plus the last partial block's first: a pyramid level."""
        return self._with(-(-self.length // factor), self.stride * factor)

    def _value(self, index: int) -> float:
        """Element *index*, in Python floats: the same IEEE arithmetic as :meth:`_take`."""
        ticks = float(index * self.stride)
        if self.step is not None:
            return self.t0 + ticks * self.step
        if self.ticks is not None:
            return (self.ticks + ticks) / self.rate
        return self.t0 + ticks / self.rate

    def _search_one(self, target: float, right: bool) -> int:
        """:meth:`searchsorted` for one value, without array overhead (a query's hot path)."""
        if target != target:  # NaN sorts after everything
            return self.length
        if target == math.inf:
            return self.length
        if target == -math.inf:
            return 0
        guess = math.ceil((target - self.t0) * self.rate / self.stride)
        index = min(max(guess, 0), self.length)

        def before(position: int) -> bool:
            value = self._value(position)
            return value <= target if right else value < target

        while index > 0 and not before(index - 1):
            index -= 1
        while index < self.length and before(index):
            index += 1
        return index

    def as_record(self) -> np.ndarray:
        """``[t0, rate or step, length, stride, form, ticks]``, as stored beside the values.

        ``form`` is 0 for a rate, 1 for a step, 2 for whole ticks.
        """
        form, value = 0.0, self.rate
        if self.step is not None:
            form, value = 1.0, self.step
        elif self.ticks is not None:
            form = 2.0
        return np.array(
            [self.t0, value, self.length, self.stride, form, self.ticks or 0.0], dtype=np.float64
        )

    @classmethod
    def from_record(cls, record: np.ndarray) -> RegularTimes:
        t0, value, length, stride = (float(x) for x in record[:4])
        form = float(record[4]) if len(record) > 4 else 0.0
        if form == 1.0:
            return cls(t0, 0.0, int(length), int(stride), step=value)
        if form == 2.0:
            return cls(t0, value, int(length), int(stride), ticks=float(record[5]))
        return cls(t0, value, int(length), int(stride))

    def searchsorted(self, value: Any, side: str = "left", sorter: Any = None) -> Any:
        """``np.searchsorted`` over the computed times, by arithmetic.

        A first guess from the formula is corrected against the values the
        formula actually yields, so the answer is the one a stored array of
        these same values would give.
        """
        del sorter
        scalar = np.ndim(value) == 0
        if scalar:
            return self._search_one(float(value), side == "right")
        targets = np.atleast_1d(np.asarray(value, dtype=np.float64))
        guess = np.ceil((targets - self.t0) * self.rate / self.stride)
        guess = np.clip(np.nan_to_num(guess, nan=self.length), 0, self.length).astype(np.int64)
        right = side == "right"

        def before(index: np.ndarray) -> np.ndarray:
            # Whether the element at *index* still belongs before the insertion point.
            value_at = self._take(np.clip(index, 0, max(self.length - 1, 0)))
            return value_at <= targets if right else value_at < targets

        # NaN sorts after everything, as NumPy orders it; only real targets move.
        movable = ~np.isnan(targets)
        for _ in range(4):
            step_back = movable & (guess > 0) & ~before(guess - 1)
            guess = np.where(step_back, guess - 1, guess)
            step_on = movable & (guess < self.length) & before(guess)
            guess = np.where(step_on, guess + 1, guess)
            if not (step_back.any() or step_on.any()):
                break
        return int(guess[0]) if scalar else guess


class ScaledColumn(LazyColumn):
    """``raw`` converted to *dtype*, multiplied by each of *scales* in turn, plus *offset*.

    The steps are the source format's own, in its order and precision, so a
    sample read in place is bit-for-bit the value its loader produced: neo
    converts to float32 and then multiplies by the gain in float64, NWB
    multiplies by a channel's conversion and then the series'. Each multiplier
    is applied as a float64 array, which is how both formats apply it.
    """

    def __init__(
        self,
        raw: Any,
        scales: tuple[float, ...] = (),
        offset: float = 0.0,
        dtype: Any = np.float32,
    ) -> None:
        self.raw = raw
        self.scales = tuple(float(scale) for scale in scales)
        self.offset = float(offset)
        self.dtype = np.dtype(dtype)

    def __len__(self) -> int:
        return int(self.raw.shape[0])

    def _convert(self, block: Any) -> np.ndarray:
        values = np.asarray(block).astype(self.dtype)
        for scale in self.scales:
            if scale != 1.0:
                values *= np.asarray([scale], dtype=np.float64)
        if self.offset != 0.0:
            values += np.asarray([self.offset], dtype=np.float64)
        return values

    def _take(self, positions: np.ndarray) -> np.ndarray:
        return self._convert(self.raw[positions])

    def _range(self, start: int, stop: int, step: int) -> np.ndarray:
        return self._convert(self.raw[start:stop:step])


def _candidates(t0: float, last: float, length: int) -> list[RegularTimes]:
    """Grids a loader could have written these times with, most likely first.

    Fitted to the endpoints, then with the rate and the interval rounded to
    fewer decimals: a clock written as ``start + i / 30000`` is matched by the
    rate ``30000.0``, not by the endpoint fit's ``29999.999999999996``.
    """
    fitted = (length - 1) / (last - t0)
    rates = [round(fitted, digits) for digits in range(10)] + [fitted]
    steps = [round(1.0 / fitted, digits) for digits in range(1, 16)] + [1.0 / fitted]
    grids: list[RegularTimes] = []
    for rate in dict.fromkeys(rates):
        if rate > 0:
            grids.append(RegularTimes(t0, rate, length))
            origin = t0 * rate
            if origin == round(origin) and abs(origin) < 2.0**53:
                grids.append(RegularTimes(t0, rate, length, ticks=float(round(origin))))
    for step in dict.fromkeys(steps):
        if step > 0:
            grids.append(RegularTimes(t0, 0.0, length, step=step))
    return grids


def _reproduces(grid: RegularTimes, times: Any, chunk: int) -> bool:
    """Whether *grid* yields exactly every one of *times*."""
    length = len(times)
    # Cheap rejection first: the two ends and a spread of samples between.
    probe = np.unique(np.linspace(0, length - 1, num=min(length, 257)).astype(np.int64))
    if not np.array_equal(np.asarray(times[probe], dtype=np.float64), grid[probe]):
        return False
    for start in range(0, length, chunk):
        stop = min(start + chunk, length)
        if not np.array_equal(np.asarray(times[start:stop], dtype=np.float64), grid[start:stop]):
            return False
    return True


def fit_regular(times: Any, chunk: int = _VERIFY_CHUNK) -> RegularTimes | None:
    """The grid that reproduces every one of *times* exactly, or ``None`` if none does.

    Regularity is a property of the stored samples, not of a declared rate: the
    candidate grids are checked against each stored timestamp, chunk by chunk so
    an mmap of any length stays bounded, and only a bit-for-bit match is
    accepted. A dropped sample, a jitter, a clock jump, or times written in a
    way no grid reproduces exactly, keeps the stored times: an export then
    writes the very numbers the file held, and an equality test against them
    still holds.
    """
    length = len(times)
    if length < 2:
        return None
    t0 = float(times[0])
    last = float(times[-1])
    if not (math.isfinite(t0) and math.isfinite(last)) or last <= t0:
        return None
    for grid in _candidates(t0, last, length):
        if _reproduces(grid, times, chunk):
            return grid
    return None
