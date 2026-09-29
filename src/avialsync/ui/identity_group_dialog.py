"""Create a user-declared pair of identity lanes from pose point names."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.identity_groups import CUSTOM, group_id
from avialsync.core.identity_swaps import SwapGroup
from avialsync.core.pose import PoseSchema
from avialsync.ui.i18n import tr


class IdentityGroupDialog(QDialog):
    """Map matching parts in two named lanes to actual pose columns."""

    def __init__(
        self, schema: PoseSchema, existing: tuple[SwapGroup, ...], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("New identity group"))
        self._existing = {group.name for group in existing}
        self._points = tuple(
            point.name for point in schema.points if {"x", "y"}.issubset(point.axes)
        )
        self._result: SwapGroup | None = None
        self._rows: list[tuple[QLineEdit, QComboBox, QComboBox]] = []

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._name = QLineEdit(self)
        self._name.setAccessibleName(tr("Identity group name"))
        self._name.setAccessibleDescription(tr("A unique name for this pair of lanes"))
        form.addRow(tr("Group name"), self._name)
        self._first = QLineEdit(tr("A"), self)
        self._first.setAccessibleName(tr("First lane name"))
        self._first.setAccessibleDescription(tr("Label shown for the first identity lane"))
        form.addRow(tr("First lane"), self._first)
        self._second = QLineEdit(tr("B"), self)
        self._second.setAccessibleName(tr("Second lane name"))
        self._second.setAccessibleDescription(tr("Label shown for the second identity lane"))
        form.addRow(tr("Second lane"), self._second)
        layout.addLayout(form)

        explanation = QLabel(
            tr("Pair the pose columns that may exchange labels. Each row is one shared part."),
            self,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self._pairs = QVBoxLayout()
        layout.addLayout(self._pairs)
        self._add_pair()
        add = QPushButton(tr("Add part pair"), self)
        add.setAccessibleName(tr("Add another pair of pose points"))
        add.setAccessibleDescription(tr("Add another shared part to this group"))
        add.clicked.connect(self._add_pair)
        layout.addWidget(add)

        self._error = QLabel(self)
        self._error.setWordWrap(True)
        self._error.setAccessibleName(tr("Identity group validation"))
        layout.addWidget(self._error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Create group"))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setAccessibleDescription(
            tr("Save the declared pose point mapping")
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setAccessibleDescription(
            tr("Leave the identity groups unchanged")
        )
        buttons.accepted.connect(self._create)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_pair(self) -> None:
        row = QHBoxLayout()
        part = QLineEdit(self)
        part.setPlaceholderText(tr("Part name"))
        part.setAccessibleName(tr("Shared part name"))
        part.setAccessibleDescription(tr("Name used to select this point pair"))
        first = QComboBox(self)
        first.setAccessibleName(tr("First lane pose point"))
        first.setAccessibleDescription(tr("Pose column shown in the first lane"))
        second = QComboBox(self)
        second.setAccessibleName(tr("Second lane pose point"))
        second.setAccessibleDescription(tr("Pose column shown in the second lane"))
        for point in self._points:
            first.addItem(point)
            second.addItem(point)
        if second.count() > 1:
            second.setCurrentIndex(1)
        row.addWidget(part)
        row.addWidget(first, 1)
        row.addWidget(second, 1)
        self._pairs.addLayout(row)
        self._rows.append((part, first, second))

    def _create(self) -> None:
        name = self._name.text().strip()
        first = self._first.text().strip()
        second = self._second.text().strip()
        identifier = group_id(CUSTOM, name)
        if not name or identifier in self._existing:
            self._error.setText(tr("Enter a unique group name."))
            return
        if not first or not second or first == second:
            self._error.setText(tr("Enter two different lane names."))
            return
        if any(character in text for text in (name, first, second) for character in ",|\r\n"):
            self._error.setText(tr("Group and lane names cannot contain commas or separators."))
            return
        parts: list[str] = []
        members: list[tuple[str, str, str]] = []
        used: set[str] = set()
        for part_edit, first_box, second_box in self._rows:
            part = part_edit.text().strip()
            a, b = first_box.currentText(), second_box.currentText()
            if not part or part in parts or a == b or a in used or b in used:
                self._error.setText(
                    tr("Each part needs a unique name and two different, unused pose points.")
                )
                return
            if any(character in part for character in ",|\r\n"):
                self._error.setText(tr("Part names cannot contain commas or separators."))
                return
            parts.append(part)
            members.extend(((first, part, a), (second, part, b)))
            used.update((a, b))
        self._result = SwapGroup(
            name=identifier, lanes=(first, second), parts=tuple(parts), members=tuple(members)
        )
        self.accept()

    def group(self) -> SwapGroup | None:
        """The validated declaration, or None if the dialog was cancelled."""
        return self._result
