"""Shared Save and Remove commands for every physical-prop editor."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget

from avialsync.ui.action_button import ActionButton
from avialsync.ui.i18n import tr


class PropRecordActions(QObject):
    """One presentation and availability policy for prop record commands.

    Editors supply their geometry-specific acceptance handler; every button
    follows these live actions, including its explanation when unavailable.
    """

    save_requested = Signal()
    remove_requested = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.save_action = QAction(tr("Save prop"), self)
        self.remove_action = QAction(tr("Remove saved prop"), self)
        self.save_button = ActionButton(parent, self.save_action)
        self.remove_button = ActionButton(parent, self.remove_action)
        self.save_button.setAccessibleName(self.save_action.text())
        self.remove_button.setAccessibleName(self.remove_action.text())
        self.save_button.setAccessibleDescription(
            tr("Save this prop's accepted geometry and evidence beside the recording.")
        )
        self.remove_button.setAccessibleDescription(
            tr("Remove this saved prop from the recording; Undo restores it.")
        )
        self.save_action.triggered.connect(self.save_requested)
        self.remove_action.triggered.connect(self.remove_requested)
        self.set_available(can_save=False, can_remove=False)

    def set_available(self, *, can_save: bool, can_remove: bool, save_reason: str = "") -> None:
        """Keep command state and its explanation identical across editors."""
        self.save_action.setEnabled(can_save)
        self.save_action.setToolTip(
            self.save_button.accessibleDescription()
            if can_save
            else save_reason or tr("Select a saved prop first.")
        )
        self.remove_action.setEnabled(can_remove)
        self.remove_action.setToolTip(
            self.remove_button.accessibleDescription()
            if can_remove
            else tr("Select a saved prop first.")
        )
