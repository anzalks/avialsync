"""Time-series reader for the cell traces in AOL hybrid-mosaic analysis files."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from avialsync.core.errors import SourceOpenError
from avialsync.core.source import ChannelInfo, TimeSeriesSource
from avialsync.loaders.aol_microscope_trial import analysis_file


class AOLRoiTraceLoader(TimeSeriesSource):
    """Expose one named activity trace per mask using the mosaic frame clock."""

    def __init__(self) -> None:
        self._times = np.empty(0, dtype=np.float64)
        self._traces = np.empty((0, 0), dtype=np.float64)
        self._descriptions: list[str] = []
        self._names: list[str] = []

    @classmethod
    def display_name(cls) -> str:
        return "ROI Traces (MATLAB)"

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        if config.get("activity_file"):
            activity = Path(config["activity_file"])
        else:
            found = analysis_file(path.parent) if path.is_dir() else None
            activity = found if found is not None else path
        series = str(config.get("series", "roi_traces"))
        try:
            with h5py.File(activity, "r") as handle:
                self._times = np.asarray(handle["frame_time_s"][()], dtype=np.float64).reshape(-1)
                values = np.asarray(handle[series][()], dtype=np.float64)
                if values.ndim != 2:
                    raise SourceOpenError(f"{series} must be a two-dimensional trace table.")
                if values.shape[0] != len(self._times) and values.shape[1] == len(self._times):
                    values = values.T
                if values.shape[0] != len(self._times):
                    raise SourceOpenError(f"{series} does not match frame_time_s.")
                self._traces = values
                masks = self._read_masks(handle)
                source_map = np.asarray(handle["mosaic_info/source_roi_map"][()])
                self._descriptions = [
                    self._covered_rois(mask, source_map) for mask in masks[: values.shape[1]]
                ]
        except SourceOpenError:
            raise
        except (OSError, KeyError, ValueError, TypeError) as exc:
            raise SourceOpenError(
                f"Could not read AOL cell traces from {activity.name}: {exc}"
            ) from exc
        if (
            len(self._times) < 2
            or not np.all(np.isfinite(self._times))
            or np.any(np.diff(self._times) <= 0)
        ):
            raise SourceOpenError("AOL cell trace frame times are not finite and increasing.")
        self._names = [f"roi_{index + 1}" for index in range(self._traces.shape[1])]
        self._descriptions.extend([""] * (len(self._names) - len(self._descriptions)))

    @staticmethod
    def _read_masks(handle: h5py.File) -> list[np.ndarray]:
        stored = np.asarray(handle["masks"][()])
        if stored.dtype.kind in "OV":
            return [
                np.asarray(handle[reference][()], dtype=bool)
                for reference in stored.reshape(-1)
                if reference
            ]
        if stored.ndim == 2:
            return [stored.astype(bool)]
        return [np.asarray(mask, dtype=bool) for mask in stored] if stored.ndim == 3 else []

    @staticmethod
    def _covered_rois(mask: np.ndarray, source_map: np.ndarray) -> str:
        if mask.shape != source_map.shape:
            return "Cell mask covers ribbon ROIs; mask geometry differs from source_roi_map."
        unique_ids = np.unique(source_map[mask])
        roi_ids = [int(value) for value in unique_ids if int(value) > 0]
        if not roi_ids:
            return "Cell mask does not overlap a ribbon ROI in source_roi_map."
        return (
            "Covers ribbon ROI"
            + ("s " if len(roi_ids) > 1 else " ")
            + ", ".join(map(str, roi_ids))
            + "."
        )

    def channels(self) -> list[ChannelInfo]:
        return [
            ChannelInfo(
                name=name,
                unit="a.u.",
                dtype="Float64",
                rate_hz=None,
                description=description,
            )
            for name, description in zip(self._names, self._descriptions, strict=True)
        ]

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        try:
            column = self._names.index(ch)
        except ValueError:
            raise SourceOpenError(f"Unknown AOL ROI trace channel {ch!r}.") from None
        for start in range(0, len(self._times), 8192):
            stop = min(start + 8192, len(self._times))
            yield self._times[start:stop].copy(), self._traces[start:stop, column].copy()
