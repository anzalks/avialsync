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
        t_first_last = lazy_df.select(
            [pl.col(time_col).first().alias("first"), pl.col(time_col).last().alias("last")]
        ).collect()

        # We need to construct a 2-element series to normalize correctly (handling rollovers)
        t_series = pl.Series([t_first_last["first"][0], t_first_last["last"][0]])
        t_norm = self._normalize_time(t_series)

        self._time_bounds = (float(t_norm[0]), float(t_norm[-1]))

    def channels(self) -> list[ChannelInfo]:
        return self._schema_channels

    def time_bounds(self) -> tuple[float, float]:
        return self._time_bounds

    def _normalize_time(self, t_series: pl.Series) -> np.ndarray:
        time_format = self._config.get("time_format", "numeric")

        if time_format == "iso8601" or time_format == "datetime":
            # parse to UTC datetime then to unix epoch seconds
            # if tz naive, assume UTC or use config
            # strptime format can be inferred or provided
            # A simple cast to Datetime usually works if it's standard ISO8601
            try:
                dt_series = t_series.str.to_datetime(time_unit="ns", time_zone="UTC")
            except Exception:
                # Fallback without timezone if it's tz naive
                dt_series = t_series.str.to_datetime(time_unit="ns")

            # cast to Float64 in seconds. Polars datetime in ns to float seconds:
            return dt_series.cast(pl.Int64).cast(pl.Float64).to_numpy() / 1e9

        elif time_format == "time_of_day":
            import datetime

            anchor_str = self._config.get("anchor_date", "1970-01-01")
            anchor_date = datetime.datetime.strptime(anchor_str, "%Y-%m-%d").date()

            # parse time string to time object, then to datetime, then to epoch
            # simpler: parse to time, convert to seconds since midnight
            time_series = t_series.str.to_time()
            # to_time gives pl.Time. We can extract microseconds and convert to seconds
            # Alternatively, cast pl.Time to Int64 gives nanoseconds since midnight.
            ns_since_midnight = time_series.cast(pl.Int64).cast(pl.Float64).to_numpy()
            sec_since_midnight = ns_since_midnight / 1e9

            # Add anchor date timestamp
            anchor_epoch = datetime.datetime(
                anchor_date.year, anchor_date.month, anchor_date.day, tzinfo=datetime.UTC
            ).timestamp()
            t_arr = sec_since_midnight + anchor_epoch

            # handle rollover if it crosses midnight
            if len(t_arr) > 1:
                dt = np.diff(t_arr)
                # if it drops by more than 12 hours, assume rollover
                rollovers = (dt < -43200).astype(int)
                days_added = np.concatenate([[0], np.cumsum(rollovers)])
                t_arr += days_added * 86400.0

            return t_arr

        else:
            # numeric
            t_arr = t_series.cast(pl.Float64).to_numpy()
            unit = self._config.get("time_unit", "s")
            if unit == "ms":
                t_arr = t_arr / 1e3
            elif unit == "us":
                t_arr = t_arr / 1e6
            elif unit == "ns":
                t_arr = t_arr / 1e9
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
                        row=row_offset + idx + 1,
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
