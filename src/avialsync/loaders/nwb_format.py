"""What an NWB 2.x file holds, and how to read it, with h5py alone (D-188).

Neurodata Without Borders stores one session per file: one subject, one
``session_start_time``, one clock, and every recording made in that session --
electrophysiology, imaging, behaviour, trials -- as objects inside an HDF5 tree.
This module is the only place that knows that tree. The loaders beside it
(:mod:`nwb_loader`, :mod:`nwb_imaging`, :mod:`nwb_session`) ask it what is there
and for samples, and never touch h5py themselves.

**Objects are recognised by structure, not by type name.** A ``TimeSeries`` is
any group holding a ``data`` dataset and either ``timestamps`` or
``starting_time``; that is the schema's own definition, and it is what lets a
series of an extension type (``ndx-*``) load without this module knowing the
extension. The ``neurodata_type`` attribute -- resolved through the specification
cached inside the file when it names an extension -- only refines *how* a
recognised series is read: an ``ElectricalSeries`` names its columns after its
electrodes, an ``ImageSeries`` is pictures, an ``IntervalSeries`` is on/off.

**Why not pynwb.** Its HDF5 data layer is h5py, so it reads samples no faster,
and it refuses files whose cached specification conflicts with the installed
schema -- including real DANDI files -- unless namespaces are not loaded, which
is the very feature it would have been here for. It also builds the whole object
tree before returning anything and pulls pandas in with it. The structural
reading above keeps extension types working without either cost.

What is not read, and said so rather than skipped silently: NWB 1.x files (a
different schema, which pynwb does not read either), Zarr-backed NWB (h5py cannot
open it), and series whose data has no time-series shape this application can
show (``SpikeEventSeries`` waveforms, ``DecompositionSeries`` bands).

No PySide6 import here: this runs on import and scan threads.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from avialsync.core.errors import FileUnreadableError, SourceOpenError
from avialsync.core.source import container_of
from avialsync.loaders.nwb_text import text
from avialsync.loaders.nwb_types import is_a, type_ancestry

logger = logging.getLogger(__name__)

NWB_SUFFIX = ".nwb"

#: The file's sections that hold recordings, and the name prefix each keeps.
#: Acquisition is the default home of raw data and needs no prefix; a stimulus
#: is named as one so it cannot be mistaken for a response with the same name.
_SECTIONS: tuple[tuple[str, str], ...] = (
    ("acquisition", ""),
    ("processing", ""),
    ("stimulus/presentation", "stimulus"),
    ("intervals", ""),
    ("units", ""),
)

#: How deep below a section a series may sit. Processing modules nest a data
#: interface inside a module (``processing/ophys/DfOverF/RoiResponseSeries``);
#: nothing in the schema goes much deeper, and the bound keeps a pathological
#: file from turning a scan into a crawl.
_MAX_DEPTH = 6

#: Types whose data is pictures, not samples. Anything inheriting from these --
#: directly or through an extension's cached specification -- is imaging.
_IMAGE_BASE = "ImageSeries"

#: Types recognised as series but declined, with the reason given to the user.
_DECLINED: dict[str, str] = {
    "ImageMaskSeries": "holds masks, not a recording",
    "SpikeEventSeries": "holds spike waveforms, not a continuous signal",
    "DecompositionSeries": "holds frequency-band decompositions, not a continuous signal",
}

#: Spellings that mean "this column is a unit's spatial axis".
_AXES = ("x", "y", "z")

#: Characters that would nest a channel name (``.``, ``/``) or break a cache
#: file name on Windows. A segment of a channel name may not contain them.
_UNSAFE_SEGMENT = re.compile(r'[./\\<>:"|?*\x00-\x1f]+')


class NWBFormatError(SourceOpenError):
    """Raised when a file is NWB this application cannot read, saying which kind."""


# ── What a file holds ──────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class SeriesInfo:
    """One ``TimeSeries`` in the file, described without reading its samples.

    ``kind`` is how it is shown: ``signal`` (plotted samples), ``interval``
    (on/off states), ``annotation`` (text at instants), ``imaging`` (pictures in
    the file) or ``external`` (pictures in a video file beside it).
    """

    path: str
    name: str
    neurodata_type: str
    kind: str
    unit: str
    length: int
    columns: tuple[str, ...]
    rate: float | None
    start: float
    has_timestamps: bool
    frame_shape: tuple[int, ...] = ()
    dtype: str = ""
    external_files: tuple[str, ...] = ()

    def channel_names(self) -> list[str]:
        """Return one channel name per column, in column order."""
        return [f"{self.name}.{column}" if column else self.name for column in self.columns]


@dataclasses.dataclass(frozen=True)
class IntervalTable:
    """A ``TimeIntervals`` table: trials, epochs, or any lab-defined intervals."""

    path: str
    name: str
    rows: int


@dataclasses.dataclass(frozen=True)
class UnitsTable:
    """A ``Units`` table: spike-sorted units and the times each one fired."""

    path: str
    name: str
    unit_ids: tuple[int, ...]
    #: The table row of each unit in :attr:`unit_ids`. Units that never fired are
    #: left out, so these need not run 0, 1, 2…
    rows: tuple[int, ...] = ()

    def channel_names(self) -> list[str]:
        return [f"{self.name}.unit{unit_id}" for unit_id in self.unit_ids]


@dataclasses.dataclass(frozen=True)
class FileContents:
    """Everything a scan found, and everything it found but could not use."""

    version: str
    reference_epoch: float | None
    reference_is_naive: bool
    series: tuple[SeriesInfo, ...]
    interval_tables: tuple[IntervalTable, ...]
    units_tables: tuple[UnitsTable, ...]
    declined: tuple[str, ...]

    def of_kind(self, *kinds: str) -> list[SeriesInfo]:
        return [info for info in self.series if info.kind in kinds]


# ── Opening ────────────────────────────────────────────────────────────────


def is_nwb_path(path: Path) -> bool:
    """Whether *path* is named like an NWB file. Cheap: no I/O beyond a stat."""
    return path.suffix.lower() == NWB_SUFFIX and path.is_file()


def is_zarr_nwb(path: Path) -> bool:
    """Whether *path* is an NWB file stored as Zarr, which h5py cannot open."""
    if not path.is_dir():
        return False
    name = path.name.lower()
    named = name.endswith(".nwb") or name.endswith(".nwb.zarr")
    return named and ((path / ".zgroup").is_file() or (path / "zarr.json").is_file())


def object_path(file: Path, object_name: str) -> Path:
    """Name an object inside *file* as a path: ``session.nwb/acquisition/TwoPhotonSeries``.

    A source is identified by its path, and an NWB file's time series already go
    by the file's own. The imaging needs a name of its own that still says
    where it lives (:func:`avialsync.core.source.container_of`).
    """
    return file / object_name.lstrip("/")


def split_object_path(path: Path) -> tuple[Path, str] | None:
    """Return ``(nwb_file, "/object/path")`` for a path made by :func:`object_path`."""
    container = container_of(path)
    if container is None or container.suffix.lower() != NWB_SUFFIX:
        return None
    return container, "/" + path.relative_to(container).as_posix()


def open_file(path: Path) -> h5py.File:
    """Open *path* read-only, raising a typed error that says what it is.

    ``locking=False`` because nothing here writes, and HDF5's advisory lock is
    refused on some network shares and read-only media -- where a recording
    that can perfectly well be read would otherwise fail to open.
    """
    if path.is_dir():
        if is_zarr_nwb(path):
            raise NWBFormatError(
                f"{path.name} is NWB stored as Zarr, which AvialSync does not read yet. "
                "Convert it to HDF5 NWB (for example with NWB Inspector's or hdmf-zarr's export)."
            )
        raise FileUnreadableError(f"{path.name} is a folder, not an NWB file.")
    try:
        handle = h5py.File(path, "r", locking=False)
    except (OSError, ValueError) as error:
        raise FileUnreadableError(f"{path.name} could not be opened as HDF5 ({error}).") from error
    version = text(handle.attrs.get("nwb_version", ""))
    if version.upper().startswith("NWB-1") or (not version and "acquisition/timeseries" in handle):
        handle.close()
        raise NWBFormatError(
            f"{path.name} is NWB 1.x ({version or 'no version attribute'}), whose layout "
            "predates NWB 2. Convert it to NWB 2 to open it."
        )
    if not version and "session_start_time" not in handle:
        handle.close()
        raise NWBFormatError(f"{path.name} is HDF5 but not NWB: it has no nwb_version.")
    return handle


def scan(path: Path) -> FileContents:
    """Describe everything in *path* without reading any samples."""
    with open_file(path) as handle:
        return _scan_open(handle)


def _scan_open(handle: h5py.File) -> FileContents:
    ancestry = type_ancestry(handle)
    declined: list[str] = []
    series: list[SeriesInfo] = []
    intervals: list[IntervalTable] = []
    units: list[UnitsTable] = []
    names: set[str] = set()

    for section, prefix in _SECTIONS:
        root = handle.get(section)
        if root is None:
            continue
        if isinstance(root, h5py.Group) and _is_units(root):
            table = _units_table(root, "units", names)
            if table is not None:
                units.append(table)
            continue
        if not isinstance(root, h5py.Group):
            continue
        for group, relative in _walk(root):
            if not (_is_units(group) or _is_interval_table(group) or _is_time_series(group)):
                continue
            stem = _unique(_channel_stem(prefix, relative), names)
            names.add(stem)
            if _is_units(group):
                table = _units_table(group, stem, set())
                if table is not None:
                    units.append(table)
            elif _is_interval_table(group):
                rows = int(group["start_time"].shape[0])
                if rows:
                    intervals.append(IntervalTable(path=group.name, name=stem, rows=rows))
            else:
                info = _describe_series(handle, group, stem, ancestry, declined)
                if info is not None:
                    series.append(info)

    epoch, naive = _reference_epoch(handle)
    return FileContents(
        version=text(handle.attrs.get("nwb_version", "")),
        reference_epoch=epoch,
        reference_is_naive=naive,
        series=tuple(series),
        interval_tables=tuple(intervals),
        units_tables=tuple(units),
        declined=tuple(declined),
    )


def _walk(root: h5py.Group, depth: int = 0, relative: str = "") -> Iterator[tuple[h5py.Group, str]]:
    """Yield every group below *root* that may be an object, outermost first.

    Soft-linked groups are not followed: a series linked from two places is one
    series, and listing it twice would import it twice. A recognised object is
    not descended into -- a series' own ``timestamps`` group or a table's columns
    are parts of it, not further objects.
    """
    if depth > _MAX_DEPTH:
        return
    for key in sorted(root.keys()):
        link = root.get(key, getlink=True)
        if not isinstance(link, h5py.HardLink):
            continue
        child = root.get(key)
        if not isinstance(child, h5py.Group):
            continue
        path = f"{relative}/{key}" if relative else key
        yield child, path
        if _is_time_series(child) or _is_interval_table(child) or _is_units(child):
            continue
        yield from _walk(child, depth + 1, path)


def _is_time_series(group: h5py.Group) -> bool:
    return isinstance(group.get("data"), h5py.Dataset) and (
        isinstance(group.get("timestamps"), h5py.Dataset)
        or isinstance(group.get("starting_time"), h5py.Dataset)
    )


def _is_interval_table(group: h5py.Group) -> bool:
    return (
        isinstance(group.get("start_time"), h5py.Dataset)
        and isinstance(group.get("stop_time"), h5py.Dataset)
        and "data" not in group
    )


def _is_units(group: h5py.Group) -> bool:
    return isinstance(group.get("spike_times"), h5py.Dataset) and isinstance(
        group.get("spike_times_index"), h5py.Dataset
    )


# ── Describing one series ──────────────────────────────────────────────────


def _describe_series(
    handle: h5py.File,
    group: h5py.Group,
    stem: str,
    ancestry: dict[str, str],
    declined: list[str],
) -> SeriesInfo | None:
    data = group["data"]
    neurodata_type = text(group.attrs.get("neurodata_type", "TimeSeries")) or "TimeSeries"
    label = f"{group.name} ({neurodata_type})"

    for base, reason in _DECLINED.items():
        if is_a(neurodata_type, base, ancestry):
            declined.append(f"{label} {reason}.")
            return None

    rate, start, has_timestamps, time_length = _time_axis(group)
    if rate is None and not has_timestamps:
        declined.append(f"{label} has no usable time axis.")
        return None

    common: dict[str, Any] = {
        "path": group.name,
        "name": stem,
        "neurodata_type": neurodata_type,
        "unit": text(data.attrs.get("unit", "")),
        "rate": rate,
        "start": start,
        "has_timestamps": has_timestamps,
        "dtype": str(data.dtype),
    }

    if is_a(neurodata_type, _IMAGE_BASE, ancestry):
        external = _external_files(group)
        if external and (data.size == 0 or data.ndim < 3):
            return SeriesInfo(
                kind="external",
                length=max(time_length, 0),
                columns=(),
                external_files=external,
                **common,
            )
        if data.ndim in (3, 4) and data.shape[0] > 0:
            return SeriesInfo(
                kind="imaging",
                length=_paired_length(data.shape[0], time_length, has_timestamps),
                columns=(),
                frame_shape=tuple(int(size) for size in data.shape[1:]),
                **common,
            )
        declined.append(f"{label} holds no frames this application can show.")
        return None

    if data.shape and data.shape[0] == 0:
        declined.append(f"{label} is empty.")
        return None

    if is_a(neurodata_type, "AnnotationSeries", ancestry) or data.dtype.kind in "OSU":
        if data.ndim != 1:
            declined.append(f"{label} holds text in more than one dimension.")
            return None
        return SeriesInfo(
            kind="annotation",
            length=_paired_length(data.shape[0], time_length, has_timestamps),
            columns=("",),
            **common,
        )

    if data.dtype.kind not in "biuf" or data.ndim not in (1, 2):
        declined.append(f"{label} has {data.ndim}-D {data.dtype} data, which is not a signal.")
        return None

    length = _paired_length(data.shape[0], time_length, has_timestamps)
    kind = "interval" if is_a(neurodata_type, "IntervalSeries", ancestry) else "signal"
    if kind == "interval" and (not has_timestamps or data.ndim != 1):
        declined.append(f"{label} is an interval series without per-edge timestamps.")
        return None
    columns = ("",) if data.ndim == 1 else _column_names(handle, group, neurodata_type, ancestry)
    return SeriesInfo(kind=kind, length=length, columns=columns, **common)


def _time_axis(group: h5py.Group) -> tuple[float | None, float, bool, int]:
    """Return ``(rate, start, has_timestamps, timestamp_count)`` for a series."""
    timestamps = group.get("timestamps")
    if isinstance(timestamps, h5py.Dataset) and timestamps.ndim == 1 and timestamps.shape[0] > 0:
        first = float(timestamps[0])
        return None, first, True, int(timestamps.shape[0])
    starting = group.get("starting_time")
    if isinstance(starting, h5py.Dataset):
        rate = float(starting.attrs.get("rate", 0.0) or 0.0)
        if rate > 0.0 and np.isfinite(rate):
            return rate, float(starting[()]), False, -1
    return None, 0.0, False, 0


def _paired_length(data_length: int, time_length: int, has_timestamps: bool) -> int:
    """How many samples have both a value and a time.

    A writer that stopped mid-session can leave one array longer than the other;
    the common prefix is correct for every sample it covers, so it is what loads.
    """
    if not has_timestamps:
        return int(data_length)
    if data_length != time_length:
        logger.warning(
            "NWB series has %d samples but %d timestamps; reading the first %d.",
            data_length,
            time_length,
            min(data_length, time_length),
        )
    return int(min(data_length, time_length))


def _column_names(
    handle: h5py.File, group: h5py.Group, neurodata_type: str, ancestry: dict[str, str]
) -> tuple[str, ...]:
    """Name each column of a 2-D series after what it measures, when the file says."""
    width = int(group["data"].shape[1])
    if is_a(neurodata_type, "SpatialSeries", ancestry) and width <= len(_AXES):
        return _AXES[:width]
    for region, prefix in (("electrodes", "ch"), ("rois", "roi")):
        ids = _region_ids(handle, group, region, width)
        if ids is not None:
            return _deduplicated([f"{prefix}{value}" for value in ids])
    return tuple(f"c{index}" for index in range(width))


def _region_ids(handle: h5py.File, group: h5py.Group, name: str, width: int) -> list[str] | None:
    """Return the ids of the table rows a ``DynamicTableRegion`` points at.

    Each column of an ``ElectricalSeries`` is one row of the electrodes table,
    and each column of a ``RoiResponseSeries`` one row of a plane segmentation.
    Naming a column by that row's id is what lets ``ch17`` here mean electrode
    17 in every other tool that reads the file.
    """
    region = group.get(name)
    if not isinstance(region, h5py.Dataset) or region.ndim != 1 or region.shape[0] != width:
        return None
    try:
        table = handle[region.attrs["table"]]
        ids = np.asarray(table["id"][()])
        rows = np.asarray(region[()], dtype=np.int64)
        return [str(int(ids[row])) for row in rows]
    except (KeyError, IndexError, TypeError, ValueError, OSError):
        logger.debug("Could not resolve %s region of %s", name, group.name, exc_info=True)
        return None


def _deduplicated(names: list[str]) -> tuple[str, ...]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in names:
        count = seen.get(name, 0)
        seen[name] = count + 1
        result.append(name if count == 0 else f"{name}_{count}")
    return tuple(result)


def _external_files(group: h5py.Group) -> tuple[str, ...]:
    external = group.get("external_file")
    if not isinstance(external, h5py.Dataset) or external.size == 0:
        return ()
    return tuple(text(value) for value in np.atleast_1d(external[()]))


# ── Names ──────────────────────────────────────────────────────────────────


def _channel_stem(prefix: str, relative: str) -> str:
    """Name an object by where it sits, so two series of one name stay apart.

    ``processing/ophys/DfOverF/RoiResponseSeries`` and
    ``processing/ophys/Fluorescence/RoiResponseSeries`` are both called
    ``RoiResponseSeries``, and real files carry exactly that pair. Their paths
    tell them apart, and ``.`` is what the channel tree nests on. A segment
    repeated by its parent (``dff_timeseries/dff_timeseries``) says nothing the
    first one did not, and is written once.
    """
    segments = [
        _UNSAFE_SEGMENT.sub("_", part).strip("_ ") or "series" for part in relative.split("/")
    ]
    if prefix:
        segments.insert(0, prefix)
    collapsed = [
        part for index, part in enumerate(segments) if index == 0 or part != segments[index - 1]
    ]
    return ".".join(collapsed)


def _unique(stem: str, taken: set[str]) -> str:
    candidate, counter = stem, 1
    while candidate in taken:
        candidate = f"{stem}_{counter}"
        counter += 1
    return candidate


# ── Session clock ──────────────────────────────────────────────────────────


def _reference_epoch(handle: h5py.File) -> tuple[float | None, bool]:
    """Return the Unix time every timestamp counts from, and whether it was naive.

    ``timestamps_reference_time`` when present -- the schema's own zero for
    every timestamp in the file -- and ``session_start_time`` otherwise, which is
    what it defaults to. A time without a zone is read as UTC and reported, never
    silently trusted: internal alignment is unaffected, but the wall clock shown
    may be hours off.
    """
    for key in ("timestamps_reference_time", "session_start_time"):
        value = handle.get(key)
        if not isinstance(value, h5py.Dataset):
            continue
        parsed = parse_iso_time(text(value[()]))
        if parsed is not None:
            return parsed
    return None, False


def parse_iso_time(text: str) -> tuple[float, bool] | None:
    """Parse an ISO 8601 time as written by NWB, returning ``(unix, was_naive)``."""
    cleaned = text.strip()
    if not cleaned:
        return None
    if cleaned.endswith(("Z", "z")):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(cleaned)
    except ValueError:
        logger.warning("Unparseable NWB time %r", text)
        return None
    naive = moment.tzinfo is None
    if naive:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp(), naive


def _units_table(group: h5py.Group, name: str, taken: set[str]) -> UnitsTable | None:
    ends = np.asarray(group["spike_times_index"][()], dtype=np.int64)
    count = int(ends.shape[0])
    ids = group.get("id")
    all_ids = (
        [int(value) for value in ids[:count]]
        if isinstance(ids, h5py.Dataset) and ids.shape[0] >= count
        else list(range(count))
    )
    # A unit that never fired has no samples to import, and a channel with none
    # would be listed in the cache manifest with no arrays behind it.
    fired = np.flatnonzero(np.diff(ends, prepend=0) > 0)
    if len(fired) == 0:
        return None
    return UnitsTable(
        path=group.name,
        name=_unique(name, taken),
        unit_ids=tuple(all_ids[row] for row in fired),
        rows=tuple(int(row) for row in fired),
    )
