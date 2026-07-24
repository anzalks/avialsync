"""Cursor readout panel — shows channel values at current t_master."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from kinochronix.core.pyramid import PyramidReader


class _ChannelReadout(QWidget):
    """Single row: channel name | value."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._name_lbl = QLabel(name)
        self._name_lbl.setFixedWidth(140)
        self._name_lbl.setStyleSheet("font-size: 11px;")

        self._val_lbl = QLabel("—")
        self._val_lbl.setStyleSheet("font-size: 11px; font-family: monospace;")
        self._val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self._name_lbl)
        layout.addWidget(self._val_lbl, stretch=1)

    def set_value(self, v: float | None) -> None:
        if v is None or np.isnan(v):
            self._val_lbl.setText("—")
        else:
            self._val_lbl.setText(f"{v:.4g}")


class _StatsRow(QWidget):
    """Shows min/max/mean/rms for one channel in a region."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._name_lbl = QLabel(name)
        self._name_lbl.setFixedWidth(80)
        self._name_lbl.setStyleSheet("font-size: 10px;")

        self._stats_lbl = QLabel("—")
        self._stats_lbl.setStyleSheet("font-size: 10px; font-family: monospace;")
        self._stats_lbl.setWordWrap(True)

        layout.addWidget(self._name_lbl)
        layout.addWidget(self._stats_lbl, stretch=1)

    def set_stats(self, stats: dict | None) -> None:
        if not stats or "min" not in stats:
            self._stats_lbl.setText("—")
            return
        self._stats_lbl.setText(
            f"min={stats['min']:.4g}  max={stats['max']:.4g}  "
            f"mean={stats['mean']:.4g}  rms={stats['rms']:.4g}"
        )


class ReadoutPanel(QGroupBox):
    """Live channel value readout at the current playhead position.

    Call `update_sources(readers)` when channels are added/removed,
    and `set_cursor(t)` every tick to refresh displayed values.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Channel Values", parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)

        self._content = QWidget()
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)

        self._stats_label = QLabel("Region Stats")
        self._stats_label.setStyleSheet(
            "font-weight: bold; font-size: 11px;"
        )
        self._stats_label.setVisible(False)

        self._layout.addStretch()
        self._scroll.setWidget(self._content)

        self._rows: dict[str, tuple[PyramidReader, _ChannelReadout]] = {}
        self._stats_rows: dict[str, _StatsRow] = {}
        self._readers: list[PyramidReader] = []

    def update_sources(self, readers: list[PyramidReader]) -> None:
        """Replace the displayed channels with a new list of readers."""
        for _, row in self._rows.values():
            self._layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._readers = list(readers)

        for reader in readers:
            row = _ChannelReadout(reader.channel_id)
            self._layout.insertWidget(self._layout.count() - 1, row)
            self._rows[reader.channel_id] = (reader, row)

    def set_cursor(self, t: float) -> None:
        """Interpolate and display each channel's value at time *t*."""
        for _name, (reader, row) in self._rows.items():
            try:
                t_arr, v_arr, _, _ = reader._load_level(1)
                if len(t_arr) == 0:
                    row.set_value(None)
                    continue
                idx = int(np.searchsorted(t_arr, t, side="right")) - 1
                idx = max(0, min(idx, len(v_arr) - 1))
                row.set_value(float(v_arr[idx]))
            except Exception:
                row.set_value(None)

    def show_region_stats(self, t0: float, t1: float) -> None:
        """Compute and display stats for the A/B loop region."""
        self._clear_stats()
        if t0 >= t1 or not self._readers:
            return

        from kinochronix.engine.export import compute_region_stats

        stats_list = compute_region_stats(self._readers, t0, t1)

        self._stats_label.setVisible(True)
        self._layout.insertWidget(self._layout.count() - 1, self._stats_label)

        for stats in stats_list:
            ch = stats.get("channel", "?")
            row = _StatsRow(ch)
            row.set_stats(stats)
            self._layout.insertWidget(self._layout.count() - 1, row)
            self._stats_rows[ch] = row

    def clear_region_stats(self) -> None:
        """Remove region stats display."""
        self._clear_stats()

    def _clear_stats(self) -> None:
        self._stats_label.setVisible(False)
        for row in self._stats_rows.values():
            self._layout.removeWidget(row)
            row.deleteLater()
        self._stats_rows.clear()
