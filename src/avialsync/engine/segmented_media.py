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
each file's times shifted to follow the previous file's, so the table is
strictly increasing and every frame keeps its own spacing. A frame is decoded by
the file's own :class:`~avialsync.engine.pyav_reader.PyAVReader`, so which
frame is shown is still decided by one authority (D-075). At most
:data:`OPEN_FILES` files are open at a time.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.errors import SourceOpenError
from avialsync.engine.pyav_reader import DEFAULT_CACHE_FRAMES, PyAVReader

__all__ = [
    "MANIFEST_SUFFIX",
    "Segment",
    "SegmentedReader",
    "is_segmented",
    "read_manifest",
    "write_manifest",
]

#: The suffix of a manifest; :class:`PyAVReader` opens such a path as one video.
MANIFEST_SUFFIX = ".segments.json"

#: Files kept open at once: the one being shown and the one a scrub just left.
OPEN_FILES = 2


@dataclass(frozen=True)
class Segment:
    """Frames ``[first, stop)`` of *path*, by its reader's frame index."""

    path: str
    first: int
    stop: int


def is_segmented(path: Path | str) -> bool:
    return str(path).endswith(MANIFEST_SUFFIX)


def write_manifest(path: Path, segments: list[Segment]) -> None:
    payload = {"segments": [{"path": s.path, "first": s.first, "stop": s.stop} for s in segments]}
    path.write_text(json.dumps(payload), encoding="utf-8")


def read_manifest(path: Path | str) -> list[Segment]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        segments = [
            Segment(str(item["path"]), int(item["first"]), int(item["stop"]))
            for item in payload["segments"]
        ]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SourceOpenError(f"Cannot read joined video manifest {path}: {error}") from error
    if not segments or any(s.stop <= s.first or s.first < 0 for s in segments):
        raise SourceOpenError(f"Joined video manifest {path} names no frames.")
    return segments


class SegmentedReader(PyAVReader):
    """A manifest's files read as one video, through each file's own reader."""

    def __init__(self, path: Path | str, max_cached_frames: int = DEFAULT_CACHE_FRAMES) -> None:
        self.path = Path(path)
        self._max_cached_frames = max(1, max_cached_frames)
        self._segments = read_manifest(self.path)
        self._open: OrderedDict[int, PyAVReader] = OrderedDict()
        times: list[np.ndarray] = []
        starts = [0]
        #: Per segment: the shift from its own times to the joined timeline.
        self._shifts: list[float] = []
        offset = 0.0
        time_base: Any = None
        for number, segment in enumerate(self._segments):
            part = self._part(number)
            local = np.asarray(part.frame_times[segment.first : segment.stop], dtype=np.float64)
            if len(local) != segment.stop - segment.first:
                raise SourceOpenError(f"{segment.path} has fewer frames than its manifest names.")
            if time_base is None:
                time_base = part.stream.time_base
            elif part.stream.time_base != time_base:
                raise SourceOpenError("The joined files do not share one time base.")
            shift = offset - float(local[0])
            times.append(local + shift)
            self._shifts.append(shift)
            step = float(np.median(np.diff(local))) if len(local) > 1 else float(time_base)
            offset = float(local[-1]) + shift + step
            starts.append(starts[-1] + len(local))
        self._frame_times = np.concatenate(times)
        self._starts = np.asarray(starts, dtype=np.int64)
        self._time_base = time_base

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
        segment = self._segments[number]
        return self._part(number).frame_at_index(segment.first + target - int(self._starts[number]))

    # -- files -----------------------------------------------------------

    def _part(self, number: int) -> PyAVReader:
        reader = self._open.get(number)
        if reader is not None:
            self._open.move_to_end(number)
            return reader
        reader = PyAVReader(self._segments[number].path, self._max_cached_frames)
        self._open[number] = reader
        while len(self._open) > OPEN_FILES:
            _number, evicted = self._open.popitem(last=False)
            evicted.close()
        return reader

    def close(self) -> None:
        while self._open:
            _number, reader = self._open.popitem(last=False)
            reader.close()
