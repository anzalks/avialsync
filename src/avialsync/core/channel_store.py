"""How one channel's columns are laid out in a cache entry, written and read.

Every level of a channel has a time column, a value column (or two, the
minimum and maximum envelope above level 1) and a gap column. Each is stored
only as far as it carries information (:mod:`avialsync.core.columns`):

==========================  =========================================================
``{ch}_t.npy``              level-1 times, when they are not a verified grid
``{ch}_tgrid.npy``          ``[t0, rate, length, stride]`` when they are
``{ch}_v.npy``              level-1 values (float64, float32, or int16 when lossless)
``{ch}_gap.npy``            level-1 gap mask, only when the channel has a gap
``{ch}_pyr_{L}_*``          the same for level ``L``, with ``vmin``/``vmax``
``{ch}_layout.json``        values read in place from the source, and/or a scale
==========================  =========================================================

An entry written before this layout is read unchanged: every array it holds
has the name the old layout gave it.

**Values read in place.** A binary source (an Open Ephys ``continuous.dat``, an
uncompressed, contiguous NWB dataset) already holds its samples in a form NumPy can
map. ``{ch}_layout.json`` names the file, its dtype, byte offset, shape and
column, and the scale the format applies; level 1 is read from there and only
the decimated levels live in the cache. The file's size and modification time
are recorded, and :func:`external_files_intact` refuses the entry when either
changed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.columns import LazyColumn, RegularTimes, ScaledColumn, no_gaps

__all__ = [
    "ExternalArray",
    "InPlaceChannel",
    "columns_intact",
    "Layout",
    "external_files_intact",
    "level_stem",
    "load_layout",
    "read_level",
    "safe_save",
    "write_layout",
    "write_times",
]

LAYOUT_SUFFIX = "_layout.json"

Column = np.ndarray | LazyColumn


def level_stem(channel: str, level: int) -> str:
    """``{channel}`` for level 1, ``{channel}_pyr_{level}`` above it."""
    return channel if level == 1 else f"{channel}_pyr_{level}"


@dataclass(frozen=True)
class ExternalArray:
    """A 1-D column inside a file the cache does not own, mapped read-only."""

    path: str
    dtype: str
    offset: int
    shape: tuple[int, ...]
    column: int | None = None
    size: int = 0
    mtime_ns: int = 0

    @classmethod
    def describe(
        cls,
        path: Path,
        dtype: Any,
        offset: int,
        shape: tuple[int, ...],
        column: int | None = None,
    ) -> ExternalArray:
        """Describe *path* as it is now, so a later change to it is noticed."""
        stat = path.stat()
        return cls(
            path=str(path.resolve()),
            dtype=np.dtype(dtype).str,
            offset=int(offset),
            shape=tuple(int(n) for n in shape),
            column=column,
            size=int(stat.st_size),
            mtime_ns=int(stat.st_mtime_ns),
        )

    def open(self) -> np.ndarray:
        mapped = np.memmap(
            self.path, dtype=np.dtype(self.dtype), mode="r", offset=self.offset, shape=self.shape
        )
        return mapped if self.column is None else mapped[:, self.column]

    def intact(self) -> bool:
        try:
            stat = os.stat(self.path)
        except OSError:
            return False
        return stat.st_size == self.size and stat.st_mtime_ns == self.mtime_ns

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "dtype": self.dtype,
            "offset": self.offset,
            "shape": list(self.shape),
            "column": self.column,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExternalArray:
        column = data.get("column")
        return cls(
            path=str(data["path"]),
            dtype=str(data["dtype"]),
            offset=int(data["offset"]),
            shape=tuple(int(n) for n in data["shape"]),
            column=None if column is None else int(column),
            size=int(data.get("size", 0)),
            mtime_ns=int(data.get("mtime_ns", 0)),
        )


@dataclass(frozen=True)
class Layout:
    """What a channel's ``_layout.json`` says: a conversion, and columns read in place.

    *scales*, *offset* and *dtype* are the source format's own conversion
    (:class:`~avialsync.core.columns.ScaledColumn`); they apply to level 1 and
    to the stored envelopes above it alike.
    """

    scales: tuple[float, ...] = ()
    offset: float = 0.0
    dtype: str = "float64"
    values: ExternalArray | None = None
    times: ExternalArray | None = None

    @property
    def scaled(self) -> bool:
        return bool(self.scales) or self.offset != 0.0 or self.values is not None


@dataclass(frozen=True)
class InPlaceChannel:
    """A channel a loader offers to leave in its source file.

    *values* is the raw column, read as ``raw * scale + offset``. *times* is a
    :class:`RegularTimes` the loader verified against the file's own per-sample
    evidence, an :class:`ExternalArray` of stored timestamps, or a column
    computed from such evidence (written to the cache, since it is not on disk
    as such). Every channel a loader offers together shares one *times*.
    """

    values: ExternalArray
    times: Any
    scales: tuple[float, ...] = ()
    offset: float = 0.0
    dtype: str = "float64"


def write_layout(directory: Path, channel: str, layout: Layout) -> None:
    payload: dict[str, Any] = {
        "scales": list(layout.scales),
        "offset": layout.offset,
        "dtype": layout.dtype,
    }
    if layout.values is not None:
        payload["values"] = layout.values.as_dict()
    if layout.times is not None:
        payload["times"] = layout.times.as_dict()
    (directory / f"{channel}{LAYOUT_SUFFIX}").write_text(json.dumps(payload), encoding="utf-8")


def load_layout(directory: Path, channel: str) -> Layout:
    path = directory / f"{channel}{LAYOUT_SUFFIX}"
    if not path.is_file():
        return Layout()
    data = json.loads(path.read_text(encoding="utf-8"))
    return Layout(
        scales=tuple(float(scale) for scale in data.get("scales", ())),
        offset=float(data.get("offset", 0.0)),
        dtype=str(data.get("dtype", "float64")),
        values=ExternalArray.from_dict(data["values"]) if "values" in data else None,
        times=ExternalArray.from_dict(data["times"]) if "times" in data else None,
    )


def external_files_intact(directory: Path, channel: str) -> bool:
    """Whether every file *channel* reads in place is still the one it was imported from."""
    try:
        layout = load_layout(directory, channel)
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return all(item.intact() for item in (layout.values, layout.times) if item is not None)


def safe_save(path: Path, arr: np.ndarray) -> None:
    """Save quickly, retrying macOS interrupted writes through a memmap."""
    try:
        np.save(path, arr)
        return
    except InterruptedError:
        # A signal can interrupt NumPy's C-level fwrite on macOS. Recreate the
        # partial file through mmap; all other storage failures remain visible.
        pass

    mapped = np.lib.format.open_memmap(path, mode="w+", dtype=arr.dtype, shape=arr.shape)
    mapped[:] = arr
    mapped.flush()


def write_times(directory: Path, stem: str, times: Any) -> None:
    """Store *times* as a grid record when it is one, else as an array."""
    if isinstance(times, RegularTimes):
        safe_save(directory / f"{stem}_tgrid.npy", times.as_record())
    else:
        safe_save(directory / f"{stem}_t.npy", np.asarray(times, dtype=np.float64))


def _times(directory: Path, stem: str, layout: Layout, level: int) -> Column:
    grid = directory / f"{stem}_tgrid.npy"
    if grid.is_file():
        return RegularTimes.from_record(np.load(grid, allow_pickle=False))
    if level == 1 and layout.times is not None:
        return layout.times.open()
    loaded: np.ndarray = np.load(directory / f"{stem}_t.npy", mmap_mode="r", allow_pickle=False)
    return loaded


def _values(array: np.ndarray, layout: Layout) -> Column:
    """Integer or scaled storage as the floats consumers read; floats untouched."""
    if layout.scaled:
        return ScaledColumn(array, layout.scales, layout.offset, layout.dtype)
    if np.issubdtype(array.dtype, np.integer):
        return ScaledColumn(array, (), 0.0, np.float32)
    return array


def _gaps(directory: Path, stem: str, length: int) -> np.ndarray:
    path = directory / f"{stem}_gap.npy"
    if path.is_file():
        loaded: np.ndarray = np.load(path, mmap_mode="r", allow_pickle=False)
        return loaded
    return no_gaps(length)


def _npy_shape(path: Path) -> tuple[tuple[int, ...], np.dtype[Any]]:
    """A ``.npy`` file's shape and dtype, from its header alone."""
    with path.open("rb") as handle:
        version = np.lib.format.read_magic(handle)
        if version == (1, 0):
            shape, _fortran, dtype = np.lib.format.read_array_header_1_0(handle)
        else:
            shape, _fortran, dtype = np.lib.format.read_array_header_2_0(handle)
    return tuple(int(n) for n in shape), np.dtype(dtype)


def _length(
    directory: Path, stem: str, kind: str, present: set[str]
) -> tuple[int, np.dtype[Any]] | None:
    """Length and dtype of one stored column, or ``None`` when it is not stored."""
    name = f"{stem}_{kind}.npy"
    if name not in present:
        return None
    path = directory / name
    shape, dtype = _npy_shape(path)
    if len(shape) != 1:
        raise ValueError(f"{path.name} is not a column")
    return shape[0], dtype


def columns_intact(
    directory: Path, channel: str, levels: list[int], present: set[str] | None = None
) -> bool:
    """Whether every level of *channel* has consistent columns, reading only headers.

    What a cached import is checked with before it is trusted. The importer's
    manifest check covers every array's size and content fingerprint, so this
    checks shapes alone: nothing is mapped, and of the grid records only level
    1's is read, for the sample count. *present* is the entry's file names, when
    the caller has listed them once for every channel.
    """
    try:
        if present is None:
            present = {entry.name for entry in os.scandir(directory)}
        layout = (
            load_layout(directory, channel) if f"{channel}{LAYOUT_SUFFIX}" in present else Layout()
        )
        if not all(item.intact() for item in (layout.values, layout.times) if item is not None):
            return False
        count = 0
        for level in levels:
            stem = level_stem(channel, level)
            if f"{stem}_tgrid.npy" in present:
                if level == 1:
                    record = np.load(directory / f"{stem}_tgrid.npy", allow_pickle=False)
                    length = len(RegularTimes.from_record(record))
                else:
                    length = -(-count // level)  # its record is fingerprinted with the rest
            elif level == 1 and layout.times is not None:
                length = layout.times.shape[0]
            else:
                stored = _length(directory, stem, "t", present)
                if stored is None or stored[1] != np.float64:
                    return False
                length = stored[0]
            if level == 1:
                if layout.values is not None:
                    value_lengths = [layout.values.shape[0]]
                else:
                    stored = _length(directory, stem, "v", present)
                    if stored is None or not np.issubdtype(stored[1], np.number):
                        return False
                    value_lengths = [stored[0]]
                count = length
                expected = count
            else:
                expected = (count + level - 1) // level
                value_lengths = []
                for kind in ("vmin", "vmax"):
                    stored = _length(directory, stem, kind, present)
                    if stored is None or not np.issubdtype(stored[1], np.number):
                        return False
                    value_lengths.append(stored[0])
            gap = _length(directory, stem, "gap", present)
            if gap is not None and (gap[1] != np.bool_ or gap[0] != length):
                return False
            if length != expected or any(n != expected for n in value_lengths) or count == 0:
                return False
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return True


def read_level(
    directory: Path, channel: str, level: int
) -> tuple[Column, Column, Column, np.ndarray]:
    """``(t, vmin, vmax, gap)`` for one level; level 1's ``vmin`` and ``vmax`` are its values."""
    layout = load_layout(directory, channel)
    stem = level_stem(channel, level)
    times = _times(directory, stem, layout, level)
    if level == 1:
        raw = (
            layout.values.open()
            if layout.values is not None
            else np.load(directory / f"{stem}_v.npy", mmap_mode="r", allow_pickle=False)
        )
        values = _values(raw, layout)
        return times, values, values, _gaps(directory, stem, len(times))
    vmin = _values(
        np.load(directory / f"{stem}_vmin.npy", mmap_mode="r", allow_pickle=False), layout
    )
    vmax = _values(
        np.load(directory / f"{stem}_vmax.npy", mmap_mode="r", allow_pickle=False), layout
    )
    return times, vmin, vmax, _gaps(directory, stem, len(times))
