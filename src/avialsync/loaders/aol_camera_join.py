"""One video per camera across an AOL experiment's trials, back to back.

The camera PC saves each trial in a folder of its own, named by its own clock
when it armed -- never by the controller's trial name, and seconds apart from
it -- so a trial's cameras are found by *when* they recorded
(:func:`~avialsync.loaders.aol_trial_matching.match_cameras`): saved inside the
trial folder, named after it, started on its trigger by the camera clock, or
the only recording left between two that did. Recordings are looked for in the
trial folders, beside them, under the configured camera data folders, and in a
sibling tree that mirrors the controller's ``<date>/<experiment>`` (such as
``videos/<date>/<experiment>`` next to ``<date>``).

Each camera's per-trial recordings are joined the way the controller's own
analysis joins trials: back to back, trial after trial, each segment starting
at its trial's start (the controller's trigger starts every camera) and trimmed
to that trial's length (the camera's stop is not triggered, so its last frames
overrun the trial). A recording that did not start on its trial's trigger is
placed where its own clock puts it, and keeps only the frames inside the trial.

The joined video is not copied. The cache holds an FFmpeg concat list naming
each trial's own file and the frames it contributes, with a per-frame timestamp
sidecar, and FFmpeg plays the list as one stream (D-216): any video is the same
whether it is one file or several back to back, so it costs no second copy of
the footage. The list is checked against the frames it should yield before it
is used; a recording the list cannot reproduce exactly is joined the old way,
by a stream copy -- no re-encoding -- into the cache. Neither is ever written
beside a recording.
Each frame keeps the time its camera recorded for it, moved onto the
joined timeline. Joining needs intra-frame or reorder-free video (MJPEG, as
this rig writes): frames of a stream that reorders packets cannot be retimed
one by one, and that is refused rather than guessed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.cache import CacheManager, cache_dir_for, source_identity
from avialsync.core.errors import SourceOpenError
from avialsync.loaders.aol_trial_matching import CameraPairing, CameraRecording, first_frame_stamp
from avialsync.loaders.video_standard import VideoStandardLoader

logger = logging.getLogger(__name__)

#: Last path part of a joined camera's source id: ``<first segment video>/joined_trials``.
JOINED_NAME = "joined_trials"
_JOIN_VERSION = 3
_VIDEO_NAME = "joined.mkv"
_LIST_NAME = "joined.ffconcat"
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
    offset: float = 0.0  # the camera's first frame after the trigger; 0 when on it

    def to_config(self) -> dict[str, Any]:
        return {
            "video": str(self.video),
            "timing": str(self.timing),
            "start": self.start,
            "length": self.length,
            "offset": self.offset,
        }

    @classmethod
    def from_config(cls, data: dict[str, Any]) -> CameraSegment:
        return cls(
            Path(data["video"]),
            Path(data["timing"]),
            float(data["start"]),
            float(data["length"]),
            float(data.get("offset", 0.0)),
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


def camera_files(folder: Path) -> dict[str, tuple[Path, Path]]:
    """``camera -> (video, timing file)`` for one recording folder."""
    return _cameras_in(folder)


def is_camera_folder(folder: Path) -> bool:
    """Whether *folder* holds one recording's camera videos and their frame times."""
    return folder.is_dir() and bool(_cameras_in(folder))


def camera_folders_in(folder: Path) -> list[Path]:
    """The camera recordings directly inside *folder* (an experiment's, on the camera PC)."""
    try:
        return sorted(child for child in folder.iterdir() if is_camera_folder(child))
    except OSError:
        return []


#: Camera data folders to search besides the trial folders themselves, and how
#: far apart a camera and a trial may start and still be matched. Set by the
#: window from the user's settings before a scan starts: the scanner runs on a
#: worker and has no settings of its own to read.
_CAMERA_ROOTS: tuple[Path, ...] = ()
_TRIAL_ROOTS: tuple[Path, ...] = ()
_MATCH_TOLERANCE_S = 10.0


def configure_camera_roots(
    roots: Sequence[Path],
    tolerance_s: float | None = None,
    trial_roots: Sequence[Path] | None = None,
) -> None:
    """Set the camera (and microscope) data folders later scans search (empty: none)."""
    global _CAMERA_ROOTS, _MATCH_TOLERANCE_S, _TRIAL_ROOTS
    _CAMERA_ROOTS = tuple(Path(root) for root in roots if str(root).strip())
    if tolerance_s is not None:
        _MATCH_TOLERANCE_S = float(tolerance_s)
    if trial_roots is not None:
        _TRIAL_ROOTS = tuple(Path(root) for root in trial_roots if str(root).strip())


def trial_roots() -> tuple[Path, ...]:
    """The configured microscope saved-data folders."""
    return _TRIAL_ROOTS


def camera_roots() -> tuple[Path, ...]:
    """The configured camera data folders."""
    return _CAMERA_ROOTS


def match_tolerance() -> float:
    """The configured camera-to-trial start tolerance, in seconds."""
    return _MATCH_TOLERANCE_S


def _mirrors(experiment: Path, roots: Sequence[Path]) -> list[Path]:
    """Folders that may hold *experiment*'s camera recordings, on the camera PC's tree.

    Under each camera data root: ``<date>/<experiment>``, ``<date>`` and the
    root. Beside the controller's own tree: any sibling of the date folder
    that mirrors ``<date>/<experiment>`` (a ``videos`` folder next to it).
    """
    date = experiment.parent
    places = [experiment]
    for root in roots:
        places += [root / date.name / experiment.name, root / date.name, root]
    try:
        siblings = sorted(child for child in date.parent.iterdir() if child.is_dir())
    except OSError:
        siblings = []
    places += [sibling / date.name / experiment.name for sibling in siblings if sibling != date]
    return places


def recording(folder: Path) -> CameraRecording | None:
    """*folder*'s cameras as one recording, started at their median first-frame stamp."""
    cameras = _cameras_in(folder)
    if not cameras:
        return None
    stamps = sorted(
        stamp for _video, timing in cameras.values() if (stamp := first_frame_stamp(timing))
    )
    return CameraRecording(folder, stamps[len(stamps) // 2] if stamps else 0.0)


def find_recordings(trial_folders: Sequence[Path], roots: Sequence[Path]) -> list[CameraRecording]:
    """Every camera recording that could belong to these trials, each folder once."""
    folders: dict[Path, None] = {}
    for trial in trial_folders:
        if is_camera_folder(trial):
            folders[trial] = None
    for experiment in dict.fromkeys(trial.parent for trial in trial_folders):
        for place in _mirrors(experiment, roots):
            if place.is_dir():
                folders.update(dict.fromkeys(camera_folders_in(place)))
    return [found for folder in folders if (found := recording(folder)) is not None]


def recording_length(folder: Path) -> float:
    """How long a recording ran: its longest camera's last frame plus one frame period."""
    lengths = [0.0]
    for _video, timing in _cameras_in(folder).values():
        try:
            times = _timing_rows(timing)[1]
        except (OSError, SourceOpenError):
            continue
        lengths.append(float(times[-1] + np.median(np.diff(times))))
    return max(lengths)


def _recorded_span(timing: Path) -> float | None:
    """Seconds from a recording's first frame to its last."""
    try:
        return float(_timing_rows(timing)[1][-1])
    except (OSError, SourceOpenError):
        return None


def camera_segments(
    pairs: Sequence[CameraPairing],
    starts: Mapping[Path, float],
    lengths: Mapping[Path, float],
) -> tuple[dict[str, list[CameraSegment]], list[str]]:
    """Each camera's per-trial segments, and the recordings that fall outside their trial.

    A recording placed by its own clock may have stopped before its trial
    began, or started after it ended; it then contributes no frames, and is
    named rather than joined as an empty segment.
    """
    joined: dict[str, list[CameraSegment]] = {}
    notes: list[str] = []
    for pair in pairs:
        folder, trial = pair.camera.folder, pair.trial.folder
        cameras = _cameras_in(folder)
        if not cameras or trial not in starts:
            continue
        length = lengths[trial]
        outside = pair.offset >= length
        if pair.offset < 0.0:
            span = _recorded_span(next(iter(cameras.values()))[1])
            outside = span is not None and pair.offset + span < 0.0
        if outside:
            notes.append(
                f"{folder.name}'s cameras recorded outside trial {trial.name} "
                f"({pair.offset:+.1f} s from its trigger); none of their frames are shown."
            )
            continue
        for camera, (video, timing) in cameras.items():
            joined.setdefault(camera, []).append(
                CameraSegment(video, timing, starts[trial], length, pair.offset)
            )
    return joined, notes


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
    # Packet times are written in milliseconds.
    time_base = Fraction(1, 1000)
    with av.open(str(video_out), mode="w", format="matroska") as output:
        stream = None
        for number, segment in enumerate(segments):
            counters, times = _timing_rows(segment.timing)
            # Where each frame falls in its trial; only those inside it are kept.
            placed = segment.offset + times
            first = int(np.searchsorted(placed, 0.0, side="left"))
            keep = int(np.searchsorted(placed, segment.length, side="left"))
            if first >= keep:
                progress((number + 1) / len(segments))
                continue
            with av.open(str(segment.video)) as source:
                source_stream = source.streams.video[0]
                if stream is None:
                    stream = output.add_stream_from_template(source_stream)
                    stream.time_base = time_base
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
                    if frame >= first:
                        instant = segment.start + float(placed[frame])
                        packet.stream = stream
                        packet.pts = packet.dts = round(instant * 1000)
                        packet.time_base = time_base
                        output.mux(packet)
                        rows.append(f"{int(counter_base + counters[frame])},{round(instant * 1e9)}")
                    frame += 1
            counter_base += float(counters[min(keep, len(counters)) - 1])
            progress((number + 1) / len(segments))
    stamps_out.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _segment_list(
    segments: Sequence[CameraSegment],
    list_out: Path,
    stamps_out: Path,
    progress: Callable[[float], None],
) -> bool:
    """Write a concat list playing each segment's kept frames in place; ``False`` if it can't.

    The frames kept and the sidecar rows are exactly :func:`_join`'s. A
    segment's first kept frame is named by its own timestamp, rounded up to the
    microsecond FFmpeg reads: the concat reader starts at the last keyframe at
    or before that point, which for intra-frame camera video is that frame. The
    out point sits halfway to the first frame left out. The list is then read
    back and must yield exactly the expected packets, or it is not used.
    """
    import av

    lines = ["ffconcat version 1.0"]
    rows: list[str] = []
    expected: list[int] = []
    counter_base = 0.0
    for number, segment in enumerate(segments):
        counters, times = _timing_rows(segment.timing)
        placed = segment.offset + times
        first = int(np.searchsorted(placed, 0.0, side="left"))
        keep = int(np.searchsorted(placed, segment.length, side="left"))
        if first >= keep:
            progress((number + 1) / len(segments))
            continue
        packets = _packets(segment.video)
        if packets is None:
            return False
        stamps, sizes = packets
        keep = min(keep, len(stamps))
        if first >= keep:
            progress((number + 1) / len(segments))
            continue
        path = str(segment.video.resolve()).replace("'", "'\\''")
        lines.append(f"file '{path}'")
        if first > 0:
            lines.append(f"inpoint {math.ceil(stamps[first] * 1e6) / 1e6!r}")
        if keep < len(stamps):
            lines.append(f"outpoint {(stamps[keep - 1] + stamps[keep]) / 2!r}")
        for frame in range(first, keep):
            instant = segment.start + float(placed[frame])
            rows.append(f"{int(counter_base + counters[frame])},{round(instant * 1e9)}")
        expected.extend(sizes[first:keep])
        counter_base += float(counters[min(keep, len(counters)) - 1])
        progress((number + 1) / len(segments))
    if not expected:
        return False
    list_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        from avialsync.engine.media_input import open_input

        with open_input(list_out) as container:
            stream = container.streams.video[0]
            played = [p.size for p in container.demux(stream) if p.size and p.pts is not None]
    except (av.FFmpegError, OSError):
        return False
    if played != expected:
        logger.info("Concat list for %s did not reproduce its frames; copying.", segments[0].video)
        return False
    stamps_out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return True


def _packets(video: Path) -> tuple[list[float], list[int]] | None:
    """Each frame's presentation time in seconds and packet size, or ``None`` if reordered."""
    import av

    stamps: list[float] = []
    sizes: list[int] = []
    with av.open(str(video)) as source:
        stream = source.streams.video[0]
        if stream.time_base is None:
            return None
        last: int | None = None
        for packet in source.demux(stream):
            if packet.size == 0 or packet.pts is None:
                continue
            if last is not None and packet.pts <= last:
                return None  # reordered frames cannot be cut frame-exactly in place
            last = packet.pts
            stamps.append(float(packet.pts * stream.time_base))
            sizes.append(packet.size)
    return stamps, sizes


def _first_instant(stamps: Path) -> float:
    """The joined timeline's time of the first joined frame, from its sidecar."""
    with stamps.open(encoding="utf-8") as handle:
        first = handle.readline().strip()
    if not first:
        raise SourceOpenError("None of this camera's recordings fall inside their trials.")
    return int(first.split(",")[1]) / 1e9


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
        built = (entry / _LIST_NAME).is_file() or (entry / _VIDEO_NAME).is_file()
        if not (cache.is_cache_valid(first) and built):
            staging = cache.get_temp_cache_dir(first)
            try:
                if not _segment_list(
                    self._segments, staging / _LIST_NAME, staging / _STAMPS_NAME, progress_cb
                ):
                    (staging / _LIST_NAME).unlink(missing_ok=True)
                    _join(
                        self._segments, staging / _VIDEO_NAME, staging / _STAMPS_NAME, progress_cb
                    )
                cache.commit_cache(first, staging)
            except BaseException:
                # Our own staging directory under the cache root, never the recording.
                shutil.rmtree(staging, ignore_errors=True)
                raise
        listed = entry / _LIST_NAME
        joined = listed if listed.is_file() else entry / _VIDEO_NAME
        config = {
            key: value for key, value in self._config.items() if key not in ("segments", "fps")
        }
        # The sidecar is rebased to its first frame, which is not the
        # timeline's zero when early trials have no camera recording, or the
        # first recording did not start on its trigger: its own stamp says.
        start = _first_instant(entry / _STAMPS_NAME)
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
