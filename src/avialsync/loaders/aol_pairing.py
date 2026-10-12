"""AOL settings and the camera-to-trial pairing, through the generic plugin hooks.

The application knows none of this by name (D-220): it shows the settings
declared here under Preferences → AOL, hands their values to
:func:`configure_aol`, and asks :func:`find_aol_partner` and
:func:`aol_partner_targets` when the user picks **Align → Find Matching
Recording** with an AOL camera session open.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from avialsync.core.settings_schema import Setting
from avialsync.core.source import LoadedSource, PartnerSearch
from avialsync.loaders.aol_camera_join import (
    configure_camera_roots,
    match_tolerance,
    trial_roots,
)
from avialsync.loaders.aol_microscope_trial import is_microscope_trial, place_trials, read_trial
from avialsync.loaders.aol_rotary_calibration import configure_model
from avialsync.loaders.aol_trial_matching import day_directory, derive_utc_offset, match_trial

__all__ = [
    "AOL_PLUGIN_ID",
    "AOL_SETTINGS",
    "aol_partner_targets",
    "configure_aol",
    "find_aol_partner",
]

#: Shared by every AOL session scanner, so they share one set of settings.
AOL_PLUGIN_ID = "aol"

_GROUP = "AOL"

AOL_SETTINGS: tuple[Setting, ...] = (
    Setting(
        key="saved_data_folder",
        label="Microscope saved-data folder",
        group=_GROUP,
        default="",
        kind=str,
        help_text="Root folder containing dated microscope experiment folders.",
        legacy_key="aol/saved_data_folder",
    ),
    Setting(
        key="camera_data_folder",
        label="Camera saved-data folder",
        group=_GROUP,
        default="",
        kind=str,
        help_text=(
            "Root folder the camera PC saves trials in. Recordings are matched to trials "
            "by when they started, not by folder name. Leave empty when cameras are saved "
            "in or beside the trial folders, or in a tree beside the date folder."
        ),
        legacy_key="aol/camera_data_folder",
    ),
    Setting(
        key="match_tolerance_seconds",
        label="Camera-to-trial match tolerance",
        group=_GROUP,
        default=10.0,
        kind=float,
        minimum=0.0,
        maximum=60.0,
        help_text="Maximum camera-PC clock difference when matching a trial start.",
        legacy_key="aol/match_tolerance_seconds",
    ),
    Setting(
        key="wheel_calibration_model",
        label="Wheel calibration model",
        group=_GROUP,
        default="",
        kind=str,
        help_text=(
            "Optional wheel_rotation_v2 JSON calibration. It is offered in Props for review "
            "and is never applied automatically."
        ),
    ),
)


def _folder(value: object) -> list[Path]:
    text = str(value or "").strip()
    return [Path(text).expanduser()] if text else []


def configure_aol(values: dict[str, Any]) -> None:
    """Adopt the AOL settings' current values for the scans and searches that follow."""
    configure_camera_roots(
        _folder(values.get("camera_data_folder")),
        float(values.get("match_tolerance_seconds", 10.0)),
        _folder(values.get("saved_data_folder")),
    )
    configure_model(values.get("wheel_calibration_model"))


def find_aol_partner(camera_local_epoch: float) -> PartnerSearch:
    """Find the one microscope trial a camera session's start stamp belongs to."""
    roots = trial_roots()
    if not roots:
        return PartnerSearch(None, "Set the AOL microscope saved-data folder in Preferences.")
    day = day_directory(roots[0], camera_local_epoch)
    if not day.is_dir():
        return PartnerSearch(None, f"No microscope folder exists for {day}.")
    trials = []
    for experiment in sorted(day.glob("experiment_*")):
        if not experiment.is_dir():
            continue
        for folder in sorted(experiment.iterdir()):
            if is_microscope_trial(folder):
                trials.append(read_trial(folder, verify=False))
    if not trials:
        return PartnerSearch(None, f"No microscope trials were found for {day}.")
    date = dt.datetime.fromtimestamp(camera_local_epoch, tz=dt.UTC).date()
    zone_offset = derive_utc_offset(trials, date)
    if zone_offset is None:
        return PartnerSearch(
            None, f"The trials for {day} imply different time-zone offsets; nothing was paired."
        )
    match = match_trial(trials, camera_local_epoch, zone_offset, match_tolerance())
    if match is None:
        return PartnerSearch(
            None, f"No unique trial is within {day}'s camera match tolerance; nothing was paired."
        )
    camera_local = dt.datetime.fromtimestamp(match.camera_local_epoch, tz=dt.UTC)
    trial_utc = dt.datetime.fromtimestamp(match.trial.start_epoch, tz=dt.UTC)
    zone = match.controller_utc_offset_s
    details = " ".join(
        (
            f"Camera start (local): {camera_local:%Y-%m-%d %H:%M:%S}.",
            f"Trial STARTTIME (UTC): {trial_utc:%Y-%m-%d %H:%M:%S}.",
            f"Derived controller offset: UTC{zone / 3600:+g}; "
            f"clock residual: {match.residual_s:+.3f} s.",
            "Camera PC and controller PC are assumed to use the same time zone.",
        )
    )
    return PartnerSearch(
        match.trial.folder,
        f"Found trial {match.trial.folder.name}.",
        details=details,
        duration=match.trial.duration,
        data={
            "start_epoch": match.trial.start_epoch,
            "utc_offset_s": zone,
            "residual_s": match.residual_s,
            "day": str(day),
        },
    )


def aol_partner_targets(
    match: PartnerSearch, loaded: Sequence[LoadedSource]
) -> list[tuple[str, float]]:
    """Loaded sources of the matched trial or of its joined experiment, with each one's zero.

    Each entry is ``(source id, seconds from the matched trial's zero to this
    source's own zero)``. A joined experiment places each trial at its start
    on the session timeline (``place_trials``), so its zero is the matched
    trial's start earlier.
    """
    if match.path is None:
        return []
    folder = Path(match.path)
    joined: dict[Path, float] = {}
    targets: list[tuple[str, float]] = []
    for source in loaded:
        members = [Path(item) for item in source.config.get("trial_folders") or ()]
        if folder not in members:
            continue
        if not joined:
            starts = source.config.get("trial_starts")
            if not starts or len(starts) != len(members):
                # A session saved before starts were stored: derive them once.
                plan = place_trials([read_trial(member, verify=False) for member in members])
                if len(plan.kept) != len(members):
                    continue
                starts = plan.starts
            joined = dict(zip(members, (float(start) for start in starts), strict=True))
        targets.append((source.source_id, -joined[folder]))

    def zero_of(trial: Path) -> float | None:
        if joined:
            return joined[trial] - joined[folder] if trial in joined else None
        return 0.0 if trial == folder else None

    for source in loaded:
        if source.config.get("trial_folders") or not source.config.get("trial_folder"):
            continue
        zero = zero_of(Path(str(source.config["trial_folder"])))
        if zero is not None:
            targets.append((source.source_id, zero))
    return targets
