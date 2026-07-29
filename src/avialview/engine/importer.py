"""Asynchronous data source importer pipeline."""

import json
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal

from avialview.core.cache import CacheManager
from avialview.core.inspection import ImportReport, IntegrityFlags, SourceInspection
from avialview.core.pyramid import PyramidBuilder, build_gap_mask
from avialview.loaders.csv_loader import CSVLoader

_IMPORT_CACHE_VERSION = 4
_IMPORT_MANIFEST = "import.json"


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
                raise ValueError("No channels found in source.")

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
        """Build aligned channels from one loader pass, retaining shared timestamps once."""
        time_chunks: list[np.ndarray] = []
        value_chunks: dict[str, list[np.ndarray]] = {channel: [] for channel in channel_names}
        for chunk in chunks:
            if self._cancel_flag:
                break
            if set(chunk) != set(channel_names):
                raise ValueError("Bulk loader did not return every declared channel.")
            reference_times: np.ndarray | None = None
            for channel in channel_names:
                times, values = chunk[channel]
                if reference_times is None:
                    reference_times = np.asarray(times, dtype=np.float64)
                elif not np.array_equal(reference_times, times):
                    raise ValueError("Bulk loader channel chunks do not share timestamps.")
                values_array = np.asarray(values, dtype=np.float64)
                if len(values_array) != len(reference_times):
                    raise ValueError("Bulk loader returned mismatched time/value chunk lengths.")
                value_chunks[channel].append(values_array)
            if reference_times is not None and len(reference_times):
                time_chunks.append(reference_times)

        if self._cancel_flag or not time_chunks:
            return 0, 0, 0, [], 0.0, 0.0
        full_t = np.concatenate(time_chunks)
        gap_mask = build_gap_mask(full_t)
        total_nan = 0
        for index, channel in enumerate(channel_names):
            full_v = np.concatenate(value_chunks[channel])
            PyramidBuilder(temp_dir, channel).build_and_save(full_t, full_v)
            total_nan += int(np.sum(np.isnan(full_v)))
            self.progress.emit(int(((index + 1) / len(channel_names)) * 100))
        return (
            int(len(full_t)),
            total_nan,
            int(np.sum(gap_mask)),
            full_t[gap_mask].tolist(),
            float(full_t[0]),
            float(full_t[-1]),
        )

    def _build_channel_by_channel(
        self,
        loader: Any,
        channel_names: list[str],
        temp_dir: Path,
    ) -> tuple[int, int, int, list[float], float, float]:
        """Build legacy plugin channels while keeping compatibility with v1 loaders."""
        total_rows = 0
        total_nan = 0
        all_gap_locations: list[float] = []
        gap_count = 0
        t0, t1 = 0.0, 0.0
        for index, channel in enumerate(channel_names):
            if self._cancel_flag:
                break
            chunks = list(loader.read_chunks(channel))
            if not chunks:
                continue
            full_t = np.concatenate([chunk[0] for chunk in chunks])
            full_v = np.concatenate([chunk[1] for chunk in chunks])
            PyramidBuilder(temp_dir, channel).build_and_save(full_t, full_v)
            if index == 0:
                total_rows = int(len(full_t))
                t0, t1 = float(full_t[0]), float(full_t[-1])
                gap_mask = build_gap_mask(full_t)
                gap_count = int(np.sum(gap_mask))
                all_gap_locations = full_t[gap_mask].tolist()
            total_nan += int(np.sum(np.isnan(full_v)))
            self.progress.emit(int(((index + 1) / len(channel_names)) * 100))
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
