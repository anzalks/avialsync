"""One list of everything a person changed, and a way back to each of them.

Before this there were two answers to "what have I done to this session" and
neither was complete.  Annotations had a table of their own; corrections had
nothing at all — the only way to find one was to spot its ring on the video and
remember which frame it was on.  Neither table was clickable, so "go back and
look at that again" meant scrubbing for it by hand.

So there is one panel.  It lists flagged frames, labelled ranges, and corrected
tracking points together, because they are the same kind of thing — a human
judgement laid over a recording — and a reviewer wants them in one place and in
time order, including accepted identity swaps. Selecting a row goes there: it
seeks the master clock, selects the camera the change belongs to, and for a
correction highlights the body part, so
landing on the right moment with nine markers on screen still tells you which
one is meant.

Deleting is the same gesture for both, and both go through the command bus:
removing an annotation removes the marker, removing a correction restores the
model's prediction, and removing a swap restores its previous routing.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.identity_swaps import SwapEvent, SwapStore
from avialsync.core.point_edits import PointEditStore, PointKey
from avialsync.ui.action_button import ActionButton
from avialsync.ui.annotations import AnnotationStore
from avialsync.ui.design_tokens import ControlRole, apply_role, spacing
from avialsync.ui.empty_note import EmptyNote
from avialsync.ui.ethogram_bar import EthogramBar
from avialsync.ui.i18n import tr
from avialsync.ui.tables import ThemedTable
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
    #: Set for an accepted identity swap, so Delete can undo that exact event.
    swap: SwapEvent | None = None
    swap_source_id: str = ""
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
    #: undo stack, so the panel asks rather than writing the store.
    delete_correction_requested = Signal(object)
    delete_swap_requested = Signal(str, object)

    def __init__(
        self,
        annotations: AnnotationStore,
        corrections: PointEditStore,
        swaps: SwapStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(tr("Changes"), parent)
        self._annotations = annotations
        self._corrections = corrections
        self._swaps = swaps
        self._all_rows: list[ChangeRow] = []
        self._search_keys: list[str] = []
        self._rows: list[ChangeRow] = []
        self._suppress_refresh = False
        #: Resolves a correction to a time, a camera, and a frame number. Set by
        #: the window, which is the only thing that knows the pose sources.
        self._resolver: Any = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(0)
        scroll.setAccessibleName(tr("Changes list and controls"))
        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(spacing("s"), spacing("s"), spacing("s"), spacing("s"))

        self.ethogram_bar = EthogramBar(annotations, content)
        layout.addWidget(self.ethogram_bar)
        layout.addLayout(self._build_filter_row())
        self._table = self._build_table()
        layout.addWidget(self._table)
        # Names what fills the page: wrapped, as the sidebar is
        # narrower than the sentence.
        self._empty = EmptyNote(
            tr(
                "Nothing has been changed yet. Flag a frame (M or Flag Frame under the "
                "videos), label a range, or correct a tracked point, and it is listed here."
            ),
            self,
        )
        layout.addWidget(self._empty)
        layout.addLayout(self._build_action_buttons())

        scroll.setWidget(content)
        outer.addWidget(scroll)

        self._annotations.changed.connect(self.refresh)
        self._time_mode = TimeDisplayMode.RELATIVE
        self._t_epoch = 0.0
        self.refresh()

    def _build_filter_row(self) -> QHBoxLayout:
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(spacing("xs"))
        self.kind_filter = QComboBox(self)
        self.kind_filter.addItem(tr("All changes"), "")
        self.kind_filter.addItem(tr("Flags"), "Flag")
        self.kind_filter.addItem(tr("Ranges"), "Range")
        self.kind_filter.addItem(tr("Corrections"), "Correction")
        self.kind_filter.addItem(tr("Identity swaps"), "Identity swap")
        self.kind_filter.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.kind_filter.setMinimumContentsLength(6)
        self.kind_filter.setAccessibleName(tr("Filter changes by kind"))
        self.kind_filter.currentIndexChanged.connect(lambda _index: self._apply_search_filter())
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText(tr("Filter label or source…"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.search_edit.setMinimumWidth(50)
        self.search_edit.setAccessibleName(tr("Filter changes by text"))
        self.search_edit.textChanged.connect(lambda _text: self._apply_search_filter())
        filter_row.addWidget(self.kind_filter)
        filter_row.addWidget(self.search_edit, 1)
        return filter_row

    def _build_table(self) -> ThemedTable:
        table = ThemedTable(0, len(_COLUMNS))
        table.setHorizontalHeaderLabels([tr(name) for name in _COLUMNS])
        table.verticalHeader().hide()
        header = table.horizontalHeader()
        header.setMinimumSectionSize(48)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        metrics = table.fontMetrics()
        pad = spacing("m", table)
        table.setColumnWidth(
            0,
            max(metrics.horizontalAdvance(tr("When")), metrics.horizontalAdvance("00:00:00.000"))
            + pad,
        )
        table.setColumnWidth(
            1,
            max(metrics.horizontalAdvance(tr("Change")), metrics.horizontalAdvance(tr("Range")))
            + pad,
        )
        table.setColumnWidth(
            2,
            max(metrics.horizontalAdvance(tr("Where")), metrics.horizontalAdvance("timeline"))
            + pad,
        )
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
        table.setAccessibleName(tr("Changes made in this session"))
        table.setAccessibleDescription(
            tr("Flagged frames, labelled ranges, corrected points, and identity swaps")
        )
        table.itemChanged.connect(self._on_item_changed)
        table.itemSelectionChanged.connect(self._on_selection_changed)
        return table

    def _build_action_buttons(self) -> QVBoxLayout:
        # Stacked, destructive last, as Open Files is: side by side the
        # pair needed 294 px at 16 pt against the 280 px page.
        buttons = QVBoxLayout()
        self._delete_button = QPushButton(tr("Delete"))
        self._delete_button.setToolTip(
            tr("Remove the selected annotation, correction, or identity swap")
        )
        apply_role(self._delete_button, ControlRole.DESTRUCTIVE)
        self._delete_button.clicked.connect(self._on_delete)
        # The same QAction the File menu carries, not a second button with its
        # own wording: a menu item and a button that invoke one
        # command are never named independently. Set by the window once the
        # menu exists.
        self._export_button = ActionButton(self)
        buttons.addWidget(self._export_button)
        buttons.addWidget(self._delete_button)
        return buttons

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
        """Follow the application's time display setting."""
        self._time_mode = mode
        self._t_epoch = t_epoch
        self.refresh()

    @property
    def rows(self) -> list[ChangeRow]:
        """The rows currently listed, in display order."""
        return list(self._rows)

    def refresh(self) -> None:
        """Rebuild the table from every store holding a user-made change."""
        if self._suppress_refresh:
            return
        all_rows = sorted(
            self._annotation_rows() + self._correction_rows() + self._swap_rows(),
            # Unplaced rows sort last rather than to zero, where a fake time
            # would put them before everything that really happened first.
            key=lambda row: (row.t_master is None, row.t_master or 0.0, row.kind, row.where),
        )
        self._all_rows = all_rows
        self._search_keys = [f"{r.detail}\n{r.where}\n{r.kind}".lower() for r in all_rows]
        unplaced_tip = tr("Waiting for this recording's tracking data to finish loading.")

        was_enabled = self._table.updatesEnabled()
        self._table.setUpdatesEnabled(False)
        blocked = self._table.blockSignals(True)
        try:
            self._table.setRowCount(len(all_rows))
            for position, row in enumerate(all_rows):
                cells = (self._when(row), row.kind, row.where, row.detail)
                for column, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    editable = column == 3 and row.marker_index is not None
                    if not editable:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if row.t_master is None:
                        item.setToolTip(unplaced_tip)
                    self._table.setItem(position, column, item)
        finally:
            self._table.blockSignals(blocked)
            self._table.setUpdatesEnabled(was_enabled)
        self._empty.setVisible(not all_rows)
        self._table.setVisible(bool(all_rows))
        self._apply_search_filter()

    def _apply_search_filter(self) -> None:
        """Hide non-matching rows in place without re-resolving or rebuilding items."""
        wanted_code = str(self.kind_filter.currentData() or "")
        wanted_kind = tr(wanted_code) if wanted_code else ""
        needle = self.search_edit.text().strip().lower()
        visible_rows: list[ChangeRow] = []

        was_enabled = self._table.updatesEnabled()
        self._table.setUpdatesEnabled(False)
        blocked = self._table.blockSignals(True)
        try:
            for position, (row, search_key) in enumerate(
                zip(self._all_rows, self._search_keys, strict=True)
            ):
                matches = (not wanted_kind or row.kind == wanted_kind) and (
                    not needle or needle in search_key
                )
                self._table.setRowHidden(position, not matches)
                if matches:
                    visible_rows.append(row)
        finally:
            self._table.blockSignals(blocked)
            self._table.setUpdatesEnabled(was_enabled)
        self._rows = visible_rows
        self._update_delete()

    def _update_delete(self) -> None:
        """Offer Delete only with a visible row selected (D-214)."""
        selected = any(
            not self._table.isRowHidden(idx.row()) for idx in self._table.selectedIndexes()
        )
        self._delete_button.setEnabled(selected)
        self._delete_button.setToolTip(
            tr("Remove the selected annotation, correction, or identity swap")
            if selected
            else tr("Select a change in the list first.")
        )

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

    def _swap_rows(self) -> list[ChangeRow]:
        """List each accepted flip, including one whose pose has not loaded yet."""
        rows: list[ChangeRow] = []
        for source_id, event in self._swaps:
            key = PointKey(source_id, "", event.index)
            placed = self._resolver(key) if self._resolver is not None else None
            t_master, camera, frame = placed if placed is not None else (None, None, event.index)
            parts = tr("all parts") if not event.parts else ", ".join(event.parts)
            rows.append(
                ChangeRow(
                    kind=tr("Identity swap"),
                    t_master=None if t_master is None else float(t_master),
                    where=_short(source_id),
                    detail=tr("{a} ↔ {b} from frame {frame} ({parts})").format(
                        a=event.lanes[0], b=event.lanes[1], frame=frame, parts=parts
                    ),
                    swap=event,
                    swap_source_id=source_id,
                    camera=camera,
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
            shown = self._corrections.shown_as(key)
            name = (
                key.point
                if shown == key.point
                else tr("{column} (shown as {label})").format(column=key.point, label=shown)
            )
            rows.append(
                ChangeRow(
                    kind=tr("Correction"),
                    t_master=None if t_master is None else float(t_master),
                    where=_short(key.source_id),
                    detail=tr("{part} moved to ({x:.1f}, {y:.1f}) px at frame {frame}").format(
                        part=name, x=x, y=y, frame=frame
                    ),
                    point=key,
                    camera=camera,
                )
            )
        return rows

    # ── interaction ──────────────────────────────────────────────────

    def _selected_row(self) -> ChangeRow | None:
        rows = {
            index.row()
            for index in self._table.selectedIndexes()
            if not self._table.isRowHidden(index.row())
        }
        if len(rows) != 1:
            return None
        position = rows.pop()
        if 0 <= position < len(self._all_rows):
            return self._all_rows[position]
        return None

    def _on_selection_changed(self) -> None:
        self._update_delete()
        row = self._selected_row()
        if row is not None:
            self.revisit_requested.emit(row)

    def _delete_selected(self) -> None:
        """Remove selected visible changes while coalescing intermediate rebuilds."""
        selected_rows = sorted(
            {
                index.row()
                for index in self._table.selectedIndexes()
                if 0 <= index.row() < len(self._all_rows)
                and not self._table.isRowHidden(index.row())
            },
            reverse=True,
        )
        if not selected_rows:
            return
        changes = [self._all_rows[row] for row in selected_rows]
        marker_indices = [c.marker_index for c in changes if c.marker_index is not None]

        self._suppress_refresh = True
        try:
            remove_indices = getattr(self._annotations, "remove_indices", None)
            if marker_indices and callable(remove_indices):
                remove_indices(marker_indices)
            else:
                for idx in sorted(marker_indices, reverse=True):
                    self._annotations.remove(idx)
            for change in changes:
                if change.point is not None:
                    self.delete_correction_requested.emit(change.point)
                elif change.swap is not None:
                    self.delete_swap_requested.emit(change.swap_source_id, change.swap)
        finally:
            self._suppress_refresh = False
        self.refresh()

    def _on_delete(self) -> None:
        """Remove whatever is selected, through whichever store owns it."""
        self._delete_selected()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Apply an edited annotation label; corrections have none to edit."""
        if item.column() != 3:
            return
        row = item.row()
        if not 0 <= row < len(self._all_rows):
            return
        change = self._all_rows[row]
        if change.marker_index is not None and item.text() != change.label:
            self._annotations.set_label(change.marker_index, item.text())


def _short(source_id: str) -> str:
    """Name a source by its file, which is what the user recognises."""
    from pathlib import Path

    return Path(source_id).name or source_id
