"""Asynchronous data source importer pipeline."""

import traceback
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal

from kinochronix.core.cache import CacheManager
from kinochronix.core.pyramid import PyramidBuilder
from kinochronix.loaders.csv_loader import CSVLoader


class ImportWorker(QObject):
    """
    Background worker for parsing and building pyramids from time-series sources.
    """

    progress = Signal(int)  # 0-100
    finished = Signal(str, str, list, tuple)  # original_path, cache_dir, channel_names, (t0, t1)
    error = Signal(str)

    def __init__(self, path: Path, config: dict[str, Any]) -> None:
        super().__init__()
        self.path = path
        self.config = config
        self._cancel_flag = False

    def cancel(self) -> None:
        self._cancel_flag = True

    def run(self) -> None:
        try:
            loader = CSVLoader()
            loader.open(self.path, self.config)

            cache_mgr = CacheManager(loader_version=1)
            temp_dir = cache_mgr.get_temp_cache_dir(self.path)

            channels = loader.channels()
            if not channels:
                raise ValueError("No channels found in source.")

            channel_names = [ch.name for ch in channels]
            num_channels = len(channel_names)

            for i, ch_name in enumerate(channel_names):
                if self._cancel_flag:
                    break

                # We could try to stream directly into PyramidBuilder, but
                # for now MVP builds the whole array in memory.
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

                # Report progress
                prog = int(((i + 1) / num_channels) * 100)
                self.progress.emit(prog)

            if self._cancel_flag:
                # Cleanup temp directory
                import shutil

                shutil.rmtree(temp_dir, ignore_errors=True)
                # Don't emit finished if cancelled
                return

            # Emit bounds of the first channel as the source bounds
            t0, t1 = 0.0, 0.0
            if channel_names:
                from kinochronix.core.pyramid import PyramidReader

                pr = PyramidReader(temp_dir, channel_names[0])
                t, _, _, _ = pr._load_level(1)
                if len(t) > 0:
                    t0, t1 = float(t[0]), float(t[-1])

            cache_mgr.commit_cache(self.path, temp_dir)
            final_dir = cache_mgr.get_cache_dir(self.path)

            self.finished.emit(str(self.path), str(final_dir), channel_names, (t0, t1))

        except Exception as e:
            traceback.print_exc()
            self.error.emit(str(e))
