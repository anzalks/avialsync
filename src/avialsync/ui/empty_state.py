"""What the window says before anything is loaded (WP-8).

Launching with no data gave bare splitters: no drop target, no mention of the
entry points, and no hint that ``avialsync demo`` generates a complete sample
session. That demo is the best onboarding asset the project has — four cameras,
sensor and ephys traces, tracking, all synchronised — and it was reachable only
from a command line the target user may never open.

Deliberately not a wizard. It names the three things that work, and gets out of
the way the moment anything is loaded.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.action_button import ActionButton
from avialsync.ui.i18n import tr
from avialsync.ui.theme import follow_palette


class EmptyState(QWidget):
    """The first thing a new user sees."""

    demo_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # The controls live inside a scroll area, and that is load-bearing.
        # This widget sits in the video grid, whose height floor is
        # deliberately low (`VideoGrid.BASE_MIN_HEIGHT`) so an empty video area
        # never takes height from the plots. Handed less height than five
        # stacked controls need, a plain layout gives each one 2px and draws a
        # row of slivers. Scrolling degrades instead: every control keeps its
        # natural size, as much as fits is shown, and the empty state never
        # dictates the window's minimum height -- which is what made a 640x480
        # window impossible to reach.
        content = QWidget(self)

        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)

        headline = QLabel(tr("Drop recordings here"))
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = headline.font()
        font.setPointSize(max(font.pointSize() + 4, 14))
        font.setBold(True)
        headline.setFont(font)

        detail = QLabel(
            tr(
                "Video, sensor, ephys, and tracking files — together or one at a time.\n"
                "A folder that is a recording is recognised as one."
            )
        )
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Secondary text, so the headline stays the thing read first.
        follow_palette(
            detail,
            lambda palette: f"color: {palette.placeholderText().color().name()};",
        )

        # The File menu's own actions, installed by the window: this said "Open
        # Sensor / Ephys Data…" beside a menu saying "Open Sensor/Ephys Data…"
        # while it carried its own text (rule 15, D-092).
        self.open_videos_button = open_videos = ActionButton(content)
        self.open_data_button = open_data = ActionButton(content)

        demo = QPushButton(tr("Try the demo session"))
        demo.setToolTip(
            tr(
                "Generate and open a complete sample session: four cameras, "
                "sensor and ephys traces, and tracking, all on one clock."
            )
        )
        demo.clicked.connect(self.demo_requested)

        layout.addWidget(headline)
        layout.addWidget(detail)
        layout.addSpacing(8)
        for button in (open_videos, open_data, demo):
            button.setMinimumWidth(240)
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignCenter)

        scroll = QScrollArea(self)
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        # After setWidget, never before: QScrollArea.setWidget switches the
        # content's fill back on, so setting it earlier did nothing.
        content.setAutoFillBackground(False)
        # No frame and no filled viewport: this reads as part of the video
        # area, not as a sunken box inside it. Both are widget properties
        # rather than QSS, which would reach every QWidget under it.
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        # A scrollbar is interactive and carries no text of its own, so the
        # accessibility sweep cannot derive a name for it -- the same reason the
        # sidebar names its two by hand.
        scroll.verticalScrollBar().setAccessibleName(tr("Scroll the drop-zone message"))
        scroll.horizontalScrollBar().setAccessibleName(tr("Scroll the drop-zone message sideways"))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.setAccessibleName(tr("No recordings are open"))

    def install_open_actions(self, open_video: QAction, open_data: QAction) -> None:
        """Show the two open buttons, driven by the File menu's actions."""
        self.open_videos_button.set_action(open_video)
        self.open_data_button.set_action(open_data)
