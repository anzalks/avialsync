"""Alignment by hand and by evidence: nudges, badges, trigger files, the wizard.

Moved from MainWindow (WINDOW_COMPOSITION_PLAN A8), which keeps one delegator
per function (D-066) and the small public queries its collaborators call.
Worker results and wizard signals still reach the window's own methods, so
delivery stays on the UI thread; the moved code's private accesses are in the
boundary baseline under D-248. Imports that were local stay local, so a test
that patches the module they come from still intercepts them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from PySide6.QtCore import QThread

from avialsync.core.timeline import TimeMap
from avialsync.ui import tracking_timing
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.core.session import TriggerEntry
    from avialsync.ui.main_window import MainWindow


def nudge_alignment(window: MainWindow, direction: int) -> None:
    """Shift the focused video by one frame against the master clock.

    Aligning by eye is the most common real workflow and had no direct
    path: the only control was a spin box with 0.05 s steps, which is more
    than a frame at any rate this application targets. A frame is the unit
    the user is actually judging.
    """
    path = window._focused_video_path()
    if path is None:
        if window.video_grid.pane_paths():
            # Several cameras and none chosen. Guessing moved the wrong
            # one silently, which is worse than saying so.
            window.notifications.show_warning(
                tr("Click the camera you want to move first, or open one fullscreen.")
            )
        else:
            window.notifications.show_warning(tr("Load a video before nudging its alignment."))
        return

    step = _frame_step(window, path, direction)
    offset, _drift = window._recorded_mappings.get(path, (0.0, 0.0))
    new_offset = offset + direction * step

    window.sidebar.set_video_offset(path, new_offset)
    window._on_video_offset_changed(path, new_offset)
    window.transport.set_status(
        f"{Path(path).name} offset {new_offset:+.3f} s ({direction:+d} frame)", "info"
    )


def _frame_step(window: MainWindow, path: str, direction: int) -> float:
    """One frame of *path* in master seconds, measured where the playhead is."""
    fps = window._video_fps.get(path, 0.0)
    step = (1.0 / fps) if fps > 0 else 0.001
    frames = window._video_frame_times.get(path)
    if frames is None or len(frames) <= 1:
        return step
    from avialsync.core.video_timing import frame_index_at
    from avialsync.ui.sync_lifecycle import source_mapping

    mapping = source_mapping(window, path)
    if mapping is None:
        return step
    index = frame_index_at(frames, mapping.to_source(window.clock.state.t))
    other = max(0, min(index + direction, len(frames) - 1))
    if other == index:
        other = max(0, min(index - direction, len(frames) - 1))
    return abs(
        mapping.to_master(float(frames[other])) - mapping.to_master(float(frames[index]))
    ) * (1.0 + mapping.drift_ms_per_hour / 3_600_000.0)


def alignment_confidence(window: MainWindow, path: str) -> str:
    """Describe current accepted evidence without overstating its method."""
    for entry in window._sync_provenance:
        if entry.target_id != path:
            continue
        if entry.superseded_by:
            return f"alignment superseded: {entry.superseded_by}"
        reference = Path(entry.reference_id).name or entry.reference_id
        return f"aligned to {reference}: {window._describe_provenance(entry)}"
    return "no accepted alignment"


def refresh_alignment_badges(window: MainWindow) -> None:
    """Push each source's alignment state onto its badge.

    Event-driven, from the four things that can change it: accepting a fit,
    moving a source by hand, removing a source, and restoring a session.
    Never sampled on the clock tick -- this walks every loaded source, and
    doing that sixty times a second to display a string that changes a
    handful of times per session would block the UI thread for nothing.
    """
    for path in window.video_grid.pane_paths():
        summary = window.alignment_confidence(path)
        window.sidebar.set_video_alignment(path, summary, accepted=window._has_live_alignment(path))
    for path in window._sensor_cache_dirs:
        summary = window.alignment_confidence(path)
        window.sidebar.set_sensor_alignment(
            path, summary, accepted=window._has_live_alignment(path)
        )

    from avialsync.ui.sync_status import refresh_cards

    refresh_cards(window)
    window._refresh_action_availability()


def open_trigger_evidence(window: MainWindow) -> None:
    """Load a trigger file and record what the user says its lines are."""
    from PySide6.QtWidgets import QFileDialog

    from avialsync.core.errors import FileUnreadableError

    chosen, _ = QFileDialog.getOpenFileName(
        window,
        tr("Open Trigger Evidence"),
        "",
        tr("Trigger and TTL files (*.csv *.tsv *.txt);;All files (*)"),
    )
    if not chosen:
        return
    path = Path(chosen)

    provider_cls = window._registry.trigger_for(path)
    if provider_cls is None:
        window.report_failure(
            FileUnreadableError(
                f"Nothing installed can read {path.name} as trigger evidence. A "
                "trigger file needs a time column and at least one logical line."
            )
        )
        return

    suggestions = provider_cls.suggest_trains(path)
    if not suggestions or not suggestions[0].get("trains"):
        window.report_failure(
            FileUnreadableError(
                f"{path.name} has no columns that look like trigger lines. Trigger "
                "evidence is a time column plus a line that goes high and low, or a "
                "column of event timestamps."
            )
        )
        return

    from avialsync.ui.trigger_dialog import TriggerEvidenceDialog

    dialog = TriggerEvidenceDialog(
        path, suggestions[0], list(window.video_grid.pane_paths()), window
    )
    if dialog.exec() != dialog.DialogCode.Accepted:
        return
    config = dialog.config()
    if not config["trains"]:
        window.notifications.show_warning(tr("No trigger lines were selected."))
        return
    window._start_trigger_read(provider_cls(), path, config)


def start_trigger_read(
    window: MainWindow, source: object, path: Path, config: dict[str, Any]
) -> None:
    """Read the declared trains off the UI thread.

    The configuration is kept beside the result, because it -- not the
    trains -- is what a session stores: the declaration of which column is
    a strobe is the fact the user supplied and the file cannot.
    """
    window._trigger_configs[str(path)] = dict(config)
    from avialsync.core.errors import FileUnreadableError
    from avialsync.engine.trigger_worker import TriggerReadWorker

    worker = TriggerReadWorker(cast(Any, source), path, config)

    def configure(_thread: QThread) -> None:
        # Connected before the thread runs: a worker that finishes first
        # would otherwise emit into nothing. Wrapped because a
        # lambda is not a QObject, so the connection would be direct and
        # both handlers would touch widgets from the worker thread.
        worker.finished.connect(
            on_ui_thread(lambda results: window._on_trigger_trains_read(str(path), results), window)
        )
        worker.error.connect(
            on_ui_thread(
                lambda message: window.report_failure(
                    FileUnreadableError(f"{path.name}: {message}")
                ),
                window,
            )
        )

    window._run_job(worker, label=f"Reading triggers from {path.name}", configure=configure)


def on_trigger_trains_read(window: MainWindow, path: str, results: object) -> None:
    """Register read trains as evidence the alignment wizard can offer."""
    if not isinstance(results, list):
        return
    window._trigger_trains[path] = list(results)
    from avialsync.ui.sync_lifecycle import restore_adjustment

    restore_adjustment(window, path)
    drops = sum(len(getattr(train, "drops", ())) for train in results)
    summary = tr("Trigger trains from {name}: {count}").format(
        count=len(results), name=Path(path).name
    )
    if drops:
        # Said on arrival rather than discovered later: a train that skips
        # beats is the evidence that frames were lost, and it is the reason
        # an index-paired mapping would be wrong.
        summary = tr("{summary} — {drops} gap(s) in the pulses").format(
            summary=summary, drops=drops
        )
    window.notifications.show_success(summary)
    window._refresh_action_availability()
    if window._sync_wizard is not None:
        window._sync_wizard.invalidate_sources()


def evidence_span(window: MainWindow, path: str) -> tuple[float, float] | None:
    """First and last accepted sync point for *path*, or None.

    Superseded evidence is not a span: the source has been moved off it by
    hand, so nothing between those points is measured any more.
    """
    for entry in window._sync_provenance:
        if entry.target_id != path or entry.superseded_by or not entry.matches:
            continue
        times = [float(match["reference_time"]) for match in entry.matches]
        return (min(times), max(times))
    return None


def on_video_mapping_changed(window: MainWindow, path: str, offset: float, drift: float) -> None:
    """Re-map one camera against the master clock, rate included.

    `_on_video_offset_changed` keeps whatever drift was already recorded,
    because a nudge is about position alone. This is the path that can
    change the rate, and it exists because a camera had no way to be given
    one by hand: the only route was an accepted fit, so a user watching a
    camera slip had to drift the *sensor* instead, moving it relative to
    every other camera at once.
    """
    _, previous_drift = window._recorded_mappings.get(path, (0.0, 0.0))
    if drift == previous_drift:
        return  # `_on_video_offset_changed` already handled the position.
    window._record_mapping_change(path, offset, drift)
    effective = window.effective_offset(path, offset)
    window.video_grid.adjust_mapping(path, effective, drift)
    if path in window._video_source_bounds:
        window._set_video_coverage(path, window._video_source_bounds[path], effective, drift)
    from avialsync.ui.sync_lifecycle import refresh_coverage

    refresh_coverage(window, path)
    tracking_timing.calibrate_overlay_timing(window, path)
    window.player.seek(window.clock.state.t, exact=True)


def restore_trigger_sources(window: MainWindow, entries: list[TriggerEntry]) -> None:
    """Re-read every trigger file a restored session declared.

    Re-read rather than restored from the file: a trigger file that has
    changed on disk is read as it now is, which is the same contract sensor
    channels have. The *declaration* is what the session owns.
    """
    for entry in entries:
        mapping = TimeMap(entry.offset, entry.drift_ms_per_hour)
        provenance = next(
            (item for item in window._sync_provenance if item.target_id == entry.path), None
        )
        if provenance is not None and len(provenance.exact_master):
            mapping.set_exact_mapping(
                np.asarray(provenance.exact_master, dtype=np.float64),
                np.asarray(provenance.exact_source, dtype=np.float64),
            )
        window._trigger_time_maps[entry.path] = mapping
        from avialsync.ui.sync_lifecycle import restore_adjustment

        restore_adjustment(window, entry.path)
        window._recorded_mappings[entry.path] = (entry.offset, entry.drift_ms_per_hour)
        path = Path(entry.path)
        if not path.exists():
            window.notifications.show_warning(
                tr("Trigger evidence is missing: {name}").format(name=path.name)
            )
            continue
        provider_cls = window._registry.trigger_for(path)
        if provider_cls is None:
            window.notifications.show_warning(
                tr("Nothing can read {name} as trigger evidence any more.").format(name=path.name)
            )
            continue
        window._start_trigger_read(provider_cls(), path, dict(entry.config))


def open_sync_wizard(window: MainWindow) -> None:
    """Open evidence-based TTL/frame-event alignment for loaded sources."""
    from avialsync.ui.sync_acceptance import collect_sync_evidence
    from avialsync.ui.sync_wizard import SyncWizard

    references, targets = collect_sync_evidence(window)
    if not targets:
        window.notifications.show_warning(
            tr(
                "Load reference evidence -- a TTL-bearing sensor or a declared "
                "trigger train -- and a source on another clock before aligning."
            )
        )
        return

    from avialsync.ui.sync_landmarks import visual_evidence

    if window._sync_wizard is not None:
        window._sync_wizard.show()
        window._sync_wizard.raise_()
        return
    wizard = SyncWizard(references, targets, window, visual_references=visual_evidence(window))
    wizard.set_coverage(window._source_coverage())
    # Held on the window, not on this frame: a non-modal dialog whose only
    # reference is a local dies the moment the function returns.
    window._sync_wizard = wizard
    wizard.seek_requested.connect(window._seek_to_evidence)
    wizard.accepted.connect(lambda: window._on_sync_wizard_accepted(wizard))
    wizard.finished.connect(lambda _result: window._release_sync_wizard())
    wizard.show()
    wizard.raise_()
