"""Tracking Data (DLC/LightningPose) Loader."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from kinochronix.core.errors import NonMonotonicTimeError
from kinochronix.core.pyramid import PyramidReader
from kinochronix.core.source import ChannelInfo, ChannelSlice, TimeSeriesSource


class TrackingLoader(TimeSeriesSource):
    """Loads DeepLabCut and LightningPose multi-index CSV files."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._schema_channels: list[ChannelInfo] = []
        self._time_bounds: tuple[float, float] = (0.0, 0.0)
        self._cache_dir: Path | None = None
        self._flat_headers: list[str] = []

    def is_frame_indexed(self) -> bool:
        return True

    @classmethod
    def can_open(cls, path: Path) -> float:
        suffix = path.suffix.lower()
        if suffix not in [".csv"]:
            return 0.0

        try:
            with open(path, encoding="utf-8") as f:
                line1 = f.readline().strip()
                line2 = f.readline().strip()
                # Check for DLC/LP multi-index signatures
                if line1.startswith("scorer") and line2.startswith("bodyparts"):
                    return 1.0
        except Exception:
            pass

        return 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        self._path = path
        self._config = config
        self._cache_dir = path.with_name(path.name + ".kcache")

        # Read the first 3 rows to build flattened headers
        with open(path, encoding="utf-8") as f:
            scorers = f.readline().strip().split(",")
            bodyparts = f.readline().strip().split(",")
            coords = f.readline().strip().split(",")

        # The first column is usually the frame index (scorer="")
        self._flat_headers = []
        for s, b, c in zip(scorers, bodyparts, coords, strict=False):
            if s == "scorer" or b == "bodyparts":
                self._flat_headers.append("frame_index")
            else:
                self._flat_headers.append(f"{b}_{c}")

        self._schema_channels = []
        for col in self._flat_headers:
            if col == "frame_index":
                continue
            # Treat all as float64
            self._schema_channels.append(
                ChannelInfo(name=col, unit="px", dtype="Float64", rate_hz=None)
            )

        # Get true time bounds from the whole file using lazy execution
        # We skip the 3 header rows and name the columns directly
        fps = float(config.get("fps", 30.0))

        lazy_df = pl.scan_csv(path, skip_rows=3, has_header=False, new_columns=self._flat_headers)

        t_first_last = lazy_df.select(
            [
                pl.col("frame_index").first().alias("first"),
                pl.col("frame_index").last().alias("last"),
            ]
        ).collect()

        first_frame = float(t_first_last["first"][0])
        last_frame = float(t_first_last["last"][0])

        self._time_bounds = (first_frame / fps, last_frame / fps)

    def channels(self) -> list[ChannelInfo]:
        return self._schema_channels

    def time_bounds(self) -> tuple[float, float]:
        return self._time_bounds

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        if self._path is None:
            raise RuntimeError("Source not opened")

        fps = float(self._config.get("fps", 30.0))

        # Read in batches skipping the 3 header rows
        reader = pl.read_csv_batched(
            self._path,
            skip_rows=3,
            has_header=False,
            new_columns=self._flat_headers,
            batch_size=50000,
        )

        row_offset = 0
        while True:
            batches = reader.next_batches(1)
            if not batches:
                break
            batch = batches[0]

            t = batch["frame_index"].cast(pl.Float64).to_numpy() / fps
            v = batch[ch].cast(pl.Float64).to_numpy()

            # Check monotonicity
            if len(t) > 1:
                dt = np.diff(t)
                if np.any(dt < 0):
                    idx = int(np.argmin(dt))
                    raise NonMonotonicTimeError(
                        f"Non-monotonic time detected at row {row_offset + idx + 1 + 3}",
                        row=row_offset + idx + 1 + 3,
                    )

            # Remove duplicates (keep last)
            if len(t) > 1:
                dt = np.diff(t)
                mask = np.ones(len(t), dtype=bool)
                mask[:-1] = dt > 0
                t = t[mask]
                v = v[mask]

            yield t, v
            row_offset += len(batch)

    def read(self, ch: str, t0: float, t1: float, max_points: int) -> ChannelSlice:
        if self._cache_dir is None:
            return np.array([]), np.array([]), np.array([]), np.array([], dtype=bool)

        reader = PyramidReader(self._cache_dir, ch)
        return reader.query(t0, t1, max_points)

    def config_widget(self) -> Any | None:
        return None
