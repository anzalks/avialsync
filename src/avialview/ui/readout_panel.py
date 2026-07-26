"""Cursor readout panel — per-channel values, camera frame numbers, Δ measurement."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from avialview.core.pyramid import PyramidReader
from avialview.ui.theme import set_font_family


def _set_monospace(widget: QWidget) -> None:
    """Preserve a fixed-width family while inheriting the application font size."""
    family = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    set_font_family(widget, family)


class _ChannelReadout(QWidget):
    """Single row: channel name | value (unit) | sample index."""

    def __init__(self, name: str, unit: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._unit = unit
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._name_lbl = QLabel(name)
        self._name_lbl.setFixedWidth(130)

        self._val_lbl = QLabel("—")
        _set_monospace(self._val_lbl)
        self._val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._idx_lbl = QLabel("")
        self._idx_lbl.setFixedWidth(60)
        self._idx_lbl.setStyleSheet("color: #777;")
        self._idx_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self._name_lbl)
        layout.addWidget(self._val_lbl, stretch=1)
        layout.addWidget(self._idx_lbl)

    def set_value(self, v: float | None, sample_idx: int | None = None) -> None:
        if v is None or np.isnan(v):
            self._val_lbl.setText("—")
        else:
            unit_str = f" {self._unit}" if self._unit else ""
            self._val_lbl.setText(f"{v:.4g}{unit_str}")
        if sample_idx is not None:
            self._idx_lbl.setText(f"[{sample_idx}]")


class _StatsRow(QWidget):
    """Shows min/max/mean/rms for one channel in a region."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._name_lbl = QLabel(name)
        self._name_lbl.setFixedWidth(80)

        self._stats_lbl = QLabel("—")
        _set_monospace(self._stats_lbl)
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


class _CameraRow(QWidget):
    """Shows frame number and media timestamp for one camera."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(label)
        lbl.setFixedWidth(90)

        self._info_lbl = QLabel("—")
        _set_monospace(self._info_lbl)

        layout.addWidget(lbl)
        layout.addWidget(self._info_lbl, stretch=1)

    def update(self, time_pos: float, fps: float) -> None:
        if fps > 0:
            frame_num = int(time_pos * fps)
            self._info_lbl.setText(f"frame {frame_num}  ({time_pos:.3f} s)")
        else:
            self._info_lbl.setText(f"{time_pos:.3f} s")


class _DeltaRow(QWidget):
    """Shows Δvalue for one channel."""

    def __init__(self, name: str, unit: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._unit = unit
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(f"Δ {name}")
        lbl.setFixedWidth(130)

        self._val_lbl = QLabel("—")
        _set_monospace(self._val_lbl)
        self._val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(lbl)
        layout.addWidget(self._val_lbl, stretch=1)

    def set_delta(self, dv: float | None) -> None:
        if dv is None or np.isnan(dv):
            self._val_lbl.setText("—")
        else:
            unit_str = f" {self._unit}" if self._unit else ""
            self._val_lbl.setText(f"{dv:+.4g}{unit_str}")


class ReadoutPanel(QGroupBox):
    """Live channel value readout at the current playhead position.

    Call `update_sources(readers, units)` when channels change,
    `set_cursor(t)` every tick, and `set_camera_states(states)` every tick.
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
        self._layout.addStretch()
        self._scroll.setWidget(self._content)

        self._rows: dict[str, tuple[PyramidReader, _ChannelReadout]] = {}
        self._units: dict[str, str] = {}
        self._readers: list[PyramidReader] = []

        # Section labels + rows for optional sections
        self._cam_label = QLabel("Camera Positions")
        self._cam_label.setStyleSheet("font-weight: bold;")
        self._cam_label.setVisible(False)
        self._cam_rows: list[_CameraRow] = []

        self._stats_label = QLabel("Region Stats")
        self._stats_label.setStyleSheet("font-weight: bold;")
        self._stats_label.setVisible(False)
        self._stats_rows: dict[str, _StatsRow] = {}

        self._delta_label = QLabel("Δ Measurement")
        self._delta_label.setStyleSheet("font-weight: bold;")
        self._delta_label.setVisible(False)
        self._delta_rows: dict[str, _DeltaRow] = {}
        self._delta_t_lbl = QLabel("Δt = —")
        _set_monospace(self._delta_t_lbl)

    # ── Public API ────────────────────────────────────────────────────

    def update_sources(
        self, readers: list[PyramidReader], units: dict[str, str] | None = None
    ) -> None:
        """Replace displayed channels with a new list of readers."""
        for _, row in self._rows.values():
            self._layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._readers = list(readers)
        self._units = dict(units or {})

        for reader in readers:
            unit = self._units.get(reader.channel_id, "")
            row = _ChannelReadout(reader.channel_id, unit)
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
                row.set_value(float(v_arr[idx]), idx)
            except Exception:
                row.set_value(None)

    def set_camera_states(self, states: list[tuple[str, float, float]]) -> None:
        """Update per-camera frame display.  states = [(label, time_pos, fps), ...]"""
        # Remove stale rows
        for row in self._cam_rows:
            self._layout.removeWidget(row)
            row.deleteLater()
        self._cam_rows.clear()
        self._layout.removeWidget(self._cam_label)

        if not states:
            self._cam_label.setVisible(False)
            return

        self._cam_label.setVisible(True)
        self._layout.insertWidget(0, self._cam_label)
        for i, (label, time_pos, fps) in enumerate(states):
            row = _CameraRow(label)
            row.update(time_pos, fps)
            self._layout.insertWidget(1 + i, row)
            self._cam_rows.append(row)

    def show_region_stats(self, t0: float, t1: float) -> None:
        """Compute and display stats for the A/B loop region."""
        self._clear_stats()
        if t0 >= t1 or not self._readers:
            return

        from avialview.engine.export import compute_region_stats

        stats_list = compute_region_stats(self._readers, t0, t1)

        self._stats_label.setVisible(True)
        self._layout.insertWidget(self._layout.count() - 1, self._stats_label)
        for stats in stats_list:
            ch = stats.get("channel", "?")
            row = _StatsRow(ch)
            row.set_stats(stats)
            self._layout.insertWidget(self._layout.count() - 1, row)
            self._stats_rows[ch] = row

    def show_delta(
        self,
        t_a: float,
        t_b: float,
        camera_states: list[tuple[str, float, float]] | None = None,
    ) -> None:
        """Show Δt and Δvalue per channel between measure points A and B."""
        self._clear_delta()
        dt = t_b - t_a
        self._delta_label.setVisible(True)
        self._delta_t_lbl.setText(f"Δt = {dt:+.3f} s")
        self._layout.insertWidget(self._layout.count() - 1, self._delta_label)
        self._layout.insertWidget(self._layout.count() - 1, self._delta_t_lbl)

        for ch_name, (reader, _) in self._rows.items():
            unit = self._units.get(ch_name, "")
            try:
                t_arr, v_arr, _, _ = reader._load_level(1)
                if len(t_arr) == 0:
                    dv = None
                else:
                    ia = max(0, int(np.searchsorted(t_arr, t_a, "right")) - 1)
                    ib = max(0, int(np.searchsorted(t_arr, t_b, "right")) - 1)
                    dv = float(v_arr[ib]) - float(v_arr[ia])
            except Exception:
                dv = None
            row = _DeltaRow(ch_name, unit)
            row.set_delta(dv)
            self._layout.insertWidget(self._layout.count() - 1, row)
            self._delta_rows[ch_name] = row

        if camera_states:
            fps_row = QLabel("Frames between:")
            fps_row.setStyleSheet("font-weight: bold;")
            self._layout.insertWidget(self._layout.count() - 1, fps_row)
            for label, _tp, fps in camera_states:
                n = int(round(dt * fps)) if fps > 0 else "—"
                r = QLabel(f"  {label}: {n} frames")
                self._layout.insertWidget(self._layout.count() - 1, r)

    def clear_region_stats(self) -> None:
        self._clear_stats()

    def clear_delta(self) -> None:
        self._clear_delta()

    # ── Internal ──────────────────────────────────────────────────────

    def _clear_stats(self) -> None:
        self._stats_label.setVisible(False)
        self._layout.removeWidget(self._stats_label)
        for row in self._stats_rows.values():
            self._layout.removeWidget(row)
            row.deleteLater()
        self._stats_rows.clear()

    def _clear_delta(self) -> None:
        self._delta_label.setVisible(False)
        self._layout.removeWidget(self._delta_label)
        self._layout.removeWidget(self._delta_t_lbl)
        for row in self._delta_rows.values():
            self._layout.removeWidget(row)
            row.deleteLater()
        self._delta_rows.clear()
