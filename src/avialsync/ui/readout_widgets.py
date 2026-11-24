"""Row and collapsible signal-group widgets for the Values inspector."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QPalette
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.design_tokens import spacing
from avialsync.ui.elided_label import ElidedLabel
from avialsync.ui.i18n import tr
from avialsync.ui.theme import set_bold, set_font_family


@lru_cache(maxsize=1)
def fixed_font_family() -> str:
    """Resolve the platform fixed-width family once rather than per label."""
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()


def set_monospace(widget: QWidget) -> None:
    """Preserve a fixed-width family while inheriting the application font size."""
    set_font_family(widget, fixed_font_family())


def format_channel_summary(name: str, unit: str, sample: tuple[int, float] | None) -> str:
    """Format a channel line for the copyable text summary (with sample index)."""
    if sample is None or np.isnan(sample[1]):
        val_text = tr("—")
        idx_text = "" if sample is None else str(sample[0])
    else:
        unit_str = f" {unit}" if unit else ""
        val_text = f"{sample[1]:.4g}{unit_str}"
        idx_text = str(sample[0])
    suffix = tr(" (sample {index})").format(index=idx_text) if idx_text else ""
    return f"{name}: {val_text}{suffix}"


class _ChannelReadout(QWidget):
    """Single clean value row: eliding channel leaf name and formatted value + unit.

    Raw array indices are kept off the visual sidebar row and surfaced only in
    ``summary_line()`` (``Text view…``) and the tooltip.
    """

    def __init__(
        self,
        name: str,
        unit: str = "",
        parent: QWidget | None = None,
        *,
        summary_name: str = "",
        indent_px: int = 0,
    ) -> None:
        super().__init__(parent)
        self._unit = unit
        self._summary_name = summary_name or name
        self._last_val_text = "—"
        self._sample_idx: int | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(indent_px, 0, 0, 0)
        layout.setSpacing(spacing("xs"))

        self._name_lbl = ElidedLabel(name, self)
        self._name_lbl.setMinimumWidth(48)
        self._name_lbl.setToolTip(self._summary_name)

        self._val_lbl = QLabel(tr("—"), self)
        set_monospace(self._val_lbl)
        self._val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self._name_lbl, stretch=1)
        layout.addWidget(self._val_lbl)

    def configure(
        self,
        name: str,
        unit: str,
        *,
        summary_name: str = "",
        indent_px: int = 0,
    ) -> None:
        """Update label, summary name, and unit in place across source refreshes."""
        if self._name_lbl.text() != name:
            self._name_lbl.setText(name)
        self._summary_name = summary_name or name
        self._name_lbl.setToolTip(self._summary_name)
        self._unit = unit
        self._last_val_text = ""
        layout = self.layout()
        if layout is not None:
            layout.setContentsMargins(indent_px, 0, 0, 0)

    def set_value(self, v: float | None, sample_idx: int | None = None) -> None:
        self._sample_idx = sample_idx
        if v is None or np.isnan(v):
            val_text = tr("—")
        else:
            unit_str = f" {self._unit}" if self._unit else ""
            val_text = f"{v:.4g}{unit_str}"
        if val_text != self._last_val_text:
            self._last_val_text = val_text
            self._val_lbl.setText(val_text)

    def summary_line(self) -> str:
        """Return the qualified channel name, value, unit, and sample index."""
        sample = "" if self._sample_idx is None else str(self._sample_idx)
        suffix = tr(" (sample {index})").format(index=sample) if sample else ""
        return f"{self._summary_name}: {self._val_lbl.text()}{suffix}"


class _SignalGroupSection(QWidget):
    """Collapsible signal group in Values showing group summary + expandable leaves."""

    def __init__(
        self,
        title: str,
        count: int,
        unit: str,
        *,
        expanded: bool,
        on_toggle: Callable[[_SignalGroupSection, bool], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.group_title = title
        self.member_count = count
        self.unit = unit
        self._expanded = expanded
        self._on_toggle = on_toggle
        self._last_summary = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(2)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(spacing("xs"))

        self.toggle_btn = QPushButton(self)
        self.toggle_btn.setFlat(True)
        self.toggle_btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.toggle_btn.setMinimumWidth(64)
        set_bold(self.toggle_btn)
        self.toggle_btn.setAccessibleName(tr("Toggle {group} values").format(group=title))
        self.toggle_btn.setToolTip(
            tr("{group} ({count} channels) — click to expand or collapse").format(
                group=title, count=count
            )
        )
        self.toggle_btn.clicked.connect(self._handle_clicked)

        self.summary_lbl = QLabel("", self)
        set_monospace(self.summary_lbl)
        self.summary_lbl.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self.summary_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header.addWidget(self.toggle_btn, stretch=1)
        header.addWidget(self.summary_lbl)
        outer.addLayout(header)

        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(2)
        self.body.setVisible(expanded)
        outer.addWidget(self.body)
        self._refresh_header_text()

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self.body.setVisible(expanded)
        self._refresh_header_text()

    def _handle_clicked(self) -> None:
        self._expanded = not self._expanded
        self.body.setVisible(self._expanded)
        self._refresh_header_text()
        self._on_toggle(self, self._expanded)

    def _refresh_header_text(self) -> None:
        glyph = "▾" if self._expanded else "▸"
        self.toggle_btn.setText(f"{glyph} {self.group_title} ({self.member_count})")

    def set_summary_values(self, values: list[float]) -> None:
        """Show concise ``mean [min…max]`` when collapsed, or unit badge when expanded."""
        if self._expanded:
            text = self.unit if self.unit else ""
        elif not values:
            text = tr("—")
        elif len(values) == 1:
            u = f" {self.unit}" if self.unit else ""
            text = f"{values[0]:.4g}{u}"
        else:
            arr = np.asarray(values, dtype=np.float64)
            lo = float(np.min(arr))
            hi = float(np.max(arr))
            mean = float(np.mean(arr))
            u = f" {self.unit}" if self.unit else ""
            text = f"μ {mean:.3g} [{lo:.3g}…{hi:.3g}]{u}"
        if text != self._last_summary:
            self._last_summary = text
            self.summary_lbl.setText(text)


class _StatsRow(QWidget):
    """Shows min/max/mean/rms for one channel in a region."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing("xs"))

        self._name_lbl = ElidedLabel(name, self)
        self._name_lbl.setMinimumWidth(48)
        self._name_lbl.setToolTip(name)

        self._stats_lbl = QLabel(tr("—"), self)
        set_monospace(self._stats_lbl)
        self._stats_lbl.setWordWrap(True)

        layout.addWidget(self._name_lbl, stretch=1)
        layout.addWidget(self._stats_lbl, stretch=2)

    def set_stats(self, stats: dict | None) -> None:
        if not stats or "min" not in stats:
            self._stats_lbl.setText(tr("—"))
            return
        self._stats_lbl.setText(
            tr("min={min}  max={max}  mean={mean}  rms={rms}").format(
                **{key: f"{stats[key]:.4g}" for key in ("min", "max", "mean", "rms")}
            )
        )


class _CameraRow(QWidget):
    """Shows frame number and media timestamp for one camera."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._raw_label = label
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing("xs"))

        self._name_lbl = ElidedLabel(label, self)
        self._name_lbl.setMinimumWidth(48)
        self._name_lbl.setToolTip(label)

        self._info_lbl = QLabel(tr("—"), self)
        set_monospace(self._info_lbl)
        self._info_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self._name_lbl, stretch=1)
        layout.addWidget(self._info_lbl)

    def set_state(self, time_pos: float, fps: float, frame_index: int | None = None) -> None:
        """Show this camera's frame number and media time."""
        if frame_index is not None:
            self._info_lbl.setText(
                tr("frame {index}  ({time:.3f} s)").format(index=frame_index, time=time_pos)
            )
        elif fps > 0:
            frame_num = int(time_pos * fps)
            self._info_lbl.setText(
                tr("frame {index}  ({time:.3f} s)").format(index=frame_num, time=time_pos)
            )
        else:
            self._info_lbl.setText(tr("{time:.3f} s").format(time=time_pos))

    def summary_line(self) -> str:
        """Return this camera's current frame and media time."""
        return tr("{camera}: {state}").format(camera=self._raw_label, state=self._info_lbl.text())


class _DeltaRow(QWidget):
    """Shows Δvalue for one channel."""

    def __init__(
        self, name: str, unit: str = "", parent: QWidget | None = None, *, tooltip: str = ""
    ) -> None:
        super().__init__(parent)
        self._unit = unit
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing("xs"))

        lbl = ElidedLabel(f"Δ {name}", self)
        lbl.setMinimumWidth(48)
        lbl.setToolTip(tooltip or name)

        self._val_lbl = QLabel(tr("—"), self)
        set_monospace(self._val_lbl)
        self._val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(lbl, stretch=1)
        layout.addWidget(self._val_lbl)

    def set_delta(self, dv: float | None) -> None:
        if dv is None or np.isnan(dv):
            self._val_lbl.setText(tr("—"))
        else:
            unit_str = f" {self._unit}" if self._unit else ""
            self._val_lbl.setText(f"{dv:+.4g}{unit_str}")
