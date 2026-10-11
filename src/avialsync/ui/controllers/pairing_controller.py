"""Find, review and explicitly accept the partner of a loaded recording.

Format-neutral (D-220). A session plugin whose layout declares a
:class:`~avialsync.core.source.PairingHint` is asked to find the recording made
with it on another machine; the user loads it, reviews the evidence, and
accepts the placement as one undoable command. Which plugin, and what it
searches, is the plugin's business.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from avialsync.core.commands import SetSourceMappingsCommand, SourceMappingChange
from avialsync.core.source import LoadedSource, PartnerSearch
from avialsync.ui.i18n import tr
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow


def can_find_partner(window: MainWindow) -> bool:
    """Whether a loaded session declared a partner to search for."""
    return window.session_runtime.pairing is not None


def find_partner(window: MainWindow) -> None:
    """Ask the declaring plugin, on a registered worker, for the partner recording."""
    from avialsync.engine.partner_search import PartnerSearchWorker
    from avialsync.ui.controllers.plugin_controller import publish_plugin_settings

    hint = window.session_runtime.pairing
    if hint is None:
        window.notifications.show_warning(
            tr("Load a session whose plugin can find a matching recording.")
        )
        return
    publish_plugin_settings(window.registry)
    worker = PartnerSearchWorker(hint.finder, hint.epoch)

    def wire(thread) -> None:
        worker.finished.connect(
            on_ui_thread(lambda result: _search_finished(window, result), window)
        )
        worker.error.connect(
            on_ui_thread(
                lambda message: window.notifications.show_error(
                    tr("Could not search for a matching recording"), details=message
                ),
                window,
            )
        )
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)

    window._run_job(worker, label=tr("Finding matching recording"), configure=wire)


def _search_finished(window: MainWindow, result: object) -> None:
    if not isinstance(result, PartnerSearch) or result.path is None:
        message = result.message if isinstance(result, PartnerSearch) else ""
        window.notifications.show_warning(message or tr("No matching recording was found."))
        return
    window.session_runtime.pending_pair = result
    folder = Path(result.path)
    if not _pair_targets(window, result):
        window.notifications.show_warning(
            tr("Found {name}. Load it, then accept alignment.").format(name=folder.name),
            action_label=tr("Load"),
            on_action=lambda: window.open_path(folder),
            on_dismiss=lambda: setattr(window.session_runtime, "pending_pair", None),
        )
        return
    _offer_acceptance(window, result)


def loaded_sources(window: MainWindow) -> list[LoadedSource]:
    """Every open source a plugin may recognise as its partner, with its import config."""
    sources = [
        LoadedSource(source_id, dict(window.imaging_pane.source_config(source_id)[1]))
        for source_id in window.imaging_pane.source_paths()
    ]
    sources += [LoadedSource(path) for path in window.video_master_spans()]
    sources += [LoadedSource(source_id) for source_id in window._sensor_cache_dirs]
    return sources


def _pair_targets(window: MainWindow, match: PartnerSearch) -> list[tuple[str, float]]:
    hint = window.session_runtime.pairing
    finder = hint.finder if hint is not None else None
    if finder is None:
        return []
    try:
        return finder.partner_targets(match, loaded_sources(window))
    except Exception as error:  # noqa: BLE001 - plugin boundary
        window.registry.plugin_errors.append(
            (finder.display_name(), f"partner_targets raised {type(error).__name__}: {error}")
        )
        return []


def partner_source_loaded(window: MainWindow) -> None:
    """Offer the pending match once every source of the chosen partner is ready."""
    result = window.session_runtime.pending_pair
    if isinstance(result, PartnerSearch) and result.path is not None:
        if _pair_targets(window, result):
            _offer_acceptance(window, result)


def _duration_summary(window: MainWindow, partner_duration: float | None) -> str:
    if partner_duration is None:
        return ""
    durations = [end - start for start, end in window.video_master_spans().values() if end > start]
    if not durations:
        return tr("Camera duration: unavailable; partner duration: {seconds:.2f} s.").format(
            seconds=partner_duration
        )
    camera_duration = max(durations)
    warning = camera_duration < partner_duration or camera_duration - partner_duration > 1.0
    text = tr("Camera duration: {camera:.2f} s; partner duration: {partner:.2f} s.").format(
        camera=camera_duration, partner=partner_duration
    )
    return text + (
        " " + tr("Duration differs by more than the expected camera overrun.") if warning else ""
    )


def _offer_acceptance(window: MainWindow, result: PartnerSearch) -> None:
    details = " ".join(
        part for part in (result.details, _duration_summary(window, result.duration)) if part
    )
    window.notifications.show_warning(
        tr("Align {name} to the first camera frame?").format(name=Path(str(result.path)).name),
        details=details,
        action_label=tr("Accept alignment"),
        on_action=lambda: accept_pair(window, result),
        on_dismiss=lambda: setattr(window.session_runtime, "pending_pair", None),
    )


def _camera_zero(window: MainWindow) -> float:
    """Master time of the cameras' shared first frame."""
    starts = [start for start, _end in window.video_master_spans().values()]
    return min(starts) if starts else 0.0


def accept_pair(window: MainWindow, result: PartnerSearch) -> None:
    """Place the partner's zero on the first camera frame, as one undoable command."""
    folder = Path(str(result.path))
    targets = _pair_targets(window, result)
    if not targets:
        window.notifications.show_warning(
            tr("Load the matching recording before accepting its alignment.")
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
    window.session_runtime.pending_pair = None
    window.notifications.show_success(
        tr("Placed {name} at the first camera frame.").format(name=folder.name)
    )
