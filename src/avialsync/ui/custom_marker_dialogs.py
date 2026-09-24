"""The two questions Add 3D Marker asks: what to call it, and where calibration comes from.

Both are dialogs the user explicitly asked for by clicking Add 3D Marker, which
is the case AGENTS rule 11 allows a modal for. Plain ``QDialog`` rather than
``QInputDialog``/``QMessageBox``: the latter is banned outside ``ui/feedback``
(rule 12), and building both the same way keeps their accessible names in one
place.
"""

from __future__ import annotations

import re
from collections.abc import Collection

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.i18n import tr

__all__ = ["ask_marker_name", "ask_calibration_source", "IMPORT", "COMPUTE"]

IMPORT = "import"
COMPUTE = "compute"

#: A marker name becomes a CSV column prefix (``<name>_x``) and, through the
#: DLC layout, a body-part name: anything a spreadsheet or pandas would split
#: or quote is refused rather than escaped.
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")


class _MarkerNameDialog(QDialog):
    def __init__(self, taken: Collection[str], suggestion: str, parent: QWidget | None) -> None:
        super().__init__(parent)
        self._taken = {name.lower() for name in taken}
        self.setWindowTitle(tr("Add 3D Marker"))
        self.setAccessibleName(tr("Name the new 3D marker"))
        layout = QVBoxLayout(self)
        prompt = QLabel(
            tr(
                "Name the new marker. You will then click it once in each "
                "camera, on the current frame."
            ),
            self,
        )
        prompt.setWordWrap(True)
        layout.addWidget(prompt)
        self.edit = QLineEdit(suggestion, self)
        self.edit.setAccessibleName(tr("Marker name"))
        self.edit.setAccessibleDescription(
            tr("Letters, digits, underscore and hyphen; must not match a tracked point")
        )
        self.edit.selectAll()
        layout.addWidget(self.edit)
        self.problem = QLabel(self)
        self.problem.setAccessibleName(tr("Why the name cannot be used"))
        layout.addWidget(self.problem)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.edit.textChanged.connect(self._validate)
        self._validate(self.edit.text())

    def _validate(self, text: str) -> None:
        name = text.strip()
        problem = ""
        if not name:
            problem = tr("Enter a name.")
        elif not _NAME_PATTERN.match(name):
            problem = tr("Use letters, digits, underscore or hyphen only.")
        elif name.lower() in self._taken:
            problem = tr("A tracked point or marker already uses this name.")
        self.problem.setText(problem)
        self.problem.setVisible(bool(problem))
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setEnabled(not problem)


def ask_marker_name(
    parent: QWidget | None, taken: Collection[str], suggestion: str = ""
) -> str | None:
    """Ask for a new marker's name; None when cancelled.

    *taken* holds every name already on screen -- tracked body parts included,
    since a marker called ``left_paw`` would land in the same column as the
    model's own ``left_paw`` in anything that merges the two files.
    """
    dialog = _MarkerNameDialog(taken, suggestion, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.edit.text().strip() or None


def ask_calibration_source(parent: QWidget | None, folder: str) -> str | None:
    """Ask how to get the missing calibration: ``IMPORT``, ``COMPUTE``, or None."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(tr("No camera calibration"))
    dialog.setAccessibleName(tr("Choose where the camera calibration comes from"))
    layout = QVBoxLayout(dialog)
    text = QLabel(
        tr(
            "A 3D marker needs the cameras' calibration, and none was found in "
            "{folder}.\n\n"
            "Import: point at an existing calibration.toml. A calibration_ref.txt "
            "naming it is written in the pose-3d folder -- copy that file to other "
            "experiments filmed with the same rig.\n\n"
            "Compute: fit one from this session's 3D pose and its 2D tracking, "
            "and save it as calibration.toml in the pose-3d folder."
        ).format(folder=folder),
        dialog,
    )
    text.setWordWrap(True)
    layout.addWidget(text)
    buttons = QDialogButtonBox(dialog)
    choice: dict[str, str | None] = {"value": None}

    def _button(label: str, value: str | None, description: str) -> QPushButton:
        button = QPushButton(label, dialog)
        button.setAccessibleName(label)
        button.setAccessibleDescription(description)

        def _chosen() -> None:
            choice["value"] = value
            if value is None:
                dialog.reject()
            else:
                dialog.accept()

        button.clicked.connect(_chosen)
        return button

    buttons.addButton(
        _button(tr("Import…"), IMPORT, tr("Choose an existing calibration.toml")),
        QDialogButtonBox.ButtonRole.AcceptRole,
    )
    buttons.addButton(
        _button(tr("Compute"), COMPUTE, tr("Fit a calibration from this session's tracking")),
        QDialogButtonBox.ButtonRole.AcceptRole,
    )
    buttons.addButton(
        _button(tr("Cancel"), None, tr("Do not add a marker")),
        QDialogButtonBox.ButtonRole.RejectRole,
    )
    layout.addWidget(buttons)
    dialog.exec()
    return choice["value"]
