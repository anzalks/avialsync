"""Headless exact-frame video reading on PyAV.

This is the decoder the application scrubs with.  It owns four things: the
presentation-timestamp table, the resolution of a source time to a frame index,
seek-and-decode, and a small window of recently decoded frames.

No PySide6 import — a reader is testable, and benchmarkable, without Qt.  It is
also safe to drive from a worker thread: PyAV releases the GIL during decode, so
several readers genuinely decode in parallel (AGENTS.md rule 3).  One reader is
*not* re-entrant, because it carries decoder position; give each pane its own.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from pathlib import Path

import av
import numpy as np

from avialsync.core.errors import SourceOpenError
from avialsync.core.video_timing import frame_index_at

# Imported at module scope deliberately. The rule forbidding a top-level decoder
# import (D-013) existed because a missing libmpv crashed with a ctypes traceback
# at launch; PyAV carries its own FFmpeg inside its wheel, so that case cannot
# occur — pip either installed the decoder or the install itself failed.
# Deferring it would only move its 94 ms first-import onto whichever thread
# reached it first: a decode thread on first open, or the diagnostics thread,
# with the two able to contend on the import lock. Paying it once at startup is
# both cheaper to reason about and deterministic.

#: Frames kept per reader.  Held in the decoder's own pixel format rather than
#: RGB — 2.3 MB per 1440x1080 frame instead of 4.6 MB — because converting on
#: demand costs 0.28 ms and re-decoding costs milliseconds.  Twenty-four frames
#: covers a slider drag's worth of back-and-forth on three cameras for ~166 MB,
#: inside the 2.5 GB idle budget.
DEFAULT_CACHE_FRAMES = 24


class PyAVReader:
    """Decode the exact frame presented at a given source time.

    The reader never guesses a frame from a nominal rate.  Every lookup goes
    through the demuxed timestamp table, so variable-rate and dropped-exposure
    footage resolve as correctly as clean CFR material.

    Attributes:
        path: The media file being read.
    """

    def __init__(self, path: Path | str, max_cached_frames: int = DEFAULT_CACHE_FRAMES) -> None:
        """Open ``path`` and build its presentation-timestamp table.

        Args:
            path: Media file to read.
            max_cached_frames: Size of the recently-decoded frame window.

        Raises:
            SourceOpenError: The file cannot be opened or carries no video
                stream with usable timestamps.
        """
        self.path = Path(path)
        self._max_cached_frames = max(1, max_cached_frames)
        self._cache: OrderedDict[int, av.VideoFrame] = OrderedDict()
        self._decoded_index: int | None = None
        self._frames: Iterator[av.VideoFrame] | None = None

        try:
            self._container = av.open(str(self.path))
        except (av.FFmpegError, OSError) as error:
            raise SourceOpenError(f"Cannot open video: {self.path} ({error})") from error
        try:
            self._stream = self._container.streams.video[0]
        except IndexError:
            self._container.close()
            raise SourceOpenError(f"No video stream in: {self.path}") from None

        # Decode with every core the machine has. Without this a single reader
        # runs one thread and the 3-cam fanout is bound by the slowest pane.
        self._stream.thread_type = "AUTO"

        # Without a time base a packet timestamp is an uninterpretable integer.
        # Refusing here is the honest outcome: the alternative is to invent a
        # rate and silently misdate every frame in the file.
        time_base = self._stream.time_base
        if time_base is None:
            self._container.close()
            raise SourceOpenError(
                f"Video stream declares no time base, so its timestamps cannot be read: {self.path}"
            )

        self._pts_ticks, self._keyframe_indices = self._build_pts_table()
        if not len(self._pts_ticks):
            self._container.close()
            raise SourceOpenError(f"Video stream carries no timestamps: {self.path}")
        self._frame_times: np.ndarray = self._pts_ticks * float(time_base)

    # -- table -----------------------------------------------------------

    def _build_pts_table(self) -> tuple[np.ndarray, np.ndarray]:
        """Demux one pass to collect presentation timestamps and keyframes.

        Demux only — no decode — so this reads the file's packet headers rather
        than its pixels.

        Trap: long-GOP H.264 arrives in *decode* order, so the raw packet
        sequence is not sorted by pts.  Sorting into display order here is what
        makes every later ``searchsorted`` mean what it says; skipping it
        scrambles every lookup quietly rather than loudly.
        """
        ticks: list[int] = []
        keyframe_ticks: list[int] = []
        for packet in self._container.demux(self._stream):
            if packet.pts is None:
                continue
            ticks.append(packet.pts)
            if packet.is_keyframe:
                keyframe_ticks.append(packet.pts)
        self._rewind()

        pts = np.sort(np.asarray(ticks, dtype=np.int64))
        keyframes = np.searchsorted(pts, np.sort(np.asarray(keyframe_ticks, dtype=np.int64)))
        if not len(keyframes) or keyframes[0] != 0:
            # A stream whose first frame is not flagged as a keyframe would
            # otherwise leave early indices with nowhere to seek back to.
            keyframes = np.concatenate(([0], keyframes))
        return pts, np.unique(keyframes)

    @property
    def frame_times(self) -> np.ndarray:
        """Presentation timestamps in source seconds, display order."""
        return self._frame_times

    @property
    def frame_count(self) -> int:
        """Number of frames the container actually carries timestamps for."""
        return int(len(self._pts_ticks))

    @property
    def stream(self) -> av.VideoStream:
        """The decoded video stream, for callers building format metadata."""
        return self._stream

    def index_at_time(self, source_time: float) -> int:
        """Return the frame index presented at ``source_time``.

        The one resolution step in the application: whatever calls this both
        selects and names the frame, so a readout can never disagree with the
        picture beside it (D-075).
        """
        return frame_index_at(self._frame_times, source_time)

    def time_at_index(self, index: int) -> float:
        """Return the real presentation timestamp of ``index``."""
        clamped = max(0, min(int(index), self.frame_count - 1))
        return float(self._frame_times[clamped])

    # -- decoding --------------------------------------------------------

    def frame_at_time(self, source_time: float) -> av.VideoFrame:
        """Return the frame whose presentation interval contains ``source_time``."""
        return self.frame_at_index(self.index_at_time(source_time))

    def frame_at_index(self, index: int) -> av.VideoFrame:
        """Return frame ``index``, decoding only what is not already cached.

        Raises:
            SourceOpenError: The stream ended before the requested frame, which
                means the timestamp table and the packet data disagree.
        """
        target = max(0, min(int(index), self.frame_count - 1))
        cached = self._cache.get(target)
        if cached is not None:
            self._cache.move_to_end(target)
            return cached

        if not self._can_reach_by_decoding(target):
            self._seek_to_keyframe_for(target)
        return self._decode_until(target)

    def _can_reach_by_decoding(self, target: int) -> bool:
        """Return True if walking forward decodes no more frames than re-seeking.

        Both sides are counted in *frames*, never in seconds.  Walking costs the
        frames between here and there; re-seeking costs the frames from the
        covering keyframe to there, plus a decoder flush.  Ties therefore go to
        the walk, which is what happens when the decoder sits one frame short of
        the next keyframe: identical decode work, one pointless seek avoided.

        The seconds-based version of this rule is the trap.  A fixed 2-second
        window at 230 fps walks ~460 frames forward where a re-seek costs ~125,
        and that alone took the 3-cam jump case from 106 ms to 293 ms — over
        budget.  Nothing here may be expressed in seconds.
        """
        decoded = self._decoded_index
        if decoded is None or decoded >= target:
            return False
        walk_frames = target - decoded
        reseek_frames = target - self._keyframe_index_for(target) + 1
        return walk_frames <= reseek_frames

    def _keyframe_index_for(self, target: int) -> int:
        """Return the last keyframe at or before ``target``."""
        position = int(np.searchsorted(self._keyframe_indices, target, side="right")) - 1
        return int(self._keyframe_indices[max(0, position)])

    def _seek_to_keyframe_for(self, target: int) -> None:
        """Seek so that decoding forward reaches ``target``."""
        keyframe = self._keyframe_index_for(target)
        self._container.seek(
            int(self._pts_ticks[keyframe]),
            stream=self._stream,
            backward=True,
            any_frame=False,
        )
        self._frames = self._container.decode(self._stream)
        self._decoded_index = None

    def _rewind(self) -> None:
        """Return the container to the start with a clean decoder."""
        self._container.seek(0, stream=self._stream, backward=True, any_frame=False)
        self._frames = None
        self._decoded_index = None

    def _decode_until(self, target: int) -> av.VideoFrame:
        """Decode forward until ``target`` has been produced, caching the walk.

        Frames passed on the way are cached too — they cost nothing extra now,
        and a scrub that just walked over them is very likely to be asked for
        them again.
        """
        if self._frames is None:
            self._frames = self._container.decode(self._stream)

        for frame in self._frames:
            if frame.pts is None:
                continue
            index = int(np.searchsorted(self._pts_ticks, frame.pts))
            if index >= self.frame_count or self._pts_ticks[index] != frame.pts:
                # A timestamp the table does not know about. The table is the
                # authority for what frame numbers exist; anything else would
                # let a decoder artefact rename a frame.
                continue
            self._decoded_index = index
            self._store(index, frame)
            if index >= target:
                break

        found = self._cache.get(target)
        if found is None:
            raise SourceOpenError(
                f"Frame {target} of {self.path.name} is listed in the timestamp table "
                "but the stream ended before decoding it"
            )
        self._cache.move_to_end(target)
        return found

    def _store(self, index: int, frame: av.VideoFrame) -> None:
        self._cache[index] = frame
        self._cache.move_to_end(index)
        while len(self._cache) > self._max_cached_frames:
            self._cache.popitem(last=False)

    # -- lifecycle -------------------------------------------------------

    def close(self) -> None:
        """Release the container and the cached frames."""
        self._cache.clear()
        self._frames = None
        self._container.close()

    def __enter__(self) -> PyAVReader:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def to_rgb_array(frame: av.VideoFrame) -> np.ndarray:
    """Convert a decoded frame to a contiguous ``(H, W, 3)`` uint8 RGB array.

    Costs ~0.5 ms at 1440x1080 — negligible beside the seek budget, and the
    reason frames are cached in their native pixel format rather than as RGB.
    """
    return frame.to_ndarray(format="rgb24")
