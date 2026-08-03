"""Asynchronous data source importer pipeline."""

import json
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
from avialsync.core.pyramid import ChannelStage, PyramidBuilder, build_gap_mask, count_nan
from avialsync.loaders.csv_loader import CSVLoader

_IMPORT_CACHE_VERSION = 4
_IMPORT_MANIFEST = "import.json"
_STAGING_DIR = "_stage"

#: Gap *locations* are display evidence, so they are capped; ``gap_count`` in the
#: import report always stays exact.  A pathological recording can otherwise put
#: millions of floats into the session file and the report dialog.
MAX_GAP_LOCATIONS = 10_000


def _gap_locations(times: np.ndarray, gap_mask: np.ndarray) -> list[float]:
    """Return up to :data:`MAX_GAP_LOCATIONS` gap timestamps as bounded evidence."""
    indices = np.flatnonzero(gap_mask)
    if len(indices) > MAX_GAP_LOCATIONS:
        indices = indices[:MAX_GAP_LOCATIONS]
    return [float(value) for value in times[indices]]


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

    def cancel(self) -> None:
        self._cancel_flag = True

    def run(self) -> None:
        try:
            cache_mgr = self._cache_manager()
            cached = self._cached_result(cache_mgr)
            if cached is not None:
                cache_dir, channels, bounds, inspection = cached
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
            bulk_reader = getattr(loader, "read_all_chunks", None)
            if callable(bulk_reader):
                result = self._build_bulk_channels(
                    bulk_reader(),
                    channel_names,
                    temp_dir,
                )
            else:
                result = self._build_channel_by_channel(loader, channel_names, temp_dir)
            total_rows, total_nan, gap_count, all_gap_locations, t0, t1 = result

            if self._cancel_flag:
                import shutil

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

            inspection = SourceInspection(
                path=str(self.path),
                loader_id=loader_id,
                import_config=dict(self.config),
                import_report=report,
                integrity_flags=flags,
                fps_binding=fps_binding,
            )

            self._write_manifest(temp_dir, channel_names, (t0, t1), inspection)
            cache_mgr.commit_cache(self.path, temp_dir)
            final_dir = cache_mgr.get_cache_dir(self.path)

            self.finished.emit(str(self.path), str(final_dir), channel_names, (t0, t1), inspection)

        except Exception as e:
            traceback.print_exc()
            self.error.emit(str(e))

    def _cache_manager(self) -> CacheManager:
        """Return the sidecar manager scoped to loader identity and accepted config."""
        loader_name = f"{self.loader_class.__module__}.{self.loader_class.__qualname__}"
        return CacheManager(
            loader_version=_IMPORT_CACHE_VERSION,
            cache_config={"loader": loader_name, "config": self.config},
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
        if not channels or bounds[1] < bounds[0]:
            return None
        return cache_dir, channels, bounds, inspection

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
        value_stages = {channel: ChannelStage(staging_dir, channel) for channel in channel_names}
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
        """Materialise staged samples into the sidecar; scopes every mmap locally."""
        shared_t_path = staging_dir / "shared_t.npy"
        shared_t = time_stage.materialize(shared_t_path)
        gap_mask = build_gap_mask(shared_t)
        gap_path = staging_dir / "shared_gap.npy"
        np.save(gap_path, gap_mask)

        total_nan = 0
        for index, channel in enumerate(channel_names):
            values = value_stages[channel].materialize(temp_dir / f"{channel}_v.npy")
            shutil.copyfile(shared_t_path, temp_dir / f"{channel}_t.npy")
            shutil.copyfile(gap_path, temp_dir / f"{channel}_gap.npy")
            PyramidBuilder(temp_dir, channel).save_levels(
                shared_t, values, gap_mask, include_base=False
            )
            total_nan += count_nan(values)
            del values
            self.progress.emit(int(((index + 1) / len(channel_names)) * 100))

        return (
            int(len(shared_t)),
            total_nan,
            int(np.count_nonzero(gap_mask)),
            _gap_locations(shared_t, gap_mask),
            float(shared_t[0]),
            float(shared_t[-1]),
        )

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
        try:
            for index, channel in enumerate(channel_names):
                if self._cancel_flag:
                    break
                time_stage = ChannelStage(staging_dir, f"{channel}__t")
                value_stage = ChannelStage(staging_dir, f"{channel}__v")
                try:
                    for chunk_t, chunk_v in loader.read_chunks(channel):
                        time_stage.append(np.asarray(chunk_t, dtype=np.float64))
                        value_stage.append(np.asarray(chunk_v, dtype=np.float64))
                    if time_stage.count == 0:
                        continue
                    times = time_stage.materialize(temp_dir / f"{channel}_t.npy")
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
        }
        (temp_dir / _IMPORT_MANIFEST).write_text(json.dumps(payload), encoding="utf-8")
