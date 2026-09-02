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
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from avialsync.ui.i18n import tr
from avialsync.ui.theme import follow_palette


class EmptyState(QWidget):
    """The first thing a new user sees."""

    open_videos_requested = Signal()
    open_data_requested = Signal()
    demo_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)

        headline = QLabel("Drop recordings here")
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = headline.font()
        font.setPointSize(max(font.pointSize() + 4, 14))
        font.setBold(True)
        headline.setFont(font)

        detail = QLabel(
            "Video, sensor, ephys, and tracking files — together or one at a time.\n"
            "A folder that is a recording is recognised as one."
        )
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Secondary text, so the headline stays the thing read first.
        follow_palette(
            detail,
            lambda palette: f"color: {palette.placeholderText().color().name()};",
        )

        open_videos = QPushButton("Open Videos…")
        open_videos.clicked.connect(self.open_videos_requested)
        open_data = QPushButton("Open Sensor / Ephys Data…")
        open_data.clicked.connect(self.open_data_requested)

        demo = QPushButton("Try the demo session")
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

        self.setAccessibleName(tr("No recordings are open"))
