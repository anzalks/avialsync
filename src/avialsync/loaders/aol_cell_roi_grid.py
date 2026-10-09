"""Raw green-channel crops of lab-analyzed cell masks, laid out as a shared ROI grid."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import h5py
import numpy as np

from avialsync.core.errors import SourceOpenError
from avialsync.core.source import ImagingMetadata, ImagingSource
from avialsync.loaders.aol_microscope_trial import analysis_file, is_microscope_trial
from avialsync.loaders.aol_ribbon_scan import AOLRibbonScanSource, green_channel
from avialsync.loaders.roi_grid_layout import geometry, mask_crop, pack


def _masks(handle: h5py.File) -> list[np.ndarray]:
    """Read MATLAB cell masks or a dense mask array into boolean planes."""
    if "masks" not in handle:
        return []
    dataset = handle["masks"]
    stored = np.asarray(dataset[()])
    if stored.dtype == h5py.ref_dtype or stored.dtype.kind == "O":
        result = []
        for reference in stored.reshape(-1):
            if not reference:
                continue
            result.append(np.asarray(handle[reference][()], dtype=bool))
        return result
    if stored.ndim == 2:
        return [stored.astype(bool)]
    if stored.ndim == 3:
        return [np.asarray(mask, dtype=bool) for mask in stored]
    return []


class AOLCellRoiGridSource(ImagingSource):
    """Show every analyzed cell's raw crop in one near-square grid."""

    def __init__(self) -> None:
        self._ribbon = AOLRibbonScanSource()
        self._masks: list[np.ndarray] = []
        self._crops: list[np.ndarray] = []
        self._corners: list[tuple[int, int]] = []
        self._grid = (0, 0)
        self._tile = (0, 0)
        self._shape = (0, 0)
        self._frame_times = np.empty(0, dtype=np.float64)
        self._green_channel = 1

    @classmethod
    def display_name(cls) -> str:
        return "ROI Grid (MATLAB)"

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Claim a trial's lab mosaic analysis, whose raw pixels sit two folders up."""
        if not path.name.lower().startswith("hybrid_mosaic_") or path.suffix.lower() != ".mat":
            return 0.0
        return 0.9 if is_microscope_trial(path.parent.parent) else 0.0

    def open(self, path: Path, config: dict[str, Any]) -> ImagingMetadata:
        """Read masks once and open the raw ribbon source on the import worker."""
        self.close()
        trial_path = Path(config.get("trial_folder", path.parent.parent))
        activity = analysis_file(trial_path)
        if activity is None:
            raise SourceOpenError("This trial has no hybrid mosaic ROI analysis.")
        with h5py.File(activity, "r") as handle:
            # Transposed like every plane: h5py reads MATLAB's column-major masks flipped.
            self._masks = [mask.T for mask in _masks(handle)]
            if not self._masks:
                raise SourceOpenError("The hybrid mosaic ROI analysis has no cell masks.")
            if "frame_time_s" not in handle:
                raise SourceOpenError("The hybrid mosaic ROI analysis has no frame_time_s.")
            self._frame_times = np.asarray(handle["frame_time_s"][()], dtype=np.float64).reshape(-1)
        if not np.all(np.isfinite(self._frame_times)) or np.any(np.diff(self._frame_times) <= 0):
            raise SourceOpenError("The hybrid mosaic frame times are not finite and increasing.")
        self._crops, self._corners = [], []
        for mask in self._masks:
            cropped, corner = mask_crop(mask)
            self._crops.append(cropped)
            self._corners.append(corner)
        self._grid, self._tile, self._shape = geometry(self._crops)
        # Cell masks are drawn on the lab's analysis mosaic, so crops use that layout.
        self._ribbon.open(trial_path, {"trial_folder": str(trial_path), "layout": "analysis"})
        trial = self._ribbon.trial
        assert trial is not None
        self._green_channel = green_channel(trial_path, trial.channels)
        mosaic_size = self._ribbon.mosaic_size
        if any(mask.shape != mosaic_size for mask in self._masks):
            self.close()
            raise SourceOpenError(
                "Cell masks do not match the ribbon-scan mosaic they are drawn on."
            )
        if len(self._frame_times) != trial.timepoints:
            self.close()
            raise SourceOpenError("Cell ROI frame times do not match the ribbon-scan trial.")
        return ImagingMetadata(
            frame_count=len(self._frame_times),
            height=self._shape[0],
            width=self._shape[1],
            dtype="float32",
            frame_times=self._frame_times.copy(),
            timing_source="hybrid mosaic frame_time_s (frame midpoint)",
            dataset=str(activity),
            channel_count=1,
            shape=(len(self._frame_times), self._shape[0], self._shape[1]),
            # The order is the loader's own, not a guess to correct (D-194 row hidden).
            axes="",
            channel_names=("Green",),
        )

    def read_frame(self, index: int, channel: int = 0) -> np.ndarray:
        if not 0 <= index < len(self._frame_times) or channel != 0:
            raise IndexError(index if channel == 0 else channel)
        mosaic = self._ribbon.read_frame(index, self._green_channel)
        tiles: list[np.ndarray] = []
        for mask, corner in zip(self._crops, self._corners, strict=True):
            top, left = corner
            raw = mosaic[top : top + mask.shape[0], left : left + mask.shape[1]]
            tiles.append(np.where(mask, raw, np.nan).astype(np.float32))
        return pack(tiles, self._grid, self._tile, self._shape)

    def close(self) -> None:
        self._ribbon.close()
        self._masks.clear()
        self._crops.clear()
        self._corners.clear()
        self._frame_times = np.empty(0, dtype=np.float64)
