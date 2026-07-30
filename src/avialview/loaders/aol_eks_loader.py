"""AOL EKS 3D Tracking Loader.

Parses Ensemble Kalman Smoother (EKS) CSV files produced by the
Lightning Pose / Anipose triangulation pipeline. Each row is one frame;
only the x/y/z coordinate triplets per bodypart are imported.
"""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from avialview.core.errors import NonMonotonicTimeError
from avialview.core.source import ChannelInfo, TimeSeriesSource

logger = logging.getLogger(__name__)


class AOLEksLoader(TimeSeriesSource):
    """Tracking Data (2D/3D).

    Format: standard CSV with header row. Columns follow the pattern
    ``{bodypart}_x``, ``{bodypart}_y``, ``{bodypart}_z`` with optional
    metadata columns (error, ncams, score, M_*, center_*, fnum).
    Only x/y/z triplets are imported. The ``fnum`` column (if present)
    provides frame indices; otherwise row index is used.
    """

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._xyz_channels: list[str] = []
        self._has_fnum: bool = False

    def is_frame_indexed(self) -> bool:
        """EKS data is always frame-indexed."""
        return True

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Detect EKS CSV by filename pattern and header structure."""
        if path.is_dir():
            return 0.0
        if path.suffix.lower() != ".csv":
            return 0.0

        # High confidence for _eks.csv in a pose-3d path
        if "_eks" in path.stem.lower():
            return 0.95

        # Check header for x/y/z triplet pattern
        try:
            with open(path, encoding="utf-8") as f:
                header = f.readline().strip()
            cols = [c.strip() for c in header.split(",")]
            xyz_count = sum(1 for c in cols if c.endswith(("_x", "_y", "_z")))
            # Need at least one complete triplet (3 columns)
            if xyz_count >= 3 and xyz_count % 3 == 0:
                return 0.85
        except (OSError, UnicodeError):
            pass

        return 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        """Read headers and identify x/y/z channels."""
        self._path = path
        self._config = config

        with open(path, encoding="utf-8") as f:
            header_line = f.readline().strip()

        all_cols = [c.strip() for c in header_line.split(",")]
        self._has_fnum = "fnum" in all_cols

        # Extract only _x, _y, _z columns
        raw_xyz = [c for c in all_cols if c.endswith(("_x", "_y", "_z"))]

        if not raw_xyz:
            raise ValueError(f"No x/y/z coordinate columns found in EKS file: {path}")

        # Try to use skeleton to identify bodyparts and strip model prefixes
        skeleton_edges = self._config.get("skeleton", [])
        known_bodyparts = set()
        for a, b in skeleton_edges:
            known_bodyparts.add(a)
            known_bodyparts.add(b)

        self._xyz_channels = []
        for c in raw_xyz:
            found_bp = None
            for bp in known_bodyparts:
                if c.endswith(f"{bp}_x") or c.endswith(f"{bp}_y") or c.endswith(f"{bp}_z"):
                    found_bp = bp
                    break
            if found_bp:
                suffix = c[-2:]  # _x, _y, _z
                self._xyz_channels.append(f"{found_bp}{suffix}")
            else:
                self._xyz_channels.append(c)

        self._col_mapping = dict(zip(self._xyz_channels, raw_xyz, strict=True))

        bodyparts = []
        for ch in self._xyz_channels:
            bp = ch.rsplit("_", 1)[0]
            if bp not in bodyparts:
                bodyparts.append(bp)

        logger.info(
            "EKS loader found %d bodyparts (%d channels) in %s",
            len(bodyparts),
            len(self._xyz_channels),
            path.name,
        )

    def channels(self) -> list[ChannelInfo]:
        """Return one ChannelInfo per x/y/z coordinate."""
        unit = "mm"  # EKS 3D coordinates are typically in mm
        return [
            ChannelInfo(name=ch, unit=unit, dtype="Float64", rate_hz=None)
            for ch in self._xyz_channels
        ]

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield (time, value) chunks for one channel."""
        if ch not in self._xyz_channels:
            raise KeyError(f"Unknown EKS channel: {ch}")
        for chunk in self.read_all_chunks():
            if ch in chunk:
                yield chunk[ch]

    def read_all_chunks(self) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
        """Yield all x/y/z channels from a single CSV pass."""
        if self._path is None:
            raise RuntimeError("Source not opened")

        fps = float(self._config.get("fps", 30.0))

        # Determine which columns to read and force them to Float64
        # to prevent Polars from inferring them as Int64 if the first few rows are integers.
        use_cols = list(self._col_mapping.values())
        if self._has_fnum:
            use_cols.append("fnum")

        schema_overrides = {col: pl.Float64 for col in use_cols}

        reader = (
            pl.scan_csv(
                self._path,
                has_header=True,
                schema_overrides=schema_overrides,
            )
            .select(use_cols)
            .collect_batches(chunk_size=50_000)
        )

        row_offset = 0
        for batch in reader:
            # Build time array from frame numbers
            if self._has_fnum:
                fnum = batch["fnum"].cast(pl.Float64).to_numpy()
            else:
                # Each row is one frame, use row index
                fnum = np.arange(row_offset, row_offset + len(batch), dtype=np.float64)

            start_epoch = self._config.get("start_epoch", 0.0)
            t = (fnum / fps) + start_epoch

            # Map original cols back to stripped channel names for yielding
            values: dict[str, np.ndarray] = {}
            for ch_name, orig_col in self._col_mapping.items():
                if orig_col in batch.columns:
                    values[ch_name] = batch[orig_col].cast(pl.Float64).to_numpy()

            # Validate monotonicity
            if len(t) > 1:
                dt = np.diff(t)
                if np.any(dt < 0):
                    idx = int(np.flatnonzero(dt < 0)[0])
                    raise NonMonotonicTimeError(
                        f"Non-monotonic frame numbers at row {row_offset + idx + 1}",
                        row=row_offset + idx + 1,
                    )

            # Remove duplicate timestamps (keep last)
            if len(t) > 1:
                dt = np.diff(t)
                mask = np.ones(len(t), dtype=bool)
                mask[:-1] = dt > 0
                t = t[mask]
                values = {ch_name: v[mask] for ch_name, v in values.items()}

            if len(t) > 0:
                yield {ch_name: (t, v) for ch_name, v in values.items()}
            row_offset += len(batch)
