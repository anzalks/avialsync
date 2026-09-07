"""A push button that is a second *way to reach* a command, not a second one.

Architecture rule 15: a menu item and the button that invokes the same command
may not carry independently written text.  Qt's own answer to that is
``QToolButton.setDefaultAction``, and using it is what put a tool button in a
row of push buttons — flatter, differently proportioned, and visibly not one of
its neighbours.

So the binding is explicit instead.  The ``QAction`` stays the single author of
the label, the tooltip, the enablement and the checked state; this is an
ordinary ``QPushButton`` that follows it and triggers it.  A button added beside
existing ones looks like them, and there is still only one place the command is
defined (D-092).

The follower is a bound method of the button, deliberately: Qt drops a
connection whose receiver ``QObject`` has been destroyed, so a button that goes
away before its action cannot be repainted after the fact.  A module-level
closure over the button would outlive it and fault on a dead C++ object.
"""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QPushButton, QWidget

__all__ = ["ActionButton"]


class ActionButton(QPushButton):
    """A push button whose text, state, and effect all come from a ``QAction``.

    The action may arrive after construction — a panel is usually built before
    the menu that owns its actions — so the button is created empty and hidden,
    and shows itself once it has something to invoke.
    """

    def __init__(self, parent: QWidget | None = None, action: QAction | None = None) -> None:
        super().__init__(parent)
        self._action: QAction | None = None
        if action is not None:
            self.set_action(action)
        else:
            self.hide()

    @property
    def action(self) -> QAction | None:
        """The action this button invokes, if one has been set."""
        return self._action

    def set_action(self, action: QAction) -> None:
        """Adopt *action*: follow its presentation, and trigger it when clicked."""
        if self._action is not None:
            self._action.changed.disconnect(self._adopt)
            self._action.toggled.disconnect(self._on_action_toggled)
            self.clicked.disconnect(self._on_clicked)

        self._action = action
        self.setCheckable(action.isCheckable())
        action.changed.connect(self._adopt)
        action.toggled.connect(self._on_action_toggled)
        self.clicked.connect(self._on_clicked)
        self._adopt()
        self.show()

    def _on_clicked(self) -> None:
        """Invoke the action; its own signal decides what the state becomes.

        A checkable ``QPushButton`` has already flipped itself by the time this
        runs, so the action is triggered and :meth:`_adopt` puts the button back
        in step with whatever the action settled on. That way a handler which
        refuses the change is obeyed rather than overridden by the widget.
        """
        if self._action is None:
            return
        self._action.trigger()
        self._adopt()

    def _on_action_toggled(self, _checked: bool) -> None:
        self._adopt()

    def _adopt(self) -> None:
        """Take the action's current presentation."""
        action = self._action
        if action is None:
            return
        self.setText(action.text())
        self.setToolTip(action.toolTip())
        self.setEnabled(action.isEnabled())
        if not action.isCheckable():
            return
        blocked = self.blockSignals(True)
        try:
            self.setChecked(action.isChecked())
        finally:
            self.blockSignals(blocked)
