"""AOL ribbon-scan imaging: trials tiled, an experiment end to end, or one ROI file.

A trial folder opens as one mosaic per frame with every scanned ROI in its
tile, laid out as the microscope controller reconstructs the dendritic tree
(:mod:`~avialsync.loaders.aol_mosaic_layout`). An experiment folder opens
as one source spanning all of its trials back to back, as the controller's own
analysis joins them (:func:`~avialsync.loaders.aol_microscope_trial.joined_starts`). A single
``RibbonScan_ROI_*.mat`` opens on its own, exactly as the controller wrote it:
both channels, ``uint16``, at that ROI's own line-clock times.

Planes are shown the way MATLAB, and so the lab's own figures, show them. h5py
reads MATLAB's column-major arrays transposed, so every stored plane is
transposed back on the way out: a tile is 51 rows by 15 columns, not 15 by 51.
"""

from __future__ import annotations

import logging
import math
from collections import OrderedDict
from dataclasses import dataclass
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
    joined_starts,
    logged_rate,
    read_trial,
    roi_file_parts,
)
from avialsync.loaders.aol_mosaic_layout import MosaicLayout, choose_layout

logger = logging.getLogger(__name__)

#: The lab analysis records green as MATLAB channel 2, hence h5py index 1.
_RIG_GREEN_CHANNEL = 1
#: Trials kept in memory at once for an experiment (about 54 MB each).
_CACHED_TRIALS = 3


def green_channel(folder: Path, channels: int) -> int:
    """The trial analysis's declared green channel, else the rig default (0-based)."""
    declared = declared_green_channel(folder)
    if declared is not None and 0 <= declared - 1 < channels:
        return declared - 1
    return _RIG_GREEN_CHANNEL if channels > _RIG_GREEN_CHANNEL else 0


def channel_names(channels: int, green: int) -> tuple[str, ...]:
    """Name each acquired channel by its colour, as the lab's record defines it.

    The rig records two PMTs, green and red; with any other channel count only
    the recorded green one is named, and the rest stay unnamed (D-195).
    """
    if channels == 1:
        return ("Green",)
    if channels == 2:
        return tuple("Green" if index == green else "Red" for index in range(channels))
    return tuple("Green" if index == green else "" for index in range(channels))


def _is_ribbon_file(path: Path) -> bool:
    if roi_file_parts(path) is None or not path.is_file():
        return False
    try:
        with h5py.File(path, "r") as handle:
            volume = handle.get("volume")
            return isinstance(volume, h5py.Dataset) and volume.ndim == 4
    except (OSError, ValueError):
        return False


@dataclass(frozen=True)
class _Segment:
    """One trial's frames inside an experiment's frame list."""

    trial: MicroscopeTrial
    first: int  # index of this trial's first frame in the combined list


_Pixels = dict[int, np.ndarray]


class AOLRibbonScanSource(ImagingSource):
    """Tile ribbon ROIs into a mosaic, end to end across trials, or show one ROI raw."""

    def __init__(self) -> None:
        self._segments: list[_Segment] = []
        self._layout: MosaicLayout | None = None
        self._lines = 0
        self._width = 0
        self._channels = 0
        self._loaded: OrderedDict[Path, _Pixels] = OrderedDict()
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
        """The (first) trial read at open, for sources that build on this one."""
        return self._segments[0].trial if self._segments else None

    @property
    def mosaic_size(self) -> tuple[int, int]:
        """``(height, width)`` of the assembled mosaic, as displayed."""
        return self._layout.size if self._layout is not None else (0, 0)

    @property
    def layout(self) -> MosaicLayout | None:
        """Where each ROI's tile sits."""
        return self._layout

    def open(self, path: Path, config: dict[str, Any]) -> ImagingMetadata:
        """Read metadata; pixels are read once per trial and kept for a few trials."""
        self.close()
        folders = config.get("trial_folders")
        folder = config.get("trial_folder")
        if folders:
            return self._open_mosaic([Path(item) for item in folders], config)
        if folder is None and path.is_file():
            return self._open_single(path, config)
        return self._open_mosaic([Path(folder) if folder else path], config)

    # -- mosaics ----------------------------------------------------------

    def _open_mosaic(self, folders: list[Path], config: dict[str, Any]) -> ImagingMetadata:
        first = read_trial(folders[0])
        self._layout = choose_layout(first, str(config.get("layout", "branches")))
        self._lines, self._width, self._channels = first.lines, first.width, first.channels
        scan = (first.roi_numbers, first.channels, first.lines, first.width)
        trials = [first] + [read_trial(folder, verify=False) for folder in folders[1:]]
        for trial in trials:
            if (trial.roi_numbers, trial.channels, trial.lines, trial.width) != scan:
                raise SourceOpenError(
                    f"Trial {trial.folder.name} does not share the first trial's scan."
                )
        times: list[np.ndarray] = []
        next_index = 0
        for trial, start in zip(trials, joined_starts(trials), strict=True):
            self._segments.append(_Segment(trial, next_index))
            times.append(trial.frame_times + start)
            next_index += trial.timepoints
        frame_times = np.concatenate(times)
        source = first.timing_source
        if len(folders) > 1:
            source += f"; {len(folders)} trials back to back"
        self._load(first)
        height, width = self._layout.size
        green = green_channel(first.folder, first.channels)
        return ImagingMetadata(
            frame_count=len(frame_times),
            height=height,
            width=width,
            dtype="float32",
            frame_times=frame_times,
            timing_source=source,
            dataset=f"ribbon_scan_mosaic_{self._layout.kind}",
            channel_count=first.channels,
            shape=(first.channels, len(frame_times), height, width),
            # The order is the loader's own, not a guess to correct (D-194 row hidden).
            axes="",
            channel_names=channel_names(first.channels, green),
        )

    def _load(self, trial: MicroscopeTrial) -> _Pixels:
        """Pixels of one trial, read once and kept for a few trials."""
        cached = self._loaded.get(trial.folder)
        if cached is not None:
            self._loaded.move_to_end(trial.folder)
            return cached
        volumes: dict[int, np.ndarray] = {}
        for roi, source in zip(trial.roi_numbers, trial.roi_files, strict=True):
            try:
                with h5py.File(source, "r") as handle:
                    volumes[roi] = np.asarray(handle["volume"][()], dtype=np.uint16)
            except (OSError, KeyError, ValueError):
                logger.warning("Could not read ribbon ROI file %s", source, exc_info=True)
        self._loaded[trial.folder] = volumes
        while len(self._loaded) > _CACHED_TRIALS:
            self._loaded.popitem(last=False)
        return volumes

    def _segment_for(self, index: int) -> tuple[_Segment, int]:
        for segment in reversed(self._segments):
            if index >= segment.first:
                return segment, index - segment.first
        raise IndexError(index)

    # -- single ROI files ---------------------------------------------------

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
            # The order is the loader's own, not a guess to correct (D-194 row hidden).
            axes="",
            channel_names=channel_names(channels, green_channel(path.parent, channels)),
        )

    @staticmethod
    def _single_times(
        folder: Path, roi: int, count: int, config: dict[str, Any]
    ) -> tuple[np.ndarray, str]:
        """This ROI's own line-clock times when its trial is beside it.

        Then, in order: the trial's own frame times, a rate the user entered,
        the controller log's nominal rate for this trial. Only with none of
        those is the user asked, so a stack never plays at a guessed speed.
        """
        if is_microscope_trial(folder):
            trial = read_trial(folder, verify=False)
            if trial.roi_frame_times is not None and trial.timepoints == count:
                if 0 < roi <= trial.roi_frame_times.shape[1]:
                    return trial.roi_frame_times[:, roi - 1].copy(), "line clock, this ROI"
            if trial.timepoints == count:
                return trial.frame_times.copy(), trial.timing_source
        fps = config.get("fps")
        if fps is not None and math.isfinite(float(fps)) and float(fps) > 0:
            return np.arange(count, dtype=np.float64) / float(fps), "import frame rate"
        rate = logged_rate(folder)
        if rate is not None:
            return np.arange(count, dtype=np.float64) / rate, f"Log.txt nominal rate ({rate:g} Hz)"
        raise ImagingChoiceRequired(
            "fps",
            "This ROI file has no trial timing beside it. Enter the acquisition frame rate.",
        )

    # -- frames -------------------------------------------------------------

    def read_frame(self, index: int, channel: int = 0) -> np.ndarray:
        """One channel of one frame: the stored plane, or the assembled mosaic."""
        if self._single is not None:
            if not 0 <= index < self._single.shape[1]:
                raise IndexError(index)
            if not 0 <= channel < self._single.shape[0]:
                raise IndexError(channel)
            return np.ascontiguousarray(self._single[channel, index].T)
        if self._layout is None or not self._segments:
            raise SourceOpenError("AOL ribbon source used before open().")
        if not 0 <= channel < self._channels:
            raise IndexError(channel)
        mosaic = np.full(self._layout.size, np.nan, dtype=np.float32)
        segment, local = self._segment_for(index)
        if not 0 <= local < segment.trial.timepoints:
            raise IndexError(index)
        volumes = self._load(segment.trial)
        tile_h, tile_w = self._width, self._lines
        for roi, (top, left) in self._layout.origins.items():
            volume = volumes.get(roi)
            if volume is None:
                continue
            mosaic[top : top + tile_h, left : left + tile_w] = volume[channel, local].T
        return mosaic

    def close(self) -> None:
        """Release the in-memory pixels; HDF5 handles are closed as they are read."""
        self._segments.clear()
        self._loaded.clear()
        self._layout = None
        self._single = None
