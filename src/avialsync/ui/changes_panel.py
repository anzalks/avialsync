"""One list of everything a person changed, and a way back to each of them.

Before this there were two answers to "what have I done to this session" and
neither was complete.  Annotations had a table of their own; corrections had
nothing at all — the only way to find one was to spot its ring on the video and
remember which frame it was on.  Neither table was clickable, so "go back and
look at that again" meant scrubbing for it by hand.

So there is one panel.  It lists flagged frames, labelled ranges, and corrected
tracking points together, because they are the same kind of thing — a human
judgement laid over a recording — and a reviewer wants them in one place and in
time order.  Selecting a row goes there: it seeks the master clock, selects the
camera the change belongs to, and for a correction highlights the body part, so
landing on the right moment with nine markers on screen still tells you which
one is meant.

Deleting is the same gesture for both, and both go through the command bus:
removing an annotation removes the marker, and removing a correction restores
the model's own prediction (D-099).  Neither is a special case of the other.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.point_edits import PointEditStore, PointKey
from avialsync.ui.action_button import ActionButton
from avialsync.ui.annotations import AnnotationStore
from avialsync.ui.i18n import tr
from avialsync.ui.time_format import TimeDisplayMode, format_time

__all__ = ["ChangeRow", "ChangesPanel"]

#: Column order. "When" first because a reviewer reads this in time order.
_COLUMNS = ("When", "Change", "Where", "Detail")


@dataclasses.dataclass(frozen=True)
class ChangeRow:
    """One line in the panel: what changed, when, and how to get back to it."""

    kind: str
    #: ``None`` while the change cannot be placed on the master clock -- a
    #: correction whose pose file has not finished importing. Not zero: a fake
    #: time in a time-sorted column reads as a measurement rather than as an
    #: absence, which is the same reason the Messages panel keeps untimed
    #: records out of its table.
    t_master: float | None
    where: str
    detail: str
    #: Set for an annotation row; its index in the annotation store.
    marker_index: int | None = None
    #: Set for a correction row; the coordinate it corrected.
    point: PointKey | None = None
    #: The camera to select on revisit, when the change names one.
    camera: str | None = None
    #: Editable in place for an annotation; corrections have no label.
    label: str = ""


class ChangesPanel(QGroupBox):
    """Every human-made change in the session, in time order."""

    #: Emitted with the :class:`ChangeRow` the user selected, to go there.
    revisit_requested = Signal(object)
    #: Emitted with a :class:`PointKey` whose correction should be undone.
    #: Restoring a prediction is a mutation like any other and belongs on the
    #: undo stack, so the panel asks rather than writing the store (rule 14).
    delete_correction_requested = Signal(object)

    def __init__(
        self,
        annotations: AnnotationStore,
        corrections: PointEditStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(tr("Changes"), parent)
        self._annotations = annotations
        self._corrections = corrections
        self._rows: list[ChangeRow] = []
        #: Resolves a correction to a time, a camera, and a frame number. Set by
        #: the window, which is the only thing that knows the pose sources.
        self._resolver: Any = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([tr(name) for name in _COLUMNS])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
        self._table.setAccessibleName(tr("Changes made in this session"))
        self._table.setAccessibleDescription(
            tr("Flagged frames, labelled ranges, and corrected tracking points")
        )
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table)

        self._empty = QLabel(tr("Nothing has been changed in this session yet."), self)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty)

        buttons = QHBoxLayout()
        self._delete_button = QPushButton(tr("Delete"))
        self._delete_button.setToolTip(
            tr("Remove the selected annotation, or restore the predicted point")
        )
        self._delete_button.clicked.connect(self._on_delete)
        # The same QAction the File menu carries, not a second button with its
        # own wording: rule 15 forbids a menu item and a button that invoke one
        # command from being named independently. Set by the window once the
        # menu exists.
        self._export_button = ActionButton(self)
        buttons.addWidget(self._delete_button)
        buttons.addWidget(self._export_button)
        layout.addLayout(buttons)

        self._annotations.changed.connect(self.refresh)
        self._time_mode = TimeDisplayMode.RELATIVE
        self._t_epoch = 0.0
        self.refresh()

    # ── what it shows ────────────────────────────────────────────────

    def set_export_action(self, action: QAction) -> None:
        """Adopt the File menu's own Export Changes action for the panel button."""
        self._export_button.set_action(action)

    def set_correction_resolver(self, resolver: Any) -> None:
        """Supply the callable that places a correction in time and on a camera.

        Signature ``(PointKey) -> (t_master, camera, frame) | None``. The panel
        cannot work this out itself: it needs the pose source's own time column
        and the video it overlays, both of which live in the window.
        """
        self._resolver = resolver
        self.refresh()

    def set_time_mode(self, mode: TimeDisplayMode, t_epoch: float) -> None:
        """Follow the application's time display setting (D-020)."""
        self._time_mode = mode
        self._t_epoch = t_epoch
        self.refresh()

    @property
    def rows(self) -> list[ChangeRow]:
        """The rows currently listed, in display order."""
        return list(self._rows)

    def refresh(self) -> None:
        """Rebuild the table from both stores."""
        self._rows = sorted(
            self._annotation_rows() + self._correction_rows(),
            # Unplaced rows sort last rather than to zero, where a fake time
            # would put them before everything that really happened first.
            key=lambda row: (row.t_master is None, row.t_master or 0.0, row.kind, row.where),
        )
        self._table.blockSignals(True)
        try:
            self._table.setRowCount(0)
            for row in self._rows:
                position = self._table.rowCount()
                self._table.insertRow(position)
                cells = (self._when(row), row.kind, row.where, row.detail)
                for column, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    editable = column == 3 and row.marker_index is not None
                    if not editable:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if row.t_master is None:
                        item.setToolTip(
                            tr("Waiting for this recording's tracking data to finish loading.")
                        )
                    self._table.setItem(position, column, item)
        finally:
            self._table.blockSignals(False)
        self._empty.setVisible(not self._rows)
        self._table.setVisible(bool(self._rows))

    def _when(self, row: ChangeRow) -> str:
        if row.t_master is None:
            return "—"
        return format_time(row.t_master, self._time_mode, self._t_epoch)

    def _annotation_rows(self) -> list[ChangeRow]:
        rows: list[ChangeRow] = []
        for index, marker in enumerate(self._annotations.markers):
            cameras = ", ".join(sorted({frame.path for frame in marker.video_frames}))
            rows.append(
                ChangeRow(
                    kind=tr("Range") if marker.t_end is not None else tr("Flag"),
                    t_master=marker.t_start,
                    where=cameras or tr("timeline"),
                    detail=marker.label,
                    marker_index=index,
                    camera=marker.video_frames[0].path if marker.video_frames else None,
                    label=marker.label,
                )
            )
        return rows

    def _correction_rows(self) -> list[ChangeRow]:
        """One row per corrected coordinate, placed in time where possible.

        A correction whose source is not loaded (a session restored before its
        pose file finished importing) still gets a row: it exists, and hiding it
        until the import lands would make the panel disagree with the count the
        session reports.
        """
        rows: list[ChangeRow] = []
        for key, (x, y) in self._corrections.items():
            placed = self._resolver(key) if self._resolver is not None else None
            t_master, camera, frame = placed if placed is not None else (None, None, key.index)
            rows.append(
                ChangeRow(
                    kind=tr("Correction"),
                    t_master=None if t_master is None else float(t_master),
                    where=_short(key.source_id),
                    detail=tr("{part} moved to ({x:.1f}, {y:.1f}) px at frame {frame}").format(
                        part=key.point, x=x, y=y, frame=frame
                    ),
                    point=key,
                    camera=camera,
                )
            )
        return rows

    # ── interaction ──────────────────────────────────────────────────

    def _selected_row(self) -> ChangeRow | None:
        rows = {index.row() for index in self._table.selectedIndexes()}
        if len(rows) != 1:
            return None
        position = rows.pop()
        if 0 <= position < len(self._rows):
            return self._rows[position]
        return None

    def _on_selection_changed(self) -> None:
        row = self._selected_row()
        if row is not None:
            self.revisit_requested.emit(row)

    def _on_delete(self) -> None:
        """Remove whatever is selected, through whichever store owns it.

        Rows are taken highest-first: removing an annotation shifts every marker
        index after it, so deleting a multi-row selection from the top would
        remove the wrong ones.
        """
        selected = sorted({index.row() for index in self._table.selectedIndexes()}, reverse=True)
        for row in selected:
            if not 0 <= row < len(self._rows):
                continue
            change = self._rows[row]
            if change.marker_index is not None:
                self._annotations.remove(change.marker_index)
            elif change.point is not None:
                self.delete_correction_requested.emit(change.point)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Apply an edited annotation label; corrections have none to edit."""
        if item.column() != 3:
            return
        row = item.row()
        if not 0 <= row < len(self._rows):
            return
        change = self._rows[row]
        if change.marker_index is not None and item.text() != change.label:
            self._annotations.set_label(change.marker_index, item.text())


def _short(source_id: str) -> str:
    """Name a source by its file, which is what the user recognises."""
    from pathlib import Path

    return Path(source_id).name or source_id
