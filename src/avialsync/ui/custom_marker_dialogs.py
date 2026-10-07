"""The two questions Add 3D Marker asks: what to call it, and where calibration comes from.

Both are dialogs the user explicitly asked for -- by choosing Add 3D Marker, Add
Wheel, or a notification's "Choose Calibration…" -- which is the case AGENTS
rule 11 allows a modal for. Never opened for an overlay switch. Plain ``QDialog`` rather than
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

__all__ = [
    "ask_marker_name",
    "ask_calibration_source",
    "CalibrationSourceDialog",
    "IMPORT",
    "COMPUTE",
]

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
        self.setAccessibleDescription(
            tr("Give the marker a name, then click it once in each camera on the current frame")
        )
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
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setAccessibleDescription(tr("Close this and click the marker in each camera"))
        cancel = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel is not None:
            cancel.setAccessibleDescription(tr("Do not add a marker"))
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


class CalibrationSourceDialog(QDialog):
    """Import or Compute: where the missing calibration comes from."""

    def __init__(self, folder: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        #: ``IMPORT``, ``COMPUTE``, or None once closed without a choice.
        self.choice: str | None = None
        self.setWindowTitle(tr("No camera calibration"))
        self.setAccessibleName(tr("Choose where the camera calibration comes from"))
        self.setAccessibleDescription(
            tr("Import an existing calibration.toml, or compute one from this session's tracking")
        )
        layout = QVBoxLayout(self)
        text = QLabel(
            tr(
                "Placing points in 3D needs the cameras' calibration, and none was "
                "found in {folder}.\n\n"
                "Import: point at an existing calibration.toml. A calibration_ref.txt "
                "naming it is written in the pose-3d folder -- copy that file to other "
                "experiments filmed with the same rig.\n\n"
                "Compute: fit one from this session's 3D pose and its 2D tracking, and "
                "save it in the pose-3d folder beside anything already there.\n\n"
                "Nothing is overwritten: a calibration_ref.txt already in the folder is "
                "kept under a dated name."
            ).format(folder=folder),
            self,
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        buttons = QDialogButtonBox(self)
        for label, value, description, role in (
            (
                tr("Import…"),
                IMPORT,
                tr("Choose an existing calibration.toml"),
                QDialogButtonBox.ButtonRole.AcceptRole,
            ),
            (
                tr("Compute"),
                COMPUTE,
                tr("Fit a calibration from this session's tracking"),
                QDialogButtonBox.ButtonRole.AcceptRole,
            ),
            (
                tr("Cancel"),
                None,
                tr("Continue without a calibration"),
                QDialogButtonBox.ButtonRole.RejectRole,
            ),
        ):
            buttons.addButton(self._button(label, value, description), role)
        layout.addWidget(buttons)

    def _button(self, label: str, value: str | None, description: str) -> QPushButton:
        button = QPushButton(label, self)
        button.setAccessibleName(label)
        button.setAccessibleDescription(description)

        def _chosen() -> None:
            self.choice = value
            if value is None:
                self.reject()
            else:
                self.accept()

        button.clicked.connect(_chosen)
        return button


def ask_calibration_source(parent: QWidget | None, folder: str) -> str | None:
    """Ask how to get the missing calibration: ``IMPORT``, ``COMPUTE``, or None."""
    dialog = CalibrationSourceDialog(folder, parent)
    dialog.exec()
    return dialog.choice
