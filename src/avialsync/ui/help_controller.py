"""Window-owned commands for Help, Preferences, and diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from avialsync.ui.about import citation_text, project_urls, version_report
from avialsync.ui.feedback.text_dialog import show_text
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.preferences_dialog import PreferencesDialog
    from avialsync.ui.review_workflow import ReviewWorkflowDialog


class HelpController(QObject):
    """Own the Help and Preferences actions for one main window."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self._window = window
        self._preferences_dialog: PreferencesDialog | None = None
        self._review_workflow_dialog: ReviewWorkflowDialog | None = None

    @Slot(str)
    def open_project_url(self, label: str) -> None:
        """Open a destination declared by the installed package."""
        url = project_urls().get(label)
        if url:
            QDesktopServices.openUrl(QUrl(url))
        else:
            self._window.notifications.show_warning(
                tr("No {label} link is declared for this build.").format(label=label)
            )

    @Slot()
    def report_a_problem(self) -> None:
        """Copy build details and open the issue tracker."""
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(version_report())
            self._window.notifications.show_success(
                tr("Version details copied — paste them into the report.")
            )
        self.open_project_url("Issues")

    @Slot()
    def show_citation(self) -> None:
        """Show the citation maintained by the release process."""
        show_text(
            self._window,
            tr("Cite AvialSync"),
            citation_text(),
            lead=tr("Citation metadata for this release:"),
        )

    @Slot()
    def show_preferences(self) -> None:
        """Show the generated Preferences dialog without blocking the workspace."""
        if self._preferences_dialog is None:
            from avialsync.ui.preferences_dialog import PreferencesDialog

            self._preferences_dialog = PreferencesDialog(self._window)
            self._preferences_dialog.setting_changed.connect(self.on_setting_changed)
        self._preferences_dialog.show()
        self._window._bring_onto_screen(self._preferences_dialog)
        self._preferences_dialog.raise_()

    @Slot()
    def show_review_workflow(self) -> None:
        """Show the task guide without blocking the recording workspace."""
        from avialsync.ui.review_workflow import ReviewWorkflowDialog

        if self._review_workflow_dialog is None:
            self._review_workflow_dialog = ReviewWorkflowDialog(
                {
                    "open_video": self._window._act_open_video,
                    "open_sensor": self._window._act_open_sensor,
                    "synchronize": self._window._act_synchronize,
                    "save_session": self._window._act_save_session,
                },
                self._window,
            )
        self._review_workflow_dialog.show()
        self._window._bring_onto_screen(self._review_workflow_dialog)
        self._review_workflow_dialog.raise_()

    @Slot(str)
    def on_setting_changed(self, key: str) -> None:
        """Apply appearance preferences immediately."""
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        if key == "theme/preference":
            from avialsync.ui.theme import apply_theme, load_saved_theme

            apply_theme(app, load_saved_theme(app))
        elif key == "font/preference":
            from avialsync.ui.theme import apply_font_size, load_saved_font_size

            apply_font_size(app, load_saved_font_size(app))
            self._window.data_streams.reload_preferences()
        elif key in {
            "interface/density",
            "timeline/compact_visible_lanes",
            "timeline/comfortable_visible_lanes",
        }:
            self._window.data_streams.reload_preferences()

    @Slot()
    def show_about(self) -> None:
        """Show build metadata suitable for a bug report."""
        show_text(
            self._window,
            tr("About AvialSync"),
            version_report(),
            lead=tr(
                "AvialSync — The Advanced Video and Instrument Alignment Library.\n"
                "Multi-camera video and time-series inspection.\n"
                "Free software under the GNU AGPL v3 or later."
            ),
        )

    @Slot()
    def show_diagnostics(self) -> None:
        """Show current machine and plugin diagnostics."""
        from avialsync.ui.diagnostics import format_diagnostics

        diagnostics = dict(getattr(self._window, "_diag", {}))
        diagnostics["plugin_errors"] = self._window._registry.plugin_errors
        text = format_diagnostics(diagnostics)
        show_text(self._window, tr("Diagnostics"), text)
