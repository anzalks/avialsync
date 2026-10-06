"""Time-synchronized two-photon image viewer with bounded background reads (D-186).

The pane follows the master clock like a video pane: the frame shown for master
time ``t`` is the one whose presentation interval contains ``t``
(``core/video_timing.frame_index_at``). Reading, averaging, windowing and
overlay all happen on one reader thread per shown stack
(:mod:`avialsync.engine.imaging_reader`); this widget only converts a finished
8-bit picture to a pixmap.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.imaging_display import ImagingView
from avialsync.core.session import ImagingEntry
from avialsync.core.source import ImagingMetadata, ImagingSource
from avialsync.core.timeline import TimeMap
from avialsync.core.video_timing import frame_index_at
from avialsync.engine.imaging_reader import ImagingReadWorker
from avialsync.ui.design_tokens import ControlRole, apply_role
from avialsync.ui.drift_spin import DriftSpinBox
from avialsync.ui.i18n import tr
from avialsync.ui.imaging_controls import ImagingControls

#: A day either way, the same bound as the sidebar's offset fields.
_OFFSET_LIMIT_S = 86_400.0

# Threads stopped without waiting are kept referenced until they finish, so
# Python never drops a running QThread (which aborts the process).
_ABANDONED: set[tuple[QThread, QObject]] = set()


@dataclasses.dataclass
class _Stack:
    """One registered stack: how to reopen it, when it is, and how it looks."""

    loader: type[ImagingSource]
    config: dict[str, Any]
    info: ImagingMetadata
    mapping: TimeMap
    view: ImagingView


class ImagingPane(QWidget):
    """Shows one of the session's imaging stacks at the master playhead."""

    error = Signal(str)
    remove_requested = Signal(str)
    #: ``(path, offset, drift_ms_per_hour)`` after the user edits the mapping.
    mapping_changed = Signal(str, float, float)
    #: ``(path, before, after, aspect)`` as view dicts, after a display edit.
    view_changed = Signal(str, object, object, str)
    decode_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(tr("Two-photon imaging viewer"))
        self.setAccessibleDescription(tr("Shows the imaging frame at the master timeline position"))
        self._sources: dict[str, _Stack] = {}
        self._thread: QThread | None = None
        self._worker: ImagingReadWorker | None = None
        self._last_index: int | None = None
        self._last_time = 0.0
        self._image: QImage | None = None
        self._out_of_range = False
        self._reported_frame_failure = False

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel(tr("2P imaging"), self))
        self.source_choice = QComboBox(self)
        self.source_choice.setAccessibleName(tr("Imaging source"))
        self.source_choice.setAccessibleDescription(tr("Choose the imaging stack to display"))
        self.source_choice.currentIndexChanged.connect(self._activate_selected)
        header.addWidget(self.source_choice, 1)
        self.remove_button = QPushButton(tr("Remove"), self)
        self.remove_button.setAccessibleName(tr("Remove selected imaging source"))
        self.remove_button.setAccessibleDescription(
            tr("Remove the selected imaging stack from this session")
        )
        apply_role(self.remove_button, ControlRole.DESTRUCTIVE)
        self.remove_button.clicked.connect(
            lambda: self.remove_requested.emit(str(self.source_choice.currentData()))
        )
        header.addWidget(self.remove_button)
        layout.addLayout(header)

        self.controls = ImagingControls(self)
        self.controls.view_edited.connect(self._on_view_edited)
        layout.addWidget(self.controls)
        mapping_row = QHBoxLayout()
        self._build_mapping_row(mapping_row)
        layout.addLayout(mapping_row)

        self.frame_label = QLabel(tr("No imaging source"), self)
        self.frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frame_label.setAccessibleName(tr("Imaging frame"))
        self.frame_label.setAccessibleDescription(tr("Current two-photon image plane"))
        self.frame_label.setMinimumSize(80, 80)
        layout.addWidget(self.frame_label, 1)
        self.status_label = QLabel("", self)
        self.status_label.setAccessibleName(tr("Imaging frame status"))
        layout.addWidget(self.status_label)

    def _build_mapping_row(self, row: QHBoxLayout) -> None:
        """Offset and drift for the shown stack, on their own row."""
        row.addWidget(QLabel(tr("Offset"), self))
        self.offset_spin = QDoubleSpinBox(self)
        self.offset_spin.setRange(-_OFFSET_LIMIT_S, _OFFSET_LIMIT_S)
        # Six decimals like every other offset field: a frame at 30 Hz is 33 ms,
        # but the sync fit reports offsets to six places (see ui/sidebar.py).
        self.offset_spin.setDecimals(6)
        self.offset_spin.setSingleStep(0.05)
        self.offset_spin.setSuffix(tr(" s"))
        self.offset_spin.setAccessibleName(tr("Imaging time offset in seconds"))
        self.offset_spin.setAccessibleDescription(
            tr("Shift this stack's timestamps against the master timeline")
        )
        row.addWidget(self.offset_spin)
        row.addWidget(QLabel(tr("Drift"), self))
        self.drift_spin = DriftSpinBox(self)
        self.drift_spin.setAccessibleName(tr("Imaging clock drift in milliseconds per hour"))
        self.drift_spin.setAccessibleDescription(
            tr("Correct gradual clock-rate differences against the master timeline")
        )
        self.drift_spin.set_base_tooltip(tr("Milliseconds this stack's clock gains per hour"))
        row.addWidget(self.drift_spin)
        row.addStretch(1)
        self.offset_spin.valueChanged.connect(self._mapping_edited)
        self.drift_spin.valueChanged.connect(self._mapping_edited)

    # ── registered stacks ────────────────────────────────────────────

    def add_source(
        self,
        path: str,
        loader_cls: type[ImagingSource],
        config: dict[str, Any],
        metadata: ImagingMetadata,
        offset: float = 0.0,
        drift_ms_per_hour: float = 0.0,
        view: ImagingView | None = None,
    ) -> None:
        """Register a stack and show it."""
        shown = (view or ImagingView()).fitted(metadata.channel_count)
        mapping = TimeMap(offset, drift_ms_per_hour)
        self._sources[path] = _Stack(loader_cls, dict(config), metadata, mapping, shown)
        if self.source_choice.findData(path) < 0:
            self.source_choice.addItem(Path(path).name, path)
        self.source_choice.setCurrentIndex(self.source_choice.findData(path))

    def session_entries(self) -> list[ImagingEntry]:
        """Serialize each stack's loader, choices, mapping and display."""
        return [
            ImagingEntry(
                path=path,
                loader_id=stack.loader.__name__,
                import_config=dict(stack.config),
                offset=stack.mapping.offset,
                drift_ms_per_hour=stack.mapping.drift_ms_per_hour,
                display=stack.view.to_dict(),
            )
            for path, stack in self._sources.items()
        ]

    def source_paths(self) -> tuple[str, ...]:
        """Return all registered imaging paths."""
        return tuple(self._sources)

    def metadata_for(self, path: str) -> ImagingMetadata:
        """Return the stack metadata needed for coverage and persistence."""
        return self._sources[path].info

    def source_config(self, path: str) -> tuple[type[ImagingSource], dict[str, Any], TimeMap]:
        """Return the loader, import choices and accepted mapping for one stack."""
        stack = self._sources[path]
        return stack.loader, dict(stack.config), stack.mapping

    def view_for(self, path: str) -> ImagingView:
        """Return how one stack is shown."""
        return self._sources[path].view

    def remove_source(self, path: str) -> None:
        """Remove one source, keeping another selection active if available."""
        if path not in self._sources:
            return
        index = self.source_choice.findData(path)
        if index == self.source_choice.currentIndex():
            self._stop_worker()
        del self._sources[path]
        self.source_choice.removeItem(index)
        if not self._sources:
            self.clear_sources()

    def clear_sources(self) -> None:
        """Discard the current session's imaging sources."""
        self._stop_worker()
        self._sources.clear()
        self.source_choice.clear()
        self.controls.set_view(ImagingView())
        self._show_message(tr("No imaging source"))
        self.status_label.clear()

    def shutdown(self) -> None:
        """Stop the reader before Qt destroys the pane."""
        self._stop_worker(wait=True)

    # ── mapping and display ──────────────────────────────────────────

    def set_mapping(self, path: str, offset: float, drift_ms_per_hour: float) -> None:
        """Apply a mapping and re-request the plane at the current time."""
        if path not in self._sources:
            return
        mapping = self._sources[path].mapping
        mapping.offset = offset
        mapping.drift_ms_per_hour = drift_ms_per_hour
        if self.source_choice.currentData() == path:
            self._show_mapping(mapping)
            self._last_index = None
            self.set_cursor(self._last_time)

    def set_view(self, path: str, view: ImagingView) -> None:
        """Show *path* with *view* (undo, redo, restore) and re-render it."""
        stack = self._sources.get(path)
        if stack is None:
            return
        stack.view = view.fitted(stack.info.channel_count)
        if self.source_choice.currentData() == path:
            self.controls.set_view(stack.view)
            self._rerender()

    def _show_mapping(self, mapping: TimeMap) -> None:
        for spin, value in (
            (self.offset_spin, mapping.offset),
            (self.drift_spin, mapping.drift_ms_per_hour),
        ):
            blocked = spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(blocked)

    @Slot()
    def _mapping_edited(self) -> None:
        path = self.source_choice.currentData()
        if path in self._sources:
            self.mapping_changed.emit(path, self.offset_spin.value(), self.drift_spin.value())

    @Slot(object, str)
    def _on_view_edited(self, view: object, aspect: str) -> None:
        path = self.source_choice.currentData()
        stack = self._sources.get(path)
        if stack is None or not isinstance(view, ImagingView):
            return
        before, stack.view = stack.view, view
        self._rerender()
        self.view_changed.emit(path, before.to_dict(), view.to_dict(), aspect)

    @Slot(str, int, float, float)
    def _on_window_measured(self, path: str, channel: int, low: float, high: float) -> None:
        """Keep a measured reference window so the session reproduces this picture.

        A measurement, not an edit: it fills in what "automatic" meant for this
        data and is not an undo step of its own.
        """
        stack = self._sources.get(path)
        if stack is None or channel >= len(stack.view.channels):
            return
        current = stack.view.channels[channel]
        if current.measured:
            return
        measured = dataclasses.replace(current, auto_low=low, auto_high=high)
        stack.view = stack.view.with_channel(channel, measured)
        if self.source_choice.currentData() == path:
            self.controls.set_view(stack.view)

    # ── following the clock ──────────────────────────────────────────

    def set_cursor(self, t_master: float) -> None:
        """Request the presentation plane containing this master instant."""
        self._last_time = t_master
        stack = self._sources.get(self.source_choice.currentData())
        if stack is None:
            return
        info = stack.info
        source_time = stack.mapping.to_source(t_master)
        if (
            source_time < info.frame_times[0]
            or source_time > info.frame_times[-1] + info.tail_duration
        ):
            if not self._out_of_range:
                self._show_message(tr("No imaging data at this time"))
            self._out_of_range = True
            self._last_index = None
            return
        self._out_of_range = False
        index = frame_index_at(info.frame_times, source_time)
        if index == self._last_index or self._worker is None:
            return
        self._last_index = index
        self._worker.request(index, stack.view)
        self.decode_requested.emit()

    def _rerender(self) -> None:
        """Re-request the shown frame after a display change."""
        self._last_index = None
        self.set_cursor(self._last_time)

    # ── reader thread ────────────────────────────────────────────────

    @Slot()
    def _activate_selected(self) -> None:
        self._stop_worker()
        self._out_of_range = False
        self._reported_frame_failure = False
        path = self.source_choice.currentData()
        stack = self._sources.get(path)
        if stack is None:
            return
        self._show_message(tr("Loading imaging frame…"))
        self._show_mapping(stack.mapping)
        self.controls.set_view(stack.view)
        worker = ImagingReadWorker(Path(path), stack.loader, stack.config, stack.info.frame_count)
        thread = QThread(self)
        thread.setObjectName(f"avialsync-imaging:{Path(path).name}")
        worker.moveToThread(thread)
        self._worker, self._thread = worker, thread
        self._last_index = None
        self.decode_requested.connect(worker.decode_pending, Qt.ConnectionType.QueuedConnection)
        worker.opened.connect(self._on_worker_opened)
        worker.frame_ready.connect(self._on_frame)
        worker.frame_failed.connect(self._on_frame_failed)
        worker.failed.connect(self._on_worker_failed)
        worker.window_measured.connect(self._on_window_measured)
        thread.started.connect(worker.open)
        thread.finished.connect(worker.close)
        thread.start()

    def _stop_worker(self, *, wait: bool = False) -> None:
        if self._thread is None or self._worker is None:
            return
        self.decode_requested.disconnect(self._worker.decode_pending)
        thread, worker = self._thread, self._worker
        self._thread = None
        self._worker = None
        thread.quit()
        if not wait or not thread.wait(3000):
            thread.setParent(None)
            entry = (thread, worker)
            _ABANDONED.add(entry)
            thread.finished.connect(lambda: _ABANDONED.discard(entry))
            if thread.isFinished():
                _ABANDONED.discard(entry)
        self._last_index = None

    @Slot(str)
    def _on_worker_opened(self, path: str) -> None:
        """Request the current frame after the reader opens on its thread."""
        if path == self.source_choice.currentData():
            self.set_cursor(self._last_time)

    @Slot(str, str)
    def _on_worker_failed(self, path: str, message: str) -> None:
        if path != self.source_choice.currentData():
            return
        self._show_message(tr("Could not open imaging source"))
        self.error.emit(message)

    @Slot(str, int, str)
    def _on_frame_failed(self, path: str, index: int, message: str) -> None:
        """Keep a damaged page from masquerading as the preceding frame."""
        if path != self.source_choice.currentData() or index != self._last_index:
            return
        self._show_message(tr("Imaging frame unavailable"))
        self.status_label.setText(tr("Frame {index} could not be read").format(index=index + 1))
        # Once per shown stack: playing through a damaged stretch must not raise
        # a notification per frame. The status line names every frame it hits.
        if not self._reported_frame_failure:
            self._reported_frame_failure = True
            self.error.emit(message)

    @Slot(str, int, object)
    def _on_frame(self, path: str, index: int, image: object) -> None:
        """Adopt a finished picture if it still belongs to the shown time."""
        if path != self.source_choice.currentData() or index != self._last_index:
            return
        stack = self._sources[path]
        if not isinstance(image, np.ndarray):
            self._show_message(tr("No channel is shown. Tick a channel to see the image."))
            return
        height, width = image.shape[:2]
        image_format = (
            QImage.Format.Format_Grayscale8 if image.ndim == 2 else QImage.Format.Format_RGB888
        )
        # copy(): QImage borrows the array, and the array is the worker's.
        self._image = QImage(image.data, width, height, image.strides[0], image_format).copy()
        self._show_image()
        average = stack.view.average
        status = tr("Frame {index}/{total} · {time:.3f} s").format(
            index=index + 1, total=stack.info.frame_count, time=float(stack.info.frame_times[index])
        )
        if average > 1:
            status += " · " + tr("mean of {count}").format(count=average)
        self.status_label.setText(status)

    def _show_message(self, text: str) -> None:
        self._image = None
        self.frame_label.setPixmap(QPixmap())
        self.frame_label.setText(text)

    def _show_image(self) -> None:
        if self._image is None:
            return
        pixmap = QPixmap.fromImage(self._image)
        self.frame_label.setPixmap(
            pixmap.scaled(
                self.frame_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        )

    def resizeEvent(self, event: Any) -> None:
        """Scale the current picture to the pane's new size."""
        super().resizeEvent(event)
        self._show_image()
