"""CSV Time Series Loader."""

import datetime
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import polars as pl

from avialview.core.errors import (
    FileUnreadableError,
    MissingColumnError,
    NonMonotonicTimeError,
    SourceOpenError,
)
from avialview.core.source import ChannelInfo, TimeSeriesSource

#: A sample must contain at least this many rows before a rate is claimed.
_RATE_SAMPLE_MINIMUM = 8
#: Maximum relative deviation from the median interval that still counts as
#: regular sampling.  Above this, ``rate_hz`` stays None — irregular is a
#: real property of many sources, not a measurement failure.
_RATE_REGULARITY_TOLERANCE = 0.05
_UNIT_SECONDS = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9}


class CSVLoader(TimeSeriesSource):
    """Loads CSV files in chunks using polars."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._schema_channels: list[ChannelInfo] = []

    @classmethod
    def can_open(cls, path: Path) -> float:
        suffix = path.suffix.lower()
        if suffix in [".csv", ".txt", ".tsv"]:
            # Could peek at the file, but for now just check extension
            return 0.8
        return 0.0

    @classmethod
    def needs_import_wizard(cls) -> bool:
        return True

    def open(self, path: Path, config: dict[str, Any]) -> None:
        self._path = path
        self._config = config

        # Read a small sample to deduce channels and bounds
        separator = config.get("separator", ",")
        time_col = config.get("time_col", "time")
        euro_decimal = config.get("euro_decimal", False)

        has_headers = config.get("has_headers", True)

        try:
            sample = pl.read_csv(
                path,
                separator=separator,
                n_rows=100,
                has_header=has_headers,
                infer_schema_length=100,
                schema_overrides={time_col: self._timestamp_dtype()},
                decimal_comma=euro_decimal or (separator == ";"),
            )
        except Exception as e:
            raise FileUnreadableError(f"Failed to parse CSV: {path}") from e

        if time_col not in sample.columns:
            raise MissingColumnError(time_col, [str(name) for name in sample.columns])

        rate_hz = self._estimate_rate(sample, time_col)
        self._schema_channels = []
        for col in sample.columns:
            if col == time_col:
                continue
            dt = sample[col].dtype
            self._schema_channels.append(
                ChannelInfo(name=col, unit="", dtype=str(dt), rate_hz=rate_hz)
            )

    def channels(self) -> list[ChannelInfo]:
        return self._schema_channels

    def _estimate_rate(self, sample: "pl.DataFrame", time_col: str) -> float | None:
        """Return the sampling rate when the sample proves it is regular.

        ``ChannelInfo.rate_hz`` documents ``None`` as *irregular*, and reporting
        None for a file that is plainly 1 kHz makes gap detection fall back to
        the 10x-median heuristic unnecessarily (V-19).

        Only a numeric time column is measured here: a datetime column still
        needs the accepted wizard configuration to become seconds, and guessing
        at open() time could label a source with a rate it does not have. If the
        intervals in the sample are not tight, None is returned — that is the
        honest answer, not a fallback.
        """
        if not sample[time_col].dtype.is_numeric():
            return None
        times = sample[time_col].to_numpy().astype(np.float64)
        if len(times) < _RATE_SAMPLE_MINIMUM:
            return None
        intervals = np.diff(times)
        intervals = intervals[np.isfinite(intervals) & (intervals > 0)]
        if len(intervals) < _RATE_SAMPLE_MINIMUM - 1:
            return None
        median = float(np.median(intervals))
        if median <= 0:
            return None
        # Irregular sampling is a real property of many sources; only claim a
        # rate when the sample is tight enough that the claim is true.
        spread = float(np.max(np.abs(intervals - median))) / median
        if spread > _RATE_REGULARITY_TOLERANCE:
            return None
        # Reuse the same unit resolution the ingest path uses, so a rate is
        # never reported in different units from the samples it describes.
        unit = self._epoch_unit_from_format(str(self._config.get("time_format", "")))
        seconds = median * _UNIT_SECONDS.get(unit, 1.0)
        return float(1.0 / seconds) if seconds > 0 else None

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
        return str(self._config.get("time_unit", "s"))

    def _timestamp_dtype(self) -> pl.DataType:
        """Return the explicit parser dtype required by the chosen time format."""
        category = self._classify_format(self._config.get("time_format", "numeric"))
        # polars exposes these as DataType subclasses; instantiate so the
        # declared return type is the value actually handed to schema_overrides.
        return pl.Float64() if category == "numeric" else pl.Utf8()

    def _timezone_name(self) -> str:
        """Resolve the wizard's explicit timezone to an IANA-compatible name."""
        configured = str(self._config.get("timezone", "UTC"))
        if configured != "local":
            return configured
        local_zone = datetime.datetime.now().astimezone().tzinfo
        name = getattr(local_zone, "key", None) or (local_zone.tzname(None) if local_zone else None)
        if not name:
            raise SourceOpenError("Could not resolve the selected local timezone.")
        return name

    def _normalize_time(self, t_series: pl.Series) -> np.ndarray:
        time_format = self._config.get("time_format", "numeric")
        category = self._classify_format(time_format)

        if category == "datetime":
            strp_fmt = None
            if time_format not in ("iso8601", "datetime", ""):
                strp_fmt = time_format

            timezone = self._timezone_name()
            try:
                if strp_fmt:
                    dt_series = t_series.str.to_datetime(
                        format=strp_fmt,
                        time_unit="ns",
                        time_zone=timezone,
                        ambiguous="raise",
                    )
                else:
                    dt_series = t_series.str.to_datetime(
                        time_unit="ns",
                        time_zone=timezone,
                        ambiguous="raise",
                    )
            except Exception as error:
                raise SourceOpenError(
                    f"Could not parse timestamps using timezone '{timezone}'."
                ) from error

            return dt_series.cast(pl.Int64).cast(pl.Float64).to_numpy() / 1e9

        elif category == "time_of_day":
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

            try:
                zone = ZoneInfo(self._timezone_name())
            except ZoneInfoNotFoundError as error:
                raise SourceOpenError(
                    "The selected timezone is unavailable on this system."
                ) from error
            anchor_epoch = datetime.datetime(
                anchor_date.year,
                anchor_date.month,
                anchor_date.day,
                tzinfo=zone,
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

    def _read_batches(self) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
        """Yield every channel from one parser pass with strict chunk boundaries."""
        if self._path is None:
            raise SourceOpenError("CSV source has not been opened.")
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

        has_headers = self._config.get("has_headers", True)

        channel_names = [channel.name for channel in self._schema_channels]
        reader = pl.scan_csv(
            self._path,
            separator=separator,
            has_header=has_headers,
            schema_overrides={time_col: self._timestamp_dtype()},
            decimal_comma=euro_decimal or (separator == ";"),
        ).collect_batches(chunk_size=int(self._config.get("batch_size", 50_000)))

        row_offset = 0
        pending_time: float | None = None
        pending_values: dict[str, float] | None = None
        for batch in reader:
            t = self._normalize_time(batch[time_col])
            values = {name: batch[name].cast(pl.Float64).to_numpy() for name in channel_names}
            if sentinel is not None:
                for value_array in values.values():
                    value_array[value_array == sentinel] = np.nan

            if pending_time is not None and pending_values is not None:
                t = np.concatenate((np.asarray([pending_time], dtype=np.float64), t))
                carried = pending_values
                values = {
                    name: np.concatenate(
                        (np.asarray([carried[name]], dtype=np.float64), value_array)
                    )
                    for name, value_array in values.items()
                }

            if len(t) > 1:
                dt = np.diff(t)
                if np.any(dt < 0):
                    index = int(np.flatnonzero(dt < 0)[0])
                    raise NonMonotonicTimeError(
                        f"Non-monotonic time detected at row {row_offset + index + 1}",
                        row=row_offset + index + 1,
                    )
                keep = np.ones(len(t), dtype=bool)
                keep[:-1] = dt > 0
                t = t[keep]
                values = {name: value_array[keep] for name, value_array in values.items()}

            if len(t):
                pending_time = float(t[-1])
                pending_values = {
                    name: float(value_array[-1]) for name, value_array in values.items()
                }
                if len(t) > 1:
                    yield {name: (t[:-1], value_array[:-1]) for name, value_array in values.items()}
            row_offset += len(batch)

        if pending_time is not None and pending_values is not None:
            yield {
                name: (
                    np.asarray([pending_time], dtype=np.float64),
                    np.asarray([value], dtype=np.float64),
                )
                for name, value in pending_values.items()
            }

    def read_all_chunks(self) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
        """Yield aligned channel chunks from a single CSV parser pass."""
        yield from self._read_batches()

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield one channel while retaining the same boundary guarantees as bulk ingest."""
        if ch not in {channel.name for channel in self._schema_channels}:
            raise MissingColumnError(ch, [channel.name for channel in self._schema_channels])
        for chunk in self._read_batches():
            yield chunk[ch]
