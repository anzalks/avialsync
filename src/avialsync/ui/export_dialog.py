"""One dialog for everything the user's own work can leave the session as.

Exporting used to be four unrelated menu items and a fifth button on the
annotation panel, each with its own file dialog, its own wording, and — in the
panel's case — its own copy of the CSV layout written on the UI thread.  A user
who had flagged frames *and* corrected points had no single place that said what
they had produced or where it would go.

This lists one row per artifact that actually has content, with the destination
already filled in beside the recording it came from.  Nothing is offered for a
source with nothing to export, so what is on screen is exactly what there is to
save.  Every destination is editable and has a Browse button, so "beside the
data" is a default rather than a rule.

The shape is the one :mod:`avialsync.ui.relink_dialog` and
:mod:`avialsync.ui.batch_import_dialog` already use — an explanatory line, a
table with a control per row, and a standard button box — because a dialog that
invents its own layout reads as a different application's.

Writing happens off the UI thread (architecture rule 3): a corrected copy of a
pose file is a full pass over hundreds of thousands of rows, and a retraining
set decodes a video frame for every corrected image.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.i18n import tr

__all__ = ["ExportItem", "ExportChangesDialog"]

#: What an artifact is. The kind decides which writer runs, never the label.
ANNOTATIONS = "annotations"
CORRECTED_POSE = "corrected_pose"
RETRAINING_SET = "retraining_set"

_COLUMNS = ("Export", "Destination", "")


@dataclasses.dataclass
class ExportItem:
    """One thing that can be written, and where it would go by default."""

    kind: str
    title: str
    detail: str
    target: Path
    #: The pose source this artifact derives from; empty for annotations.
    source_id: str = ""
    #: The video the pose source overlays, for a retraining set's images.
    video: str = ""
    selected: bool = True


class ExportChangesDialog(QDialog):
    """Choose which artifacts to write, and where each one goes."""

    def __init__(self, items: list[ExportItem], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Export Changes"))
        self.setMinimumSize(680, 320)
        self._items = items

        layout = QVBoxLayout(self)

        intro = QLabel(
            tr(
                "Only recordings with something to export are listed. Each "
                "destination defaults to the folder its data came from; edit it "
                "or use Browse to put the file somewhere else."
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._table = QTableWidget(len(items), len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([tr(name) for name in _COLUMNS])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().hide()
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setAccessibleName(tr("Artifacts to export"))
        self._table.setAccessibleDescription(
            tr("Tick what to write, and where each file should go")
        )

        for row, item in enumerate(items):
            title = QTableWidgetItem(item.title)
            title.setFlags(
                (title.flags() & ~Qt.ItemFlag.ItemIsEditable) | Qt.ItemFlag.ItemIsUserCheckable
            )
            title.setCheckState(Qt.CheckState.Checked if item.selected else Qt.CheckState.Unchecked)
            # The explanation rides on the row rather than under it: a second
            # line of grey text per artifact turns a four-row dialog into a wall.
            title.setToolTip(item.detail)
            self._table.setItem(row, 0, title)

            destination = QTableWidgetItem(str(item.target))
            destination.setToolTip(str(item.target))
            self._table.setItem(row, 1, destination)

            browse = QPushButton(tr("Browse…"))
            browse.setAccessibleName(
                tr("Choose a destination for {title}").format(title=item.title)
            )
            browse.clicked.connect(lambda _checked=False, index=row: self._browse(index))
            self._table.setCellWidget(row, 2, browse)

        layout.addWidget(self._table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Export"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self, index: int) -> None:
        item = self._table.item(index, 1)
        if item is None:
            return
        chosen, _ = QFileDialog.getSaveFileName(
            self, tr("Export To"), item.text(), tr("CSV files (*.csv);;All files (*)")
        )
        if chosen:
            item.setText(chosen)
            item.setToolTip(chosen)

    def selected_items(self) -> list[ExportItem]:
        """Return the ticked artifacts, each with the destination as edited."""
        chosen: list[ExportItem] = []
        for row, item in enumerate(self._items):
            title = self._table.item(row, 0)
            destination = self._table.item(row, 1)
            if title is None or destination is None:
                continue
            if title.checkState() != Qt.CheckState.Checked:
                continue
            text = destination.text().strip()
            if not text:
                continue
            chosen.append(dataclasses.replace(item, target=Path(text), selected=True))
        return chosen
