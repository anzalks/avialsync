"""Annotation markers: point and range, with list panel and CSV export."""

from __future__ import annotations

import csv
import dataclasses
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Palette for cycling annotation colours
_COLORS = ["#f4a261", "#e76f51", "#2a9d8f", "#e9c46a", "#a8dadc", "#b5838d", "#84a98c"]


@dataclasses.dataclass
class VideoFrame:
    """Per-video frame snapshot stored with an annotation marker."""

    path: str
    frame_index: int
    media_timestamp: float


@dataclasses.dataclass
class Marker:
    """A single annotation marker on the timeline.

    If ``t_end`` is None this is a point marker; otherwise it is a range.
    ``video_frames`` holds one record per loaded video at the moment of marking.
    """

    t_start: float
    t_end: float | None
    label: str
    color: str = "#f4a261"
    video_frames: list[VideoFrame] = dataclasses.field(default_factory=list)


class AnnotationStore(QObject):
    """In-memory store for timeline markers.

    Emits ``changed`` whenever markers are added or removed so that
    connected UI components (plot, annotation panel) can redraw.
    """

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._markers: list[Marker] = []
        self._color_idx = 0

    @property
    def markers(self) -> list[Marker]:
        return list(self._markers)

    def add_point(
        self, t: float, label: str = "", video_frames: list[VideoFrame] | None = None
    ) -> Marker:
        """Add a point marker at time *t*."""
        color = _COLORS[self._color_idx % len(_COLORS)]
        self._color_idx += 1
        m = Marker(t_start=t, t_end=None, label=label, color=color, video_frames=video_frames or [])
        self._markers.append(m)
        self.changed.emit()
        return m

    def add_range(
        self,
        t_start: float,
        t_end: float,
        label: str = "",
        video_frames: list[VideoFrame] | None = None,
    ) -> Marker:
        """Add a range marker from *t_start* to *t_end*."""
        if t_start > t_end:
            t_start, t_end = t_end, t_start
        color = _COLORS[self._color_idx % len(_COLORS)]
        self._color_idx += 1
        m = Marker(
            t_start=t_start, t_end=t_end, label=label, color=color, video_frames=video_frames or []
        )
        self._markers.append(m)
        self.changed.emit()
        return m

    def remove(self, index: int) -> None:
        """Remove a marker by index."""
        if 0 <= index < len(self._markers):
            self._markers.pop(index)
            self.changed.emit()

    def clear(self) -> None:
        self._markers.clear()
        self.changed.emit()

    def export_csv(self, path: Path) -> None:
        """Write one row per (marker, video) — format for DLC/LightningPose retraining.

        Columns: label, comment, t_master, video_path, frame_index, media_timestamp.
        Markers with no video_frames produce one row with empty video columns.

        Synchronous; the application uses
        :class:`~avialview.engine.export_worker.AnnotationExportWorker` so the
        UI thread never writes this file itself.
        """
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["label", "comment", "t_master", "video_path", "frame_index", "media_timestamp"]
            )
            for m in self._markers:
                if m.video_frames:
                    for vf in m.video_frames:
                        writer.writerow(
                            [m.label, "", m.t_start, vf.path, vf.frame_index, vf.media_timestamp]
                        )
                else:
                    writer.writerow([m.label, "", m.t_start, "", "", ""])


class AnnotationPanel(QGroupBox):
    """Widget that lists annotations and provides add/delete/export controls."""

    def __init__(self, store: AnnotationStore, parent: QWidget | None = None) -> None:
        super().__init__("Annotations", parent)
        self._store = store
        self._store.changed.connect(self._refresh)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Table
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Start", "End", "Label", "Cameras"])
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
        self._table.itemChanged.connect(self._on_label_edited)
        layout.addWidget(self._table)

        # Buttons
        btn_row = QHBoxLayout()
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._on_delete)
        export_btn = QPushButton("Export CSV…")
        export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(export_btn)
        layout.addLayout(btn_row)

    def _refresh(self) -> None:
        """Rebuild the table from the store."""
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for m in self._store.markers:
            row = self._table.rowCount()
            self._table.insertRow(row)

            def _fmt(t: float) -> str:
                h, rem = divmod(t, 3600)
                mins, s = divmod(rem, 60)
                return f"{int(h):02d}:{int(mins):02d}:{s:05.2f}"

            t_start_item = QTableWidgetItem(_fmt(m.t_start))
            t_start_item.setFlags(t_start_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            t_end_item = QTableWidgetItem(_fmt(m.t_end) if m.t_end is not None else "—")
            t_end_item.setFlags(t_end_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            label_item = QTableWidgetItem(m.label)
            cameras_str = "  ".join(
                f"{Path(vf.path).stem}:f{vf.frame_index}" for vf in m.video_frames
            )
            cameras_item = QTableWidgetItem(cameras_str)
            cameras_item.setFlags(cameras_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self._table.setItem(row, 0, t_start_item)
            self._table.setItem(row, 1, t_end_item)
            self._table.setItem(row, 2, label_item)
            self._table.setItem(row, 3, cameras_item)
        self._table.blockSignals(False)

    def _on_delete(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            self._store.remove(row)

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Annotations", "", "CSV files (*.csv)")
        if path:
            self._store.export_csv(Path(path))

    def _on_label_edited(self, item: QTableWidgetItem) -> None:
        if item.column() == 2:
            row = item.row()
            if 0 <= row < len(self._store._markers):
                self._store._markers[row].label = item.text()
