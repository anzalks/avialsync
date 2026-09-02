"""The Edit menu, driven by the document's own history (WP-2, D-097).

WP-2 was planned as a ``QUndoStack`` fed by wrapping each
:class:`~avialsync.core.document.Command` in a ``QUndoCommand``.  That is not
what this does, and the reason is worth stating where the code is.

:class:`~avialsync.core.document.Document` already *is* an undo stack.  It
holds the ordered history, coalesces continuous edits so a two-hundred-step
spin-box drag stays one entry, bounds itself at
:data:`~avialsync.core.document.MAX_LOG_ENTRIES`, releases the bulk state a
reset retains, and derives dirty state from where the save point sits in that
same history (D-087).  Adding a ``QUndoStack`` beside it would mean two
histories that must agree about depth, coalescing, and eviction — and the first
time they disagreed, the title would claim saved while the stack still had
edits, or undo would step somewhere the document had already discarded.

So there is one stack.  This module is the menu that drives it: two actions
whose text and enablement follow the document, and which call
``undo``/``redo`` against the live :class:`WindowMutationTarget`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QKeySequence

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMenu

    from avialsync.ui.main_window import MainWindow


class UndoActions(QObject):
    """Undo and Redo, kept in step with the document's history.

    The labels are not static.  A user reading "Undo" learns nothing about what
    is about to happen; "Undo Set offset for cam2.mp4 to 1.240 s" tells them
    whether they want it.  The text comes from the command's own ``label``, so
    there is no second place where an action is named.
    """

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self._window = window

        self.undo_action = QAction("Undo", window)
        self.undo_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Undo))
        self.undo_action.triggered.connect(self._undo)

        self.redo_action = QAction("Redo", window)
        # Both conventions, stated explicitly. On Windows
        # `StandardKey.Redo` resolves to Ctrl+Y alone, so leaving it to the
        # standard key would silently drop Ctrl+Shift+Z -- the binding a user
        # coming from any other platform will try first.
        self.redo_action.setShortcuts(
            [
                QKeySequence(QKeySequence.StandardKey.Redo),
                QKeySequence("Ctrl+Shift+Z"),
                QKeySequence("Ctrl+Y"),
            ]
        )
        self.redo_action.triggered.connect(self._redo)

        window.document.observe_log(self.refresh)
        self.refresh()

    def _undo(self) -> None:
        self._window.document.undo(self._window._mutations)

    def _redo(self) -> None:
        self._window.document.redo(self._window._mutations)

    def refresh(self) -> None:
        """Re-label and re-enable both actions from the document."""
        document = self._window.document

        undo_label = document.undo_label()
        self.undo_action.setEnabled(document.can_undo())
        self.undo_action.setText(f"Undo {undo_label}" if undo_label else "Undo")

        redo_label = document.redo_label()
        self.redo_action.setEnabled(document.can_redo())
        self.redo_action.setText(f"Redo {redo_label}" if redo_label else "Redo")


def install_edit_menu(window: MainWindow, menu: QMenu) -> UndoActions:
    """Populate the Edit menu and return the actions, for the shortcuts dialog."""
    actions = UndoActions(window)
    menu.addAction(actions.undo_action)
    menu.addAction(actions.redo_action)
    return actions
