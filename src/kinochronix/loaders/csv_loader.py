"""CSV Time Series Loader."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from kinochronix.core.errors import NonMonotonicTimeError
from kinochronix.core.pyramid import PyramidReader
from kinochronix.core.source import ChannelInfo, ChannelSlice, TimeSeriesSource


class CSVLoader(TimeSeriesSource):
    """Loads CSV files in chunks using polars."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._schema_channels: list[ChannelInfo] = []
        self._time_bounds: tuple[float, float] = (0.0, 0.0)
        self._cache_dir: Path | None = None

    @classmethod
    def can_open(cls, path: Path) -> float:
        suffix = path.suffix.lower()
        if suffix in [".csv", ".txt", ".tsv"]:
            # Could peek at the file, but for now just check extension
            return 0.8
        return 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        self._path = path
        self._config = config
        self._cache_dir = path.with_name(path.name + ".kcache")

        # Read a small sample to deduce channels and bounds
        separator = config.get("separator", ",")
        time_col = config.get("time_col", "time")

        try:
            sample = pl.read_csv(
                path,
                separator=separator,
                n_rows=100,
                infer_schema_length=100,
                decimal_comma=(separator == ";"),
            )
        except Exception as e:
            raise ValueError(f"Failed to parse CSV: {path}") from e

        if time_col not in sample.columns:
            raise ValueError(f"Time column '{time_col}' not found in {path}")

        self._schema_channels = []
        for col in sample.columns:
            if col == time_col:
                continue
            dt = sample[col].dtype
            self._schema_channels.append(
                ChannelInfo(name=col, unit="", dtype=str(dt), rate_hz=None)
            )

        # Get true time bounds from the whole file using lazy execution if possible
        # For robustness in tests, we just use a scan
        lazy_df = pl.scan_csv(path, separator=separator, decimal_comma=(separator == ";"))
        t_min_max = lazy_df.select(
            [pl.col(time_col).min().alias("min"), pl.col(time_col).max().alias("max")]
        ).collect()

        self._time_bounds = (float(t_min_max["min"][0]), float(t_min_max["max"][0]))

    def channels(self) -> list[ChannelInfo]:
        return self._schema_channels

    def time_bounds(self) -> tuple[float, float]:
        return self._time_bounds

    def _normalize_time(self, t_series: pl.Series) -> np.ndarray:
        t_arr = t_series.cast(pl.Float64).to_numpy()
        unit = self._config.get("time_unit", "s")
        if unit == "ms":
            t_arr /= 1e3
        elif unit == "us":
            t_arr /= 1e6
        elif unit == "ns":
            t_arr /= 1e9
        return t_arr

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        if self._path is None:
            raise RuntimeError("Source not opened")

        separator = self._config.get("separator", ",")
        time_col = self._config.get("time_col", "time")
        sentinel = self._config.get("sentinel", None)

        # Read in batches
        reader = pl.read_csv_batched(
            self._path, separator=separator, batch_size=50000, decimal_comma=(separator == ";")
        )

        row_offset = 0
        while True:
            batches = reader.next_batches(1)
            if not batches:
                break
            batch = batches[0]

            t = self._normalize_time(batch[time_col])
            v = batch[ch].cast(pl.Float64).to_numpy()

            if sentinel is not None:
                v[v == sentinel] = np.nan

            # Check monotonicity
            if len(t) > 1:
                dt = np.diff(t)
                if np.any(dt < 0):
                    idx = int(np.argmin(dt))
                    raise NonMonotonicTimeError(
                        f"Non-monotonic time detected at row {row_offset + idx + 1}",
                        row=row_offset + idx + 1
                    )

            # Remove duplicates (keep last)
            if len(t) > 1:
                # dt == 0 means duplicate. We keep the last one by masking out where dt==0
                # If dt == 0, then t[i+1] == t[i]. We want to drop t[i].
                # Keep where dt > 0, plus the last element.
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
