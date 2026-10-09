"""Find, review and explicitly accept an AOL camera-to-trial placement."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import TYPE_CHECKING, Any

from avialsync.core.commands import SetSourceMappingsCommand, SourceMappingChange
from avialsync.core.settings_schema import setting_for
from avialsync.engine.aol_trial_search import AOLTrialSearchWorker
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


def _expected_paths(folder: Path) -> list[str]:
    expected = [str(folder)]
    activity = sorted((folder / "roi_activity").glob("hybrid_mosaic_*_activity.mat"))
    if activity:
        expected.extend((str(activity[0]), str(activity[0].parent)))
    return expected


def _trial_sources_loaded(window: MainWindow, folder: Path) -> bool:
    expected = _expected_paths(folder)
    active = set(window.imaging_pane.source_paths()) | set(window._sensor_cache_dirs)
    return all(path in active for path in expected)


def trial_source_loaded(window: MainWindow) -> None:
    """Offer the pending match after every source in its chosen trial is ready."""
    result = window.session_runtime.pending_aol_pair
    if not isinstance(result, dict) or result.get("status") != "matched":
        return
    folder = Path(str(result["folder"]))
    if _trial_sources_loaded(window, folder):
        _offer_acceptance(window, result)


def _duration_summary(window: MainWindow, trial_duration: float) -> str:
    durations = [end - start for start, end in window._video_source_bounds.values() if end > start]
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


def accept_trial_pair(window: MainWindow, result: dict[str, Any]) -> None:
    """Place the loaded trial's sources at camera frame zero as one command."""
    folder = Path(str(result["folder"]))
    if not _trial_sources_loaded(window, folder):
        window.notifications.show_warning(
            tr("Load the selected trial sources before accepting its alignment.")
        )
        return
    changes = []
    active = set(window.imaging_pane.source_paths()) | set(window._sensor_cache_dirs)
    for source_id in _expected_paths(folder):
        if source_id not in active:
            continue
        before = window._mutations.source_mapping(source_id)
        residual = -window.base_offset(source_id)
        changes.append(SourceMappingChange(source_id, before, (residual, 0.0)))
    if not changes:
        window.notifications.show_warning(tr("No loaded trial source can be aligned."))
        return
    window.document.execute(
        SetSourceMappingsCommand(tuple(changes), display_name=folder.name), window._mutations
    )
    window.session_runtime.pending_aol_pair = None
    window.notifications.show_success(
        tr("Placed {trial} at the shared camera trigger start.").format(trial=folder.name)
    )
