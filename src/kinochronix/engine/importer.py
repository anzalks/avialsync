"""Asynchronous data source importer pipeline."""

import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal

from kinochronix.core.cache import CacheManager
from kinochronix.core.inspection import ImportReport, IntegrityFlags, SourceInspection
from kinochronix.core.pyramid import PyramidBuilder, build_gap_mask
from kinochronix.loaders.csv_loader import CSVLoader


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
            loader = self.loader_class()
            loader.open(self.path, self.config)

            cache_mgr = CacheManager(loader_version=3)
            temp_dir = cache_mgr.get_temp_cache_dir(self.path)

            channels = loader.channels()
            if not channels:
                raise ValueError("No channels found in source.")

            channel_names = [ch.name for ch in channels]
            num_channels = len(channel_names)

            # Accumulators for ImportReport
            total_rows = 0
            total_nan = 0
            all_gap_locations: list[float] = []
            gap_count = 0

            for i, ch_name in enumerate(channel_names):
                if self._cancel_flag:
                    break

                all_chunks = []
                for t_chunk, v_chunk in loader.read_chunks(ch_name):
                    if self._cancel_flag:
                        break
                    all_chunks.append((t_chunk, v_chunk))

                if self._cancel_flag:
                    break

                if all_chunks:
                    full_t = np.concatenate([c[0] for c in all_chunks])
                    full_v = np.concatenate([c[1] for c in all_chunks])

                    builder = PyramidBuilder(temp_dir, ch_name)
                    builder.build_and_save(full_t, full_v)

                    # Accumulate stats from first channel only (all channels share the same t)
                    if i == 0:
                        total_rows = int(len(full_t))
                        gap_mask = build_gap_mask(full_t)
                        gap_count = int(np.sum(gap_mask))
                        if gap_count:
                            all_gap_locations = full_t[gap_mask].tolist()
                    total_nan += int(np.sum(np.isnan(full_v)))

                prog = int(((i + 1) / num_channels) * 100)
                self.progress.emit(prog)

            if self._cancel_flag:
                import shutil

                shutil.rmtree(temp_dir, ignore_errors=True)
                return

            t0, t1 = 0.0, 0.0
            if channel_names:
                from kinochronix.core.pyramid import PyramidReader

                pr = PyramidReader(temp_dir, channel_names[0])
                t, _, _, _ = pr._load_level(1)
                if len(t) > 0:
                    t0, t1 = float(t[0]), float(t[-1])

            cache_mgr.commit_cache(self.path, temp_dir)
            final_dir = cache_mgr.get_cache_dir(self.path)

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

            self.finished.emit(str(self.path), str(final_dir), channel_names, (t0, t1), inspection)

        except Exception as e:
            traceback.print_exc()
            self.error.emit(str(e))
