"""Tracking Data (DLC/LightningPose) Loader."""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from avialview.core.errors import NonMonotonicTimeError
from avialview.core.source import ChannelInfo, TimeSeriesSource

logger = logging.getLogger(__name__)


class TrackingLoader(TimeSeriesSource):
    """Loads DeepLabCut and LightningPose multi-index CSV files."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._schema_channels: list[ChannelInfo] = []
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
        except (OSError, UnicodeError):
            logger.debug("Tracking loader could not inspect %s", path, exc_info=True)

        return 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        self._path = path
        self._config = config

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

    def channels(self) -> list[ChannelInfo]:
        return self._schema_channels

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield one tracking channel while preserving the single-pass parser API."""
        for chunk in self.read_all_chunks():
            yield chunk[ch]

    def read_all_chunks(self) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
        """Yield every tracking channel from one CSV parser pass.

        The importer consumes this bulk API once, rather than asking the loader
        to reparse the tracking file for every coordinate channel.
        """
        if self._path is None:
            raise RuntimeError("Source not opened")

        fps = float(self._config.get("fps", 30.0))
        channel_names = [channel.name for channel in self._schema_channels]

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
            values = {
                channel: batch[channel].cast(pl.Float64).to_numpy() for channel in channel_names
            }
            # Check monotonicity
            if len(t) > 1:
                dt = np.diff(t)
                if np.any(dt < 0):
                    idx = int(np.flatnonzero(dt < 0)[0])
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
                values = {channel: value[mask] for channel, value in values.items()}

            if len(t):
                yield {channel: (t, value) for channel, value in values.items()}
            row_offset += len(batch)
