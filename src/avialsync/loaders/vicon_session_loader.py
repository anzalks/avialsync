"""Discover Vicon Nexus trials and pair C3D markers with their video camera.

A session folder holds many trials, and each is placed where it was captured
(D-217): the trial's ``.xcp`` records every camera's ``Capture`` start and end
to the millisecond (``2026-06-25 13:59:36.246 DST``), so trials sit one after
another with the time between them kept as a gap. Each trial's video and
markers start together at that instant, as before. The stamp is the capture
PC's local time and names no zone, so it places trials against each other and
nothing more: the session shows time from its first trial, not wall clock.

A camera's trials are one camera, and their markers one set of markers: they
load as one joined video and one joined marker source
(:mod:`~avialsync.loaders.joined_parts`, D-219) -- one pane, one Data Streams
lane, one 3D object -- each trial still projected through its own calibration.
"""

from __future__ import annotations

import datetime as dt
import logging
import struct
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from typing import Any

import av

from avialsync.core.errors import SourceOpenError
from avialsync.core.source import SessionItem, SessionLayout, SessionSource
from avialsync.core.trials import Part, place
from avialsync.loaders.joined_parts import (
    JOINED_PARTS,
    JoinedTimeSeriesSource,
    JoinedVideoSource,
    loader_name,
    part_stamp,
)
from avialsync.loaders.vicon_c3d_loader import ViconC3DLoader, camera_from_xcp

logger = logging.getLogger(__name__)
_VIDEO_SUFFIXES = {".avi", ".mkv", ".mov", ".mp4", ".m4v"}


def _trial_files(path: Path) -> list[Path]:
    return sorted({*path.glob("*.c3d"), *path.glob("*/*.c3d")})


#: Said once per session whose trials are placed by their capture stamps.
_LOCAL_CLOCK_NOTE = (
    "Vicon stamps each capture in the capture PC's local time without its time zone: "
    "trials are placed against each other by it, and the clock shows time from the "
    "first trial rather than wall clock."
)


def capture_span(xcp_path: Path) -> tuple[float, float] | None:
    """When the trial was captured, ``(start, end)``, from its ``.xcp``; ``None`` if unsaid.

    Every camera's ``Capture`` element carries the same instants. They are the
    capture PC's local time with no zone, returned as seconds on a clock that
    only orders and spaces trials -- never as UTC.
    """
    try:
        root = ET.parse(xcp_path).getroot()
    except (OSError, ET.ParseError):
        return None
    for capture in root.iter("Capture"):
        start = _local_stamp(capture.get("START_TIME", ""))
        end = _local_stamp(capture.get("END_TIME", ""))
        if start is not None and end is not None and end >= start:
            return start, end
    return None


def _local_stamp(text: str) -> float | None:
    """``2026-06-25 13:59:36.246 DST`` as seconds, read as a zone-less clock."""
    fields = text.split()
    if len(fields) < 2:
        return None
    try:
        stamp = dt.datetime.strptime(f"{fields[0]} {fields[1]}", "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        try:
            stamp = dt.datetime.strptime(f"{fields[0]} {fields[1]}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    # Only differences between these are used: the zone cancels out.
    return stamp.replace(tzinfo=dt.UTC).timestamp()


def _matching_video(c3d_path: Path, camera_id: str) -> list[Path]:
    prefix = f"{c3d_path.stem}.{camera_id}."
    return sorted(
        candidate
        for candidate in c3d_path.parent.glob(f"{prefix}*")
        if candidate.suffix.lower() in _VIDEO_SUFFIXES
    )


def _video_metadata(path: Path) -> tuple[float, int, int, int]:
    """Read the video header fields needed to sample pose on its frame grid."""
    try:
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            rate = stream.average_rate or stream.base_rate or stream.guessed_rate
            fps = float(rate) if rate is not None else 0.0
            return fps, int(stream.frames), int(stream.width), int(stream.height)
    except (av.FFmpegError, IndexError, OSError, TypeError, ValueError) as error:
        raise SourceOpenError(f"Could not inspect paired video {path.name}: {error}") from error


class ViconSessionSource(SessionSource):
    """Lay out Vicon C3D trajectories and their calibrated video recordings."""

    @classmethod
    def display_name(cls) -> str:
        return "Vicon Nexus Session"

    @classmethod
    def can_open(cls, path: Path) -> float:
        if not path.is_dir():
            return 0.0
        return (
            0.9
            if any(
                c3d_path.with_suffix(".xcp").is_file()
                and any(
                    candidate.suffix.lower() in _VIDEO_SUFFIXES
                    for candidate in c3d_path.parent.glob(f"{c3d_path.stem}.*")
                )
                for c3d_path in _trial_files(path)
            )
            else 0.0
        )

    def scan(self, path: Path, registry: Any) -> SessionLayout:
        trials: list[tuple[Path, list[SessionItem]]] = []
        warnings: list[str] = []
        for c3d_path in _trial_files(path):
            items: list[SessionItem] = []
            xcp_path = c3d_path.with_suffix(".xcp")
            if not xcp_path.is_file():
                warnings.append(f"{c3d_path.name} has no matching XCP camera calibration.")
                continue
            try:
                camera = camera_from_xcp(xcp_path)
            except SourceOpenError as error:
                warnings.append(str(error))
                continue

            videos = _matching_video(c3d_path, camera.name)
            if len(videos) != 1:
                state = "no" if not videos else "more than one"
                warnings.append(
                    f"{c3d_path.name} has {state} video matching calibrated camera {camera.name}."
                )
                continue
            video = videos[0]
            video_loader = registry.find_best_loader(video)
            if video_loader is None:
                warnings.append(f"No video loader is available for {video.name}.")
                continue
            try:
                fps, frame_count, width, height = _video_metadata(video)
            except SourceOpenError as error:
                warnings.append(str(error))
                continue
            if fps <= 0.0 or width <= 0 or height <= 0:
                warnings.append(f"{video.name} has no usable frame rate or image dimensions.")
                continue

            items.append(
                SessionItem(
                    path=video,
                    loader=video_loader,
                    label=f"{video.name} - video",
                    coverage_group=f"Vicon camera {camera.name}",
                )
            )
            items.append(
                SessionItem(
                    path=c3d_path,
                    loader=ViconC3DLoader,
                    config={
                        "xcp_path": str(xcp_path),
                        "camera_id": camera.name,
                        "fps": fps,
                        "frame_count": frame_count,
                        "video_width": width,
                        "video_height": height,
                        "role": "pose3d_overlay2d",
                        "overlay_video": str(video),
                        "overlay_camera": camera.name,
                        "overlay_label": "Vicon markers",
                    },
                    label=f"{c3d_path.name} - markers over {video.name}",
                    coverage_group=f"Vicon markers over camera {camera.name}",
                )
            )
            trials.append((c3d_path, items))

        layout = _placed(trials, warnings)
        if not layout.items:
            layout.warnings.append("No Vicon C3D trials could be paired with calibrated video.")
        logger.info("Vicon session: %d items from %s", len(layout.items), path.name)
        return layout


def _placed(trials: list[tuple[Path, list[SessionItem]]], warnings: list[str]) -> SessionLayout:
    """The trials at their capture starts, the time between them a gap (D-217).

    Trials whose ``.xcp`` names no capture time cannot be placed; when none
    can, they are laid out as before, each from zero, and the layout says so.
    """
    spans = [capture_span(c3d_path.with_suffix(".xcp")) for c3d_path, _items in trials]
    parts = [
        Part(c3d_path.stem, span[1] - span[0], span[0]) if span else Part(c3d_path.stem, 0.0)
        for (c3d_path, _items), span in zip(trials, spans, strict=True)
    ]
    order = sorted(range(len(parts)), key=lambda index: (parts[index].start or 0.0, index))
    plan = place([parts[index] for index in order])
    if len(trials) > 1 and not plan.kept:
        warnings.append(
            "No trial's calibration file records when it was captured, so the trials "
            "all start at zero."
        )
        return SessionLayout(items=[i for _c3d, items in trials for i in items], warnings=warnings)
    items: list[SessionItem] = []
    cameras: dict[str, list[tuple[float, list[SessionItem]]]] = {}
    for position, start in zip(plan.kept, plan.starts, strict=True):
        trial = trials[order[position]][1]
        cameras.setdefault(str(trial[1].config["camera_id"]), []).append((start, trial))
    for camera, placed in cameras.items():
        if len(placed) > 1:
            items += _joined(camera, placed, plan.epoch or None)
            continue
        start, trial = placed[0]
        epoch = plan.epoch + start if plan.epoch > 0 else None
        items += [replace(item, source_epoch=epoch) for item in trial]
    if plan.epoch > 0:
        warnings = [*warnings, *plan.warnings, _LOCAL_CLOCK_NOTE]
    return SessionLayout(
        items=items,
        session_epoch=plan.epoch,
        segments=plan.segments() if len(plan.kept) > 1 else [],
        warnings=warnings,
    )


def _joined(
    camera: str, placed: list[tuple[float, list[SessionItem]]], epoch: float | None
) -> list[SessionItem]:
    """One camera's trials as one video and one marker source, each trial at its start."""
    videos = [trial[0] for _start, trial in placed]
    markers = [trial[1] for _start, trial in placed]
    starts = [start for start, _trial in placed]
    video_id = videos[0].path / JOINED_PARTS
    first = markers[0].config
    count = len(placed)
    # Each trial's own projection channels (a header read each), and one map
    # for the joined source: a marker spelled two ways across blocks of trials
    # is one marker, under its first spelling, as the joined channels are.
    configs = [_prepared(marker) for marker in markers]
    projection: dict[str, list[str]] = {}
    spellings: set[str] = set()
    for config in configs:
        for point, pair in dict(config.get("vicon_projection_channels") or {}).items():
            if point.casefold() not in spellings:
                spellings.add(point.casefold())
                projection[point] = list(pair)
    return [
        SessionItem(
            path=video_id,
            loader=JoinedVideoSource,
            config={
                "parts": [
                    {"path": str(video.path), "start": start}
                    for video, start in zip(videos, starts, strict=True)
                ]
            },
            label=f"camera {camera} — {count} trials",
            source_epoch=epoch,
        ),
        SessionItem(
            path=markers[0].path,
            loader=JoinedTimeSeriesSource,
            config={
                "part_loader": loader_name(ViconC3DLoader),
                "parts": [
                    {
                        "path": str(marker.path),
                        "start": start,
                        "config": config,
                        **part_stamp(marker.path),
                    }
                    for marker, start, config in zip(markers, starts, configs, strict=True)
                ],
                "role": first["role"],
                "vicon_projection_channels": projection,
                "fps": first["fps"],
                "overlay_video": str(video_id),
                "overlay_camera": camera,
                "overlay_label": first.get("overlay_label", "Vicon markers"),
            },
            label=f"markers over camera {camera} — {count} trials",
            source_epoch=epoch,
        ),
    ]


def _prepared(marker: SessionItem) -> dict[str, Any]:
    """A trial's import config as its loader completes it, or as scanned if unreadable.

    An unreadable header is left for the import to report, where the user sees
    which file it was; the scan does not fail every trial for one.
    """
    try:
        return ViconC3DLoader.prepare_import_config(marker.path, dict(marker.config))
    except (SourceOpenError, OSError, ValueError, struct.error) as error:
        logger.warning("Could not read marker labels of %s: %s", marker.path.name, error)
        return dict(marker.config)
