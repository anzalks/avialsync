"""The status bar's Tasks button and the popover that lists jobs (D-172).

Tasks was the sixth inspector tab, consulted only when something takes longer
than expected, and its share of the tab bar was what elided every other title.
It now opens from the status bar, beside the activity area that reports the
same jobs, as a popover that closes when the user clicks elsewhere.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QToolButton, QWidget, QWidgetAction

from avialsync.ui.feedback.jobs_panel import JobsPanel
from avialsync.ui.i18n import tr
from avialsync.ui.icons import set_svg_icon

__all__ = ["TasksButton"]


class TasksButton(QToolButton):
    """Opens *panel* in a popover anchored on the status bar."""

    def __init__(self, panel: JobsPanel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.panel = panel
        self.setText(tr("Tasks"))
        self.setAccessibleName(tr("Background tasks"))
        self.setAccessibleDescription(tr("Show running and recently finished background tasks"))
        self.setToolTip(tr("Show running and recently finished background tasks"))
        self.setAutoRaise(True)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        set_svg_icon(self, "tasks")

        self.popover = QMenu(self)
        self.popover.setAccessibleName(tr("Background tasks"))
        holder = QWidgetAction(self.popover)
        panel.setMinimumSize(360, 200)
        holder.setDefaultWidget(panel)
        self.popover.addAction(holder)
        self.setMenu(self.popover)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

    def show_popover(self) -> None:
        """Open the popover from the menu or palette without blocking (no ``exec``)."""
        self.popover.popup(self.mapToGlobal(self.rect().topLeft()))
