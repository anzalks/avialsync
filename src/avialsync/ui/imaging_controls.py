"""The imaging pane's display controls: channels, brightness, contrast, averaging.

Every control edits an :class:`~avialsync.core.imaging_display.ImagingView` and
reports the whole new view with the *aspect* it changed, so the window can log
one undoable command per drag (D-190). Nothing here touches pixels: the reader
thread renders whatever view it is handed.

Each channel row names its colour in words beside the swatch, because colour is
never the only carrier of meaning (D-094).
"""

from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.imaging_display import (
    CHANNEL_COLORS,
    MAX_AVERAGE,
    ChannelView,
    ImagingView,
)
from avialsync.ui.i18n import tr

__all__ = ["ImagingControls"]

#: Slider travel either side of zero for brightness and contrast.
_STEPS = 100


def _color_names() -> dict[str, str]:
    """Colour keys to translated names, in menu order."""
    return {
        "grey": tr("Grey"),
        "green": tr("Green"),
        "magenta": tr("Magenta"),
        "cyan": tr("Cyan"),
        "yellow": tr("Yellow"),
        "red": tr("Red"),
        "blue": tr("Blue"),
    }


def _swatch(color: str) -> QIcon:
    pixmap = QPixmap(12, 12)
    pixmap.fill(QColor(*CHANNEL_COLORS[color]))
    return QIcon(pixmap)


class _ChannelRow:
    """The widgets for one channel, placed into the shared grid."""

    def __init__(self, parent: QWidget, channel: int, single: bool) -> None:
        number = channel + 1
        self.shown = QCheckBox(tr("Ch {number}").format(number=number), parent)
        self.shown.setAccessibleName(tr("Show channel {number}").format(number=number))
        self.shown.setAccessibleDescription(
            tr("Include channel {number} in the overlay").format(number=number)
        )
        # One channel cannot be hidden from itself; a row label says what the
        # sliders belong to without offering a switch that blanks the pane.
        self.shown.setVisible(not single)
        self.label = QLabel(tr("Image"), parent)
        self.label.setVisible(single)
        self.color = QComboBox(parent)
        for key, name in _color_names().items():
            self.color.addItem(_swatch(key), name, key)
        self.color.setAccessibleName(tr("Channel {number} colour").format(number=number))
        self.color.setAccessibleDescription(
            tr("Colour channel {number} is drawn in").format(number=number)
        )
        self.brightness = self._slider(
            parent,
            tr("Channel {number} brightness").format(number=number),
            tr("Move the display window down to brighten, up to darken"),
        )
        self.contrast = self._slider(
            parent,
            tr("Channel {number} contrast").format(number=number),
            tr("Narrow the display window for more contrast, widen it for less"),
        )
        self.widgets = (self.shown, self.label, self.color, self.brightness, self.contrast)

    @staticmethod
    def _slider(parent: QWidget, name: str, description: str) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal, parent)
        slider.setRange(-_STEPS, _STEPS)
        slider.setAccessibleName(name)
        slider.setAccessibleDescription(description)
        slider.setToolTip(description)
        return slider

    def show_channel(self, view: ChannelView) -> None:
        self.shown.setChecked(view.visible)
        index = self.color.findData(view.color)
        self.color.setCurrentIndex(max(index, 0))
        self.brightness.setValue(round(view.brightness * _STEPS))
        self.contrast.setValue(round(view.contrast * _STEPS))


class ImagingControls(QWidget):
    """Channel rows plus averaging and automatic levels for one stack."""

    #: ``(view, aspect)`` -- the whole new view and what the user changed.
    view_edited = Signal(object, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(tr("Imaging display controls"))
        self._view = ImagingView()
        self._rows: list[_ChannelRow] = []
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(6)
        self._grid.setVerticalSpacing(2)
        self._grid.setColumnStretch(3, 1)
        self._grid.setColumnStretch(5, 1)
        # The averaging control fills the corner above the channel names, so the
        # slider headings cost no row of their own.
        self._grid.addWidget(QLabel(tr("Average"), self), 0, 0)
        # The average is centred, so its length is always odd (D-190). The box
        # counts the frames either side -- Off, ±1, ±2 ... -- so every value it
        # accepts is a real window; a frame count would have to reject or
        # silently round every even number typed.
        self.average = QSpinBox(self)
        self.average.setRange(0, MAX_AVERAGE // 2)
        self.average.setSpecialValueText(tr("Off"))
        self.average.setPrefix("±")
        self.average.setSuffix(tr(" frames"))
        # Commit on Enter or focus loss: the unit follows the value, and
        # rewriting it mid-entry would move the cursor under the user's typing.
        self.average.setKeyboardTracking(False)
        self.average.setAccessibleName(tr("Moving average half-width in frames"))
        self.average.setAccessibleDescription(
            tr("Average this many frames either side of the current one; Off shows raw frames")
        )
        self.average.setToolTip(
            tr("Centred on the current frame, so averaging never shifts an event in time")
        )
        self.average.valueChanged.connect(self._on_average)
        self._grid.addWidget(self.average, 0, 1)
        self._brightness_heading = QLabel(tr("Brightness"), self)
        self._contrast_heading = QLabel(tr("Contrast"), self)
        self._grid.addWidget(self._brightness_heading, 0, 2, 1, 2)
        self._grid.addWidget(self._contrast_heading, 0, 4, 1, 2)
        layout.addLayout(self._grid)

    # ── state in ─────────────────────────────────────────────────────

    def view(self) -> ImagingView:
        """Return the view these controls show."""
        return self._view

    def set_view(self, view: ImagingView) -> None:
        """Show *view* without reporting it as an edit."""
        if len(view.channels) != len(self._rows):
            self._rebuild(len(view.channels))
        self._view = view
        self._updating = True
        try:
            for row, channel in zip(self._rows, view.channels, strict=True):
                row.show_channel(channel)
            self.average.setValue(view.average // 2)
            self._name_average_unit()
        finally:
            self._updating = False

    def _rebuild(self, count: int) -> None:
        for row in self._rows:
            for widget in row.widgets:
                self._grid.removeWidget(widget)
                widget.deleteLater()
        self._rows = []
        for channel in range(count):
            row = _ChannelRow(self, channel, single=count == 1)
            grid_row = channel + 1
            self._grid.addWidget(row.shown, grid_row, 0)
            self._grid.addWidget(row.label, grid_row, 0)
            self._grid.addWidget(row.color, grid_row, 1)
            self._grid.addWidget(row.brightness, grid_row, 2, 1, 2)
            self._grid.addWidget(row.contrast, grid_row, 4, 1, 2)
            row.shown.toggled.connect(
                lambda on, c=channel: self._edit_channel(c, "channels", visible=on)
            )
            row.color.currentIndexChanged.connect(
                lambda _i, c=channel, box=row.color: self._edit_channel(
                    c, "colour", color=str(box.currentData())
                )
            )
            row.brightness.valueChanged.connect(
                lambda value, c=channel: self._edit_channel(
                    c, "brightness", brightness=value / _STEPS
                )
            )
            row.contrast.valueChanged.connect(
                lambda value, c=channel: self._edit_channel(c, "contrast", contrast=value / _STEPS)
            )
            self._rows.append(row)
        has_channels = count > 0
        self._brightness_heading.setVisible(has_channels)
        self._contrast_heading.setVisible(has_channels)

    # ── edits out ────────────────────────────────────────────────────

    def _emit(self, view: ImagingView, aspect: str) -> None:
        self._view = view
        self.view_edited.emit(view, aspect)

    def _edit_channel(self, channel: int, aspect: str, **changes: object) -> None:
        if self._updating or channel >= len(self._view.channels):
            return
        updated = dataclasses.replace(self._view.channels[channel], **changes)  # type: ignore[arg-type]
        self._emit(self._view.with_channel(channel, updated), aspect)

    @Slot(int)
    def _on_average(self, _half_width: int) -> None:
        if self._updating:
            return
        self._name_average_unit()
        frames = 2 * self.average.value() + 1
        if frames != self._view.average:
            self._emit(dataclasses.replace(self._view, average=frames), "averaging")

    def _name_average_unit(self) -> None:
        self.average.setSuffix(tr(" frame") if self.average.value() == 1 else tr(" frames"))

    @Slot()
    def apply_auto_levels(self) -> None:
        """Re-measure each visible channel's window and reset its sliders."""
        channels = tuple(
            dataclasses.replace(c, auto_low=None, auto_high=None, brightness=0.0, contrast=0.0)
            if c.visible
            else c
            for c in self._view.channels
        )
        view = dataclasses.replace(self._view, channels=channels)
        self.set_view(view)
        self._emit(view, "levels")
