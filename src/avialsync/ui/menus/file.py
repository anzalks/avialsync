"""Build the File menu from live actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu, QMenuBar

from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

Register = Callable[[QAction, str], QAction]


def build_file_menu(window: MainWindow, menu: QMenuBar, _reg: Register) -> QMenu:
    """Create File actions in their original order."""
    file_menu = menu.addMenu(tr("File"))
    _file_open(window, file_menu, _reg)
    _file_reset(window, file_menu, _reg)
    _file_changes(window, file_menu, _reg)
    _file_exports(window, file_menu, _reg)
    _file_cache(window, file_menu, _reg)
    _file_application(window, file_menu, _reg)
    return file_menu


def _file_open(window: MainWindow, file_menu: QMenu, _reg: Register) -> None:
    """Open recordings, sessions, and recovery snapshots."""
    # Ctrl+Shift+V (not Ctrl+V — system Paste collision, D-022.7 / Trap §18)
    window._act_open_video = file_menu.addAction(tr("Open Videos…"))
    act = window._act_open_video
    # Renamed from "Open Video(s)…"; keep that label's id so a remapped
    # shortcut survives the rename.
    act.setProperty("av_id", "file_open_video_s")
    act.setShortcut(QKeySequence("Ctrl+Shift+V"))
    act.triggered.connect(window._open_video)
    _reg(act, "File")

    # Ctrl+Shift+D (not Ctrl+D — bookmark/dock collision, D-022.7 / Trap §18)
    window._act_open_sensor = file_menu.addAction(tr("Open Sensor/Ephys Data…"))
    act = window._act_open_sensor
    act.setShortcut(QKeySequence("Ctrl+Shift+D"))
    act.triggered.connect(window._open_data)
    _reg(act, "File")

    _file_dandi(window, file_menu, _reg)

    window._act_open_imaging = file_menu.addAction(tr("Open 2P Imaging…"))
    act = window._act_open_imaging
    act.setToolTip(tr("Open a two-photon HDF5 or TIFF stack on the shared timeline"))
    act.triggered.connect(window._open_imaging)
    _reg(act, "File")

    file_menu.addSeparator()

    window._act_save_session = file_menu.addAction(tr("Save Session…"))
    act = window._act_save_session
    act.setShortcut(QKeySequence(QKeySequence.StandardKey.Save))
    act.triggered.connect(window._save_session)
    _reg(act, "File")
    window._require(
        act,
        window._anything_loaded,
        tr("Open a recording first — an empty workspace has nothing to save."),
    )

    act = file_menu.addAction(tr("Open Session…"))
    act.setShortcut(QKeySequence(QKeySequence.StandardKey.Open))
    act.triggered.connect(window._open_session)
    _reg(act, "File")
    window.sidebar.install_open_session_action(act)

    # The way to the recovery snapshot that does not depend on a launch-time
    # notification. The snapshot is written on every quit whether or not the
    # bar is offered, and it is not an `.avv` file, so Open Session cannot
    # read it -- without this command, turning the offer off would put
    # unsaved work out of reach (D-133).
    act = file_menu.addAction(tr("Recover Unsaved Work…"))
    act.triggered.connect(window._recover_unsaved_work)
    _reg(act, "File")
    window._require(
        act,
        lambda: window.session_runtime.pending_recovery is not None,
        tr("No unsaved work from a previous run was found to recover."),
    )


def _file_dandi(window: MainWindow, file_menu: QMenu, reg: Register) -> None:
    """Expose streamed NWB assets through the ordinary file menu."""
    act = file_menu.addAction(tr("Open NWB from DANDI…"))
    act.triggered.connect(window._open_dandi)
    reg(act, "File")


def _file_reset(window: MainWindow, file_menu: QMenu, _reg: Register) -> None:
    """Reset Session, and the buttons that reach Open and Reset outside the menu.

    Reset had only a sidebar button with its own text, so it was the one
    workspace command the palette, the shortcut editor and the menu bar could
    not reach. It is undoable and never asks first (UX_FOUNDATIONS WP-2).
    """
    window._act_reset_session = file_menu.addAction(tr("Reset Session"))
    act = window._act_reset_session
    act.setToolTip(tr("Close all loaded sources and start a fresh session (undoable)"))
    act.triggered.connect(window._reset_session)
    _reg(act, "File")
    window.sidebar.install_open_actions(window._act_open_video, window._act_open_sensor, act)
    window.sidebar.install_open_imaging_action(window._act_open_imaging)
    # Empty pages offer the command that fills them (D-176).
    window.message_panel.install_empty_action(window._act_open_sensor)
    window.readout_panel.install_empty_action(window._act_open_sensor)
    file_menu.addSeparator()


def _file_changes(window: MainWindow, file_menu: QMenu, _reg: Register) -> None:
    """Offer change export and recent sessions."""
    file_menu.addSeparator()

    window._act_export_changes = file_menu.addAction(tr("Export Changes…"))
    act = window._act_export_changes
    act.triggered.connect(window._export_changes)
    window.changes_panel.set_export_action(act)
    window._require(
        act,
        lambda: (
            bool(window.annotation_store.markers)
            or len(window.point_edits) > 0
            or bool(window.identity_swaps.source_ids())
        ),
        tr("Flag a frame, correct a tracked point, or accept an identity swap first."),
    )

    window._recent_menu = file_menu.addMenu(tr("Recent Sessions"))
    window._rebuild_recent_menu()

    file_menu.addSeparator()


def _file_exports(window: MainWindow, file_menu: QMenu, _reg: Register) -> None:
    """Offer exports and proxy generation."""
    # Export Snapshot — Ctrl+E is the single authority; no duplicate QShortcut
    window._act_snapshot = file_menu.addAction(tr("Export Snapshot…"))
    window._act_snapshot.setShortcut(QKeySequence("Ctrl+E"))
    window._act_snapshot.triggered.connect(window._export_snapshot)
    _reg(window._act_snapshot, "File")
    window.view_toolbar.install_snapshot_action(window._act_snapshot)
    window._require(
        window._act_snapshot,
        window._anything_loaded,
        tr("Load a video or a data file to have something to snapshot."),
    )

    act = file_menu.addAction(tr("Export Trimmed Video Clip…"))
    act.triggered.connect(window._export_video_clip)
    window._require(
        act,
        lambda: bool(window.video_grid._paths) and window.transport._ab_in_t is not None,
        tr("Load a video and mark an A/B loop — [ and ] set where a clip starts and ends."),
    )

    act = file_menu.addAction(tr("Export Stimulus Grid…"))
    act.triggered.connect(window._export_stimulus_grid)
    _reg(act, "File")
    window._require(
        act,
        lambda: bool(window.video_grid._paths) and bool(window.plot_pane.channels),
        tr("Load at least one video and one sensor channel first."),
    )

    act = file_menu.addAction(tr("Export Data Slice…"))
    act.triggered.connect(window._export_data_slice)
    window._require(
        act,
        lambda: bool(window.plot_pane.channels),
        tr("Load sensor or ephys data to have a slice to export."),
    )

    act = file_menu.addAction(tr("Generate Proxy…"))
    act.triggered.connect(window._generate_proxy)
    window._require(
        act,
        lambda: bool(window.video_grid._paths),
        tr("Load a video first — a proxy is a lighter copy of one."),
    )

    file_menu.addSeparator()


def _file_cache(window: MainWindow, file_menu: QMenu, _reg: Register) -> None:
    """Offer the cache folder: one trial's entries, all of them, or the folder (D-160)."""
    from avialsync.ui.controllers import cache_controller

    def idle() -> bool:
        # A job may be writing into the cache, or a sidecar beside the data
        # that the reload would then read half-written.
        return not window._job_manager.is_busy()

    cache_menu = file_menu.addMenu(tr("Cache"))
    # Opening the submenu re-answers its preconditions: a job may have finished
    # since File itself was opened.
    cache_menu.aboutToShow.connect(window._refresh_action_availability)

    act = cache_menu.addAction(tr("Delete Cache for This Trial"))
    act.setStatusTip(
        tr("Delete the cached imports of every file in this trial's folder, then re-import it.")
    )
    act.triggered.connect(lambda: cache_controller.delete_trial_cache(window))
    _reg(act, "File")
    window._require(
        act,
        lambda: window._anything_loaded() and idle(),
        tr("Open a trial, and let background work finish — its cache is what this deletes."),
    )

    act = cache_menu.addAction(tr("Delete All Cache"))
    act.setStatusTip(
        tr("Delete every cached import. Recordings, corrections and sessions are not touched.")
    )
    act.triggered.connect(lambda: cache_controller.delete_all_cache(window))
    _reg(act, "File")
    window._require(
        act, idle, tr("Let background work finish first — it may be writing to the cache.")
    )

    act = cache_menu.addAction(tr("Show Cache Folder"))
    act.triggered.connect(lambda: cache_controller.show_cache_folder(window))
    _reg(act, "File")

    file_menu.addSeparator()


def _file_application(window: MainWindow, file_menu: QMenu, _reg: Register) -> None:
    """Offer preferences and platform quit."""
    # Preferences stays in the File menu on every platform (D-135).
    # `PreferencesRole` moved it into the macOS application menu, which is
    # named after the running process -- so anyone who starts AvialSync
    # from a terminal or a conda env looks in "File", is told by our own
    # documentation to look in "File", and finds it under a menu called
    # "python". Cmd+, still works, and About and Quit keep their roles.
    act = file_menu.addAction(tr("Preferences…"))
    act.setShortcut(QKeySequence(QKeySequence.StandardKey.Preferences))
    act.setMenuRole(QAction.MenuRole.NoRole)
    act.triggered.connect(window._help_controller.show_preferences)
    _reg(act, "File")

    file_menu.addSeparator()

    # Quit — macOS QuitRole moves this to the app menu (D-022.3)
    act = file_menu.addAction(tr("Quit"))
    act.setShortcut(QKeySequence(QKeySequence.StandardKey.Quit))
    act.setMenuRole(QAction.MenuRole.QuitRole)
    act.triggered.connect(window.close)
    _reg(act, "File")
