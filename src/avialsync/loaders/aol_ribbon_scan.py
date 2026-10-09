"""In-memory, frame-at-a-time mosaic view of an AOL ribbon-scan trial."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from avialsync.core.errors import SourceOpenError
from avialsync.core.source import ImagingMetadata, ImagingSource
from avialsync.loaders.aol_microscope_trial import MicroscopeTrial, read_trial

#: The lab analysis records green as MATLAB channel 2, hence h5py index 1.
_RIG_GREEN_CHANNEL = 1


class AOLRibbonScanSource(ImagingSource):
    """Tile every ribbon ROI into a gutterless mosaic for the imaging pane."""

    def __init__(self) -> None:
        self._trial: MicroscopeTrial | None = None
        self._volumes: list[np.ndarray] = []
        self._green_channel = _RIG_GREEN_CHANNEL
        self._side = 0
        self._roi_numbers: list[int] = []

    @classmethod
    def display_name(cls) -> str:
        return "Imaging Stack (AOL Ribbon Scan)"

    @classmethod
    def can_open(cls, path: Path) -> float:
        """The session scanner owns trial directories; never claim an ROI file."""
        return 0.0

    def open(self, path: Path, config: dict[str, Any]) -> ImagingMetadata:
        """Load and close every ROI file, leaving only the small array stack in memory."""
        self.close()
        trial_path = Path(config.get("trial_folder", path))
        self._trial = read_trial(trial_path)
        self._roi_numbers = [int(source.name.split("_")[2]) for source in self._trial.roi_files]
        self._side = math.ceil(math.sqrt(max(self._roi_numbers, default=1)))
        self._volumes = []
        for source in self._trial.roi_files:
            with h5py.File(source, "r") as handle:
                self._volumes.append(np.asarray(handle["volume"][()], dtype=np.uint16))
        self._green_channel = self._analysis_green_channel(trial_path)
        names = ["Red"] * self._trial.channels
        if self._trial.channels > 1:
            names[self._green_channel] = "Green"
            other = 1 - self._green_channel
            names[other] = "Red"
        else:
            names = ["Green"]
        return ImagingMetadata(
            frame_count=self._trial.timepoints,
            height=self._side * self._trial.lines,
            width=self._side * self._trial.width,
            dtype="float32",
            frame_times=self._trial.frame_times.copy(),
            timing_source=self._trial.timing_source,
            dataset="ribbon_scan_mosaic",
            channel_count=self._trial.channels,
            shape=(
                self._trial.channels,
                self._trial.timepoints,
                self._trial.lines,
                self._trial.width,
            ),
            axes="CTYX",
            channel_names=tuple(names[: self._trial.channels]),
        )

    def _analysis_green_channel(self, folder: Path) -> int:
        """Use a trial analysis declaration, otherwise the measured rig default."""
        activity = folder / "roi_activity"
        try:
            for source in activity.glob("hybrid_mosaic_*_activity.mat"):
                with h5py.File(source, "r") as handle:
                    value = np.asarray(handle["correction_info/green_channel"][()]).reshape(-1)
                    if value.size:
                        channel = int(value[0]) - 1
                        if 0 <= channel < (self._trial.channels if self._trial else 0):
                            return channel
        except (OSError, KeyError, ValueError):
            return _RIG_GREEN_CHANNEL
        return _RIG_GREEN_CHANNEL

    def read_frame(self, index: int, channel: int = 0) -> np.ndarray:
        """Assemble one channel and frame, leaving unoccupied tiles as NaN."""
        if self._trial is None:
            raise SourceOpenError("AOL ribbon source used before open().")
        if not 0 <= index < self._trial.timepoints:
            raise IndexError(index)
        if not 0 <= channel < self._trial.channels:
            raise IndexError(channel)
        mosaic = np.full(
            (self._side * self._trial.lines, self._side * self._trial.width),
            np.nan,
            dtype=np.float32,
        )
        for roi_number, volume in zip(self._roi_numbers, self._volumes, strict=True):
            row, col = (roi_number - 1) % self._side, (roi_number - 1) // self._side
            top, left = row * self._trial.lines, col * self._trial.width
            mosaic[top : top + self._trial.lines, left : left + self._trial.width] = volume[
                channel, index
            ]
        return mosaic

    def close(self) -> None:
        """Release the in-memory volumes; HDF5 handles are closed by ``open``."""
        self._volumes.clear()
        self._roi_numbers.clear()
        self._trial = None
