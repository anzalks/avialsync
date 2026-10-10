"""Describe an NWB series' samples where they already are in the file.

HDF5 stores a dataset written without chunking or compression as one run of
bytes at a known offset, which NumPy can map directly. :func:`in_place_series`
offers such a series to the importer
(:class:`~avialsync.core.channel_store.InPlaceChannel`), so its samples stay in
the ``.nwb`` file and only the decimated levels go into the cache.

A chunked or compressed dataset, a file streamed from DANDI, and a Zarr store
are not offered: reading them sample by sample is not fast enough to replace
the cache, so they keep the copy. Times are offered as the series stores them:
``timestamps`` mapped in place (the importer turns them into a grid if every
one of them is on one), or ``starting_time`` and ``rate`` when the series has no
per-sample times, which is the schema's own definition of when its samples were
taken.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from avialsync.core.channel_store import ExternalArray, InPlaceChannel
from avialsync.core.columns import RegularTimes
from avialsync.loaders.nwb_format import SeriesInfo
from avialsync.loaders.nwb_storage import is_dataset

logger = logging.getLogger(__name__)

#: Timestamps checked per pass for order, so a series of any length stays bounded.
_CHECK_CHUNK = 4_000_000


def in_place_series(
    path: Path, handle: Any, info: SeriesInfo, names: list[str]
) -> dict[str, InPlaceChannel] | None:
    """Offer every column of *info* in place, or ``None`` when the file cannot be mapped."""
    if not isinstance(handle, h5py.File) or not path.is_file():
        return None
    group = handle[info.path]
    data = group.get("data")
    located = _mappable(data, path)
    if located is None or data.ndim not in (1, 2):
        return None
    if data.ndim == 2 and data.shape[1] != len(names) or data.ndim == 1 and len(names) != 1:
        return None
    times = _times(path, group, info)
    if times is None:
        return None
    offset_bytes, dtype = located
    shape = tuple(int(n) for n in data.shape)
    per_column = group.get("channel_conversion")
    column_scales = (
        np.asarray(per_column[()], dtype=np.float64)
        if is_dataset(per_column) and per_column.shape == (len(names),)
        else None
    )
    conversion = float(data.attrs.get("conversion", 1.0))
    offset = float(data.attrs.get("offset", 0.0))
    offers: dict[str, InPlaceChannel] = {}
    for column, name in enumerate(names):
        scales: list[float] = []
        if column_scales is not None:
            scales.append(float(column_scales[column]))
        scales.append(conversion)
        if any(not scale > 0 for scale in scales):
            return None  # a negative scale would swap each stored minimum and maximum
        offers[name] = InPlaceChannel(
            values=ExternalArray.describe(
                path, dtype, offset_bytes, shape, column=None if data.ndim == 1 else column
            ),
            times=times,
            scales=tuple(scales),
            offset=offset,
            dtype="float64",
        )
    return offers


def _mappable(dataset: Any, path: Path) -> tuple[int, np.dtype[Any]] | None:
    """``(byte offset, dtype)`` of a contiguous, uncompressed, numeric dataset in *path*."""
    if not isinstance(dataset, h5py.Dataset) or dataset.size == 0:
        return None
    if dataset.chunks is not None or dataset.compression is not None:
        return None
    if Path(dataset.file.filename).resolve() != path.resolve():
        return None  # an external link: the bytes are in another file
    if dataset.id.get_create_plist().get_external_count():
        return None
    offset = dataset.id.get_offset()
    dtype = dataset.dtype
    if offset is None or dtype.kind not in "iuf":
        return None
    return int(offset), dtype


def _times(path: Path, group: Any, info: SeriesInfo) -> Any:
    """The series' clock as the file states it, or ``None`` when it cannot be mapped."""
    if not info.has_timestamps:
        if info.rate is None or not info.rate > 0:
            return None
        return RegularTimes(info.start, info.rate, info.length)
    stored = group.get("timestamps")
    located = _mappable(stored, path)
    if located is None or located[1] != np.dtype(np.float64) or len(stored) != info.length:
        return None
    offset, dtype = located
    times = ExternalArray.describe(path, dtype, offset, (info.length,))
    return times if _increasing(times.open()) else None


def _increasing(times: np.ndarray) -> bool:
    """Whether *times* strictly increase; the copy path sorts them otherwise."""
    previous = -np.inf
    for start in range(0, len(times), _CHECK_CHUNK):
        block = np.asarray(times[start : start + _CHECK_CHUNK])
        if block[0] <= previous or (len(block) > 1 and not bool(np.all(np.diff(block) > 0))):
            return False
        previous = float(block[-1])
    return True
