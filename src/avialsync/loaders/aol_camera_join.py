"""One video per camera across an AOL experiment's trials, back to back.

The camera PC saves each trial under the controller's own trial name
(``HH-MM-SS``), so a trial's cameras are found by that name: inside the trial
folder itself, or under a camera data folder that mirrors the controller's
``<date>/<experiment>/<HH-MM-SS>`` tree. Each camera's per-trial recordings
are joined the way the controller's own analysis joins trials: back to back,
trial after trial, each segment starting at its trial's start (the
controller's trigger starts every camera) and trimmed to that trial's length
(the camera's stop is not triggered, so its last frames overrun the trial).

The joined video is a stream copy -- no re-encoding -- written once into the
per-user cache with a per-frame timestamp sidecar, never beside a recording
(D-160). Each frame keeps the time its camera recorded for it, moved onto the
joined timeline. Joining needs intra-frame or reorder-free video (MJPEG, as
this rig writes): frames of a stream that reorders packets cannot be retimed
one by one, and that is refused rather than guessed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.cache import CacheManager, cache_dir_for, source_identity
from avialsync.core.errors import SourceOpenError
from avialsync.loaders.video_standard import VideoStandardLoader

logger = logging.getLogger(__name__)

#: Last path part of a joined camera's source id: ``<first segment video>/joined_trials``.
JOINED_NAME = "joined_trials"
_JOIN_VERSION = 1
_VIDEO_NAME = "joined.mkv"
_STAMPS_NAME = "joined_timestamps.csv"
_TIMING_SUFFIX = "-relative times.txt"
_VIDEO_SUFFIXES = (".mp4", ".avi")


@dataclass(frozen=True)
class CameraSegment:
    """One trial's recording of one camera, placed on the joined timeline."""

    video: Path
    timing: Path
    start: float  # seconds on the joined timeline where the trial's trigger falls
    length: float  # the trial's length; later frames are the camera's overrun

    def to_config(self) -> dict[str, Any]:
        return {
            "video": str(self.video),
            "timing": str(self.timing),
            "start": self.start,
            "length": self.length,
        }

    @classmethod
    def from_config(cls, data: dict[str, Any]) -> CameraSegment:
        return cls(
            Path(data["video"]), Path(data["timing"]), float(data["start"]), float(data["length"])
        )


def _cameras_in(folder: Path) -> dict[str, tuple[Path, Path]]:
    """``camera -> (video, timing file)`` for the camera recordings in *folder*."""
    found: dict[str, tuple[Path, Path]] = {}
    try:
        children = sorted(folder.iterdir())
    except OSError:
        return found
    for timing in children:
        if not timing.name.endswith(_TIMING_SUFFIX):
            continue
        camera = timing.name[: -len(_TIMING_SUFFIX)]
        for suffix in _VIDEO_SUFFIXES:  # MP4 first, as the AOL session prefers it
            for candidate in (folder / f"{camera}{suffix}", folder / f"{camera}{suffix.upper()}"):
                if candidate.is_file():
                    found[camera] = (candidate, timing)
                    break
            if camera in found:
                break
    return found


#: Camera data folders to search besides the trial folders themselves. Set by
#: the window from the user's setting before a scan starts: the scanner runs on
#: a worker and has no settings of its own to read.
_CAMERA_ROOTS: tuple[Path, ...] = ()


def configure_camera_roots(roots: Sequence[Path]) -> None:
    """Set the camera data folders later scans search (empty to search none)."""
    global _CAMERA_ROOTS
    _CAMERA_ROOTS = tuple(Path(root) for root in roots if str(root).strip())


def camera_roots() -> tuple[Path, ...]:
    """The configured camera data folders."""
    return _CAMERA_ROOTS


def camera_folder_for(trial: Path, roots: Sequence[Path] = ()) -> Path | None:
    """The folder holding *trial*'s camera recordings, found by the trial's own name.

    The trial folder itself first; then, under each camera data root, the
    controller's ``<date>/<experiment>/<trial>`` tree, ``<date>/<trial>`` and
    ``<trial>`` -- the camera PC names its folders after the controller's trials.
    """
    candidates = [trial]
    tail = trial.parts[-3:]
    for root in roots:
        candidates += [root.joinpath(*tail), root / tail[0] / trial.name, root / trial.name]
    for folder in candidates:
        if folder.is_dir() and _cameras_in(folder):
            return folder
    return None


def camera_segments(
    trials: Sequence[Path], starts: Sequence[float], lengths: Sequence[float], roots: Sequence[Path]
) -> dict[str, list[CameraSegment]]:
    """Each camera's per-trial segments, for the trials whose cameras are found."""
    joined: dict[str, list[CameraSegment]] = {}
    for trial, start, length in zip(trials, starts, lengths, strict=True):
        folder = camera_folder_for(trial, roots)
        if folder is None:
            continue
        for camera, (video, timing) in _cameras_in(folder).items():
            joined.setdefault(camera, []).append(CameraSegment(video, timing, start, length))
    return joined


def joined_source_id(segments: Sequence[CameraSegment]) -> Path:
    """The source id of a joined camera: a name inside its first recording."""
    return segments[0].video / JOINED_NAME


def _timing_rows(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """``(frame counters, seconds since the first frame)`` from a relative-times file."""
    counters: list[float] = []
    seconds: list[float] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        try:
            counters.append(float(fields[0]))
            seconds.append(float(fields[1]) / 1000.0)
        except ValueError:
            continue
    if len(seconds) < 2:
        raise SourceOpenError(f"{path.name} holds no usable frame times.")
    times = np.asarray(seconds, dtype=np.float64)
    return np.asarray(counters, dtype=np.float64), times - times[0]


class _JoinCache(CacheManager):
    """A cache entry keyed on the first recording and on every segment it joins."""

    def __init__(self, segments: Sequence[CameraSegment]) -> None:
        listing = []
        for segment in segments:
            stat = segment.video.stat()
            listing.append(
                {
                    **segment.to_config(),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime_ns,
                    "timing_mtime": segment.timing.stat().st_mtime_ns,
                }
            )
        super().__init__(loader_version=_JOIN_VERSION, cache_config={"segments": listing})
        self._digest = json.dumps(listing, sort_keys=True)
        self._count = len(segments)

    def get_cache_dir(self, source_path: Path) -> Path:
        # A stable digest: the built-in hash() changes between runs.
        digest = hashlib.sha1(self._digest.encode("utf-8")).hexdigest()[:12]
        tag = f"{source_identity(source_path)}#joined{self._count}-{digest}"
        return cache_dir_for(tag, self._root)


def _join(
    segments: Sequence[CameraSegment],
    video_out: Path,
    stamps_out: Path,
    progress: Callable[[float], None],
) -> None:
    """Stream-copy every segment's frames onto the joined timeline."""
    import av

    rows: list[str] = []
    counter_base = 0.0
    with av.open(str(video_out), mode="w", format="matroska") as output:
        stream = None
        for number, segment in enumerate(segments):
            counters, times = _timing_rows(segment.timing)
            keep = int(np.searchsorted(times, segment.length, side="left"))
            with av.open(str(segment.video)) as source:
                source_stream = source.streams.video[0]
                if stream is None:
                    stream = output.add_stream_from_template(source_stream)
                    stream.time_base = Fraction(1, 1000)
                frame = 0
                last_pts: int | None = None
                for packet in source.demux(source_stream):
                    if packet.size == 0 or packet.pts is None:
                        continue
                    if last_pts is not None and packet.pts <= last_pts:
                        raise SourceOpenError(
                            f"{segment.video.name} reorders its frames; only intra-frame "
                            "camera video (such as MJPEG) can be joined."
                        )
                    last_pts = packet.pts
                    if frame >= keep:
                        break
                    instant = segment.start + float(times[frame])
                    packet.stream = stream
                    packet.pts = packet.dts = round(instant * 1000)
                    packet.time_base = stream.time_base
                    output.mux(packet)
                    rows.append(f"{int(counter_base + counters[frame])},{round(instant * 1e9)}")
                    frame += 1
            counter_base += float(counters[min(keep, len(counters)) - 1]) if keep else 0.0
            progress((number + 1) / len(segments))
    stamps_out.write_text("\n".join(rows) + "\n", encoding="utf-8")


class AOLJoinedCameraSource(VideoStandardLoader):
    """One camera's trials as a single video, joined in the per-user cache."""

    def __init__(self) -> None:
        super().__init__()
        self._segments: list[CameraSegment] = []
        self._source_id: Path | None = None
        self._joined: Path | None = None

    @classmethod
    def display_name(cls) -> str:
        return "Video (Joined Trials)"

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Claim only the joined-camera name inside an existing recording."""
        return 1.0 if path.name == JOINED_NAME and path.parent.is_file() else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        segments = [CameraSegment.from_config(dict(item)) for item in config.get("segments", ())]
        if not segments:
            raise SourceOpenError("A joined camera needs its trial segments.")
        self._segments, self._source_id, self._config = segments, path, dict(config)

    def needs_conversion(self) -> bool:
        return True

    def prepare_is_atomic(self) -> bool:
        """The join writes one file and its timestamps before publishing either."""
        return True

    def prepare(self, progress_cb: Callable[[float], None]) -> Path:
        if self._source_id is None:
            raise SourceOpenError("Joined camera source has not been opened.")
        first = self._segments[0].video
        cache = _JoinCache(self._segments)
        entry = cache.get_cache_dir(first)
        if not (cache.is_cache_valid(first) and (entry / _VIDEO_NAME).is_file()):
            staging = cache.get_temp_cache_dir(first)
            try:
                _join(self._segments, staging / _VIDEO_NAME, staging / _STAMPS_NAME, progress_cb)
                cache.commit_cache(first, staging)
            except BaseException:
                # Our own staging directory under the cache root, never the recording.
                shutil.rmtree(staging, ignore_errors=True)
                raise
        joined = entry / _VIDEO_NAME
        config = {
            key: value for key, value in self._config.items() if key not in ("segments", "fps")
        }
        # The sidecar is rebased to its first frame; that frame is the first
        # segment's trigger, which is not the timeline's zero when early trials
        # have no camera recording.
        start = self._segments[0].start
        config.update({"frame_timestamps": str(entry / _STAMPS_NAME), "start_time": start})
        super().open(joined, config)
        mapping = self.exact_time_mapping()
        if mapping is not None and len(mapping[0]) > 1:
            # The container counts in milliseconds and so "declares" 1000 fps;
            # the camera's own recorded frame times say what it really ran at.
            self._fps = 1.0 / float(np.median(np.diff(mapping[0])))
        self._joined = joined
        progress_cb(1.0)
        return joined

    def media_path(self) -> Path:
        if self._joined is None:
            raise SourceOpenError("Joined camera has not been prepared.")
        return self._joined
