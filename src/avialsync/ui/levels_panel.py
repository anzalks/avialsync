"""Choosing which part of a recording's range to show (WP-9, D-093).

Only offered for sources that need it.  The panel asks the decoder what the
footage actually is — a :class:`~avialsync.engine.display_pipeline.SourceFormat`
read from the frame — and stays out of the way for ordinary 8-bit colour, which
already fills the screen's range.

The controls are in normalised units and labelled in the recording's own, so a
12-bit camera shows 0–4095 and a 10-bit one 0–1023 without either number
appearing anywhere in the code.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

from avialsync.engine.display_pipeline import DisplayLevels, SourceFormat
from avialsync.ui.i18n import tr

#: Slider resolution. Independent of the source's bit depth on purpose: the
#: control is normalised, and a 65536-step slider would be unusable anyway.
_STEPS = 1000


class LevelsPanel(QGroupBox):
    """Black point, white point, and gamma for one camera."""

    #: Emitted with the new window whenever the user moves anything.
    levels_changed = Signal(object)
    #: Emitted when the user asks for levels chosen from the current frame.
    auto_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Display Levels", parent)
        self._source: SourceFormat | None = None
        self._levels = DisplayLevels()
        self._emitting = True

        layout = QGridLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self._black = self._make_slider("Black", layout, row=0)
        self._white = self._make_slider("White", layout, row=1)
        self._gamma = self._make_slider("Gamma", layout, row=2)

        self._black.setValue(0)
        self._white.setValue(_STEPS)
        self._gamma.setValue(_STEPS // 2)

        self._auto = QPushButton("Auto")
        self._auto.setToolTip(tr("Choose black and white from what this frame contains"))
        self._auto.clicked.connect(self.auto_requested)
        layout.addWidget(self._auto, 3, 1)

        self._reset = QPushButton("Full range")
        self._reset.setToolTip(tr("Show the whole recorded range"))
        self._reset.clicked.connect(self.reset)
        layout.addWidget(self._reset, 3, 2)

        self.setVisible(False)

    def _make_slider(self, name: str, layout: QGridLayout, row: int) -> QSlider:
        label = QLabel(name)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, _STEPS)
        slider.setAccessibleName(f"{name} point")
        value = QLabel("")
        slider.valueChanged.connect(lambda _v: self._on_changed())
        slider.valueChanged.connect(lambda _v, lbl=value, s=slider: self._update_readout(lbl, s))
        layout.addWidget(label, row, 0)
        layout.addWidget(slider, row, 1)
        layout.addWidget(value, row, 2)
        setattr(self, f"_{name.lower()}_readout", value)
        return slider

    # ── source ───────────────────────────────────────────────────────

    def set_source_format(self, source: SourceFormat | None) -> None:
        """Show the panel only when the recording has range worth choosing from.

        Eight-bit colour is already the screen's range; offering a window over
        it would be a control that cannot improve anything.
        """
        self._source = source
        self.setVisible(bool(source and source.needs_windowing))
        if source is not None:
            self.setTitle(f"Display Levels — {source.bits}-bit")
        self._refresh_readouts()

    # ── values ───────────────────────────────────────────────────────

    def levels(self) -> DisplayLevels:
        return self._levels

    def set_levels(self, levels: DisplayLevels) -> None:
        """Show *levels* without emitting, for a restore or an undo."""
        self._emitting = False
        try:
            self._levels = levels.normalised()
            self._black.setValue(int(round(self._levels.black * _STEPS)))
            self._white.setValue(int(round(self._levels.white * _STEPS)))
            # Gamma 0.1-10 on a log-ish scale, with 1.0 at the midpoint: the
            # useful range is multiplicative, and a linear slider would spend
            # most of its travel above 1.
            self._gamma.setValue(int(round((self._levels.gamma ** (1 / 3)) * _STEPS / 2)))
        finally:
            self._emitting = True
        self._refresh_readouts()

    def reset(self) -> None:
        self.set_levels(DisplayLevels())
        self.levels_changed.emit(self._levels)

    def _on_changed(self) -> None:
        if not self._emitting:
            return
        gamma = max(0.1, (self._gamma.value() * 2 / _STEPS) ** 3)
        self._levels = DisplayLevels(
            black=self._black.value() / _STEPS,
            white=self._white.value() / _STEPS,
            gamma=gamma,
        ).normalised()
        self.levels_changed.emit(self._levels)

    # ── readouts, in the recording's own units ───────────────────────

    def _update_readout(self, label: QLabel, slider: QSlider) -> None:
        del slider
        self._refresh_readouts()
        _ = label

    def _refresh_readouts(self) -> None:
        """Label the sliders in the source's counts, not in percentages.

        Someone setting a black point on a 12-bit camera thinks in 0-4095. The
        scale comes from the format, so a 10-bit or 14-bit source labels itself
        correctly with no special case.
        """
        full_scale = (self._source.levels_count - 1) if self._source else 255
        black_label = getattr(self, "_black_readout", None)
        white_label = getattr(self, "_white_readout", None)
        gamma_label = getattr(self, "_gamma_readout", None)
        if black_label is not None:
            black_label.setText(str(int(round(self._levels.black * full_scale))))
        if white_label is not None:
            white_label.setText(str(int(round(self._levels.white * full_scale))))
        if gamma_label is not None:
            gamma_label.setText(f"{self._levels.gamma:.2f}")
