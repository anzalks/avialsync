"""One stream across a session's parts: a camera's trials as one video, its markers as one source.

A session made of parts (D-217) records the same streams in every part: the
same camera, the same markers, trial after trial. Opened file by file they
are one pane and one 3D object per trial; joined they are what they are -- one
camera, one set of markers -- with the time between parts kept as a gap
(D-219). Any session scanner declares a joined stream as one item:

* :class:`JoinedVideoSource` -- the parts' video files read as one video in
  place (:mod:`~avialsync.engine.segmented_media`), each file at its part's
  start. Any codec: each file is read through its own keyframes.
* :class:`JoinedTimeSeriesSource` -- each part read by its own loader with its
  own config (its own calibration, its own video size), every chunk moved to
  its part's start.

``parts`` in the item's config is ``[{"path", "start", "config"?}]``, with
``start`` in seconds from the item's ``source_epoch`` -- the plan from
:func:`avialsync.core.trials.place`. The time series also names the loader
that reads one part (``part_loader``, ``module:Class``).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.cache import CacheManager, cache_dir_for, source_identity
from avialsync.core.errors import SourceOpenError
from avialsync.core.pose import PoseSchema
from avialsync.core.source import ChannelInfo, TimeSeriesSource
from avialsync.loaders.video_standard import VideoStandardLoader

#: Last path part of a joined video's source id: ``<first part's file>/joined_parts``.
JOINED_PARTS = "joined_parts"
_VERSION = 1
_MANIFEST_NAME = "parts.segments.json"


def _parts(config: dict[str, Any]) -> list[dict[str, Any]]:
    parts = [dict(part) for part in config.get("parts", ())]
    if not parts:
        raise SourceOpenError("A joined stream needs its parts.")
    return parts


def part_stamp(path: Path) -> dict[str, Any]:
    """What changes when a part's file does: in the config, so a cache follows it."""
    stat = path.stat()
    return {"size": stat.st_size, "mtime": stat.st_mtime_ns}


class _PartsCache(CacheManager):
    """A cache entry keyed on every part, named inside the first part's file."""

    def __init__(self, parts: list[dict[str, Any]]) -> None:
        listing = [
            {
                "path": str(part["path"]),
                "start": float(part["start"]),
                **part_stamp(Path(part["path"])),
            }
            for part in parts
        ]
        super().__init__(loader_version=_VERSION, cache_config={"parts": listing})
        self._digest = hashlib.sha1(json.dumps(listing, sort_keys=True).encode("utf-8")).hexdigest()
        self._count = len(parts)

    def get_cache_dir(self, source_path: Path) -> Path:
        tag = f"{source_identity(source_path)}#parts{self._count}-{self._digest[:12]}"
        return cache_dir_for(tag, self._root)


class JoinedVideoSource(VideoStandardLoader):
    """A camera's part files as one video, each at its part's start, read in place."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[dict[str, Any]] = []
        self._joined: Path | None = None

    @classmethod
    def display_name(cls) -> str:
        return "Video (Joined Parts)"

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Claim only the joined name inside an existing file; sessions declare it."""
        return 1.0 if path.name == JOINED_PARTS and path.parent.is_file() else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        self._parts, self._config = _parts(config), dict(config)

    def needs_conversion(self) -> bool:
        return True

    def prepare_is_atomic(self) -> bool:
        return True

    def prepare(self, progress_cb: Callable[[float], None]) -> Path:
        if not self._parts:
            raise SourceOpenError("A joined video has not been opened.")
        first = Path(self._parts[0]["path"])
        cache = _PartsCache(self._parts)
        entry = cache.get_cache_dir(first)
        if not (cache.is_cache_valid(first) and (entry / _MANIFEST_NAME).is_file()):
            self._build(cache, first, progress_cb)
        manifest = entry / _MANIFEST_NAME
        config = {key: value for key, value in self._config.items() if key != "parts"}
        super().open(manifest, config)
        self._joined = manifest
        progress_cb(1.0)
        return manifest

    def _build(self, cache: _PartsCache, first: Path, progress_cb: Callable[[float], None]) -> None:
        """One table per file, read once, and the manifest placing each file at its start."""
        from avialsync.engine.segmented_media import (
            Segment,
            file_table,
            write_manifest,
            write_tables,
        )

        staging = cache.get_temp_cache_dir(first)
        try:
            tables = []
            segments = []
            for number, part in enumerate(self._parts):
                ticks, keys, base = file_table(part["path"])
                if not len(ticks):
                    raise SourceOpenError(f"{Path(part['path']).name} holds no frames.")
                tables.append((ticks, keys, base))
                segments.append(
                    Segment(str(Path(part["path"]).resolve()), 0, len(ticks), float(part["start"]))
                )
                progress_cb((number + 1) / len(self._parts))
            write_manifest(staging / _MANIFEST_NAME, segments)
            write_tables(staging / _MANIFEST_NAME, tables)
            cache.commit_cache(first, staging)
        except BaseException:
            # Our own staging directory under the cache root, never a recording.
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def media_path(self) -> Path:
        if self._joined is None:
            raise SourceOpenError("A joined video has not been prepared.")
        return self._joined


def _loader_class(name: str) -> type[TimeSeriesSource]:
    """The loader one part is read with, from its ``module:Class`` name."""
    module_name, _, class_name = name.partition(":")
    try:
        loader = getattr(importlib.import_module(module_name), class_name)
    except (ImportError, AttributeError) as error:
        raise SourceOpenError(f"The loader {name} for a joined stream is not installed.") from error
    if not (isinstance(loader, type) and issubclass(loader, TimeSeriesSource)):
        raise SourceOpenError(f"{name} does not read time series.")
    return loader


def loader_name(loader: type) -> str:
    """The ``module:Class`` name :class:`JoinedTimeSeriesSource` reads a part with."""
    return f"{loader.__module__}:{loader.__qualname__}"


class JoinedTimeSeriesSource(TimeSeriesSource):
    """A stream's parts, each read by its own loader, moved to each part's start.

    Parts need not record the same channels -- a later block of trials may
    track more markers. The joined source has every channel any part has;
    where a part did not record one, it reads NaN for that part's samples,
    which every view shows as missing, never as a value.
    """

    def __init__(self) -> None:
        self._parts: list[dict[str, Any]] = []
        self._loader: type[TimeSeriesSource] | None = None
        self._readers: list[TimeSeriesSource] = []
        self._channels: list[ChannelInfo] = []

    @classmethod
    def display_name(cls) -> str:
        return "Data (Joined Parts)"

    @classmethod
    def display_aliases(cls) -> list[str]:
        return ["3D Marker Tracking"]

    @classmethod
    def pose_roles(cls) -> tuple[str, ...]:
        return ("overlay2d", "pose3d", "pose3d_overlay2d")

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 0.0  # declared by a session, never claimed by a drop

    def is_frame_indexed(self) -> bool:
        return bool(self._readers) and self._readers[0].is_frame_indexed()

    def open(self, path: Path, config: dict[str, Any]) -> None:
        """Open every part: their headers say which channels the joined stream has."""
        self._parts = _parts(config)
        self._loader = _loader_class(str(config.get("part_loader", "")))
        self._readers = [self._open_part(part) for part in self._parts]
        known: dict[str, ChannelInfo] = {}
        for reader in self._readers:
            for channel in reader.channels():
                known.setdefault(channel.name, channel)
        self._channels = list(known.values())

    def _open_part(self, part: dict[str, Any]) -> TimeSeriesSource:
        assert self._loader is not None
        loader = self._loader()
        loader.open(Path(part["path"]), dict(part.get("config") or {}))
        return loader

    def channels(self) -> list[ChannelInfo]:
        if not self._readers:
            raise SourceOpenError("A joined stream has not been opened.")
        return list(self._channels)

    def pose_schema(self) -> PoseSchema | None:
        """Every part's points, in the order they first appear."""
        schemas = [schema for reader in self._readers if (schema := reader.pose_schema())]
        if not schemas:
            return None
        points = {point.name: point for schema in schemas for point in schema.points}
        return replace(schemas[0], points=tuple(points.values()))

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        for chunk in self.read_all_chunks((ch,)):
            yield chunk[ch]

    def read_all_chunks(
        self, channels: tuple[str, ...] | None = None
    ) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
        """Each part's chunks in turn, every time moved to its part's start."""
        if not self._readers:
            raise SourceOpenError("A joined stream has not been opened.")
        wanted = tuple(channels or (channel.name for channel in self._channels))
        for part, reader in zip(self._parts, self._readers, strict=True):
            own = [channel.name for channel in reader.channels()]
            present = tuple(name for name in wanted if name in own)
            # A part with none of the wanted channels still has samples: read
            # one of its own for their times, and the wanted ones are NaN there.
            asked = present or tuple(own[:1])
            start = float(part["start"])
            for chunk in _chunks(reader, asked):
                times = next(iter(chunk.values()))[0]
                missing = np.full(len(times), np.nan, dtype=np.float64)
                yield {
                    name: (start + times, chunk[name][1] if name in present else missing)
                    for name in wanted
                }


def _chunks(
    reader: TimeSeriesSource, channels: tuple[str, ...]
) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
    """A part's chunks, through its bulk read when it has one."""
    bulk = getattr(reader, "read_all_chunks", None)
    if callable(bulk):
        yield from bulk(channels)
        return
    # Without a bulk read, each channel whole: one part is one chunk.
    chunk: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for name in channels:
        pieces = list(reader.read_chunks(name))
        if not pieces:
            return
        chunk[name] = (
            np.concatenate([times for times, _values in pieces]),
            np.concatenate([values for _times, values in pieces]),
        )
    yield chunk
