"""The Fix Identities dock: opening it, its gestures, and its braid jobs.

Moved from MainWindow (WINDOW_COMPOSITION_PLAN A7), which keeps one delegator
per function (D-066). Panel signals and worker results still reach the window's
own methods, so delivery stays on the UI thread; the moved code's private
accesses are in the boundary baseline under D-248. What the panel shows is
:mod:`identity_view`; persistence and the edited cache are
:mod:`identity_controller`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QDialog
from shiboken6 import isValid

from avialsync.core.commands import SetIdentityGroupCommand
from avialsync.ui.controllers import corrections_controller, identity_view
from avialsync.ui.i18n import tr
from avialsync.ui.identity_group_dialog import IdentityGroupDialog
from avialsync.ui.identity_model_worker import BraidBuildJob, BraidBuildWorker
from avialsync.ui.identity_panel import IdentityWindow
from avialsync.ui.job_manager import on_ui_thread

if TYPE_CHECKING:
    from avialsync.ui.identity_braid import BraidModel
    from avialsync.ui.main_window import MainWindow

#: Delay before a braid read starts, so a rapid walk through the Part menu
#: starts one read for the final selection rather than one per transient item.
_MODEL_DEBOUNCE_MS = 75


def _build_dock(window: MainWindow) -> IdentityWindow:
    """Create the dock once and route each of its gestures to the window."""
    dock = IdentityWindow(window)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    dock.hide()
    panel = dock.panel
    panel.swap_requested.connect(lambda event: identity_view.swap(window, panel.source_id(), event))
    panel.undo_requested.connect(lambda event: identity_view.undo(window, panel.source_id(), event))
    panel.seek_requested.connect(lambda at: window.player.seek(at, exact=True))
    panel.play_region_requested.connect(window._play_identity_region)
    panel.apply_requested.connect(window._apply_identity_swap)
    panel.remove_requested.connect(window._remove_identity_swap)
    panel.remove_all_requested.connect(lambda: identity_view.remove_all(window, panel.source_id()))
    panel.detect_requested.connect(
        lambda group, part: identity_view.detect(window, panel.source_id(), group, part)
    )
    panel.new_group_requested.connect(window._new_identity_group)
    panel.selection_changed.connect(lambda _group, _part: window._refresh_identity_panel())
    dock.visibilityChanged.connect(window._identity_dock_visibility_changed)
    return dock


def open_identity_panel(window: MainWindow) -> None:
    """Dock the braid beside the video so the crossing can be reviewed."""
    source_id = identity_view.current_source(window)
    if not source_id:
        return
    if window._identity_window is None:
        window._identity_window = _build_dock(window)
    dock = window._identity_window
    dock.show()
    if dock.isFloating():
        window._bring_onto_screen(dock)
    dock.raise_()
    if not dock.isFloating():
        window.resizeDocks(
            [dock], [min(480, max(340, window.width() // 3))], Qt.Orientation.Horizontal
        )
    window._refresh_identity_panel(source_id)


def play_identity_region(window: MainWindow, start: float, end: float) -> None:
    """Review a crossing in the existing video and master-clock A/B loop."""
    window.transport.set_ab_region(start, end)
    window.player.seek(max(window.transport.bounds[0], start), exact=True)
    window.player.set_playing(True)


def identity_dock_visibility_changed(window: MainWindow, visible: bool) -> None:
    """A closed editor leaves neither stale proposals nor a pending scan."""
    if visible:
        return
    window._identity_request_serial += 1
    window._identity_model_timer.stop()
    window._pending_identity_model = None
    window.transport.set_identity_candidates([])


def new_identity_group(window: MainWindow) -> None:
    """Ask for pose-column pairs, then record their group through the bus."""
    dock = window._identity_window
    if dock is None:
        return
    source_id = dock.panel.source_id()
    schema = window._pose_schemas.get(source_id)
    if schema is None:
        return
    dialog = IdentityGroupDialog(schema, window.identity_swaps.groups_for(source_id), window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    group = dialog.group()
    if group is None:
        return
    window.document.execute(SetIdentityGroupCommand(source_id, group), window._mutations)
    dock.panel.select_group(group.name)


def apply_identity_swap(window: MainWindow) -> None:
    """Accept a swap where the review is.

    One button, because there is one gesture: choosing a crossing seeks the
    video to it, so "apply the selected crossing" and "apply where the
    video is" name the same frame. When nothing is selected -- a flip the
    person spotted by watching, which nothing proposed -- the clock is the
    answer, and it works while playing, because that is when they see one.
    """
    dock = window._identity_window
    if dock is None or not isValid(dock):
        return
    panel = dock.panel
    # The clock, and nothing else. Every way of choosing a crossing seeks
    # the video to it, so the playhead already *is* the frame under review
    # -- and when nothing was proposed, it is the frame the person watched
    # the flip happen on.
    index = identity_view.index_at_time(window, panel.source_id(), window.clock.state.t)
    if index is None:
        return
    event = panel.event_at(index)
    if event is None:
        return
    identity_view.swap(window, panel.source_id(), event)
    window.notifications.show_success(
        tr("{a} and {b} swapped from frame {frame}. Undo reverses it.").format(
            a=event.lanes[0],
            b=event.lanes[1],
            frame=corrections_controller.frame_for(window, panel.source_id(), event.index),
        )
    )


def remove_identity_swap(window: MainWindow) -> None:
    """Reverse the swap in force where the video is.

    The mirror of applying one, and deliberately as simple: the playhead
    says which swap is meant, so removing never reaches back and changes
    identities in a part of the recording the person is not looking at.
    """
    dock = window._identity_window
    if dock is None or not isValid(dock):
        return
    panel = dock.panel
    source_id = panel.source_id()
    index = identity_view.index_at_time(window, source_id, window.clock.state.t)
    if index is None:
        return
    event = identity_view.accepted_at(
        window, source_id, panel.group_id(), panel.part(), index, panel.pair()
    )
    if event is None:
        window.notifications.show_warning(
            tr("No accepted swap is in force here, so there is nothing to reverse.")
        )
        return
    identity_view.undo(window, source_id, event)


def refresh_identity_panel(window: MainWindow, source_id: str = "") -> None:
    """Start a registered braid job for the selected source, group and part."""
    dock = window._identity_window
    if dock is None or not isValid(dock) or dock.isHidden():
        return
    panel = dock.panel
    source_id = source_id or panel.source_id() or identity_view.current_source(window)
    if not source_id:
        return
    groups = identity_view.groups_for(window, source_id)
    counts: dict[tuple[str, str], tuple[int, int]] = {}
    for group in groups:
        counts.update(identity_view.counts_for(window, source_id, group))
    if (
        panel.source_id() != source_id
        or panel.group() is None
        or panel.group_ids() != tuple(group.name for group in groups)
    ):
        panel.set_groups(source_id, groups, counts)
    else:
        panel.set_counts(counts)
    dock.setWindowTitle(tr("Fix Identities — {source}").format(source=Path(source_id).name))
    panel.set_video_available(bool(window.video_grid._paths))
    panel.set_swap_count(window.identity_swaps.count_for(source_id))
    window._identity_request_serial += 1
    serial = window._identity_request_serial
    job = identity_view.job_for(window, source_id, panel.group_id(), panel.part(), panel.pair())
    if job is None:
        # No group to draw. "Loading" would replace the panel's own
        # explanation -- that this recording needs New group -- with a
        # spinner for work that is never going to start.
        if groups:
            panel.set_loading()
        return
    panel.set_loading()
    window.transport.set_identity_candidates([])
    window._pending_identity_model = (serial, job)
    window._identity_model_timer.start(_MODEL_DEBOUNCE_MS)


def start_identity_model_job(window: MainWindow) -> None:
    """Start the braid read the debounce timer was holding, if still wanted."""
    pending = window._pending_identity_model
    window._pending_identity_model = None
    dock = window._identity_window
    if pending is None or dock is None or dock.isHidden():
        return
    serial, job = pending
    worker = BraidBuildWorker(job)

    def _wire(_thread: QThread) -> None:
        worker.finished.connect(
            on_ui_thread(
                lambda result_job, model: window._show_identity_model(serial, result_job, model),
                window,
            )
        )
        worker.error.connect(
            on_ui_thread(lambda message: window._identity_model_failed(serial, message), window)
        )

    window._run_job(worker, label=tr("Reading identity evidence"), configure=_wire)


def show_identity_model(
    window: MainWindow, serial: int, job: BraidBuildJob, model: BraidModel
) -> None:
    """Show a finished braid, ignoring a selection the reviewer has already changed."""
    dock = window._identity_window
    if serial != window._identity_request_serial or dock is None or not isValid(dock):
        return
    panel = dock.panel
    if (panel.source_id(), panel.group_id(), panel.part()) != (
        job.source_id,
        job.group.name,
        job.part,
    ):
        return
    panel.show_model(model)
    window.transport.set_identity_candidates(
        [(node.at, node.detail) for node in model.nodes if not node.accepted]
    )


def identity_model_failed(window: MainWindow, serial: int, message: str) -> None:
    """Report only the failure of the current requested evidence slice."""
    if serial == window._identity_request_serial:
        window.notifications.show_warning(
            tr("Identity evidence could not be read."), details=message
        )


def refresh_identity_lane(window: MainWindow) -> None:
    """Show every accepted flip in the Data Streams lanes, in master time."""
    events: list[tuple[float, str]] = []
    by_source: dict[str, list[tuple[float, str]]] = {}
    for source_id, event in window.identity_swaps:
        when = window._master_time_of_sample(source_id, event.index)
        if when is None:
            continue
        named = (
            when,
            tr("{a} and {b} swap from frame {frame}").format(
                a=event.lanes[0],
                b=event.lanes[1],
                frame=corrections_controller.frame_for(window, source_id, event.index),
            ),
        )
        events.append(named)
        by_source.setdefault(source_id, []).append(named)
    window.transport.set_identity_events(sorted(events))
    for source_id in window._pose_schemas:
        window.sidebar.set_sensor_identity_count(
            source_id, window.identity_swaps.count_for(source_id)
        )
        window.plot_pane.set_identity_events(source_id, by_source.get(source_id, []))
