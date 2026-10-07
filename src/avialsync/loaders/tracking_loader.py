"""Tracking Data (DLC/LightningPose) Loader."""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from avialsync.core.errors import MissingColumnError, NonMonotonicTimeError, SourceOpenError
from avialsync.core.pose import PoseSchema
from avialsync.core.pose_header import PoseHeader, read_pose_header
from avialsync.core.source import ChannelInfo, TimeSeriesSource

logger = logging.getLogger(__name__)


class TrackingLoader(TimeSeriesSource):
    """Loads DeepLabCut and LightningPose multi-index CSV files."""

    @classmethod
    def display_name(cls) -> str:
        return "Tracking Data (2D/3D)"

    @classmethod
    def pose_roles(cls) -> tuple[str, ...]:
        """DLC and LightningPose files can carry 2D or 3D coordinates."""
        return ("overlay2d", "pose3d")

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._schema_channels: list[ChannelInfo] = []
        self._flat_headers: list[str] = []
        self._header: PoseHeader | None = None
        self._pose: PoseSchema | None = None

    def is_frame_indexed(self) -> bool:
        return True

    @classmethod
    def can_open(cls, path: Path) -> float:
        if path.suffix.lower() != ".csv":
            return 0.0
        # Both header shapes -- single-animal (scorer/bodyparts/coords) and
        # multi-animal (with `individuals` between the first two) -- are this
        # loader's, and telling them apart is the header parser's job.
        return 1.0 if read_pose_header(path) is not None else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        self._path = path
        self._config = config

        header = read_pose_header(path)
        if header is None:
            raise SourceOpenError(
                f"{path.name} has no DeepLabCut or LightningPose header block; "
                "its first rows are not scorer/[individuals/]bodyparts/coords."
            )
        self._header = header
        # Column zero is the frame index, and in a multi-animal file a point is
        # named for its individual as well as its body part -- see
        # `core.pose_header`.
        self._flat_headers = header.flat_names()

        self._pose = header.pose_schema(frame_indexed=True)

        # ``coords`` narrows ingest to the listed coordinate suffixes, and is
        # honoured when a caller passes it. Nobody has to: the schema already
        # declares which columns the format *derived* from the coordinates, and
        # those are dropped by default. The ensemble smoother writes eleven
        # columns per body part -- ``x_ens_median``, ``x_ens_var``, ``zscore``,
        # ``nll``, ``x_posterior_var`` and the rest -- and building a decimation
        # pyramid for every one of them multiplied import work several-fold for
        # data nothing reads. Only the AOL session loader ever remembered to
        # pass the key, so a drag-and-dropped Lightning Pose file paid it in
        # full (D-140).
        wanted: list[str] = list(config.get("coords") or [])
        suffixes = tuple(f"_{coord}" for coord in wanted) if wanted else None
        derived = tuple(f"_{coord}" for coord in self._pose.derived)

        rate_hz = float(config.get("fps", 0.0)) or None
        self._schema_channels = []
        # Only columns the header actually names: a ragged trailing column has a
        # placeholder name that keeps the reader's column list distinct and is
        # not a coordinate anyone can plot or overlay.
        for col in header.named_columns():
            if suffixes is not None:
                if not col.endswith(suffixes):
                    continue
            elif derived and col.endswith(derived):
                continue
            # Treat all as float64
            self._schema_channels.append(
                ChannelInfo(name=col, unit="px", dtype="Float64", rate_hz=rate_hz)
            )

        if suffixes is not None and not self._schema_channels:
            raise MissingColumnError(",".join(wanted), self._flat_headers)

    def channels(self) -> list[ChannelInfo]:
        return self._schema_channels

    def pose_schema(self) -> PoseSchema | None:
        """The individuals, body parts and axes this file declares (D-140)."""
        return self._pose

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
            raise SourceOpenError(
                "Tracking source used before open(). Call open(path, config) first."
            )

        fps = float(self._config.get("fps", 30.0))
        channel_names = [channel.name for channel in self._schema_channels]

        # Read in batches skipping this file's own header rows -- three, or four
        # when multi-animal -- projecting only the channels that survived the
        # ``coords`` filter so unused derived columns are never materialised or
        # pyramided.
        header_rows = self._header.rows if self._header is not None else 3
        reader = (
            pl.scan_csv(
                self._path,
                skip_rows=header_rows,
                has_header=False,
                new_columns=self._flat_headers,
                infer_schema_length=10000,
                ignore_errors=True,
            )
            .select(["frame_index", *channel_names])
            .collect_batches(chunk_size=50000)
        )

        row_offset = 0
        for batch in reader:
            t = batch["frame_index"].cast(pl.Float64).to_numpy() / fps
            values = {
                channel: batch[channel].cast(pl.Float64).to_numpy() for channel in channel_names
            }
            # Check monotonicity
            if len(t) > 1:
                dt = np.diff(t)
                if np.any(dt < 0):
                    idx = int(np.flatnonzero(dt < 0)[0])
                    row = row_offset + idx + 1 + header_rows
                    raise NonMonotonicTimeError(
                        f"Non-monotonic time detected at row {row}", row=row
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
