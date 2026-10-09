"""Session scanner for AOL microscope trials and experiment folders.

A trial folder is one session: its ribbon scan as the reconstructed tree,
its dendrite ROIs (``thin_mask.mat``) on that tree, and, when the lab has
analysed it, the analysis cell ROIs and their traces.

An experiment folder is one long session: every trial that shares the first
trial's scan is joined into one ribbon source and one dendrite-ROI source on
the trials' own ``STARTTIME`` clock, so the experiment plays end to end with
its real gaps. Analysed trials add their cell ROIs and traces at their own
start. A trial scanned differently cannot be joined and is reported, not
dropped silently (D-085).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from avialsync.core.source import SessionItem, SessionLayout, SessionSource
from avialsync.loaders.aol_cell_roi_grid import AOLCellRoiGridSource
from avialsync.loaders.aol_microscope_trial import (
    MicroscopeTrial,
    analysis_file,
    experiment_trials,
    is_microscope_trial,
    read_trial,
)
from avialsync.loaders.aol_ribbon_scan import AOLRibbonScanSource
from avialsync.loaders.aol_roi_trace import AOLRoiTraceLoader

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


def _epoch(trial: MicroscopeTrial) -> float | None:
    return trial.start_epoch if trial.start_epoch > 0 else None


def _scan_signature(trial: MicroscopeTrial) -> tuple[Any, ...]:
    return (trial.roi_numbers, trial.channels, trial.lines, trial.width)


def _analysis_items(trial: MicroscopeTrial) -> list[SessionItem]:
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
            source_epoch=_epoch(trial),
        ),
        SessionItem(
            path=activity.parent,
            loader=AOLRoiTraceLoader,
            config={**config, "series": "roi_traces"},
            label=f"{trial.folder.name} — cell ROI traces",
            source_epoch=_epoch(trial),
        ),
    ]


def _imaging_items(
    trials: list[MicroscopeTrial], path: Path, config: dict[str, object], name: str
) -> list[SessionItem]:
    """The ribbon mosaic and, when masks exist, its dendrite ROIs."""
    first = trials[0]
    rois = len(first.roi_files)
    items = [
        SessionItem(
            path=path,
            loader=AOLRibbonScanSource,
            config=config,
            label=f"{name} — {rois} ribbon ROIs, reconstructed tree",
            source_epoch=_epoch(first),
        )
    ]
    if (first.folder / "thin_mask.mat").is_file():
        items.append(
            SessionItem(
                path=first.folder / "thin_mask.mat",
                loader=AOLRibbonScanSource,
                config={**config, "mask": "thin"},
                label=f"{name} — dendrite ROIs (thin mask)",
                source_epoch=_epoch(first),
            )
        )
    return items


class AOLMicroscopeTrialSource(SessionSource):
    """Load one controller trial, or a whole experiment end to end."""

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
            items += _analysis_items(trial)
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
        if any(trial.start_epoch <= 0 for trial in joined) and len(joined) > 1:
            warnings.append("Some trials have no STARTTIME; the experiment cannot be joined.")
            joined = joined[:1]
        for trial in trials:
            if trial not in joined:
                warnings.append(
                    f"{trial.folder.name} was scanned differently and is not joined; "
                    "open its folder on its own."
                )
        config: dict[str, object] = {"trial_folders": [str(t.folder) for t in joined]}
        name = f"{path.name} — {len(joined)} trials"
        items = _imaging_items(joined, path, config, name)
        for trial in joined:
            items += _analysis_items(trial)
        epoch = joined[0].start_epoch if joined[0].start_epoch > 0 else 0.0
        return SessionLayout(
            items=items, session_epoch=epoch, anchor_epoch=epoch, warnings=warnings
        )
