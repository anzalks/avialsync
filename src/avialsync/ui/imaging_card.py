"""An imaging stack's card on the Sources page, shaped like a camera's (D-175, D-196).

The card is the one place a stack's offset and drift are edited, and the one
place it is removed from; the imaging pane shows the picture and how it is
drawn, nothing else.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.source import ImagingMetadata
from avialsync.ui.design_tokens import spacing
from avialsync.ui.drift_spin import DriftSpinBox
from avialsync.ui.elided_label import ElidedLabel
from avialsync.ui.i18n import tr
from avialsync.ui.source_card import (
    TimingDisclosure,
    commit_on_edit,
    copy_to_clipboard,
    kind_glyph,
    overflow_button,
    show_value,
)
from avialsync.ui.theme import set_bold
from avialsync.ui.time_format import format_rate

#: A day either way, the same bound as every other offset field.
_OFFSET_LIMIT_S = 86_400.0


def bit_depth(dtype: str) -> str:
    """``16-bit`` for an integer sample type, ``32-bit float`` for a float one."""
    kind = np.dtype(dtype)
    bits = tr("{bits}-bit").format(bits=kind.itemsize * 8)
    return bits + " " + tr("float") if kind.kind == "f" else bits


def describe_picture(info: ImagingMetadata) -> str:
    """``512×512 · 16-bit``: what the picture is, as the video overlay says it (D-183)."""
    return f"{info.width}×{info.height} · {bit_depth(info.dtype)}"


def frame_rate(info: ImagingMetadata) -> float:
    """Mean acquisition rate over the stack, or 0 when it has one frame."""
    times = info.frame_times
    if len(times) < 2 or times[-1] <= times[0]:
        return 0.0
    return float((len(times) - 1) / (times[-1] - times[0]))


def properties_text(path: str, info: ImagingMetadata) -> str:
    """The stack's properties as plain text, for Properties and Copy details."""
    rate = frame_rate(info)
    rows = [
        (tr("File"), path),
        (tr("Picture"), describe_picture(info)),
        (tr("Frames"), str(info.frame_count)),
        (tr("Frame rate"), format_rate(rate) if rate else tr("unknown")),
        (tr("Timing from"), info.timing_source),
        (tr("Channels"), ", ".join(info.channel_names) or str(info.channel_count)),
    ]
    if info.axes:
        rows.append((tr("Axes"), info.axes))
    if info.depth_planes > 1:
        rows.append((tr("Depth planes"), str(info.depth_planes)))
    if info.dataset:
        rows.append((tr("Dataset"), info.dataset))
    return "\n".join(f"{label}: {value}" for label, value in rows)


class ImagingInfoWidget(QFrame):
    """One imaging stack: name, picture summary, timing, and its overflow."""

    remove_requested = Signal(str)
    mapping_changed = Signal(str, float, float)  # path, offset_s, drift_ms_per_hour
    properties_requested = Signal(str)

    def __init__(self, path: str, info: ImagingMetadata, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.info = info
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        name = Path(path).name
        layout = QVBoxLayout(self)
        margin = spacing("s", self)
        layout.setContentsMargins(margin, margin, margin, margin)

        header = QHBoxLayout()
        name_label = ElidedLabel(name)
        name_label.setToolTip(path)
        set_bold(name_label)
        self.more_button = overflow_button(
            self,
            tr("More actions for {name}").format(name=name),
            [
                (tr("Properties"), lambda: self.properties_requested.emit(self.path), False),
                (tr("Copy details"), self._copy_details, False),
                (tr("Remove imaging source"), lambda: self.remove_requested.emit(self.path), True),
            ],
        )
        header.addWidget(kind_glyph("imaging", tr("Imaging source"), self))
        header.addWidget(name_label, stretch=1)
        header.addWidget(self.more_button)
        layout.addLayout(header)

        self.summary_label = QLabel(self)
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        self.set_info(info)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-_OFFSET_LIMIT_S, _OFFSET_LIMIT_S)
        self.offset_spin.setDecimals(6)
        self.offset_spin.setSingleStep(0.05)
        self.offset_spin.setSuffix(" s")
        self.offset_spin.setMinimumWidth(90)
        self.offset_spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.offset_spin.setAccessibleName(tr("Time offset for {name}").format(name=name))
        self.offset_spin.setToolTip(
            tr("Shift this stack against the master clock. The recording is never rewritten.")
        )
        commit_on_edit(self.offset_spin)
        form.addRow(tr("Offset:"), self.offset_spin)
        self.drift_spin = DriftSpinBox()
        self.drift_spin.setMinimumWidth(90)
        self.drift_spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.drift_spin.setAccessibleName(tr("Clock drift for {name}").format(name=name))
        self.drift_spin.set_base_tooltip(
            tr("How much this stack's clock gains on master time per hour of recording.")
        )
        rate = frame_rate(info)
        if rate:
            self.drift_spin.set_sample_rate(rate, tr("frames"))
        commit_on_edit(self.drift_spin)
        form.addRow(tr("Drift:"), self.drift_spin)
        body = QWidget(self)
        body.setLayout(form)
        self.timing = TimingDisclosure(body, self.offset_spin, self.drift_spin, self)
        layout.addWidget(self.timing)
        self.offset_spin.valueChanged.connect(self._emit_mapping)
        self.drift_spin.valueChanged.connect(self._emit_mapping)

    def set_info(self, info: ImagingMetadata) -> None:
        """Show a reopened stack's metadata (another axis order or plane)."""
        self.info = info
        rate = frame_rate(info)
        parts = [describe_picture(info), tr("{count} frames").format(count=info.frame_count)]
        if rate:
            parts.append(format_rate(rate))
        self.summary_label.setText(" · ".join(parts))

    def mapping(self) -> tuple[float, float]:
        """Return the displayed ``(offset_s, drift_ms_per_hour)``."""
        return self.offset_spin.value(), self.drift_spin.value()

    def set_mapping(self, offset: float, drift_ms_per_hour: float) -> None:
        """Show a mapping without re-emitting it (undo, restore, accepted fit)."""
        for spin, value in ((self.offset_spin, offset), (self.drift_spin, drift_ms_per_hour)):
            blocked = spin.blockSignals(True)
            try:
                show_value(spin, value)
            finally:
                spin.blockSignals(blocked)
        self.timing.summary_label.setText(self.timing.summary())

    def properties_text(self) -> str:
        """The card's properties as plain text."""
        return properties_text(self.path, self.info)

    def _emit_mapping(self, _value: float) -> None:
        self.mapping_changed.emit(self.path, *self.mapping())

    def _copy_details(self) -> None:
        copy_to_clipboard(
            f"{Path(self.path).name}\n{self.properties_text()}\n"
            f"{tr('Offset and drift')}: {self.timing.summary()}"
        )
