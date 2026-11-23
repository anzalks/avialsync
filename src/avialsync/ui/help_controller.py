"""Window-owned commands for Help, Preferences, and diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from avialsync.ui.about import citation_text, docs_url, project_urls, version_report
from avialsync.ui.feedback.text_dialog import show_text
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow
    from avialsync.ui.preferences_dialog import PreferencesDialog
    from avialsync.ui.review_workflow import ReviewWorkflowDialog


def sync_appearance_menus(window: MainWindow) -> None:
    """Keep View -> Theme and View -> Font Size radio buttons synced with Preferences."""
    window._sync_theme_menu()
    window._sync_font_size_menu()


def reload_autosave_interval(window: MainWindow) -> None:
    """Apply the ``storage/autosave_minutes`` preference to the autosave timer."""
    from avialsync.core.settings_schema import setting_for
    from avialsync.ui.preferences_dialog import read_setting

    setting = setting_for("storage/autosave_minutes")
    minutes = int(read_setting(setting)) if setting is not None else 2
    window._autosave_timer.start(max(1, minutes) * 60_000)


def reload_loop_ab_preference(window: MainWindow) -> None:
    """Apply the ``playback/loop_ab`` preference to ``Player``."""
    from avialsync.core.settings_schema import setting_for
    from avialsync.ui.preferences_dialog import read_setting

    setting = setting_for("playback/loop_ab")
    enabled = bool(read_setting(setting)) if setting is not None else True
    window.player.set_loop_ab_enabled(enabled)


def apply_point_labels_default(window: MainWindow, *, repaint: bool = True) -> None:
    """Seed or refresh ``tracking.point_labels`` from ``overlays/point_labels_default``."""
    from avialsync.core.settings_schema import setting_for
    from avialsync.ui.preferences_dialog import read_setting

    setting = setting_for("overlays/point_labels_default")
    visible = bool(read_setting(setting)) if setting is not None else False
    window.overlay_state.set_visible("tracking.point_labels", visible)
    if repaint:
        window._apply_overlay_state()


class HelpController(QObject):
    """Own the Help and Preferences actions for one main window."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self._window = window
        self._preferences_dialog: PreferencesDialog | None = None
        #: The plugin set the dialog's plugin tabs were built from.
        self._preferences_generation = -1
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

    def open_docs_page(self, page: str) -> None:
        """Open *page* of the published guide, built on ``[project.urls]``."""
        QDesktopServices.openUrl(QUrl(docs_url(page)))

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
        if self._preferences_generation != self._window.registry.generation:
            self.forget_preferences()
        if self._preferences_dialog is None:
            from avialsync.ui.preferences_dialog import PreferencesDialog

            self._preferences_generation = self._window.registry.generation

            self._preferences_dialog = PreferencesDialog(
                self._window, extra=self._window.registry.plugin_settings()
            )
            self._preferences_dialog.setting_changed.connect(self.on_setting_changed)
        self._preferences_dialog.show()
        self._window._bring_onto_screen(self._preferences_dialog)
        self._preferences_dialog.raise_()

    def forget_preferences(self) -> None:
        """Rebuild Preferences next time: the plugins, and so their settings, changed."""
        if self._preferences_dialog is not None:
            self._preferences_dialog.close()
            self._preferences_dialog.deleteLater()
            self._preferences_dialog = None

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
        if key.startswith("plugins/"):
            from avialsync.ui.controllers.plugin_controller import publish_plugin_settings

            publish_plugin_settings(self._window.registry)
            return
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        if key == "playback/collapse_gaps":
            from avialsync.ui.controllers import gap_view

            # The menu action is the switch; setting it applies the preference.
            self._window._act_collapse_gaps.setChecked(gap_view.collapse_enabled())
            return
        if key == "theme/preference":
            from avialsync.ui.theme import apply_theme, load_saved_theme

            apply_theme(app, load_saved_theme(app))
            sync_appearance_menus(self._window)
        elif key == "font/preference":
            from avialsync.ui.theme import apply_font_size, load_saved_font_size

            apply_font_size(app, load_saved_font_size(app))
            sync_appearance_menus(self._window)
            self._window.data_streams.reload_preferences()
        elif key == "palette/colour_vision_safe":
            self._window.plot_pane.refresh_palette()
        elif key == "playback/loop_ab":
            reload_loop_ab_preference(self._window)
        elif key == "overlays/point_labels_default":
            apply_point_labels_default(self._window, repaint=True)
        elif key == "storage/autosave_minutes":
            reload_autosave_interval(self._window)
        elif key in {
            "interface/density",
            "timeline/compact_visible_lanes",
            "timeline/comfortable_visible_lanes",
        }:
            self._window.data_streams.reload_preferences()
        elif key == "overlays/osd_detail":
            from avialsync.ui.video_pane import _saved_osd_detail

            for pane in self._window.video_grid.panes:
                pane.set_osd_detail(_saved_osd_detail())
        elif key == "interface/toolbar_labels":
            self._window.view_toolbar.reload_preferences()
        elif key in {
            "overlays/confidence_threshold",
            "overlays/trail_frames",
            "overlays/marker_radius",
        }:
            from avialsync.ui.pose_overlay_extras import invalidate_overlay_settings_cache

            invalidate_overlay_settings_cache()
            self._window.video_grid.refresh_point_edits()
            self._window.tracking_3d_pane.canvas.update()

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
