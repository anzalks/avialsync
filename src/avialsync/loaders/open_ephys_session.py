"""Lay out an Open Ephys recording folder, with its cameras, as one session.

An acquisition folder is not a pile of files that happen to be adjacent.  The
record node, its TTL line and the cameras beside it are one experiment on one
clock, and the only reason they look separate is that three programs wrote them.
This scanner puts them back on a single axis.

The axis is the recording's own acquisition clock, unmodified — raw source
timestamps survive into the session exactly as recorded, and
:attr:`SessionLayout.anchor_epoch` carries the UTC instant that clock's zero
corresponds to so the UI can show wall clock without anything being rewritten.

Sample reading is neo's, throughout: every stream and every TTL line is a
:class:`~avialsync.loaders.neo_loader.NeoLoader` item, so a rig recording in some
other format arrives downstream in the same shape.  What this module supplies is
what neo does not model — which directory is a recording, what wall-clock instant
the acquisition clock started at, and where the cameras belong on it.

Camera placement is deliberately *declared*, never fitted.  The video's filename
gives its start to about a second, and the recording's own local/UTC evidence
converts it onto the same axis; the sidecar then times every frame within the
video exactly.  Fitting the residual second against the TTL line is a
synchronization proposal, and a proposal needs the user to accept it (D-030), so
it belongs to the sync wizard and not to a folder scan.
"""

from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from avialsync.core.source import SessionItem, SessionLayout, SessionSource
from avialsync.loaders.neo_loader import NeoLoader
from avialsync.loaders.open_ephys_camera import OpenEphysCameraLoader, find_timestamp_sidecar
from avialsync.loaders.open_ephys_format import (
    anchor_epoch,
    find_recordings,
    parse_software_epoch,
    recording_utc_offset,
    stream_folder_names,
)

logger = logging.getLogger(__name__)

#: Container suffixes treated as session cameras.
VIDEO_SUFFIXES: frozenset[str] = frozenset({".avi", ".mp4", ".mov", ".mkv", ".webm"})

#: ``camera_top2026-06-21T17_54_59.avi`` — a date and time embedded in a
#: filename, with the separators capture software variously uses because a colon
#: is not a legal filename character on Windows.
_FILENAME_TIME_PATTERN = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})[T_ ](?P<h>\d{2})[-_.](?P<m>\d{2})[-_.](?P<s>\d{2})"
)


def parse_filename_time(name: str) -> datetime.datetime | None:
    """Return the naive local timestamp a capture filename embeds, if any.

    Naive on purpose: the filename records no zone.  It only becomes an instant
    once the recording's own local/UTC evidence says which zone the rig was in.
    """
    match = _FILENAME_TIME_PATTERN.search(name)
    if match is None:
        return None
    stamp = f"{match.group('date')} {match.group('h')}:{match.group('m')}:{match.group('s')}"
    try:
        return datetime.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    except ValueError:  # pragma: no cover - the pattern already constrains this
        return None


class OpenEphysSessionSource(SessionSource):
    """Lay out an Open Ephys record-node tree and the cameras recorded with it."""

    @classmethod
    def display_name(cls) -> str:
        return "Open Ephys Session"

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 1.0 if find_recordings(path) else 0.0

    def scan(self, path: Path, registry: Any) -> SessionLayout:
        recordings = find_recordings(path)
        if not recordings:  # pragma: no cover - can_open already rejected this
            return SessionLayout()
        if len(recordings) > 1:
            logger.info(
                "%s holds %d recordings; timing them all against the first.",
                path.name,
                len(recordings),
            )

        primary = recordings[0]
        clock = _RecordingClock.probe(primary)

        items: list[SessionItem] = []
        for recording in recordings:
            items.extend(_stream_items(recording))
            items.extend(_event_items(recording))
        items.extend(_camera_items(path, recordings, clock))

        logger.info(
            "Open Ephys session: %d item(s) from %s (anchor_epoch=%.3f, utc_offset=%s)",
            len(items),
            path.name,
            clock.anchor_epoch,
            "unknown" if clock.utc_offset is None else f"{clock.utc_offset / 3600:+.2f} h",
        )
        return SessionLayout(items=items, anchor_epoch=clock.anchor_epoch)


class _RecordingClock:
    """What one recording knows about its own place in wall-clock time."""

    def __init__(
        self, anchor: float, utc_offset: float | None, first_sample_time: float | None
    ) -> None:
        self.anchor_epoch = anchor
        self.utc_offset = utc_offset
        self.first_sample_time = first_sample_time

    @classmethod
    def probe(cls, recording: Path) -> _RecordingClock:
        """Read the recording's absolute instant and the offset it implies."""
        software_epoch = parse_software_epoch(recording)
        first_sample = _first_sample_time(recording)
        return cls(
            anchor=anchor_epoch(software_epoch, first_sample),
            utc_offset=recording_utc_offset(recording),
            first_sample_time=first_sample,
        )

    def master_time_for(self, local_naive: datetime.datetime | None) -> float | None:
        """Return where a local wall-clock instant sits on the acquisition clock."""
        if local_naive is None or self.utc_offset is None or self.anchor_epoch <= 0.0:
            return None
        utc_epoch = local_naive.replace(tzinfo=datetime.UTC).timestamp() - self.utc_offset
        return utc_epoch - self.anchor_epoch


def _first_sample_time(recording: Path) -> float | None:
    """Return the earliest ``t_start`` across the recording's streams, via neo.

    Read through neo rather than from ``timestamps.npy`` so the anchor is
    expressed on exactly the clock the imported samples will carry.  Neo
    reconstructs sample times from the first sample number and the rate; taking
    the anchor from a different source would leave every stream offset from its
    own wall clock by the difference between the two.
    """
    try:
        import neo

        block = neo.io.get_io(str(recording)).read_block(lazy=True)
    except Exception:  # noqa: BLE001 - plugin boundary: neo's dependencies are the user's
        logger.warning("Neo could not open %s to read its start time.", recording, exc_info=True)
        return None
    starts = [
        float(signal.t_start.magnitude)
        for segment in block.segments
        for signal in segment.analogsignals
    ]
    return min(starts) if starts else None


@dataclass(frozen=True)
class _Stream:
    """One continuous stream, as much as a folder scan needs to know about it."""

    stream_id: str
    name: str
    channels: int = 0
    rate_hz: float = 0.0

    def label(self, folder: str) -> str:
        """Return the dialog row for this stream: what it is, and what it costs.

        The manifest's short stream name, not the decorated directory, and the
        shape that decides whether importing it takes two seconds or four
        minutes.  Four rows reading ``Acquisition_Board-124.<something>`` said
        nothing about which one was the 32-channel 30 kHz stream.
        """
        short = self.name.rsplit("#", 1)[-1] or folder
        short = short.rsplit(".", 1)[-1] or short
        if self.channels and self.rate_hz:
            return f"{short} — {self.channels} ch @ {_format_rate(self.rate_hz)}"
        return short


def _format_rate(rate_hz: float) -> str:
    """Render a sampling rate the way an experimenter says it."""
    if rate_hz >= 1000.0:
        return f"{rate_hz / 1000.0:g} kHz"
    return f"{rate_hz:g} Hz"


def _neo_streams(recording: Path) -> list[_Stream]:
    """Return every continuous stream neo sees, with its shape.

    The raw header is asked first because it names streams, whereas a signal only
    names itself.  A stream neo splits into several signals — one per unit, which
    is what an 18-channel IMU becomes — has no signal carrying the stream's name,
    so deriving it from the first signal produced ``Channels: (Eul-Y Eul-R
    Eul-P)`` and matched no directory at all.  The signals are still read, for
    the channel count and rate, which only they carry.
    """
    try:
        import neo

        io = neo.io.get_io(str(recording))
        header = getattr(io, "header", None)
        if header is None and hasattr(io, "parse_header"):
            io.parse_header()
            header = getattr(io, "header", None)
        block = io.read_block(lazy=True)
    except Exception:  # noqa: BLE001 - plugin boundary, as above
        logger.warning("Neo could not enumerate streams in %s.", recording, exc_info=True)
        return []

    shapes: dict[str, tuple[int, float]] = {}
    fallback_names: dict[str, str] = {}
    for segment in block.segments:
        for signal in segment.analogsignals:
            stream_id = str(signal.annotations.get("stream_id", ""))
            if not stream_id:
                continue
            channels, rate = shapes.get(stream_id, (0, 0.0))
            shapes[stream_id] = (
                channels + int(signal.shape[1]),
                rate or float(signal.sampling_rate.magnitude),
            )
            fallback_names.setdefault(stream_id, str(signal.name or ""))

    names: dict[str, str] = fallback_names
    if header is not None and "signal_streams" in header:
        names = {str(stream["id"]): str(stream["name"]) for stream in header["signal_streams"]}

    return sorted(
        (
            _Stream(stream_id, names.get(stream_id, ""), *shapes.get(stream_id, (0, 0.0)))
            for stream_id in names
        ),
        key=lambda stream: stream.stream_id,
    )


def _stream_items(recording: Path) -> list[SessionItem]:
    """One item per continuous stream, each pointed at its own directory."""
    folders = stream_folder_names(recording)
    items: list[SessionItem] = []

    for stream in _neo_streams(recording):
        folder = _match_folder(stream.name, folders)
        if folder is None:
            logger.warning(
                "Open Ephys stream %r (id %s) matches no directory the manifest declares; "
                "skipping it rather than sharing another stream's cache.",
                stream.name,
                stream.stream_id,
            )
            continue
        directory = recording / "continuous" / folder
        if not directory.is_dir():
            logger.warning("Open Ephys stream directory %s is missing; skipping it.", directory)
            continue
        items.append(
            SessionItem(
                directory,
                NeoLoader,
                {"root": str(recording), "stream_id": stream.stream_id, "auto_resolved": True},
                label=stream.label(folder),
            )
        )
    return items


def _match_folder(stream_name: str, folders: list[str]) -> str | None:
    """Resolve a neo stream name to the manifest directory it was read from.

    Neo decorates a stream name with the record node it arrived through
    (``Record Node 116#Acquisition_Board-124.acquisition_board``), so the
    manifest's folder name is a suffix of it.  Longest first, so a stream cannot
    be matched by a shorter name that happens to be a suffix of it too.
    """
    for folder in sorted(folders, key=len, reverse=True):
        if stream_name.endswith(folder):
            return folder
    return None


def _event_items(recording: Path) -> list[SessionItem]:
    """One item for the recording's TTL lines, if it recorded any.

    All TTL lines come through a single item: they are edge lists, not sampled
    streams, so they carry no shared timestamp array to split apart and each one
    is a few hundred kilobytes.
    """
    events_dir = recording / "events"
    if not events_dir.is_dir():
        return []
    ttl_dirs = sorted(child for child in events_dir.glob("*/TTL") if child.is_dir())
    if not ttl_dirs:
        return []
    return [
        SessionItem(
            ttl_dirs[0],
            NeoLoader,
            {"root": str(recording), "events": True, "auto_resolved": True},
            label=f"TTL events — {ttl_dirs[0].parent.name.rsplit('.', 1)[-1]}",
        )
    ]


def _camera_items(
    session_dir: Path, recordings: list[Path], clock: _RecordingClock
) -> list[SessionItem]:
    """Cameras recorded beside the ephys, placed on the acquisition clock.

    A video whose wall-clock start cannot be resolved is placed at the first
    sample instead of at zero.  Zero would be correct only if the acquisition
    clock had been reset at record start, which it is not — the streams here begin
    several seconds in, and a video at zero would sit off the front of every one
    of them with no visible reason why.
    """
    recording_roots = {
        recording.parents[2] if len(recording.parents) > 2 else recording
        for recording in recordings
    }
    items: list[SessionItem] = []

    for video in sorted(session_dir.iterdir()):
        if video.name.startswith(".") or video.suffix.lower() not in VIDEO_SUFFIXES:
            continue
        if any(root in video.parents for root in recording_roots):
            continue

        start_time = clock.master_time_for(parse_filename_time(video.name))
        if start_time is None:
            start_time = clock.first_sample_time or 0.0
            logger.info(
                "%s declares no resolvable wall-clock start; placing it at the recording's "
                "first sample (%.3f s). Align it against the TTL line to refine.",
                video.name,
                start_time,
            )

        config: dict[str, Any] = {"start_time": start_time, "auto_resolved": True}
        sidecar = find_timestamp_sidecar(video)
        if sidecar is not None:
            config["frame_timestamps"] = str(sidecar)
        else:
            logger.info(
                "No frame timestamp sidecar for %s; its container's nominal rate is all "
                "the timing evidence there is.",
                video.name,
            )
        items.append(
            SessionItem(
                video,
                OpenEphysCameraLoader,
                config,
                label=f"{video.name} — camera",
            )
        )
    return items
