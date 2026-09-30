"""A task-oriented guide for reviewing a synchronized recording."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.action_button import ActionButton
from avialsync.ui.i18n import tr


class ReviewWorkflowDialog(QDialog):
    """Show the ordered checks for an evidence-based review."""

    def __init__(self, actions: Mapping[str, QAction], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Review Workflow"))
        self.setAccessibleName(tr("Recording review workflow"))
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        intro = QLabel(
            tr(
                "Review source timing and alignment before interpreting events. "
                "Mappings change the session timeline; source files remain unchanged."
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.action_buttons: dict[str, ActionButton] = {}
        steps = (
            (
                tr("1. Load a camera recording"),
                tr("Check its duration, frame timing, and source-quality badge."),
                "open_video",
            ),
            (
                tr("2. Load the sensor or tracking recording"),
                tr("Confirm the time column, units, and channels before comparing traces."),
                "open_sensor",
            ),
            (
                tr("3. Align from shared evidence"),
                tr("Preview event matches and residuals, then accept only a suitable fit."),
                "synchronize",
            ),
            (
                tr("4. Inspect the same instant across views"),
                tr("Compare video, plots, and values on the shared master timeline."),
                None,
            ),
            (
                tr("5. Record an observation"),
                tr("Flag the frame or annotate the interval you want to revisit."),
                None,
            ),
            (
                tr("6. Save the session"),
                tr("Mappings and annotations are saved separately from the source recordings."),
                "save_session",
            ),
        )

        for title, detail, action_key in steps:
            row = QHBoxLayout()
            text_layout = QVBoxLayout()
            title_label = QLabel(title)
            title_label.setAccessibleName(title)
            detail_label = QLabel(detail)
            detail_label.setWordWrap(True)
            text_layout.addWidget(title_label)
            text_layout.addWidget(detail_label)
            row.addLayout(text_layout, 1)
            if action_key is not None:
                button = ActionButton(self)
                button.set_action(actions[action_key])
                row.addWidget(button)
                self.action_buttons[action_key] = button
            layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
