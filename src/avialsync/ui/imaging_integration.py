"""Open and place independent imaging stacks on the master timeline."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QObject, Qt, QThread
from PySide6.QtWidgets import QFileDialog, QInputDialog

from avialsync.core.commands import RemoveSourceCommand, SetImagingViewCommand
from avialsync.core.errors import SourceOpenError
from avialsync.core.imaging_display import ImagingView
from avialsync.core.source import ImagingMetadata, ImagingSource, source_exists
from avialsync.core.timeline import TimeMap
from avialsync.engine.imaging_probe import ImagingProbeWorker
from avialsync.ui.i18n import tr
from avialsync.ui.imaging_pane import ImagingPane
from avialsync.ui.job_manager import on_ui_thread
from avialsync.ui.splitter import PaneSplitter

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings

    from avialsync.core.document import SourceRecord
    from avialsync.core.session import ImagingEntry
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.tracking_3d_pane import Tracking3DPane


class _VisibilityFilter(QObject):
    """Keep the right column present when either child is explicitly shown."""

    def __init__(self, splitter: PaneSplitter, tracking: Tracking3DPane, pane: ImagingPane) -> None:
        super().__init__(splitter)
        self._splitter = splitter
        self._tracking = tracking
        self._pane = pane

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Honor a child's direct visibility change, including under a hidden parent."""
        if event.type() == QEvent.Type.ShowToParent:
            self._splitter.setVisible(True)
        elif event.type() == QEvent.Type.HideToParent:
            self._splitter.setVisible(not (self._tracking.isHidden() and self._pane.isHidden()))
        return False


def install(
    window: MainWindow, tracking: Tracking3DPane
) -> tuple[ImagingPane, PaneSplitter, QObject]:
    """Build the lower imaging pane and its 3D/imaging split."""
    pane = ImagingPane(window)
    pane.remove_requested.connect(window._on_imaging_remove_requested)
    pane.mapping_changed.connect(window._on_imaging_mapping_changed)
    pane.view_changed.connect(
        lambda path, before, after, aspect: record_view(window, path, before, after, aspect)
    )
    pane.error.connect(
        lambda message: window.report_failure(
            SourceOpenError(message), doing=tr("Reading imaging frame")
        )
    )
    splitter = PaneSplitter(Qt.Orientation.Vertical)
    splitter.setAccessibleName(tr("3D tracking and imaging splitter"))
    splitter.addWidget(tracking)
    splitter.addWidget(pane)
    splitter.setStretchFactor(0, 1)
    splitter.setStretchFactor(1, 1)
    tracking.setVisible(False)
    pane.setVisible(False)
    splitter.setVisible(False)
    visibility = _VisibilityFilter(splitter, tracking, pane)
    tracking.installEventFilter(visibility)
    pane.installEventFilter(visibility)
    return pane, splitter, visibility


def open_dialog(window: MainWindow) -> None:
    """Choose a stack through the same intake path as drag and drop."""
    path, _ = QFileDialog.getOpenFileName(
        window,
        tr("Open 2P Imaging"),
        "",
        tr("Imaging stacks (*.h5 *.hdf5 *.tif *.tiff);;All files (*)"),
    )
    if path:
        window.open_path(Path(path))


def source_payload(window: MainWindow, path: str) -> tuple[dict[str, Any], float, float]:
    """Capture the imaging choices and display a source undo must retain."""
    loader_cls, config, mapping = window.imaging_pane.source_config(path)
    payload = {
        "loader_id": loader_cls.__name__,
        "config": config,
        "display": window.imaging_pane.view_for(path).to_dict(),
    }
    return payload, mapping.offset, mapping.drift_ms_per_hour


def loader_named(window: MainWindow, loader_id: str) -> type[ImagingSource] | None:
    """Return the registered imaging loader a session or undo record names."""
    for cls in window._registry.loaders():
        if cls.__name__ == loader_id and issubclass(cls, ImagingSource):
            return cls
    return None


def record_view(
    window: MainWindow, path: str, before: dict[str, Any], after: dict[str, Any], aspect: str
) -> None:
    """Log a display edit the pane has already applied (rule 14)."""
    if before == after:
        return
    window._record(SetImagingViewCommand(path, before, after, aspect, display_name=Path(path).name))


def apply_view(window: MainWindow, path: str, view: dict[str, Any]) -> None:
    """Show *path* with a stored view, for undo and redo."""
    window.imaging_pane.set_view(path, ImagingView.from_dict(view))


def restore_geometry(window: MainWindow, settings: QSettings) -> None:
    """Restore the personal 3D/imaging split from application settings."""
    state = settings.value("splitter/right_media")
    if state:
        window.imaging_splitter.restoreState(state)


def save_geometry(window: MainWindow, settings: QSettings) -> None:
    """Persist the personal 3D/imaging split outside the session file."""
    settings.setValue("splitter/right_media", window.imaging_splitter.saveState())


def clear_session(window: MainWindow) -> None:
    """Stop and hide imaging, and clear its coverage, when the session is reset."""
    for path in window.imaging_pane.source_paths():
        window.transport.set_source_coverage(path, 0.0, 0.0, "data")
    window.imaging_pane.clear_sources()
    window.imaging_pane.setVisible(False)
    window.imaging_pending.clear()


def collect_missing(
    entries: Iterable[ImagingEntry], missing: list[str], kinds: dict[str, str]
) -> None:
    """Include imaging paths in the common relink dialog."""
    for entry in entries:
        if not source_exists(Path(entry.path)):
            missing.append(entry.path)
            kinds[entry.path] = "imaging"


def restore_record(window: MainWindow, record: SourceRecord) -> None:
    """Reopen a removed stack from its undo record, with its choices and display."""
    loader_cls = loader_named(window, str(record.payload.get("loader_id", "")))
    if loader_cls is None:
        return
    load_imaging(
        window,
        Path(record.path),
        loader_cls,
        dict(record.payload.get("config", {})),
        offset=record.offset,
        drift_ms_per_hour=record.drift_ms_per_hour,
        view=ImagingView.from_dict(dict(record.payload.get("display", {}))),
    )


def restore_entries(
    window: MainWindow, entries: Iterable[ImagingEntry], relink_map: Mapping[str, str]
) -> None:
    """Reopen all imaging sources after the session clock is established."""
    for entry in entries:
        path = Path(relink_map.get(entry.path, entry.path))
        if source_exists(path):
            restore_entry(window, entry, path)


def remove(window: MainWindow, path: str) -> None:
    """Remove one stack and its coverage after the document records it."""
    if path not in window.imaging_pane.source_paths():
        return
    window._record(RemoveSourceCommand(window._source_record(path, "imaging")))
    window.imaging_pane.remove_source(path)
    window.transport.set_source_coverage(path, 0.0, 0.0, "data")
    window.imaging_pane.setVisible(bool(window.imaging_pane.source_paths()))
    window._recompute_bounds()
    window._refresh_empty_state()


def change_mapping(window: MainWindow, path: str, offset: float, drift_ms_per_hour: float) -> None:
    """Apply a user edit to one imaging TimeMap and coverage span."""
    if path not in window.imaging_pane.source_paths():
        return
    window._record_mapping_change(path, offset, drift_ms_per_hour)
    window.imaging_pane.set_mapping(path, offset, drift_ms_per_hour)
    info = window.imaging_pane.metadata_for(path)
    _show_coverage(window, path, info, TimeMap(offset, drift_ms_per_hour))


def restore_entry(window: MainWindow, entry: ImagingEntry, path: Path) -> None:
    """Resolve the persisted loader and reopen one imaging source."""
    loader_cls = loader_named(window, entry.loader_id)
    if loader_cls is None:
        window.report_failure(
            SourceOpenError(f"Imaging loader {entry.loader_id} is unavailable"),
            doing=tr("Restoring imaging data"),
        )
        return
    load_imaging(
        window,
        path,
        loader_cls,
        dict(entry.import_config),
        offset=entry.offset,
        drift_ms_per_hour=entry.drift_ms_per_hour,
        view=ImagingView.from_dict(entry.display),
        restoring=True,
    )


def ask_choice(
    window: MainWindow,
    choice: str,
    message: str,
    options: tuple[str, ...],
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Ask for the one scientific choice a probe found missing (D-190).

    Returns the config with the answer added, or ``None`` if the user cancels or
    the file offers nothing to choose from. The answer is saved with the
    session, so it is asked once per stack, never guessed.
    """
    updated = dict(config)
    if choice == "fps":
        fps, accepted = QInputDialog.getDouble(
            window,
            tr("Imaging frame rate"),
            message + "\n" + tr("Acquisition frames per second"),
            30.0,
            0.001,
            100000.0,
            4,
        )
        if accepted:
            updated["fps"] = fps
    elif choice in ("dataset", "series") and options:
        title = tr("Imaging dataset") if choice == "dataset" else tr("Imaging series")
        item, accepted = QInputDialog.getItem(window, title, message, list(options), 0, False)
        if accepted:
            updated[choice] = item if choice == "dataset" else int(item.split(":", 1)[0])
    elif choice == "z" and options:
        plane, accepted = QInputDialog.getInt(
            window, tr("Imaging depth plane"), message, 0, 0, len(options) - 1
        )
        if accepted:
            updated["z"] = plane
    elif choice == "axes":
        axes, accepted = QInputDialog.getText(
            window,
            tr("Imaging axes"),
            message + "\n" + tr("Dimension order, such as TYX or TCZYX"),
        )
        if accepted and axes.strip():
            updated["axes"] = axes.strip().upper()
    return None if updated == config else updated


def load_imaging(
    window: MainWindow,
    path: Path,
    loader_cls: type[ImagingSource],
    config: dict[str, Any] | None = None,
    *,
    offset: float = 0.0,
    drift_ms_per_hour: float = 0.0,
    view: ImagingView | None = None,
    restoring: bool = False,
) -> None:
    """Probe asynchronously, then register a lazy reader in the lower pane."""
    chosen = dict(config or {})
    source_id = str(path)
    if source_id in window.imaging_pending:
        return
    if source_id in window.imaging_pane.source_paths():
        window.imaging_pane.source_choice.setCurrentIndex(
            window.imaging_pane.source_choice.findData(source_id)
        )
        return
    generation = window.session_runtime.generation
    window.imaging_pending.add(source_id)
    worker = ImagingProbeWorker(path, loader_cls, chosen)

    def current() -> bool:
        if generation != window.session_runtime.generation:
            return False
        window.imaging_pending.discard(source_id)
        return True

    def done(metadata: object) -> None:
        if not current() or not isinstance(metadata, ImagingMetadata):
            return
        window.imaging_pane.add_source(
            source_id, loader_cls, chosen, metadata, offset, drift_ms_per_hour, view
        )
        window._recorded_mappings[source_id] = (offset, drift_ms_per_hour)
        _reveal(window)
        _show_coverage(window, source_id, metadata, TimeMap(offset, drift_ms_per_hour))
        window._note_source_loaded(source_id, "imaging")
        window._refresh_empty_state()
        window.imaging_pane.set_cursor(window.clock.state.t)

    def needs_choice(choice: str, message: str, options: object) -> None:
        if not current():
            return
        # A restore must not interrupt with questions its saved choices should
        # have answered; the file changed, and that is reported instead.
        listed = tuple(str(item) for item in options) if isinstance(options, tuple) else ()
        extra = None if restoring else ask_choice(window, choice, message, listed, chosen)
        if extra is None:
            window.report_failure(SourceOpenError(message), doing=tr("Opening imaging data"))
            return
        load_imaging(
            window,
            path,
            loader_cls,
            extra,
            offset=offset,
            drift_ms_per_hour=drift_ms_per_hour,
            view=view,
        )

    def failed(message: str) -> None:
        if current():
            window.report_failure(SourceOpenError(message), doing=tr("Opening imaging data"))

    def wire(thread: QThread) -> None:
        worker.finished.connect(on_ui_thread(done, window))
        worker.needs_choice.connect(on_ui_thread(needs_choice, window))
        worker.error.connect(on_ui_thread(failed, window))
        for signal in (worker.finished, worker.needs_choice, worker.error):
            signal.connect(thread.quit)

    window._run_job(worker, label=tr("Reading imaging metadata"), configure=wire)


def _reveal(window: MainWindow) -> None:
    """Show the pane, giving its column a third of the media width on first show.

    A third rather than the 3D pane's quarter: a 512-pixel field of view and its
    channel rows need the room, and two video columns still fit beside it.
    """
    column_was_hidden = window.imaging_splitter.isHidden()
    window.imaging_pane.setVisible(True)
    if column_was_hidden:
        width = max(window._media_splitter.width(), 600)
        window._media_splitter.setSizes([int(width * 2 / 3), int(width / 3)])
        window._pane_proportions.record(window._media_splitter)


def _show_coverage(
    window: MainWindow, source_id: str, info: ImagingMetadata, mapping: TimeMap
) -> None:
    """Put the stack's span on the coverage lanes and widen the session bounds."""
    first = mapping.to_master(float(info.frame_times[0]))
    last = mapping.to_master(float(info.frame_times[-1]) + info.tail_duration)
    window.transport.set_source_coverage(source_id, first, last, "data")
    window._recompute_bounds()
