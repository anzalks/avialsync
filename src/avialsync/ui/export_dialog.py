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

Writing happens off the UI thread (architecture rule 3): an edited copy of a
pose file is a full pass over hundreds of thousands of rows, and a retraining
set decodes a video frame for every corrected image.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.dlc_export import training_csv_path
from avialsync.ui.export_destinations import choose_file, choose_folder, remember, suggested
from avialsync.ui.i18n import tr
from avialsync.ui.tables import ThemedTable

__all__ = ["ExportItem", "ExportChangesDialog"]

#: What an artifact is. The kind decides which writer runs, never the label.
ANNOTATIONS = "annotations"
CORRECTED_POSE = "corrected_pose"
RETRAINING_SET = "retraining_set"

_COLUMNS = ("Export", "Destination", "Format", "Scorer", "")


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
    profile: str = "dlc"
    scorer: str = ""
    multi_animal: bool = False


class ExportChangesDialog(QDialog):
    """Choose which artifacts to write, and where each one goes."""

    def __init__(self, items: list[ExportItem], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Export Changes"))
        self.setMinimumSize(900, 320)
        self._items = items

        layout = QVBoxLayout(self)

        intro = QLabel(
            tr(
                "Only recordings with something to export are listed. Each "
                "destination defaults beside its data. A retraining destination "
                "is a folder whose contents can be copied into your project root."
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._table = ThemedTable(len(items), len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([tr(name) for name in _COLUMNS])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
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

            destination = QTableWidgetItem(str(suggested("changes", item.target)))
            destination.setToolTip(str(item.target))
            self._table.setItem(row, 1, destination)

            if item.kind == RETRAINING_SET:
                profile = QComboBox(self._table)
                profile.addItem(tr("DeepLabCut"), "dlc")
                if not item.multi_animal:
                    profile.addItem(tr("Lightning Pose (single view)"), "lightning_pose")
                profile.setAccessibleName(
                    tr("Training format for {title}").format(title=item.title)
                )
                profile.setAccessibleDescription(tr("Choose the project format for these labels"))
                profile.setCurrentIndex(max(0, profile.findData(item.profile)))
                self._table.setCellWidget(row, 2, profile)

                scorer = QLineEdit(self._table)
                scorer.setText(item.scorer)
                scorer.setPlaceholderText(tr("Project scorer"))
                scorer.setAccessibleName(tr("Project scorer for {title}").format(title=item.title))
                scorer.setAccessibleDescription(tr("Enter the scorer name used by your project"))
                self._table.setCellWidget(row, 3, scorer)

            browse = QPushButton(tr("Browse…"))
            browse.setAccessibleName(
                tr("Choose a destination for {title}").format(title=item.title)
            )
            browse.clicked.connect(lambda _checked=False, index=row: self._browse(index))
            self._table.setCellWidget(row, 4, browse)

        layout.addWidget(self._table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Export"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._export_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._table.itemChanged.connect(self._update_can_export)
        for row, item in enumerate(items):
            if item.kind == RETRAINING_SET:
                scorer_widget = self._table.cellWidget(row, 3)
                if isinstance(scorer_widget, QLineEdit):
                    scorer_widget.textChanged.connect(self._update_can_export)
        self._update_can_export()

    def _update_can_export(self) -> None:
        """A selected training set needs a scorer before it can be written."""
        valid = True
        for row, item in enumerate(self._items):
            title = self._table.item(row, 0)
            if item.kind != RETRAINING_SET or title is None:
                continue
            if title.checkState() != Qt.CheckState.Checked:
                continue
            destination = self._table.item(row, 1)
            if destination is None or not destination.text().strip():
                valid = False
            scorer = self._table.cellWidget(row, 3)
            if not isinstance(scorer, QLineEdit):
                valid = False
                continue
            try:
                training_csv_path(Path("."), "video", scorer.text().strip(), "dlc")
            except ValueError:
                valid = False
        self._export_button.setEnabled(valid)
        self._export_button.setToolTip(
            "" if valid else tr("Enter a portable scorer name used by the target project")
        )

    def _browse(self, index: int) -> None:
        item = self._table.item(index, 1)
        if item is None:
            return
        target = Path(item.text())
        if self._items[index].kind == RETRAINING_SET:
            parent = choose_folder(
                self, "changes", tr("Choose Export Parent Folder"), target.parent
            )
            chosen = parent / target.name if parent else None
        else:
            chosen = choose_file(
                self,
                "changes",
                tr("Export To"),
                target,
                tr("CSV files (*.csv);;All files (*)"),
            )
        if chosen:
            item.setText(str(chosen))
            item.setToolTip(str(chosen))

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
            target = Path(text)
            remember("changes", target)
            if item.kind == RETRAINING_SET:
                profile = self._table.cellWidget(row, 2)
                scorer = self._table.cellWidget(row, 3)
                if not isinstance(profile, QComboBox) or not isinstance(scorer, QLineEdit):
                    continue
                chosen.append(
                    dataclasses.replace(
                        item,
                        target=target,
                        profile=str(profile.currentData()),
                        scorer=scorer.text().strip(),
                        selected=True,
                    )
                )
            else:
                chosen.append(dataclasses.replace(item, target=target, selected=True))
        return chosen
