"""The status bar's Tasks button and the popover that lists jobs (D-172).

Tasks was the sixth inspector tab, consulted only when something takes longer
than expected, and its share of the tab bar was what elided every other title.
It now opens from the status bar, beside the activity area that reports the
same jobs, as a popover that closes when the user clicks elsewhere.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QWidgetAction

from avialsync.ui.feedback.jobs_panel import JobsPanel
from avialsync.ui.i18n import tr
from avialsync.ui.menu_button import MenuGlyphButton

__all__ = ["TasksButton"]


class TasksButton(MenuGlyphButton):
    """Opens *panel* in a popover anchored on the status bar."""

    def __init__(self, panel: JobsPanel, parent: QWidget | None = None) -> None:
        super().__init__("tasks", tr("Background tasks"), parent)
        self.panel = panel
        self.setText(tr("Tasks"))
        self.setAccessibleDescription(tr("Show running and recently finished background tasks"))
        self.setToolTip(tr("Show running and recently finished background tasks"))
        self.popover = self.menu()
        holder = QWidgetAction(self.popover)
        panel.setMinimumSize(360, 200)
        holder.setDefaultWidget(panel)
        self.popover.addAction(holder)

    def show_menu(self) -> None:
        """A click opens the popover upward, off the bottom of the window."""
        self.show_popover()

    def show_popover(self) -> None:
        """Open the popover above the status bar without blocking (no ``exec``)."""
        self.popover.popup(self.mapToGlobal(self.rect().topLeft()))
