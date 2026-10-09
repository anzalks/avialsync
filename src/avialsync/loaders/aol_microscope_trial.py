"""Read-only discovery and timing metadata for one AOL microscope trial."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path

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
    #: Scanned ROI numbers, 1-based, in the order of :attr:`roi_files`.
    roi_numbers: tuple[int, ...] = ()
    #: Every ROI the line clock scanned, including files dropped as unreadable;
    #: :attr:`roi_frame_times` columns are indexed by ``roi_number - 1``.
    scanned_roi_count: int = 0


def roi_file_parts(path: Path) -> tuple[int, int, int] | None:
    """``(roi, repeat, timepoints)`` from a ribbon-scan file name, or ``None``."""
    match = _ROI_FILE.match(path.name)
    if match is None:
        return None
    roi, repeat, timepoints = (int(value) for value in match.groups())
    return roi, repeat, timepoints


def _roi_files(path: Path) -> list[tuple[int, int, int, Path]]:
    found: list[tuple[int, int, int, Path]] = []
    try:
        for child in path.iterdir():
            parts = roi_file_parts(child)
            if parts is not None and child.is_file():
                found.append((*parts, child))
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


def _cell_value(handle: h5py.File, name: str) -> np.ndarray | None:
    """A MATLAB field stored directly or as the first element of a cell.

    The controller writes its timing fields as one-element cells, so the value
    sits behind an object reference rather than in the dataset itself.
    """
    if name not in handle:
        return None
    stored = np.asarray(handle[name][()])
    if stored.size == 0:
        return None
    if stored.dtype == h5py.ref_dtype or stored.dtype.kind == "O":
        reference = stored.reshape(-1)[0]
        if not isinstance(reference, h5py.Reference) or not reference:
            return None
        target = handle[reference]
        if not isinstance(target, h5py.Dataset) or target.attrs.get("MATLAB_empty", 0):
            return None
        stored = np.asarray(target[()])
    return stored.reshape(-1) if stored.size else None


def _cell_first(handle: h5py.File, name: str) -> float | None:
    """The first finite scalar of a direct or cell-wrapped MATLAB field."""
    values = _cell_value(handle, name)
    if values is None:
        return None
    number = float(values[0])
    return number if math.isfinite(number) else None


def _volume_shape(source: Path) -> tuple[int, ...] | None:
    with h5py.File(source, "r") as handle:
        if "volume" not in handle:
            return None
        return tuple(int(size) for size in handle["volume"].shape)


def _checked_files(
    files: list[tuple[int, int, int, Path]], verify: bool, warnings: list[str]
) -> tuple[tuple[int, ...], list[tuple[int, int, int, Path]]]:
    """The shared volume shape and the files that match it.

    With *verify* off only the first readable file is opened: the rest are
    trusted by their names, which is what a folder scan needs to stay fast on
    an experiment of many trials. The source that reads pixels verifies all.
    """
    first_shape: tuple[int, ...] | None = None
    valid: list[tuple[int, int, int, Path]] = []
    for entry in files:
        _roi, _repeat, declared_t, source = entry
        if first_shape is not None and not verify:
            if declared_t == first_shape[1]:
                valid.append(entry)
            else:
                warnings.append(f"Ignored {source.name}: its declared timepoints differ.")
            continue
        try:
            shape = _volume_shape(source)
        except (OSError, KeyError, ValueError):
            warnings.append(f"Ignored unreadable ribbon ROI file {source.name}.")
            continue
        if shape is None:
            warnings.append(f"Ignored {source.name}: it has no volume dataset.")
            continue
        if len(shape) != 4 or shape[1] != declared_t:
            warnings.append(
                f"Ignored {source.name}: its volume axes or declared timepoints differ."
            )
            continue
        if first_shape is not None and shape != first_shape:
            warnings.append(f"Ignored {source.name}: its volume shape differs.")
            continue
        first_shape = first_shape or shape
        valid.append(entry)
    if first_shape is None:
        raise SourceOpenError("No readable ribbon ROI volume has valid C,T,Y,X axes.")
    return first_shape, valid


def read_trial(path: Path, *, verify: bool = True) -> MicroscopeTrial:
    """Read timing and shape metadata; all inputs are opened strictly read-only."""
    folder = path
    files = _roi_files(folder)
    if not files:
        raise SourceOpenError(f"No ribbon-scan ROI files found in {folder}.")
    warnings: list[str] = []
    first_shape, valid = _checked_files(files, verify, warnings)
    channels, timepoints, lines, width = first_shape
    repeats = {entry[1] for entry in files}
    repeat = min(repeats) if repeats else 1
    if len(repeats) > 1:
        warnings.append(
            "Multiple repeats are present; trial timing uses uniform time over duration."
        )

    start_ms: float | None = None
    duration: float | None = None
    line_time: np.ndarray | None = None
    try:
        with h5py.File(folder / "params.mat", "r") as handle:
            start_ms = _cell_first(handle, "timings/timing_FIFO/STARTTIME")
            duration = _cell_first(handle, "timings/summary")
            ticks = _cell_value(handle, "timings/timing_FIFO/line_time")
            if ticks is not None:
                line_time = np.asarray(ticks, dtype=np.float64)
    except (OSError, KeyError, ValueError, TypeError) as exc:
        warnings.append(f"Could not read complete trial timing metadata: {exc}")
    start_epoch = start_ms / 1000.0 if start_ms is not None and start_ms > 0 else 0.0
    duration_recorded = duration is not None and duration > 0
    # The rate, best evidence first: the trial's recorded duration, the line
    # clock's own span, the controller log's nominal rate. Never a guess.
    rate_origin = "uniform over the recorded trial duration"
    if duration is None or duration <= 0:
        log_rate = logged_rate(folder)
        if line_time is not None and len(line_time) > 1:
            duration = float((line_time[-1] - line_time[0]) * _LINE_TICK_S)
            rate_origin = "uniform over the line clock's span"
        elif log_rate is not None:
            duration = timepoints / log_rate
            rate_origin = f"Log.txt nominal rate ({log_rate:g} Hz)"
        else:
            duration = float(timepoints)
            rate_origin = "one frame per second (no rate recorded)"
            warnings.append("No trial rate is recorded; frames are placed one second apart.")
        warnings.append("Trial duration is provisional because timings/summary is missing.")

    roi_count = len({entry[0] for entry in files})
    expected = timepoints * roi_count * lines
    timing_ok = line_time is not None and len(line_time) == expected and len(repeats) <= 1
    if timing_ok:
        assert line_time is not None
        tick, tick_origin = _line_tick(line_time, duration if duration_recorded else None)
        rows = line_time.reshape(timepoints, roi_count, lines) * tick
        roi_frame_times = rows.mean(axis=2)
        frame_times = rows.mean(axis=(1, 2))
        # One mosaic frame carries one time; its tiles were scanned this far either side.
        skew_ms = 1000.0 * float(np.max(np.ptp(roi_frame_times, axis=1))) / 2.0
        timing_source = f"line clock{tick_origin}, frame midpoint (tiles ±{skew_ms:.0f} ms)"
    else:
        frame_times = np.arange(timepoints, dtype=np.float64) * duration / timepoints
        roi_frame_times = None
        timing_source = rate_origin
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
        roi_files=tuple(entry[3] for entry in valid),
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
        roi_numbers=tuple(entry[0] for entry in valid),
        scanned_roi_count=roi_count,
    )


def analysis_file(folder: Path) -> Path | None:
    """The trial's lab mosaic analysis, when it has one."""
    files = sorted((folder / "roi_activity").glob("hybrid_mosaic_*_activity.mat"))
    return files[0] if files else None


def declared_green_channel(folder: Path) -> int | None:
    """The 1-based green channel the lab's analysis recorded for this trial.

    The mosaic analysis keeps ``correction_info`` as a cell of one struct per
    ribbon ROI; a per-ROI analysis keeps it as one struct. Either way the
    answer is used only when every struct agrees.
    """
    source = analysis_file(folder)
    if source is None:
        return None
    try:
        with h5py.File(source, "r") as handle:
            info = handle.get("correction_info")
            groups: list[h5py.Group] = []
            if isinstance(info, h5py.Group):
                groups.append(info)
            elif isinstance(info, h5py.Dataset) and info.dtype == h5py.ref_dtype:
                for reference in np.asarray(info[()]).reshape(-1):
                    target = handle[reference] if reference else None
                    if isinstance(target, h5py.Group):
                        groups.append(target)
            found = {
                int(np.asarray(group["green_channel"][()]).reshape(-1)[0])
                for group in groups
                if isinstance(group.get("green_channel"), h5py.Dataset)
            }
    except (OSError, KeyError, ValueError, TypeError):
        logger.warning("Could not read correction_info in %s", source, exc_info=True)
        return None
    return found.pop() if len(found) == 1 else None


_LOG_RECORDING = re.compile(
    r"Recording\s*@\s*(\d{2}-\d{2}-\d{2})\s*:(?P<rest>[^\r\n]*)", re.IGNORECASE
)
_LOG_RATE = re.compile(r"@\s*([0-9]+(?:\.[0-9]+)?)\s*Hz", re.IGNORECASE)


def logged_rate(folder: Path) -> float | None:
    """The nominal imaging rate the controller's ``Log.txt`` gives for this trial.

    The experiment folder's log has one ``Recording @ HH-MM-SS : ... @18 Hz``
    line per trial. It is rounded, so it is used only where the trial's own
    line clock and duration are missing -- never in their place.
    """
    try:
        text = (folder.parent / "Log.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for match in _LOG_RECORDING.finditer(text):
        if match.group(1) != folder.name:
            continue
        rate = _LOG_RATE.search(match.group("rest"))
        if rate is not None and float(rate.group(1)) > 0:
            return float(rate.group(1))
    return None


def experiment_trials(folder: Path) -> list[Path]:
    """The trial folders directly inside an experiment folder, in name order."""
    try:
        return sorted(child for child in folder.iterdir() if is_microscope_trial(child))
    except OSError:
        return []


def joined_starts(trials: list[MicroscopeTrial]) -> list[float]:
    """Where each trial starts when an experiment's trials play back to back.

    The controller's own analysis joins trials end to end with the gaps between
    them removed; each trial takes its recorded length, or longer if its last
    frame (plus one frame period) runs past that, so trials never overlap.
    """
    starts: list[float] = []
    position = 0.0
    for trial in trials:
        starts.append(position)
        frames = trial.frame_times
        period = float(np.median(np.diff(frames))) if len(frames) > 1 else 0.0
        position += max(trial.duration, float(frames[-1]) + period if len(frames) else 0.0)
    return starts


def _line_tick(ticks: np.ndarray, duration: float | None) -> tuple[float, str]:
    """Seconds per line-clock tick, checked against the trial's recorded duration.

    The controller documents a 200 MHz clock (5 ns). Its trials record their
    duration too, and the line clock spans almost all of it; should the two
    ever disagree by more than 1 % the clock is not 200 MHz on that rig, and
    the tick is taken from the recording rather than from the documentation.
    """
    span = float(ticks[-1] - ticks[0]) if len(ticks) > 1 else 0.0
    if duration is None or span <= 0:
        return _LINE_TICK_S, ""
    if abs(span * _LINE_TICK_S - duration) <= 0.01 * duration:
        return _LINE_TICK_S, ""
    logger.warning(
        "Line clock spans %.3f s at 5 ns per tick but the trial lasted %.3f s; "
        "using the recorded duration to set the tick.",
        span * _LINE_TICK_S,
        duration,
    )
    return duration / span, " (tick from the recorded duration)"
