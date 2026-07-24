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
        euro_decimal = config.get("euro_decimal", False)

        try:
            sample = pl.read_csv(
                path,
                separator=separator,
                n_rows=100,
                infer_schema_length=100,
                decimal_comma=euro_decimal or (separator == ";"),
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
        lazy_df = pl.scan_csv(
            path, separator=separator, decimal_comma=euro_decimal or (separator == ";")
        )
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

    def _classify_format(self, fmt: str) -> str:
        """Map wizard format strings to internal categories."""
        if not fmt or fmt == "numeric":
            return "numeric"
        if fmt.startswith("epoch_"):
            return "numeric"
        if fmt in ("iso8601", "datetime"):
            return "datetime"
        if fmt == "time_of_day":
            return "time_of_day"
        # strftime patterns containing date components → datetime
        if any(d in fmt for d in ("%Y", "%m", "%d")):
            return "datetime"
        # time-only strftime patterns
        if any(d in fmt for d in ("%H", "%M", "%S")):
            return "time_of_day"
        return "numeric"

    def _epoch_unit_from_format(self, fmt: str) -> str:
        """Extract epoch unit from wizard format like 'epoch_ms'."""
        if fmt == "epoch_ms":
            return "ms"
        if fmt == "epoch_us":
            return "us"
        if fmt == "epoch_ns":
            return "ns"
        return self._config.get("time_unit", "s")

    def _normalize_time(self, t_series: pl.Series) -> np.ndarray:
        time_format = self._config.get("time_format", "numeric")
        category = self._classify_format(time_format)

        if category == "datetime":
            strp_fmt = None
            if time_format not in ("iso8601", "datetime", ""):
                strp_fmt = time_format

            try:
                if strp_fmt:
                    dt_series = t_series.str.to_datetime(format=strp_fmt, time_unit="ns")
                else:
                    dt_series = t_series.str.to_datetime(time_unit="ns", time_zone="UTC")
            except Exception:
                try:
                    if strp_fmt:
                        dt_series = t_series.str.to_datetime(format=strp_fmt, time_unit="ns")
                    else:
                        dt_series = t_series.str.to_datetime(time_unit="ns")
                except Exception:
                    dt_series = t_series.str.to_datetime(time_unit="ns")

            return dt_series.cast(pl.Int64).cast(pl.Float64).to_numpy() / 1e9

        elif category == "time_of_day":
            import datetime

            anchor_str = self._config.get("anchor_date", "1970-01-01")
            anchor_date = datetime.datetime.strptime(anchor_str, "%Y-%m-%d").date()

            strp_fmt = None
            if time_format not in ("time_of_day", ""):
                strp_fmt = time_format

            if strp_fmt:
                time_series = t_series.str.to_time(format=strp_fmt)
            else:
                time_series = t_series.str.to_time()

            ns_since_midnight = time_series.cast(pl.Int64).cast(pl.Float64).to_numpy()
            sec_since_midnight = ns_since_midnight / 1e9

            anchor_epoch = datetime.datetime(
                anchor_date.year, anchor_date.month, anchor_date.day, tzinfo=datetime.UTC
            ).timestamp()
            t_arr = sec_since_midnight + anchor_epoch

            if len(t_arr) > 1:
                dt = np.diff(t_arr)
                rollovers = (dt < -43200).astype(int)
                days_added = np.concatenate([[0], np.cumsum(rollovers)])
                t_arr += days_added * 86400.0

            return t_arr

        else:
            # numeric / epoch
            t_arr = t_series.cast(pl.Float64).to_numpy()
            unit = self._epoch_unit_from_format(time_format)
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
        sentinel_raw = self._config.get("sentinel", None)
        euro_decimal = self._config.get("euro_decimal", False)

        sentinel: float | None = None
        if sentinel_raw is not None and sentinel_raw != "":
            try:
                sentinel = float(sentinel_raw)
            except (ValueError, TypeError):
                sentinel = None

        # Read in batches
        reader = pl.read_csv_batched(
            self._path,
            separator=separator,
            batch_size=50000,
            decimal_comma=euro_decimal or (separator == ";"),
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
