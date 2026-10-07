"""Buttons that place a measured belt from four camera clicks (D-165).

In 3D, the four clicks are the top run's corners, each in two calibrated
cameras. In one camera, they are the two roller hubs and the belt's top above
each, all in the same view. The measured centre distance and radius size the
belt either way; the clicks only say where it is.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from avialsync.core.physical_props import BeltProp
from avialsync.ui.i18n import tr

__all__ = ["BeltPlacementControls", "placement_point_label"]


def placement_point_label(mode: str, index: int) -> str:
    """The short on-video name of one placement click."""
    if mode == "side":
        return (tr("hub 1"), tr("hub 2"), tr("top 1"), tr("top 2"))[index]
    return tr("corner {number}").format(number=index + 1)


def placement_prompt(mode: str, index: int) -> str:
    """What to click next, in the words the overlay labels use."""
    if mode == "side":
        return (
            tr("Click the first roller's hub in one camera."),
            tr("Click the second roller's hub in the same camera."),
            tr("Click the belt's top directly above the first hub."),
            tr("Click the belt's top directly above the second hub."),
        )[index]
    return (
        tr("Click one top corner near the first roller in two calibrated cameras."),
        tr("Click the other top corner near the first roller in two cameras."),
        tr("Click the top corner near the second roller on the first corner's side."),
        tr("Click the last top corner near the second roller in two cameras."),
    )[index]


class BeltPlacementControls(QWidget):
    """Start, advance, accept, or cancel the four placement clicks."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.start = QPushButton(tr("Click 4 top corners"), self)
        self.next_point = QPushButton(tr("Next placement point"), self)
        self.place = QPushButton(tr("Place belt from clicks"), self)
        self.cancel = QPushButton(tr("Cancel placement clicks"), self)
        for button in (self.start, self.next_point, self.place, self.cancel):
            button.setAccessibleName(button.text())
            layout.addWidget(button)
        self.place.setAccessibleDescription(
            tr("Use the clicks for position and the measurements for size.")
        )
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._mode = "rollers"
        self.set_mode("rollers")

    def set_mode(self, mode: str) -> None:
        """Word the controls for 3D corners or one camera's side view."""
        self._mode = mode
        self.setVisible(mode in ("rollers", "side"))
        text = tr("Click hubs and belt top") if mode == "side" else tr("Click 4 top corners")
        self.start.setText(text)
        self.start.setAccessibleName(text)
        self.start.setAccessibleDescription(
            tr("Four clicks in one camera: both roller hubs, then the top above each.")
            if mode == "side"
            else tr("Four top-surface corners, two near each roller, in two calibrated cameras.")
        )
        self.status.setText(
            tr("Enter the centre distance, radius and width, then click four points in one view.")
            if mode == "side"
            else tr("Enter the radius and width, then click four top corners, or type the centres.")
        )

    def show_saved(self, belt: BeltProp) -> None:
        """Say which clicks placed a saved belt."""
        if belt.side_view is not None:
            self.status.setText(
                tr("Placed in {camera}'s side view; not placed in 3D.").format(
                    camera=belt.side_view.camera
                )
            )
        elif belt.corners is not None:
            self.status.setText(tr("Placed in 3D from four clicked top corners."))
        else:
            self.set_mode(self._mode)
