"""Find, review and explicitly accept an AOL camera-to-trial placement."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import TYPE_CHECKING, Any

from avialsync.core.commands import SetSourceMappingsCommand, SourceMappingChange
from avialsync.core.settings_schema import setting_for
from avialsync.engine.aol_trial_search import AOLTrialSearchWorker
from avialsync.loaders.aol_microscope_trial import joined_starts, read_trial
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

_SAVED_FOLDER = setting_for("aol/saved_data_folder")
_MATCH_TOLERANCE = setting_for("aol/match_tolerance_seconds")


def can_find_trial(window: MainWindow) -> bool:
    """Whether the action has the AOL camera clock and a configured search root."""
    if _SAVED_FOLDER is None:
        return False
    from avialsync.ui.preferences_dialog import read_setting

    return bool(
        window.session_runtime.aol_camera_start_epoch and str(read_setting(_SAVED_FOLDER)).strip()
    )


def find_trial(window: MainWindow) -> None:
    """Search the dated microscope folder on a registered worker."""
    if not can_find_trial(window) or _SAVED_FOLDER is None or _MATCH_TOLERANCE is None:
        window.notifications.show_warning(
            tr("Load an AOL camera session and set its microscope folder in Preferences.")
        )
        return
    from avialsync.ui.preferences_dialog import read_setting

    root = Path(str(read_setting(_SAVED_FOLDER))).expanduser()
    tolerance = float(read_setting(_MATCH_TOLERANCE))
    worker = AOLTrialSearchWorker(root, window.session_runtime.aol_camera_start_epoch, tolerance)

    def wire(thread) -> None:
        worker.finished.connect(
            on_ui_thread(lambda result: _search_finished(window, result), window)
        )
        worker.error.connect(
            on_ui_thread(
                lambda message: window.notifications.show_error(
                    tr("Could not search for a microscope trial"), details=message
                ),
                window,
            )
        )
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)

    window._run_job(worker, label=tr("Finding microscope trial"), configure=wire)


def _search_finished(window: MainWindow, result: object) -> None:
    if not isinstance(result, dict):
        window.notifications.show_warning(tr("The microscope search returned no match."))
        return
    status = result.get("status")
    if status != "matched":
        messages = {
            "missing_day": tr("No microscope folder exists for {day}.").format(
                day=result.get("day")
            ),
            "no_trials": tr("No microscope trials were found for {day}.").format(
                day=result.get("day")
            ),
            "inconsistent_zone": tr(
                "The trials for {day} imply different time-zone offsets; nothing was paired."
            ).format(day=result.get("day")),
            "ambiguous_or_distant": tr(
                "No unique trial is within {day}'s camera match tolerance; nothing was paired."
            ).format(day=result.get("day")),
        }
        window.notifications.show_warning(
            messages.get(str(status), tr("No unique trial was found."))
        )
        return
    window.session_runtime.pending_aol_pair = result
    folder = Path(str(result["folder"]))
    if not _trial_sources_loaded(window, folder):
        window.notifications.show_warning(
            tr("Found trial {trial}. Load its sources, then accept alignment.").format(
                trial=folder.name
            ),
            action_label=tr("Load trial"),
            on_action=lambda: window.open_path(folder),
            on_dismiss=lambda: setattr(window.session_runtime, "pending_aol_pair", None),
        )
        return
    _offer_acceptance(window, result)


def _pair_targets(window: MainWindow, folder: Path) -> list[tuple[str, float]]:
    """Loaded sources of the matched trial or of its joined experiment, with each one's zero.

    Each entry is ``(source id, seconds from the matched trial's zero to this
    source's own zero)``. A joined experiment plays its trials back to back
    (``joined_starts``), so its zero is the matched trial's joined start
    earlier.
    """
    joined: dict[Path, float] = {}
    targets: list[tuple[str, float]] = []
    for source_id in window.imaging_pane.source_paths():
        _loader, config, _mapping = window.imaging_pane.source_config(source_id)
        members = [Path(item) for item in config.get("trial_folders") or ()]
        if folder not in members:
            continue
        if not joined:
            starts = config.get("trial_starts")
            if not starts or len(starts) != len(members):
                # A session saved before starts were stored: derive them once.
                starts = joined_starts([read_trial(member, verify=False) for member in members])
            joined = dict(zip(members, (float(start) for start in starts), strict=True))
        targets.append((source_id, -joined[folder]))

    def zero_of(trial: Path) -> float | None:
        if joined:
            return joined[trial] - joined[folder] if trial in joined else None
        return 0.0 if trial == folder else None

    for source_id in window.imaging_pane.source_paths():
        _loader, config, _mapping = window.imaging_pane.source_config(source_id)
        if config.get("trial_folders") or not config.get("trial_folder"):
            continue
        zero = zero_of(Path(str(config["trial_folder"])))
        if zero is not None:
            targets.append((source_id, zero))
    return targets


def _trial_sources_loaded(window: MainWindow, folder: Path) -> bool:
    return bool(_pair_targets(window, folder))


def trial_source_loaded(window: MainWindow) -> None:
    """Offer the pending match after every source in its chosen trial is ready."""
    result = window.session_runtime.pending_aol_pair
    if not isinstance(result, dict) or result.get("status") != "matched":
        return
    folder = Path(str(result["folder"]))
    if _trial_sources_loaded(window, folder):
        _offer_acceptance(window, result)


def _duration_summary(window: MainWindow, trial_duration: float) -> str:
    durations = [end - start for start, end in window.video_master_spans().values() if end > start]
    if not durations:
        return tr("Camera duration: unavailable; trial duration: {seconds:.2f} s.").format(
            seconds=trial_duration
        )
    camera_duration = max(durations)
    warning = camera_duration < trial_duration or camera_duration - trial_duration > 1.0
    text = tr("Camera duration: {camera:.2f} s; trial duration: {trial:.2f} s.").format(
        camera=camera_duration, trial=trial_duration
    )
    return text + (
        " " + tr("Duration differs by more than the expected camera overrun.") if warning else ""
    )


def _offer_acceptance(window: MainWindow, result: dict[str, Any]) -> None:
    camera_local = dt.datetime.fromtimestamp(float(result["camera_local_epoch"]), tz=dt.UTC)
    trial_utc = dt.datetime.fromtimestamp(float(result["start_epoch"]), tz=dt.UTC)
    zone = int(result["utc_offset_s"])
    zone_text = f"UTC{zone / 3600:+g}"
    residual = float(result["residual_s"])
    details = " ".join(
        (
            tr("Camera start (local): {time}.").format(
                time=camera_local.strftime("%Y-%m-%d %H:%M:%S")
            ),
            tr("Trial STARTTIME (UTC): {time}.").format(
                time=trial_utc.strftime("%Y-%m-%d %H:%M:%S")
            ),
            tr("Derived controller offset: {zone}; clock residual: {residual:+.3f} s.").format(
                zone=zone_text, residual=residual
            ),
            tr("Camera PC and controller PC are assumed to use the same time zone."),
            _duration_summary(window, float(result["duration"])),
        )
    )
    window.notifications.show_warning(
        tr("Align {trial} to the camera trigger start?").format(
            trial=Path(str(result["folder"])).name
        ),
        details=details,
        action_label=tr("Accept alignment"),
        on_action=lambda: accept_trial_pair(window, result),
        on_dismiss=lambda: setattr(window.session_runtime, "pending_aol_pair", None),
    )


def _camera_zero(window: MainWindow) -> float:
    """Master time of the cameras' shared first frame (the controller's trigger)."""
    starts = [start for start, _end in window.video_master_spans().values()]
    return min(starts) if starts else 0.0


def accept_trial_pair(window: MainWindow, result: dict[str, Any]) -> None:
    """Place the matched trial's zero on camera frame zero, as one undoable command.

    A joined experiment moves as one: its own zero is its first trial's, so it
    lands the matched trial's joined start earlier.
    """
    folder = Path(str(result["folder"]))
    targets = _pair_targets(window, folder)
    if not targets:
        window.notifications.show_warning(
            tr("Load the selected trial sources before accepting its alignment.")
        )
        return
    camera_zero = _camera_zero(window)
    changes = []
    for source_id, zero_after_match in targets:
        # t_source = t_master + offset, so a source's zero sits at master -offset.
        wanted = -(camera_zero + zero_after_match)
        before = window._mutations.source_mapping(source_id)
        residual = wanted - window.base_offset(source_id)
        changes.append(SourceMappingChange(source_id, before, (residual, 0.0)))
    window.document.execute(
        SetSourceMappingsCommand(tuple(changes), display_name=folder.name), window._mutations
    )
    window.session_runtime.pending_aol_pair = None
    window.notifications.show_success(
        tr("Placed {trial} at the shared camera trigger start.").format(trial=folder.name)
    )
