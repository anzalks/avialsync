"""Several video files read as one, without copying them.

An AOL camera saves one file per trial; the application shows one video per
camera across the experiment. Joining them used to mean copying every trial's
footage into the cache (13 GB for one 17-trial, three-camera experiment), which
took minutes and doubled the disk used. FFmpeg's concat reader cannot seek
those files reliably (D-216), so the files are read here instead, each with
its own ordinary container and seek.

A **manifest** (``*.segments.json`` in the cache) names each file and the run
of its frames that belongs to the joined video. :class:`SegmentedReader` reads
it as one stream: its frame table is the kept frames of every file in order,
each file's times shifted to the ``start`` the manifest gives it -- so the time
between two files stays a gap, where no frame is shown (D-217) -- or, for a
file without one, to follow the previous file's. The table is strictly
increasing and every frame keeps its own spacing. A frame is decoded by
the file's own :class:`~avialsync.engine.pyav_reader.PyAVReader`, so which
frame is shown is still decided by one authority (D-075).

**As fast to open and seek as one file.** The manifest stores each file's kept
frame timestamps (``*.ticks.npy``) and the shared time base, so opening the
joined video opens no file. A file is opened the first time one of its frames
is wanted (about 1.3 ms, given its table) and stays open; decoded frames are
capped across all files at the reader's own budget.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.errors import LoaderContractError, SourceOpenError
from avialsync.engine.pyav_reader import DEFAULT_CACHE_FRAMES, PyAVReader

__all__ = [
    "MANIFEST_SUFFIX",
    "Segment",
    "SegmentedReader",
    "file_table",
    "is_segmented",
    "read_manifest",
    "write_manifest",
    "write_tables",
]

#: The suffix of a manifest; :class:`PyAVReader` opens such a path as one video.
MANIFEST_SUFFIX = ".segments.json"


@dataclass(frozen=True)
class Segment:
    """Frames ``[first, stop)`` of *path*, by its reader's frame index.

    ``start`` is where the first kept frame sits on the joined video's
    timeline, in seconds; ``None`` puts it one frame after the previous file.
    """

    path: str
    first: int
    stop: int
    start: float | None = None


def is_segmented(path: Path | str) -> bool:
    return str(path).endswith(MANIFEST_SUFFIX)


def _ticks_path(path: Path) -> Path:
    return path.with_name(path.name[: -len(MANIFEST_SUFFIX)] + ".ticks.npy")


def _tables_path(path: Path) -> Path:
    return path.with_name(path.name[: -len(MANIFEST_SUFFIX)] + ".tables.npz")


def file_table(path: Path | str) -> tuple[np.ndarray, np.ndarray, float]:
    """A file's own ``(pts ticks, keyframe indices, seconds per tick)``, read once."""
    with PyAVReader(path) as reader:
        base = reader.stream.time_base
        if base is None:  # PyAVReader refuses these; said here for the type
            raise SourceOpenError(f"{Path(path).name} has no time base.")
        return (
            np.asarray(reader._pts_ticks, dtype=np.int64),
            np.asarray(reader._keyframe_indices, dtype=np.int64),
            float(base),
        )


def write_tables(path: Path, tables: list[tuple[np.ndarray, np.ndarray, float]]) -> None:
    """Store each file's own table beside *path*'s manifest, so opening reads no file.

    For inter-frame video (H.264): each file is then read through its own
    keyframes, in its own frame numbering.
    """
    arrays: dict[str, np.ndarray] = {}
    for number, (ticks, keys, base) in enumerate(tables):
        arrays[f"ticks{number}"] = ticks
        arrays[f"keys{number}"] = keys
        arrays[f"base{number}"] = np.asarray([base], dtype=np.float64)
    with _tables_path(path).open("wb") as handle:
        np.savez(handle, **arrays)  # type: ignore[arg-type]  # numpy stubs: **dict unpacking


def _stored_tables(
    path: Path, segments: list[Segment]
) -> list[tuple[np.ndarray, np.ndarray, float]] | None:
    try:
        with np.load(_tables_path(path), allow_pickle=False) as stored:
            tables = [
                (
                    stored[f"ticks{n}"].astype(np.int64, copy=False),
                    stored[f"keys{n}"].astype(np.int64, copy=False),
                    float(stored[f"base{n}"][0]),
                )
                for n in range(len(segments))
            ]
    except (OSError, ValueError, KeyError):
        return None
    if any(len(ticks) < s.stop for (ticks, _k, _b), s in zip(tables, segments, strict=True)):
        return None
    return tables


def write_manifest(
    path: Path,
    segments: list[Segment],
    ticks: list[np.ndarray] | None = None,
    time_base: Fraction | None = None,
) -> None:
    """Write *segments*, and each one's kept frame ticks when known, so opening reads no file."""
    payload: dict[str, Any] = {
        "segments": [
            {"path": s.path, "first": s.first, "stop": s.stop}
            | ({} if s.start is None else {"start": s.start})
            for s in segments
        ]
    }
    if ticks is not None and time_base is not None:
        if [len(t) for t in ticks] != [s.stop - s.first for s in segments]:
            raise LoaderContractError("each segment needs one tick per kept frame")
        np.save(_ticks_path(path), np.concatenate(ticks).astype(np.int64))
        payload["time_base"] = [time_base.numerator, time_base.denominator]
    path.write_text(json.dumps(payload), encoding="utf-8")


def read_manifest(path: Path | str) -> list[Segment]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        segments = [
            Segment(
                str(item["path"]),
                int(item["first"]),
                int(item["stop"]),
                None if item.get("start") is None else float(item["start"]),
            )
            for item in payload["segments"]
        ]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SourceOpenError(f"Cannot read joined video manifest {path}: {error}") from error
    if not segments or any(s.stop <= s.first or s.first < 0 for s in segments):
        raise SourceOpenError(f"Joined video manifest {path} names no frames.")
    return segments


def _stored_ticks(path: Path, segments: list[Segment]) -> tuple[np.ndarray, Fraction] | None:
    """The kept frames' ticks and time base the manifest stored, if it stored them."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        numerator, denominator = (int(n) for n in payload["time_base"])
        ticks = np.load(_ticks_path(path), allow_pickle=False)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if ticks.ndim != 1 or len(ticks) != sum(s.stop - s.first for s in segments):
        return None
    return ticks.astype(np.int64, copy=False), Fraction(numerator, denominator)


class SegmentedReader(PyAVReader):
    """A manifest's files read as one video, through each file's own reader."""

    def __init__(
        self,
        path: Path | str,
        max_cached_frames: int = DEFAULT_CACHE_FRAMES,
        *,
        table: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> None:
        del table  # a joined video's table is its manifest's
        self.path = Path(path)
        self._max_cached_frames = max(1, max_cached_frames)
        self._segments = read_manifest(self.path)
        self._open: OrderedDict[int, PyAVReader] = OrderedDict()
        counts = [s.stop - s.first for s in self._segments]
        self._starts = np.concatenate(([0], np.cumsum(counts))).astype(np.int64)
        #: Each file's own ``(pts ticks, keyframe indices)``, when the manifest
        #: stored none: then frames are addressed in the file's own numbering,
        #: and inter-frame video (H.264) seeks through its real keyframes.
        self._tables: list[tuple[np.ndarray, np.ndarray]] | None = None
        stored = _stored_ticks(self.path, self._segments)
        if stored is not None:
            ticks, time_base = stored
            self._ticks = [
                ticks[int(self._starts[n]) : int(self._starts[n + 1])]
                for n in range(len(self._segments))
            ]
            bases = [float(time_base)] * len(self._segments)
        else:  # each file's own table: stored beside the manifest, or read once here
            tables = _stored_tables(self.path, self._segments) or self._read_tables()
            self._tables = [(ticks, keys) for ticks, keys, _base in tables]
            self._ticks = [
                ticks[s.first : s.stop]
                for (ticks, _k, _b), s in zip(tables, self._segments, strict=True)
            ]
            bases = [base for _t, _k, base in tables]
        times: list[np.ndarray] = []
        #: Per segment: the shift from its own times to the joined timeline.
        self._shifts: list[float] = []
        offset = 0.0
        for segment, local_ticks, base in zip(self._segments, self._ticks, bases, strict=True):
            local = local_ticks * base
            # A file placed before the previous one ends would reorder frames;
            # it follows on instead, as a file with no place of its own does.
            begin = offset if segment.start is None else max(segment.start, offset)
            shift = begin - float(local[0])
            times.append(local + shift)
            self._shifts.append(shift)
            step = float(np.median(np.diff(local))) if len(local) > 1 else base
            offset = float(local[-1]) + shift + step
        self._frame_times = np.concatenate(times)

    def _read_tables(self) -> list[tuple[np.ndarray, np.ndarray, float]]:
        """Each file's own table, read from the file. Files may differ in time base."""
        tables = [file_table(segment.path) for segment in self._segments]
        for (ticks, _keys, _base), segment in zip(tables, self._segments, strict=True):
            if len(ticks) < segment.stop:
                raise SourceOpenError(f"{segment.path} has fewer frames than its manifest names.")
        return tables

    # -- the joined table ------------------------------------------------

    @property
    def frame_count(self) -> int:
        return int(len(self._frame_times))

    @property
    def stream(self) -> Any:
        """The first file's stream: every file shares its codec and time base."""
        return self._part(0).stream

    def spans(self) -> Iterator[tuple[str, float, float, float]]:
        """Each file's ``(path, first kept time, last kept time, shift to the joined timeline)``."""
        for number, segment in enumerate(self._segments):
            first = int(self._starts[number])
            last = int(self._starts[number + 1]) - 1
            shift = self._shifts[number]
            yield (
                segment.path,
                float(self._frame_times[first]) - shift,
                float(self._frame_times[last]) - shift,
                shift,
            )

    def frame_at_index(self, index: int) -> Any:
        target = max(0, min(int(index), self.frame_count - 1))
        number = int(np.searchsorted(self._starts, target, side="right")) - 1
        local = target - int(self._starts[number])
        if self._tables is not None:  # the file's own numbering
            local += self._segments[number].first
        frame = self._part(number).frame_at_index(local)
        self._trim_caches()
        return frame

    # -- files -----------------------------------------------------------

    def _part(self, number: int) -> PyAVReader:
        """File *number*'s reader over its kept frames, opened on first use and kept."""
        reader = self._open.get(number)
        if reader is None:
            if self._tables is not None:
                table = self._tables[number]
            else:
                # Stored ticks are only written for MJPEG camera video, which
                # is intra-frame: every kept frame is a keyframe.
                ticks = self._ticks[number]
                table = (ticks, np.arange(len(ticks), dtype=np.int64))
            reader = PyAVReader(self._segments[number].path, self._max_cached_frames, table=table)
            self._open[number] = reader
        self._open.move_to_end(number)
        return reader

    def _trim_caches(self) -> None:
        """Hold no more decoded frames across all files than one reader would."""
        held = sum(len(reader._cache) for reader in self._open.values())
        for reader in list(self._open.values())[:-1]:  # least recently used first
            if held <= self._max_cached_frames:
                break
            held -= len(reader._cache)
            reader._cache.clear()

    def close(self) -> None:
        while self._open:
            _number, reader = self._open.popitem(last=False)
            reader.close()
