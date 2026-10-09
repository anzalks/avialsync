"""Session scanner for AOL microscope trials and experiment folders.

A trial folder is one session: its ribbon scan as the reconstructed tree,
its dendrite ROIs (``thin_mask.mat``) on that tree, the lab's analysis cell
ROIs and traces when it has them, and the trial's cameras when they were saved
with it -- each camera's frame 0 on the trial's trigger.

An experiment folder is one long session, joined back to back the way the
controller's own analysis joins trials
(:func:`~avialsync.loaders.aol_microscope_trial.joined_starts`): one ribbon
source and one dendrite-ROI source across every trial that shares the first
trial's scan, each camera's per-trial recordings as one video
(:mod:`~avialsync.loaders.aol_camera_join`), and each analysed trial's cell
items at that trial's place. A trial scanned differently cannot be joined and
is reported, not dropped silently (D-085).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from avialsync.core.source import SessionItem, SessionLayout, SessionSource
from avialsync.loaders.aol_camera_join import (
    AOLJoinedCameraSource,
    camera_roots,
    camera_segments,
    joined_source_id,
)
from avialsync.loaders.aol_cell_roi_grid import AOLCellRoiGridSource
from avialsync.loaders.aol_microscope_trial import (
    MicroscopeTrial,
    analysis_file,
    experiment_trials,
    is_microscope_trial,
    joined_starts,
    read_trial,
)
from avialsync.loaders.aol_ribbon_scan import AOLRibbonScanSource
from avialsync.loaders.aol_roi_trace import AOLRoiTraceLoader
from avialsync.loaders.video_standard import VideoStandardLoader

_LOG_RECORDING = re.compile(r"Recording\s*@\s*([^\r\n]+)", re.IGNORECASE)


def _log_note(folder: Path) -> str:
    """This trial's line from the controller's free-text ``Log.txt``, if any."""
    try:
        text = (folder.parent / "Log.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for match in _LOG_RECORDING.finditer(text):
        line = match.group(1).strip()
        if line.startswith(folder.name):
            return line[len(folder.name) :].lstrip(" :-").strip()
    return ""


def _at(epoch: float, offset: float = 0.0) -> float | None:
    """A source epoch, or no claim when the trial has no ``STARTTIME``."""
    return epoch + offset if epoch > 0 else None


def _scan_signature(trial: MicroscopeTrial) -> tuple[Any, ...]:
    return (trial.roi_numbers, trial.channels, trial.lines, trial.width)


def _analysis_items(trial: MicroscopeTrial, epoch: float | None) -> list[SessionItem]:
    """The lab's cell ROIs and their traces, when this trial was analysed."""
    activity = analysis_file(trial.folder)
    if activity is None:
        return []
    config: dict[str, object] = {"trial_folder": str(trial.folder), "activity_file": str(activity)}
    return [
        SessionItem(
            path=activity,
            loader=AOLCellRoiGridSource,
            config=config,
            label=f"{trial.folder.name} — cell ROIs (lab ROI analysis)",
            source_epoch=epoch,
        ),
        SessionItem(
            path=activity.parent,
            loader=AOLRoiTraceLoader,
            config={**config, "series": "roi_traces"},
            label=f"{trial.folder.name} — cell ROI traces",
            source_epoch=epoch,
        ),
    ]


def _imaging_items(
    trials: list[MicroscopeTrial], path: Path, config: dict[str, object], name: str
) -> list[SessionItem]:
    """The ribbon mosaic and, when masks exist, its dendrite ROIs."""
    first = trials[0]
    items = [
        SessionItem(
            path=path,
            loader=AOLRibbonScanSource,
            config=config,
            label=f"{name} — {len(first.roi_files)} ribbon ROIs, reconstructed tree",
            source_epoch=_at(first.start_epoch),
        )
    ]
    if (first.folder / "thin_mask.mat").is_file():
        items.append(
            SessionItem(
                path=first.folder / "thin_mask.mat",
                loader=AOLRibbonScanSource,
                config={**config, "mask": "thin"},
                label=f"{name} — dendrite ROIs (thin mask)",
                source_epoch=_at(first.start_epoch),
            )
        )
    return items


def camera_items(
    trials: Sequence[MicroscopeTrial], roots: Sequence[Path] | None = None
) -> list[SessionItem]:
    """Each camera found for these trials, placed on the trials' trigger.

    One trial: its recordings directly, frame 0 on the trial's ``STARTTIME``.
    Several: one joined video per camera on the back-to-back timeline. Cameras
    are looked for in the trial folders and under the configured camera data
    folders (:func:`~avialsync.loaders.aol_camera_join.camera_roots`).
    """
    roots = camera_roots() if roots is None else roots
    if not trials:
        return []
    starts = joined_starts(list(trials))
    lengths = [
        (starts[index + 1] if index + 1 < len(starts) else starts[index] + trial.duration)
        - starts[index]
        for index, trial in enumerate(trials)
    ]
    found = camera_segments([t.folder for t in trials], starts, lengths, roots)
    epoch = _at(trials[0].start_epoch)
    items: list[SessionItem] = []
    for camera, segments in sorted(found.items()):
        if len(trials) == 1:
            segment = segments[0]
            items.append(
                SessionItem(
                    path=segment.video,
                    loader=VideoStandardLoader,
                    config={
                        "frame_timestamps": str(segment.timing),
                        "frame_timestamps_format": "aol_relative_ms",
                        "start_time": 0.0,
                    },
                    label=f"{segment.video.name} — camera, {trials[0].folder.name} trigger",
                    source_epoch=epoch,
                )
            )
            continue
        items.append(
            SessionItem(
                path=joined_source_id(segments),
                loader=AOLJoinedCameraSource,
                config={"segments": [segment.to_config() for segment in segments]},
                label=f"{camera} — camera, {len(segments)} of {len(trials)} trials joined",
                source_epoch=epoch,
            )
        )
    return items


class AOLMicroscopeTrialSource(SessionSource):
    """Load one controller trial, or a whole experiment back to back."""

    @classmethod
    def display_name(cls) -> str:
        return "AOL Microscope Trial"

    @classmethod
    def can_open(cls, path: Path) -> float:
        if is_microscope_trial(path):
            return 1.0
        return 0.8 if experiment_trials(path) else 0.0

    def scan(self, path: Path, registry: Any) -> SessionLayout:
        """Lay out one trial, or join an experiment's trials into one session."""
        if is_microscope_trial(path):
            # Names and timing only: pixels are verified by the source that reads them.
            trial = read_trial(path, verify=False)
            note = _log_note(path)
            name = f"{path.name} ({note})" if note else path.name
            items = _imaging_items([trial], path, {"trial_folder": str(path)}, name)
            items += _analysis_items(trial, _at(trial.start_epoch))
            items += camera_items([trial])
            epoch = trial.start_epoch if trial.start_epoch > 0 else 0.0
            return SessionLayout(
                items=items,
                session_epoch=epoch,
                anchor_epoch=epoch,
                warnings=[f"{path.name}: {warning}" for warning in trial.warnings],
            )
        folders = experiment_trials(path)
        if not folders:
            return SessionLayout()
        trials = sorted(
            (read_trial(folder, verify=False) for folder in folders),
            key=lambda trial: (trial.start_epoch, trial.folder.name),
        )
        warnings = [f"{t.folder.name}: {w}" for t in trials for w in t.warnings]
        joined = [t for t in trials if _scan_signature(t) == _scan_signature(trials[0])]
        for trial in trials:
            if trial not in joined:
                warnings.append(
                    f"{trial.folder.name} was scanned differently and is not joined; "
                    "open its folder on its own."
                )
        starts = joined_starts(joined)
        # Stored so placing the experiment later costs no file reads on the UI thread.
        config: dict[str, object] = {
            "trial_folders": [str(t.folder) for t in joined],
            "trial_starts": starts,
        }
        items = _imaging_items(joined, path, config, f"{path.name} — {len(joined)} trials")
        first_epoch = joined[0].start_epoch
        for trial, start in zip(joined, starts, strict=True):
            items += _analysis_items(trial, _at(first_epoch, start))
        items += camera_items(joined)
        epoch = first_epoch if first_epoch > 0 else 0.0
        return SessionLayout(
            items=items, session_epoch=epoch, anchor_epoch=epoch, warnings=warnings
        )
