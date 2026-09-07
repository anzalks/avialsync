"""One dialog for everything the user's own work can leave the session as.

Exporting used to be four unrelated menu items and a fifth button on the
annotation panel, each with its own file dialog, its own wording, and — in the
panel's case — its own copy of the CSV layout written on the UI thread.  A user
who had flagged frames *and* corrected points had no single place that said what
they had produced or where it would go.

This lists one row per artifact that actually has content, with the destination
already filled in beside each recording it came from.  Nothing is offered for a
source with nothing to export, so what is on screen is exactly what there is to
save.  The paths are editable and each has a Browse button, so "beside the data"
is a default rather than a rule.

Writing happens off the UI thread (architecture rule 3): a corrected copy of a
pose file is a full pass over hundreds of thousands of rows, and a retraining
set decodes a video frame for every corrected image.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.i18n import tr

__all__ = ["ExportItem", "ExportChangesDialog"]

#: What an artifact is. The kind decides which writer runs, never the label.
ANNOTATIONS = "annotations"
CORRECTED_POSE = "corrected_pose"
RETRAINING_SET = "retraining_set"


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
        self._items = items
        self._checks: list[QCheckBox] = []
        self._fields: list[QLineEdit] = []

        layout = QVBoxLayout(self)
        intro = QLabel(
            tr(
                "Only recordings with something to export are listed. Each "
                "destination defaults to the folder its data came from."
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        for row, item in enumerate(items):
            check = QCheckBox(item.title, self)
            check.setChecked(item.selected)
            check.setToolTip(item.detail)
            check.setAccessibleDescription(item.detail)
            self._checks.append(check)

            field = QLineEdit(str(item.target), self)
            field.setAccessibleName(tr("Destination for {title}").format(title=item.title))
            self._fields.append(field)

            browse = QPushButton(tr("Browse…"), self)
            browse.setAccessibleName(
                tr("Choose a destination for {title}").format(title=item.title)
            )
            browse.clicked.connect(lambda _checked=False, index=row: self._browse(index))

            detail = QLabel(item.detail, self)
            detail.setWordWrap(True)
            detail.setEnabled(False)

            grid.addWidget(check, row * 2, 0)
            grid.addWidget(field, row * 2, 1)
            grid.addWidget(browse, row * 2, 2)
            grid.addWidget(detail, row * 2 + 1, 1, 1, 2)
        layout.addLayout(grid)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Export"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self, index: int) -> None:
        current = Path(self._fields[index].text())
        chosen, _ = QFileDialog.getSaveFileName(
            self, tr("Export To"), str(current), tr("CSV files (*.csv);;All files (*)")
        )
        if chosen:
            self._fields[index].setText(chosen)

    def selected_items(self) -> list[ExportItem]:
        """Return the checked artifacts, each with the destination as edited."""
        chosen: list[ExportItem] = []
        for item, check, field in zip(self._items, self._checks, self._fields, strict=True):
            if not check.isChecked():
                continue
            text = field.text().strip()
            if not text:
                continue
            chosen.append(dataclasses.replace(item, target=Path(text), selected=True))
        return chosen
