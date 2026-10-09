"""Session scanner for AOL microscope trials and experiment folders."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from avialsync.core.source import SessionItem, SessionLayout, SessionSource
from avialsync.loaders.aol_cell_roi_grid import AOLCellRoiGridSource
from avialsync.loaders.aol_microscope_trial import is_microscope_trial, read_trial
from avialsync.loaders.aol_ribbon_scan import AOLRibbonScanSource
from avialsync.loaders.aol_roi_trace import AOLRoiTraceLoader

_LOG_RECORDING = re.compile(r"Recording\s*@\s*([^\r\n]+)", re.IGNORECASE)


def _direct_trials(folder: Path) -> list[Path]:
    try:
        return sorted(child for child in folder.iterdir() if is_microscope_trial(child))
    except OSError:
        return []


def _log_note(folder: Path) -> str:
    """Summarize recording lines from optional free-text acquisition notes."""
    try:
        text = (folder / "Log.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [match.group(1).strip() for match in _LOG_RECORDING.finditer(text)]
    return " · ".join(lines[:3])


class AOLMicroscopeTrialSource(SessionSource):
    """Load one controller trial through ordinary session and imaging routes."""

    @classmethod
    def display_name(cls) -> str:
        return "AOL Microscope Trial"

    @classmethod
    def can_open(cls, path: Path) -> float:
        if is_microscope_trial(path):
            return 1.0
        return 0.8 if _direct_trials(path) else 0.0

    def scan(self, path: Path, registry: Any) -> SessionLayout:
        """Lay out one trial, or expose experiment trials as an exclusive picker."""
        trials = [path] if is_microscope_trial(path) else _direct_trials(path)
        if not trials:
            return SessionLayout()
        is_experiment = len(trials) > 1 or trials[0] != path
        group = str(path) if is_experiment else ""
        items: list[SessionItem] = []
        warnings: list[str] = []
        starts: list[float] = []
        for folder in trials:
            trial = read_trial(folder)
            starts.append(trial.start_epoch)
            notes = _log_note(folder)
            suffix = f" — {notes}" if notes else ""
            label = f"{folder.name} — {len(trial.roi_files)} ribbon ROIs{suffix}"
            config: dict[str, object] = {"trial_folder": str(folder)}
            if group:
                config["_exclusive_group"] = group
            items.append(
                SessionItem(
                    path=folder,
                    loader=AOLRibbonScanSource,
                    config=config,
                    label=label,
                    source_epoch=trial.start_epoch if trial.start_epoch > 0 else None,
                )
            )
            activity_files = sorted((folder / "roi_activity").glob("hybrid_mosaic_*_activity.mat"))
            if activity_files:
                activity_file = activity_files[0]
                shared_config: dict[str, object] = {
                    "trial_folder": str(folder),
                    "activity_file": str(activity_file),
                }
                items.append(
                    SessionItem(
                        path=activity_file,
                        loader=AOLCellRoiGridSource,
                        config=shared_config,
                        label=f"{folder.name} — cell ROIs (lab ROI analysis)",
                        source_epoch=trial.start_epoch if trial.start_epoch > 0 else None,
                    )
                )
                items.append(
                    SessionItem(
                        path=activity_file.parent,
                        loader=AOLRoiTraceLoader,
                        config={**shared_config, "series": "roi_traces"},
                        label=f"{folder.name} — cell ROI traces",
                        source_epoch=trial.start_epoch if trial.start_epoch > 0 else None,
                    )
                )
            warnings.extend(f"{folder.name}: {warning}" for warning in trial.warnings)
        if is_experiment:
            session_epoch = 0.0
        else:
            session_epoch = starts[0] if starts and starts[0] > 0 else 0.0
        return SessionLayout(
            items=items,
            session_epoch=session_epoch,
            anchor_epoch=session_epoch,
            warnings=warnings,
        )
