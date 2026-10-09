"""Asynchronous data source importer pipeline."""

import dataclasses
import hashlib
import json
import logging
import os
import shutil
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal

from avialsync.core.cache import CacheManager
from avialsync.core.errors import LoaderContractError, SourceOpenError
from avialsync.core.inspection import ImportReport, IntegrityFlags, SourceInspection
from avialsync.core.messages import Message, bounded
from avialsync.core.pyramid import LEVELS, ChannelStage, PyramidBuilder, build_gap_mask, count_nan
from avialsync.core.source import display_unit
from avialsync.loaders.csv_loader import CSVLoader

logger = logging.getLogger(__name__)

# Increment when imported array layout or validation metadata changes.
_IMPORT_CACHE_VERSION = 9
_IMPORT_MANIFEST = "import.json"
_STAGING_DIR = "_stage"
_ARRAY_SAMPLE_BYTES = 4096

#: Gap *locations* are display evidence, so they are capped; ``gap_count`` in the
#: import report always stays exact.  A pathological recording can otherwise put
#: millions of floats into the session file and the report dialog.
MAX_GAP_LOCATIONS = 10_000


def _array_fingerprint(path: Path) -> str:
    """Fingerprint three bounded regions of one derived array."""
    size = path.stat().st_size
    digest = hashlib.blake2b(digest_size=16)
    with path.open("rb") as stream:
        for offset in (
            0,
            max(0, size // 2 - _ARRAY_SAMPLE_BYTES // 2),
            max(0, size - _ARRAY_SAMPLE_BYTES),
        ):
            stream.seek(offset)
            digest.update(stream.read(_ARRAY_SAMPLE_BYTES))
    return digest.hexdigest()


def _share_file(source: Path, target: Path) -> None:
    """Give *target* the same bytes as *source*, without a second copy if possible.

    Every channel of one stream carries the same timestamps and the same gap mask,
    and the cache entry names a copy of each after every channel.  For a 32-channel
    30 kHz headstage that is 32 identical 191 MB timestamp arrays — six gigabytes
    of the same numbers, and six gigabytes of write time before anything can be
    plotted.  A hard link is the same file under a second name, so the reader,
    which only ever mmaps these read-only, cannot tell the difference.

    Filesystems that cannot link (FAT, exFAT, some network mounts) fall back to
    copying, because a slower correct import beats a failed one.
    """
    try:
        os.link(source, target)
    except (OSError, NotImplementedError, AttributeError):
        # Not an error worth surfacing: only the disk cost changes.
        logger.debug("Cannot hard link %s; copying instead.", target.name, exc_info=True)
        shutil.copyfile(source, target)


def _gap_locations(times: np.ndarray, gap_mask: np.ndarray) -> list[float]:
    """Return up to :data:`MAX_GAP_LOCATIONS` gap timestamps as bounded evidence."""
    indices = np.flatnonzero(gap_mask)
    if len(indices) > MAX_GAP_LOCATIONS:
        indices = indices[:MAX_GAP_LOCATIONS]
    return [float(value) for value in times[indices]]


def _declared_units(channels: Any) -> dict[str, str]:
    """Each named channel's declared unit, omitting the ones that declare none."""
    units = {str(ch.name): display_unit(str(getattr(ch, "unit", ""))) for ch in channels}
    return {name: unit for name, unit in units.items() if unit}


def _declared_visibility(channels: Any) -> dict[str, bool]:
    """Each channel's initial visibility, defaulting older plugins to shown."""
    return {str(ch.name): bool(getattr(ch, "shown", True)) for ch in channels}


def _declared_descriptions(channels: Any) -> dict[str, str]:
    """Each channel's optional context, omitting empty descriptions."""
    return {
        str(ch.name): str(getattr(ch, "description", ""))
        for ch in channels
        if getattr(ch, "description", "")
    }


class ImportWorker(QObject):
    """Background worker for parsing and building pyramids from time-series sources."""

    progress = Signal(int)  # 0-100
    # path, cache_dir, channel_names, (t0, t1), SourceInspection
    finished = Signal(str, str, list, tuple, object)
    error = Signal(str)

    def __init__(self, path: Path, config: dict[str, Any], loader_class: type = CSVLoader) -> None:
        super().__init__()
        self.path = path
        self.config = config
        self.loader_class = loader_class
        self._cancel_flag = False
        #: The share of the whole import the current pass reports into. A
        #: grouped import builds each group with the bulk builder, whose progress
        #: would otherwise run 0-100 once per group (D-188).
        self._progress_span = (0.0, 1.0)

    def cancel(self) -> None:
        self._cancel_flag = True

    def run(self) -> None:
        temp_dir: Path | None = None
        try:
            cache_mgr = self._cache_manager()
            cached = self._cached_result(cache_mgr)
            if cached is not None:
                cache_dir, channels, bounds, inspection = cached
                cache_mgr.record_access(self.path)
                if (
                    inspection.channel_units is None
                    or inspection.default_channel_visibility is None
                    or inspection.channel_descriptions is None
                ):
                    inspection = self._backfill_units(cache_dir, channels, bounds, inspection)
                self.progress.emit(100)
                self.finished.emit(str(self.path), str(cache_dir), channels, bounds, inspection)
                return

            loader = self.loader_class()
            loader.open(self.path, self.config)

            temp_dir = cache_mgr.get_temp_cache_dir(self.path)

            channels = loader.channels()
            if not channels:
                raise SourceOpenError("No channels found in source.")

            channel_names = [ch.name for ch in channels]
            group_reader = getattr(loader, "iter_channel_groups", None)
            bulk_reader = getattr(loader, "read_all_chunks", None)
            if callable(group_reader):
                result = self._build_channel_groups(group_reader(), channel_names, temp_dir)
            elif callable(bulk_reader):
                result = self._build_bulk_channels(
                    bulk_reader(),
                    channel_names,
                    temp_dir,
                )
            else:
                result = self._build_channel_by_channel(loader, channel_names, temp_dir)
            total_rows, total_nan, gap_count, all_gap_locations, t0, t1 = result

            if self._cancel_flag:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return

            fps_provisional = bool(
                loader.is_frame_indexed() and self.config.get("fps_provisional", False)
            )

            report = ImportReport(
                rows_parsed=total_rows,
                gap_count=gap_count,
                nan_count=total_nan,
                gap_locations=tuple(all_gap_locations),
                import_timestamp=time.time(),
            )
            flags = IntegrityFlags(
                has_gaps=gap_count > 0,
                fps_provisional=fps_provisional,
            )
            loader_id = type(loader).__name__
            fps_binding = "provisional" if fps_provisional else ""

            # Asked once, here, while the loader is open: every consumer of
            # this source reads the schema off the inspection rather than
            # recovering it from channel names (D-140).
            pose_schema = None
            try:
                pose_schema = loader.pose_schema()
            except Exception:  # noqa: BLE001 - plugin boundary
                logger.warning("%s.pose_schema() failed; importing as plain channels", loader_id)

            inspection = SourceInspection(
                path=str(self.path),
                loader_id=loader_id,
                pose=pose_schema,
                import_config=dict(self.config),
                import_report=report,
                integrity_flags=flags,
                fps_binding=fps_binding,
                messages=self._collect_messages(loader),
                channel_units=_declared_units(channels),
                default_channel_visibility=_declared_visibility(channels),
                channel_descriptions=_declared_descriptions(channels),
            )

            self._write_manifest(temp_dir, channel_names, (t0, t1), inspection)
            cache_mgr.commit_cache(self.path, temp_dir)
            final_dir = cache_mgr.get_cache_dir(self.path)

            self.finished.emit(str(self.path), str(final_dir), channel_names, (t0, t1), inspection)

        except Exception as e:
            traceback.print_exc()
            self.error.emit(str(e))
        finally:
            if temp_dir is not None and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _backfill_units(
        self,
        cache_dir: Path,
        channels: list[str],
        bounds: tuple[float, float],
        inspection: SourceInspection,
    ) -> SourceInspection:
        """Read the units a cache written before they were recorded never kept.

        Only the channel list is asked for -- no samples are parsed -- and the
        manifest is rewritten so this happens once per cached source. A loader
        that cannot say is not an error: the plots show the bare channel name.
        """
        units: dict[str, str] = {}
        visibility: dict[str, bool] = {}
        descriptions: dict[str, str] = {}
        loader = None
        try:
            loader = self.loader_class()
            loader.open(self.path, self.config)
            channels_info = loader.channels()
            units = _declared_units(channels_info)
            visibility = _declared_visibility(channels_info)
            descriptions = _declared_descriptions(channels_info)
        except Exception:  # noqa: BLE001 - optional metadata from a plugin boundary
            logger.info("Could not read channel units for %s", self.path, exc_info=True)
        finally:
            close = getattr(loader, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - closing a reader we only asked for names
                    logger.debug("Closing %s after reading units failed", self.path)
        updated: SourceInspection = dataclasses.replace(
            inspection,
            channel_units=units,
            default_channel_visibility=visibility,
            channel_descriptions=descriptions,
        )
        try:
            self._write_manifest(cache_dir, channels, bounds, updated)
        except OSError:
            logger.info("Could not record channel units in the cache for %s", self.path)
        return updated

    @staticmethod
    def _collect_messages(loader: Any) -> tuple[Message, ...]:
        """Return the loader's free-text records, bounded, never fatally.

        A format's prose is the least load-bearing thing it carries: losing the
        samples fails the import, losing a note must not.  A third-party plugin
        that raises here would otherwise turn a readable recording into an
        unopenable one over a comment field.
        """
        reader = getattr(loader, "messages", None)
        if not callable(reader):
            return ()
        try:
            return bounded(list(reader()))
        except Exception:  # noqa: BLE001 - third-party plugin surface
            logger.warning(
                "Loader %s failed to read messages; importing without them.",
                type(loader).__name__,
                exc_info=True,
            )
            return ()

    def _cache_manager(self) -> CacheManager:
        """Return the cache manager scoped to loader identity and accepted config."""
        prepare_config = getattr(self.loader_class, "prepare_import_config", None)
        if callable(prepare_config):
            self.config = prepare_config(self.path, self.config)
        loader_name = f"{self.loader_class.__module__}.{self.loader_class.__qualname__}"
        cache_config: dict[str, Any] = {"loader": loader_name, "config": self.config}
        root = self.config.get("root")
        if root:
            manifest = Path(root) / "structure.oebin"
            if manifest.is_file():
                # Neo opens the recording root even though each stream's cache
                # identity is its own directory. The root manifest controls
                # channel layout and timing, so it must invalidate every stream.
                cache_config["root_manifest"] = CacheManager().generate_key(manifest)
        return CacheManager(
            loader_version=_IMPORT_CACHE_VERSION,
            cache_config=cache_config,
        )

    def _cached_result(
        self, cache_mgr: CacheManager
    ) -> tuple[Path, list[str], tuple[float, float], SourceInspection] | None:
        """Return a validated cache manifest without opening the source parser."""
        cache_dir = cache_mgr.get_cache_dir(self.path)
        manifest_path = cache_dir / _IMPORT_MANIFEST
        if not cache_mgr.is_cache_valid(self.path) or not manifest_path.is_file():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            channels = [str(channel) for channel in manifest["channels"]]
            bounds_raw = manifest["bounds"]
            bounds = (float(bounds_raw[0]), float(bounds_raw[1]))
            inspection = SourceInspection.from_dict(manifest["inspection"])
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if (
            not channels
            or bounds[1] < bounds[0]
            or not self._arrays_intact(
                cache_dir,
                channels,
                manifest.get("array_sizes"),
                manifest.get("array_fingerprints"),
            )
        ):
            return None
        return cache_dir, channels, bounds, inspection

    @staticmethod
    def _arrays_intact(cache_dir: Path, channels: list[str], sizes: Any, fingerprints: Any) -> bool:
        """Reject missing, truncated, or structurally invalid cached arrays."""
        if not isinstance(sizes, dict) or not sizes or not isinstance(fingerprints, dict):
            return False
        if sizes.keys() != fingerprints.keys():
            return False
        try:
            for name, expected_size in sizes.items():
                if (
                    not isinstance(name, str)
                    or Path(name).name != name
                    or not name.endswith(".npy")
                    or not isinstance(expected_size, int)
                    or (cache_dir / name).stat().st_size != expected_size
                    or _array_fingerprint(cache_dir / name) != fingerprints[name]
                ):
                    return False
            for channel in channels:
                base = [f"{channel}_{suffix}.npy" for suffix in ("t", "v", "gap")]
                if any(name not in sizes for name in base):
                    return False
                columns = [
                    np.load(cache_dir / name, mmap_mode="r", allow_pickle=False) for name in base
                ]
                count = len(columns[0])
                if (
                    count == 0
                    or any(column.ndim != 1 or len(column) != count for column in columns)
                    or columns[0].dtype != np.float64
                    or not np.issubdtype(columns[1].dtype, np.number)
                    or columns[2].dtype != np.bool_
                ):
                    return False
                for level in LEVELS[1:]:
                    names = [
                        f"{channel}_pyr_{level}_{suffix}.npy"
                        for suffix in ("t", "vmin", "vmax", "gap")
                    ]
                    if any(name not in sizes for name in names):
                        return False
                    pyramid = [
                        np.load(cache_dir / name, mmap_mode="r", allow_pickle=False)
                        for name in names
                    ]
                    expected_count = (count + level - 1) // level
                    if (
                        any(array.ndim != 1 or len(array) != expected_count for array in pyramid)
                        or pyramid[0].dtype != np.float64
                        or pyramid[3].dtype != np.bool_
                        or not all(
                            np.issubdtype(array.dtype, np.floating) for array in pyramid[1:3]
                        )
                    ):
                        return False
        except (OSError, TypeError, ValueError):
            return False
        return True

    def _build_bulk_channels(
        self,
        chunks: Any,
        channel_names: list[str],
        temp_dir: Path,
    ) -> tuple[int, int, int, list[float], float, float]:
        """Build aligned channels from one loader pass, retaining shared timestamps once.

        Parser chunks are appended straight to on-disk staging buffers, so peak
        memory is one chunk per channel rather than the whole recording.
        """
        staging_dir = temp_dir / _STAGING_DIR
        staging_dir.mkdir(parents=True, exist_ok=True)
        time_stage = ChannelStage(staging_dir, "_shared_t")
        value_stages = {
            channel: ChannelStage(staging_dir, channel, allow_float32=True)
            for channel in channel_names
        }
        try:
            for chunk in chunks:
                if self._cancel_flag:
                    break
                if set(chunk) != set(channel_names):
                    raise LoaderContractError("Bulk loader did not return every declared channel.")
                reference_times: np.ndarray | None = None
                for channel in channel_names:
                    times, values = chunk[channel]
                    if reference_times is None:
                        reference_times = np.asarray(times, dtype=np.float64)
                    elif not np.array_equal(reference_times, times):
                        raise LoaderContractError(
                            "Bulk loader channel chunks do not share timestamps."
                        )
                    values_array = np.asarray(values, dtype=np.float64)
                    if len(values_array) != len(reference_times):
                        raise LoaderContractError(
                            "Bulk loader returned mismatched time/value chunk lengths."
                        )
                    value_stages[channel].append(values_array)
                if reference_times is not None and len(reference_times):
                    time_stage.append(reference_times)

            if self._cancel_flag or time_stage.count == 0:
                return 0, 0, 0, [], 0.0, 0.0
            return self._finalize_bulk_channels(
                staging_dir, temp_dir, channel_names, time_stage, value_stages
            )
        finally:
            time_stage.discard()
            for stage in value_stages.values():
                stage.discard()
            # Every mmap opened by the finalize step is out of scope here, so the
            # staging files can be removed on Windows as well as POSIX.  Staging
            # lives inside the temp cache dir and must never reach a committed
            # sidecar.
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _finalize_bulk_channels(
        self,
        staging_dir: Path,
        temp_dir: Path,
        channel_names: list[str],
        time_stage: ChannelStage,
        value_stages: dict[str, ChannelStage],
    ) -> tuple[int, int, int, list[float], float, float]:
        """Materialise staged samples into the cache entry; scopes every mmap locally."""
        shared_t_path = staging_dir / "shared_t.npy"
        shared_t = time_stage.materialize(shared_t_path)
        gap_mask = build_gap_mask(shared_t)
        gap_path = staging_dir / "shared_gap.npy"
        np.save(gap_path, gap_mask)

        total_nan = 0
        for index, channel in enumerate(channel_names):
            values = value_stages[channel].materialize(temp_dir / f"{channel}_v.npy")
            _share_file(shared_t_path, temp_dir / f"{channel}_t.npy")
            _share_file(gap_path, temp_dir / f"{channel}_gap.npy")
            PyramidBuilder(temp_dir, channel).save_levels(
                shared_t, values, gap_mask, include_base=False
            )
            total_nan += count_nan(values)
            del values
            self._emit_progress((index + 1) / len(channel_names))

        return (
            int(len(shared_t)),
            total_nan,
            int(np.count_nonzero(gap_mask)),
            _gap_locations(shared_t, gap_mask),
            float(shared_t[0]),
            float(shared_t[-1]),
        )

    def _build_channel_groups(
        self,
        groups: Any,
        channel_names: list[str],
        temp_dir: Path,
    ) -> tuple[int, int, int, list[float], float, float]:
        """Build channels group by group, each group on its own shared clock.

        For a loader whose channels sit on several clocks -- an NWB file holds a
        30 kHz probe, a 6 Hz fluorescence matrix and a 100 Hz wheel -- neither
        existing path fits. One bulk read needs one clock for everything; reading
        channel by channel reads a 2-D series once per column and writes one
        timestamp copy per channel. ``iter_channel_groups`` yields
        ``(names, chunks)`` per clock, and each group goes through the bulk
        builder: one pass over its rows, one stored timestamp array (D-188).

        Row and gap counts come from the first group with samples, as the
        per-channel path takes them from its first channel; the bounds span every
        group, because a source's coverage is where any of its channels has data.
        """
        declared = set(channel_names)
        total_rows = gap_count = total_nan = 0
        gap_locations: list[float] = []
        t0, t1 = float("inf"), float("-inf")
        counted = False
        done = 0
        try:
            for names, chunks in groups:
                if self._cancel_flag:
                    break
                if not set(names) <= declared:
                    raise LoaderContractError(
                        "Grouped loader yielded channels it did not declare: "
                        + ", ".join(sorted(set(names) - declared))
                    )
                total = max(1, len(channel_names))
                self._progress_span = (done / total, (done + len(names)) / total)
                rows, nan_count, gaps, locations, start, end = self._build_bulk_channels(
                    chunks, list(names), temp_dir
                )
                done += len(names)
                if rows == 0:
                    continue
                total_nan += nan_count
                t0, t1 = min(t0, start), max(t1, end)
                if not counted:
                    total_rows, gap_count, gap_locations = rows, gaps, locations
                    counted = True
        finally:
            self._progress_span = (0.0, 1.0)
        if not counted:
            return 0, 0, 0, [], 0.0, 0.0
        return total_rows, total_nan, gap_count, gap_locations, t0, t1

    def _emit_progress(self, fraction: float) -> None:
        low, high = self._progress_span
        self.progress.emit(int((low + fraction * (high - low)) * 100))

    def _build_channel_by_channel(
        self,
        loader: Any,
        channel_names: list[str],
        temp_dir: Path,
    ) -> tuple[int, int, int, list[float], float, float]:
        """Build legacy plugin channels while keeping compatibility with v1 loaders.

        Each channel is staged to disk as its chunks arrive; nothing accumulates a
        complete channel in memory.
        """
        staging_dir = temp_dir / _STAGING_DIR
        staging_dir.mkdir(parents=True, exist_ok=True)
        total_rows = 0
        total_nan = 0
        all_gap_locations: list[float] = []
        gap_count = 0
        t0, t1 = 0.0, 0.0
        time_axes: dict[tuple[int, str], Path] = {}
        try:
            for index, channel in enumerate(channel_names):
                if self._cancel_flag:
                    break
                time_stage = ChannelStage(staging_dir, f"{channel}__t", hash_content=True)
                value_stage = ChannelStage(staging_dir, f"{channel}__v", allow_float32=True)
                try:
                    for chunk_t, chunk_v in loader.read_chunks(channel):
                        time_stage.append(np.asarray(chunk_t, dtype=np.float64))
                        value_stage.append(np.asarray(chunk_v, dtype=np.float64))
                    if time_stage.count == 0:
                        continue
                    time_path = temp_dir / f"{channel}_t.npy"
                    identity = (time_stage.count, time_stage.content_digest or "")
                    earlier = time_axes.get(identity)
                    if earlier is None:
                        times = time_stage.materialize(time_path)
                        time_axes[identity] = time_path
                    else:
                        time_stage.discard()
                        _share_file(earlier, time_path)
                        times = np.load(time_path, mmap_mode="r", allow_pickle=False)
                    values = value_stage.materialize(temp_dir / f"{channel}_v.npy")
                finally:
                    time_stage.discard()
                    value_stage.discard()

                gap_mask = build_gap_mask(times)
                np.save(temp_dir / f"{channel}_gap.npy", gap_mask)
                PyramidBuilder(temp_dir, channel).save_levels(
                    times, values, gap_mask, include_base=False
                )
                if index == 0:
                    total_rows = int(len(times))
                    t0, t1 = float(times[0]), float(times[-1])
                    gap_count = int(np.count_nonzero(gap_mask))
                    all_gap_locations = _gap_locations(times, gap_mask)
                total_nan += count_nan(values)
                self.progress.emit(int(((index + 1) / len(channel_names)) * 100))
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
        return total_rows, total_nan, gap_count, all_gap_locations, t0, t1

    @staticmethod
    def _write_manifest(
        temp_dir: Path,
        channels: list[str],
        bounds: tuple[float, float],
        inspection: SourceInspection,
    ) -> None:
        """Persist cache metadata required to reopen without parsing the source."""
        payload = {
            "channels": channels,
            "bounds": list(bounds),
            "inspection": inspection.as_dict(),
            "array_sizes": {item.name: item.stat().st_size for item in temp_dir.glob("*.npy")},
            "array_fingerprints": {
                item.name: _array_fingerprint(item) for item in temp_dir.glob("*.npy")
            },
        }
        (temp_dir / _IMPORT_MANIFEST).write_text(json.dumps(payload), encoding="utf-8")
