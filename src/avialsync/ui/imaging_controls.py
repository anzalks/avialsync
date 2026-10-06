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
    QHBoxLayout,
    QLabel,
    QPushButton,
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
from avialsync.ui.design_tokens import spacing
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

    def __init__(self, parent: QWidget, channel: int, name: str) -> None:
        number = channel + 1
        # The tick box is the *acquired* channel -- which recorded signal is
        # drawn -- and carries the name the file gives it. The colour list
        # beside it only says what colour that signal is drawn in. Shown even
        # for a single channel, so the two are never confused (D-195).
        self.shown = QCheckBox(name, parent)
        self.shown.setAccessibleName(tr("Show acquired channel {name}").format(name=name))
        self.shown.setAccessibleDescription(
            tr("Include the {name} channel in the picture").format(name=name)
        )
        self.shown.setToolTip(tr("Acquired channel {number} of the stack").format(number=number))
        self.color = QComboBox(parent)
        for key, name in _color_names().items():
            self.color.addItem(_swatch(key), name, key)
        self.color.setAccessibleName(tr("Display colour of {name}").format(name=name))
        self.color.setAccessibleDescription(
            tr("Colour the {name} channel is drawn in; does not change which data is shown").format(
                name=name
            )
        )
        self.color.setToolTip(tr("Display colour only; the tick box chooses the channel"))
        self.brightness = self._slider(
            parent,
            tr("{name} brightness").format(name=name),
            tr("Move the display window down to brighten, up to darken"),
        )
        self.contrast = self._slider(
            parent,
            tr("{name} contrast").format(name=name),
            tr("Narrow the display window for more contrast, widen it for less"),
        )
        self.widgets = (self.shown, self.color, self.brightness, self.contrast)

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
        self._names: tuple[str, ...] = ()
        self._value_range: tuple[float, float] | None = None
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(spacing("s", self))
        self._grid.setVerticalSpacing(spacing("xs", self))
        self._grid.setColumnStretch(3, 1)
        self._grid.setColumnStretch(5, 1)
        # One heading per column, so "which channel" and "what colour" are
        # read as the two different questions they are (D-195).
        self._headings = [
            QLabel(tr("Channel"), self),
            QLabel(tr("Colour"), self),
            QLabel(tr("Brightness"), self),
            QLabel(tr("Contrast"), self),
        ]
        for heading, (column, span) in zip(
            self._headings, ((0, 1), (1, 1), (2, 2), (4, 2)), strict=True
        ):
            self._grid.addWidget(heading, 0, column, 1, span)
        layout.addLayout(self._grid)

        average_row = QHBoxLayout()
        average_row.setContentsMargins(0, spacing("s", self), 0, 0)
        average_row.setSpacing(spacing("s", self))
        average_row.addWidget(QLabel(tr("Average"), self))
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
        average_row.addWidget(self.average)
        average_row.addStretch(1)
        # Auto and Full range, the same pair the video's Display Levels offers.
        self.auto_button = QPushButton(tr("Auto"), self)
        self.auto_button.setAccessibleName(tr("Automatic display levels"))
        self.auto_button.setAccessibleDescription(
            tr("Measure each visible channel's levels from the picture now shown")
        )
        self.auto_button.setToolTip(tr("Choose black and white from what this frame contains"))
        self.auto_button.clicked.connect(self.apply_auto_levels)
        average_row.addWidget(self.auto_button)
        self.full_range_button = QPushButton(tr("Full range"), self)
        self.full_range_button.setAccessibleName(tr("Full display range"))
        self.full_range_button.setToolTip(tr("Show the whole recorded range"))
        self.full_range_button.clicked.connect(self.apply_full_range)
        average_row.addWidget(self.full_range_button)
        layout.addLayout(average_row)

    # ── state in ─────────────────────────────────────────────────────

    def view(self) -> ImagingView:
        """Return the view these controls show."""
        return self._view

    def set_channel_names(self, names: tuple[str, ...]) -> None:
        """Name each acquired channel as the file does; ``Ch N`` where it is silent."""
        if names == self._names:
            return
        self._names = names
        # Rebuilt rather than relabelled: names arrive with a new stack, whose
        # rows are about to be replaced anyway.
        self._rebuild(len(self._rows))
        self.set_view(self._view)

    def set_value_range(self, value_range: tuple[float, float] | None) -> None:
        """The stored sample range Full range shows; None for float data, which has none."""
        self._value_range = value_range
        self.full_range_button.setEnabled(value_range is not None)

    def _channel_name(self, channel: int) -> str:
        if channel < len(self._names) and self._names[channel]:
            return self._names[channel]
        return tr("Ch {number}").format(number=channel + 1)

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
            row = _ChannelRow(self, channel, self._channel_name(channel))
            grid_row = channel + 1
            self._grid.addWidget(row.shown, grid_row, 0)
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
        for heading in self._headings:
            heading.setVisible(has_channels)

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

    @Slot()
    def apply_full_range(self) -> None:
        """Window each visible channel over the whole stored range and reset its sliders."""
        if self._value_range is None:
            return
        low, high = self._value_range
        channels = tuple(
            dataclasses.replace(c, auto_low=low, auto_high=high, brightness=0.0, contrast=0.0)
            if c.visible
            else c
            for c in self._view.channels
        )
        view = dataclasses.replace(self._view, channels=channels)
        self.set_view(view)
        self._emit(view, "levels")
