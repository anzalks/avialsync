"""AOL ribbon-scan imaging: a trial's ROIs tiled, or one ROI file as stored.

A trial folder opens as one mosaic per frame with every scanned ROI in its
tile, placed where the lab's own analysis places it. A single
``RibbonScan_ROI_*.mat`` opens on its own, exactly as the controller wrote it:
both channels, ``uint16``, and timed by that ROI's own line-clock times rather
than the frame midpoint a mosaic has to share.

Planes are shown the way MATLAB, and so the lab's own figures, show them. h5py
reads MATLAB's column-major arrays transposed, so every stored plane is
transposed back on the way out: a tile is 51 rows by 15 columns, not 15 by 51.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from avialsync.core.errors import ImagingChoiceRequired, SourceOpenError
from avialsync.core.source import ImagingMetadata, ImagingSource
from avialsync.loaders.aol_microscope_trial import (
    MicroscopeTrial,
    declared_green_channel,
    is_microscope_trial,
    read_trial,
    roi_file_parts,
    tile_origins,
)

logger = logging.getLogger(__name__)

#: The lab analysis records green as MATLAB channel 2, hence h5py index 1.
_RIG_GREEN_CHANNEL = 1


def green_channel(folder: Path, channels: int) -> int:
    """The trial analysis's declared green channel, else the rig default (0-based)."""
    declared = declared_green_channel(folder)
    if declared is not None and 0 <= declared - 1 < channels:
        return declared - 1
    return _RIG_GREEN_CHANNEL if channels > _RIG_GREEN_CHANNEL else 0


def channel_names(channels: int, green: int) -> tuple[str, ...]:
    """Name each acquired channel by its colour, as the lab's record defines it."""
    if channels == 1:
        return ("Green",)
    return tuple("Green" if index == green else "Red" for index in range(channels))


def _is_ribbon_file(path: Path) -> bool:
    if roi_file_parts(path) is None or not path.is_file():
        return False
    try:
        with h5py.File(path, "r") as handle:
            volume = handle.get("volume")
            return isinstance(volume, h5py.Dataset) and volume.ndim == 4
    except (OSError, ValueError):
        return False


class AOLRibbonScanSource(ImagingSource):
    """Tile every ribbon ROI into a gutterless mosaic, or show one ROI raw."""

    def __init__(self) -> None:
        self._trial: MicroscopeTrial | None = None
        self._volumes: list[np.ndarray] = []
        self._origins: list[tuple[int, int]] = []
        self._size = (0, 0)
        self._single: np.ndarray | None = None

    @classmethod
    def display_name(cls) -> str:
        return "Imaging Stack (MATLAB)"

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Claim one ribbon-scan ROI file; trial folders belong to the session."""
        return 0.9 if _is_ribbon_file(path) else 0.0

    @property
    def trial(self) -> MicroscopeTrial | None:
        """The trial read at open, for sources that build on this one."""
        return self._trial

    @property
    def mosaic_size(self) -> tuple[int, int]:
        """``(height, width)`` of the assembled mosaic, as displayed."""
        return self._size

    def open(self, path: Path, config: dict[str, Any]) -> ImagingMetadata:
        """Read the pixels once and close every file; frames are cut from memory."""
        self.close()
        folder = config.get("trial_folder")
        if folder is None and path.is_file():
            return self._open_single(path, config)
        return self._open_mosaic(Path(folder) if folder else path)

    def _open_mosaic(self, folder: Path) -> ImagingMetadata:
        trial = read_trial(folder)
        self._trial = trial
        origins, self._size = tile_origins(trial)
        self._origins = [origins[roi] for roi in trial.roi_numbers]
        for source in trial.roi_files:
            with h5py.File(source, "r") as handle:
                self._volumes.append(np.asarray(handle["volume"][()], dtype=np.uint16))
        return ImagingMetadata(
            frame_count=trial.timepoints,
            height=self._size[0],
            width=self._size[1],
            dtype="float32",
            frame_times=trial.frame_times.copy(),
            timing_source=trial.timing_source,
            dataset="ribbon_scan_mosaic",
            channel_count=trial.channels,
            shape=(trial.channels, trial.timepoints, self._size[0], self._size[1]),
            axes="CTYX",
            channel_names=channel_names(trial.channels, green_channel(folder, trial.channels)),
        )

    def _open_single(self, path: Path, config: dict[str, Any]) -> ImagingMetadata:
        parts = roi_file_parts(path)
        if parts is None:
            raise SourceOpenError(f"{path.name} is not a ribbon-scan ROI file.")
        roi, _repeat, _timepoints = parts
        try:
            with h5py.File(path, "r") as handle:
                volume = np.asarray(handle["volume"][()])
        except (OSError, KeyError, ValueError) as exc:
            raise SourceOpenError(f"Could not read {path.name}: {exc}") from exc
        if volume.ndim != 4:
            raise SourceOpenError(f"{path.name} does not hold a C,T,Y,X volume.")
        self._single = volume
        channels, count = int(volume.shape[0]), int(volume.shape[1])
        height, width = int(volume.shape[3]), int(volume.shape[2])
        times, origin = self._single_times(path.parent, roi, count, config)
        return ImagingMetadata(
            frame_count=count,
            height=height,
            width=width,
            dtype=str(volume.dtype),
            frame_times=times,
            timing_source=origin,
            dataset="volume",
            channel_count=channels,
            shape=(channels, count, height, width),
            axes="CTYX",
            channel_names=channel_names(channels, green_channel(path.parent, channels)),
        )

    @staticmethod
    def _single_times(
        folder: Path, roi: int, count: int, config: dict[str, Any]
    ) -> tuple[np.ndarray, str]:
        """This ROI's own line-clock times when its trial is beside it."""
        if is_microscope_trial(folder):
            trial = read_trial(folder, verify=False)
            if trial.roi_frame_times is not None and trial.timepoints == count:
                if 0 < roi <= trial.roi_frame_times.shape[1]:
                    return trial.roi_frame_times[:, roi - 1].copy(), "line clock, this ROI"
        fps = config.get("fps")
        if fps is None or not math.isfinite(float(fps)) or float(fps) <= 0:
            raise ImagingChoiceRequired(
                "fps",
                "This ROI file has no trial timing beside it. Enter the acquisition frame rate.",
            )
        return np.arange(count, dtype=np.float64) / float(fps), "import frame rate"

    def read_frame(self, index: int, channel: int = 0) -> np.ndarray:
        """One channel of one frame: the stored plane, or the assembled mosaic."""
        if self._single is not None:
            if not 0 <= index < self._single.shape[1]:
                raise IndexError(index)
            if not 0 <= channel < self._single.shape[0]:
                raise IndexError(channel)
            return np.ascontiguousarray(self._single[channel, index].T)
        trial = self._trial
        if trial is None:
            raise SourceOpenError("AOL ribbon source used before open().")
        if not 0 <= index < trial.timepoints:
            raise IndexError(index)
        if not 0 <= channel < trial.channels:
            raise IndexError(channel)
        mosaic = np.full(self._size, np.nan, dtype=np.float32)
        for (top, left), volume in zip(self._origins, self._volumes, strict=True):
            mosaic[top : top + trial.width, left : left + trial.lines] = volume[channel, index].T
        return mosaic

    def close(self) -> None:
        """Release the in-memory pixels; HDF5 handles are closed by ``open``."""
        self._volumes.clear()
        self._origins.clear()
        self._single = None
        self._trial = None
