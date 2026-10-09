"""Read-only discovery and timing metadata for one AOL microscope trial."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from avialsync.core.errors import SourceOpenError

logger = logging.getLogger(__name__)
_ROI_FILE = re.compile(r"^RibbonScan_ROI_(\d+)_repeat_(\d+)_timepoints_(\d+)\.mat$", re.IGNORECASE)
_LINE_TICK_S = 5e-9  # The rig's 200 MHz line clock, as recorded in trial timing metadata.


@dataclass(frozen=True)
class MicroscopeTrial:
    """Metadata needed to load one trial without retaining source file handles."""

    folder: Path
    start_epoch: float
    duration: float
    roi_files: tuple[Path, ...]
    repeat: int
    timepoints: int
    lines: int
    width: int
    channels: int
    frame_times: np.ndarray
    roi_frame_times: np.ndarray | None
    timing_source: str
    warnings: tuple[str, ...]


def _roi_files(path: Path) -> list[tuple[int, int, int, Path]]:
    found: list[tuple[int, int, int, Path]] = []
    try:
        for child in path.iterdir():
            match = _ROI_FILE.match(child.name)
            if child.is_file() and match:
                roi_number, repeat, timepoints = (int(value) for value in match.groups())
                found.append((roi_number, repeat, timepoints, child))
    except OSError:
        return []
    return sorted(found)


def is_microscope_trial(path: Path) -> bool:
    """Cheaply identify a trial by its files, then its HDF5 signature."""
    if not path.is_dir() or not (path / "params.mat").is_file() or not _roi_files(path):
        return False
    try:
        with h5py.File(path / "params.mat", "r") as handle:
            return "controller/aol_params" in handle
    except (OSError, ValueError):
        return False


def _cell_first(handle: h5py.File, dataset: Any) -> float | None:
    """Read the first scalar from a MATLAB direct value or object-reference cell."""
    values = np.asarray(dataset[()])
    if values.size == 0:
        return None
    value = values.reshape(-1)[0]
    if isinstance(value, h5py.Reference):
        if not value:
            return None
        value = np.asarray(handle[value][()]).reshape(-1)[0]
    number = float(value)
    return number if math.isfinite(number) else None


def read_trial(path: Path) -> MicroscopeTrial:
    """Read timing and shape metadata; all inputs are opened strictly read-only."""
    folder = path
    files = _roi_files(folder)
    if not files:
        raise SourceOpenError(f"No ribbon-scan ROI files found in {folder}.")
    warnings: list[str] = []
    first_shape: tuple[int, ...] | None = None
    valid: list[Path] = []
    valid_tuples: list[tuple[int, int, int, Path]] = []
    for entry in files:
        _roi, _repeat, declared_t, source = entry
        try:
            with h5py.File(source, "r") as handle:
                if "volume" not in handle:
                    warnings.append(f"Ignored {source.name}: it has no volume dataset.")
                    continue
                shape = tuple(int(size) for size in handle["volume"].shape)
            if len(shape) != 4 or shape[1] != declared_t:
                warnings.append(
                    f"Ignored {source.name}: its volume axes or declared timepoints differ."
                )
                continue
            if first_shape is not None and shape != first_shape:
                warnings.append(
                    f"Ignored {source.name}: its volume shape or declared timepoints differ."
                )
                continue
            if first_shape is None:
                first_shape = shape
            valid.append(source)
            valid_tuples.append(entry)
        except (OSError, KeyError, ValueError):
            warnings.append(f"Ignored unreadable ribbon ROI file {source.name}.")
    if first_shape is None:
        raise SourceOpenError("No readable ribbon ROI volume has valid C,T,Y,X axes.")
    channels, timepoints, lines, width = first_shape
    repeats = {entry[1] for entry in files}
    repeat = min(repeats) if repeats else 1
    if len(repeats) > 1:
        warnings.append(
            "Multiple repeats are present; trial timing uses uniform time over duration."
        )

    start_epoch = 0.0
    duration: float | None = None
    line_time: np.ndarray | None = None
    try:
        with h5py.File(folder / "params.mat", "r") as handle:
            if "timings/timing_FIFO/STARTTIME" in handle:
                start_epoch = (
                    float(np.asarray(handle["timings/timing_FIFO/STARTTIME"][()]).reshape(-1)[0])
                    / 1000.0
                )
            if "timings/summary" in handle:
                duration = _cell_first(handle, handle["timings/summary"])
            if "timings/timing_FIFO/line_time" in handle:
                line_time = np.asarray(
                    handle["timings/timing_FIFO/line_time"][()], dtype=np.float64
                ).reshape(-1)
    except (OSError, KeyError, ValueError, TypeError) as exc:
        warnings.append(f"Could not read complete trial timing metadata: {exc}")
    if duration is None or duration <= 0:
        if line_time is not None and len(line_time) > 1:
            duration = float((line_time[-1] - line_time[0]) * _LINE_TICK_S)
        else:
            duration = float(timepoints)
        warnings.append("Trial duration is provisional because timings/summary is missing.")

    roi_count = len({entry[0] for entry in files})
    expected = timepoints * roi_count * lines
    timing_ok = line_time is not None and len(line_time) == expected and len(repeats) <= 1
    if timing_ok:
        assert line_time is not None
        rows = line_time.reshape(timepoints, roi_count, lines) * _LINE_TICK_S
        roi_frame_times = rows.mean(axis=2)
        frame_times = rows.mean(axis=(1, 2))
        timing_source = "line clock, frame midpoint (tiles ±27 ms)"
    else:
        frame_times = np.arange(timepoints, dtype=np.float64) * duration / timepoints
        roi_frame_times = None
        timing_source = "uniform over trial duration (line clock unreadable)"
        warnings.append(
            "Line-clock timing is unavailable or inconsistent; using uniform trial timing."
        )
    if start_epoch <= 0:
        warnings.append(
            "Trial STARTTIME is unavailable; absolute trial matching cannot be offered."
        )
    return MicroscopeTrial(
        folder=folder,
        start_epoch=start_epoch,
        duration=float(duration),
        roi_files=tuple(valid),
        repeat=repeat,
        timepoints=timepoints,
        lines=lines,
        width=width,
        channels=channels,
        frame_times=np.asarray(frame_times, dtype=np.float64),
        roi_frame_times=(
            np.asarray(roi_frame_times, dtype=np.float64) if roi_frame_times is not None else None
        ),
        timing_source=timing_source,
        warnings=tuple(warnings),
    )
