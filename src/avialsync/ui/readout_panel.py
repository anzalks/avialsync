"""Cursor readout panel — grouped signal values, camera frames, Δ measurement."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import cast

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QPalette, QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.channel_reader import ChannelKey, MappedChannelReader, disambiguate
from avialsync.ui.channel_tree import channel_tree_paths, compact_channel_label, matches_filter
from avialsync.ui.design_tokens import spacing
from avialsync.ui.elided_label import ElidedLabel
from avialsync.ui.empty_note import EmptyNote
from avialsync.ui.i18n import tr
from avialsync.ui.readout_widgets import (
    _CameraRow,
    _ChannelReadout,
    _DeltaRow,
    _SignalGroupSection,
    _StatsRow,
    format_channel_summary,
    set_monospace,
)
from avialsync.ui.theme import set_bold

__all__ = ["ReadoutPanel", "_ChannelReadout", "_MAX_WIDGET_ROWS"]

#: Maximum live per-channel QWidget rows mounted in the sidebar scroll area;
#: dense groups start collapsed to a summary line and remain listed in ``Text view…``.
_MAX_WIDGET_ROWS = 64

#: Signal groups with more channels than this start collapsed to a group summary
#: (mean + min…max) so high-ROI/ephys sources do not dump raw numbers down the page.
_AUTO_COLLAPSE_GROUP_ROWS = 6

#: Maximum channels sampled per collapsed dense group on each cursor update.
_MAX_GROUP_SUMMARY_SAMPLES = 24

_FILTER_THRESHOLD = 8


def _display_sample(reader: MappedChannelReader, time: float) -> tuple[int, float] | None:
    """Use availability-aware sampling, retaining legacy reader adapters."""
    available = getattr(reader, "available_sample_at", None)
    if callable(available):
        return cast(tuple[int, float] | None, available(time))
    return reader.sample_at(time)


class ReadoutPanel(QWidget):
    """Grouped live signal summary and camera frame readout at the playhead.

    Shows only active/visible signals when connected to ``PlotPane``, organized
    by signal group with collapsible summaries for dense multi-ROI / electrode
    banks rather than dumping raw ungrouped array indices.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(tr("Channel values and camera frames"))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(spacing("s"), spacing("s"), spacing("s"), spacing("s"))
        outer.setSpacing(spacing("xs"))

        self._toolbar = QWidget(self)
        top_bar = QHBoxLayout(self._toolbar)
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(spacing("xs"))

        self._filter_edit = QLineEdit(self._toolbar)
        self._filter_edit.setPlaceholderText(tr("Filter signals…"))
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.setAccessibleName(tr("Filter displayed signal values"))
        self._filter_edit.setVisible(False)
        self._filter_edit.textChanged.connect(self._apply_filter)

        self._text_summary_button = QPushButton(tr("Text view…"), self._toolbar)
        self._text_summary_button.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self._text_summary_button.setAccessibleName(tr("Show a text summary of current values"))
        self._text_summary_button.setToolTip(
            tr("Open a copyable text summary of channel values and camera frames.")
        )
        self._text_summary_button.clicked.connect(self._show_text_summary)
        top_bar.addWidget(self._filter_edit, stretch=1)
        top_bar.addStretch(0)
        top_bar.addWidget(self._text_summary_button, 0, Qt.AlignmentFlag.AlignRight)
        outer.addWidget(self._toolbar)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(self._scroll)

        self.empty_note = EmptyNote(
            tr(
                "No values yet. Each visible channel and camera shows its value here "
                "once a recording is open."
            ),
            self,
        )
        outer.addWidget(self.empty_note)

        self._content = QWidget()
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(spacing("xs"))

        self._cam_box = QWidget(self._content)
        self._cam_layout = QVBoxLayout(self._cam_box)
        self._cam_layout.setContentsMargins(0, 0, 0, 2)
        self._cam_layout.setSpacing(2)
        self._cam_label = QLabel(tr("Cameras"), self._cam_box)
        set_bold(self._cam_label)
        self._cam_layout.addWidget(self._cam_label)
        self._cam_box.setVisible(False)
        self._layout.addWidget(self._cam_box)

        self._signals_box = QWidget(self._content)
        self._signals_layout = QVBoxLayout(self._signals_box)
        self._signals_layout.setContentsMargins(0, 0, 0, 0)
        self._signals_layout.setSpacing(spacing("xs"))
        self._layout.addWidget(self._signals_box)

        self._extras_box = QWidget(self._content)
        self._extras_layout = QVBoxLayout(self._extras_box)
        self._extras_layout.setContentsMargins(0, 0, 0, 0)
        self._extras_layout.setSpacing(2)
        self._layout.addWidget(self._extras_box)

        self._layout.addStretch()
        self._scroll.setWidget(self._content)
        self._content.setAutoFillBackground(False)

        self._rows: dict[ChannelKey, tuple[MappedChannelReader, _ChannelReadout | None]] = {}
        self._labels: dict[ChannelKey, str] = {}
        self._compact_labels: dict[ChannelKey, str] = {}
        self._units: dict[ChannelKey, str] = {}
        self._readers: list[MappedChannelReader] = []
        self._group_sections: list[tuple[_SignalGroupSection, list[ChannelKey]]] = []
        self._group_expansion_prefs: dict[tuple[str, str], bool] = {}
        self._signal_headers: list[QWidget] = []
        self._cursor_time: float | None = None
        self._cursor_dirty = False

        self._overflow_lbl = QLabel(self._signals_box)
        self._overflow_lbl.setWordWrap(True)
        self._overflow_lbl.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self._overflow_lbl.setVisible(False)

        self._cam_rows: list[_CameraRow] = []

        self._stats_label = QLabel(tr("Region Stats"), self._extras_box)
        set_bold(self._stats_label)
        self._stats_label.setVisible(False)
        self._stats_rows: dict[str, _StatsRow] = {}

        self._delta_label = QLabel(tr("Δ Measurement"), self._extras_box)
        set_bold(self._delta_label)
        self._delta_label.setVisible(False)
        self._delta_rows: dict[ChannelKey, _DeltaRow] = {}
        self._delta_extra_widgets: list[QWidget] = []
        self._delta_t_lbl = QLabel(tr("Δt = —"), self._extras_box)
        set_monospace(self._delta_t_lbl)
        self._delta_t_lbl.setVisible(False)

        self._refresh_empty()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._cursor_dirty:
            self._flush_cursor()

    # ── Public API ────────────────────────────────────────────────────

    def update_sources(
        self,
        readers: list[MappedChannelReader],
        units: dict[ChannelKey, str] | None = None,
    ) -> None:
        """Rebuild grouped signal sections from the active *readers*."""
        self._readers = list(readers)
        if units is not None:
            self._units = dict(units)
        labels = disambiguate([reader.key for reader in readers])
        self._labels = labels
        previous = self._rows
        next_rows: dict[ChannelKey, tuple[MappedChannelReader, _ChannelReadout | None]] = {}

        self._content.setUpdatesEnabled(False)
        try:
            self._teardown_signal_widgets(previous)
            self._filter_edit.setVisible(len(readers) > _FILTER_THRESHOLD)
            mounted = self._build_grouped_signals(readers, previous, next_rows)
            if len(readers) > _MAX_WIDGET_ROWS and mounted >= _MAX_WIDGET_ROWS:
                extra = len(readers) - mounted
                self._overflow_lbl.setText(
                    tr("+{count} more channels — use Text view… for all values").format(count=extra)
                )
                self._overflow_lbl.setVisible(True)
                self._signals_layout.addWidget(self._overflow_lbl)
            for _, stale_row in previous.values():
                if stale_row is not None:
                    stale_row.deleteLater()
            self._rows = next_rows
            if self._filter_edit.text().strip():
                self._apply_filter(self._filter_edit.text())
            self._cursor_dirty = self._cursor_time is not None
            if self._cursor_dirty and (self.parentWidget() is None or self.isVisible()):
                self._flush_cursor()
            self._refresh_empty()
        finally:
            self._content.setUpdatesEnabled(True)

    def _teardown_signal_widgets(
        self,
        previous: dict[ChannelKey, tuple[MappedChannelReader, _ChannelReadout | None]],
    ) -> None:
        self._signals_layout.removeWidget(self._overflow_lbl)
        self._overflow_lbl.setVisible(False)
        for _, old_row in previous.values():
            if old_row is not None:
                old_row.setParent(None)
        for section, _keys in self._group_sections:
            self._signals_layout.removeWidget(section)
            section.deleteLater()
        self._group_sections.clear()
        for hdr in self._signal_headers:
            self._signals_layout.removeWidget(hdr)
            hdr.deleteLater()
        self._signal_headers.clear()
        self._compact_labels.clear()

    def _build_grouped_signals(
        self,
        readers: list[MappedChannelReader],
        previous: dict[ChannelKey, tuple[MappedChannelReader, _ChannelReadout | None]],
        next_rows: dict[ChannelKey, tuple[MappedChannelReader, _ChannelReadout | None]],
    ) -> int:
        by_source: dict[str, list[MappedChannelReader]] = {}
        for reader in readers:
            by_source.setdefault(reader.key.source_id, []).append(reader)

        multi_source = len(by_source) > 1
        mounted = 0

        for src_id, src_readers in by_source.items():
            if multi_source and src_id:
                src_lbl = ElidedLabel(Path(src_id).name, self._signals_box)
                set_bold(src_lbl)
                src_lbl.setToolTip(src_id)
                self._signals_layout.addWidget(src_lbl)
                self._signal_headers.append(src_lbl)

            paths = channel_tree_paths([r.key.channel_id for r in src_readers])
            groups: dict[str, list[tuple[MappedChannelReader, list[str]]]] = {}
            order: list[tuple[str, str]] = []
            for r in src_readers:
                cid = r.key.channel_id
                parts = paths.get(cid, [cid])
                self._compact_labels[r.key] = compact_channel_label(cid, parts)
                if len(parts) > 1:
                    gk = "/".join(parts[:-1])
                    if gk not in groups:
                        order.append(("group", gk))
                    groups.setdefault(gk, []).append((r, parts))
                else:
                    solo_key = f"__solo__:{cid}"
                    groups[solo_key] = [(r, parts)]
                    order.append(("solo", solo_key))

            for kind, gk in order:
                items = groups[gk]
                if kind == "solo":
                    r, parts = items[0]
                    mounted += self._mount_channel_row(
                        r,
                        parts[-1],
                        self._signals_layout,
                        previous,
                        next_rows,
                        mounted,
                        indent_px=0,
                    )
                    continue

                sample_parts = items[0][1]
                g_title = (
                    sample_parts[-2]
                    if len(sample_parts) == 2
                    else f"{sample_parts[-3]} / {sample_parts[-2]}"
                )
                units_in_group = {self._unit_for(r.key) for r, _ in items if self._unit_for(r.key)}
                g_unit = next(iter(units_in_group)) if len(units_in_group) == 1 else ""
                pref_key = (src_id, gk)
                default_open = len(items) <= _AUTO_COLLAPSE_GROUP_ROWS
                expanded = self._group_expansion_prefs.get(pref_key, default_open)

                section = _SignalGroupSection(
                    g_title,
                    len(items),
                    g_unit,
                    expanded=expanded,
                    on_toggle=partial(self._on_group_toggled, pref_key),
                    parent=self._signals_box,
                )
                self._signals_layout.addWidget(section)
                member_keys = [r.key for r, _ in items]
                self._group_sections.append((section, member_keys))

                for r, parts in items:
                    mounted += self._mount_channel_row(
                        r,
                        parts[-1],
                        section.body_layout,
                        previous,
                        next_rows,
                        mounted,
                        indent_px=10,
                    )
        return mounted

    def _mount_channel_row(
        self,
        reader: MappedChannelReader,
        leaf_name: str,
        target_layout: QVBoxLayout,
        previous: dict[ChannelKey, tuple[MappedChannelReader, _ChannelReadout | None]],
        next_rows: dict[ChannelKey, tuple[MappedChannelReader, _ChannelReadout | None]],
        mounted_so_far: int,
        *,
        indent_px: int,
    ) -> int:
        key = reader.key
        unit = self._unit_for(key)
        summary_name = self._labels.get(key, key.channel_id)
        reused = previous.pop(key, None)
        old_widget = reused[1] if reused is not None else None
        if mounted_so_far < _MAX_WIDGET_ROWS:
            if old_widget is not None:
                row = old_widget
                row.setParent(self._signals_box)
                row.configure(leaf_name, unit, summary_name=summary_name, indent_px=indent_px)
            else:
                row = _ChannelReadout(
                    leaf_name,
                    unit,
                    self._signals_box,
                    summary_name=summary_name,
                    indent_px=indent_px,
                )
            target_layout.addWidget(row)
            next_rows[key] = (reader, row)
            return 1
        if old_widget is not None:
            old_widget.deleteLater()
        next_rows[key] = (reader, None)
        return 0

    def _unit_for(self, key: ChannelKey) -> str:
        return self._units.get(key, self._units.get(ChannelKey("", key.channel_id), ""))

    def _on_group_toggled(
        self, pref_key: tuple[str, str], _section: _SignalGroupSection, expanded: bool
    ) -> None:
        self._group_expansion_prefs[pref_key] = expanded
        if self._cursor_time is not None:
            self._flush_cursor()

    def _apply_filter(self, needle: str) -> None:
        query = needle.strip()
        grouped_keys = {k for _, keys in self._group_sections for k in keys}
        for key, (_reader, row) in self._rows.items():
            if row is not None and key not in grouped_keys:
                row.setVisible(matches_filter(key.channel_id, query))
        for section, keys in self._group_sections:
            any_match = False
            for key in keys:
                matched = matches_filter(key.channel_id, query) or matches_filter(
                    section.group_title, query
                )
                if matched:
                    any_match = True
                entry = self._rows.get(key)
                if entry is not None and entry[1] is not None:
                    entry[1].setVisible(matched)
            section.setVisible(any_match)
            if query and any_match:
                section.set_expanded(True)

    def set_cursor(self, t: float) -> None:
        """Display the last available sample at or before *t*."""
        self._cursor_time = float(t)
        if self.parentWidget() is not None and not self.isVisible():
            self._cursor_dirty = True
            return
        self._flush_cursor()

    def _flush_cursor(self) -> None:
        self._cursor_dirty = False
        t = self._cursor_time
        if t is None:
            return

        collapsed_keys: set[ChannelKey] = set()
        for section, keys in self._group_sections:
            if not section.is_expanded:
                collapsed_keys.update(keys)
                stride = max(1, len(keys) // _MAX_GROUP_SUMMARY_SAMPLES)
                vals: list[float] = []
                for key in keys[::stride]:
                    entry = self._rows.get(key)
                    if entry is None:
                        continue
                    try:
                        sample = _display_sample(entry[0], t)
                        if sample is not None and np.isfinite(sample[1]):
                            vals.append(float(sample[1]))
                    except Exception:
                        continue
                section.set_summary_values(vals)
            else:
                section.set_summary_values([])

        for key, (reader, row) in self._rows.items():
            if row is None or key in collapsed_keys:
                continue
            try:
                sample = _display_sample(reader, t)
                if sample is None:
                    row.set_value(None)
                    continue
                index, value = sample
                row.set_value(value, index)
            except Exception:
                row.set_value(None)

    def textual_summary(self) -> str:
        """Return a screen-reader-friendly and copyable text view of current values."""
        if self._cursor_dirty:
            self._flush_cursor()
        if self._cursor_time is None:
            lines = [tr("Playhead time is not available.")]
        else:
            lines = [tr("Master time: {time:.6f} s").format(time=self._cursor_time)]
        for key, (reader, row) in self._rows.items():
            unit = self._unit_for(key)
            label = self._labels.get(key, key.channel_id)
            sample: tuple[int, float] | None = None
            if self._cursor_time is not None:
                try:
                    sample = _display_sample(reader, self._cursor_time)
                except Exception:
                    sample = None
            if row is not None and sample is not None:
                row.set_value(sample[1], sample[0])
                lines.append(row.summary_line())
                continue
            if row is not None and self._cursor_time is None:
                lines.append(row.summary_line())
                continue
            lines.append(format_channel_summary(label, unit, sample))
        lines.extend(row.summary_line() for row in self._cam_rows)
        if not self._rows and not self._cam_rows:
            lines.append(tr("No channel values or camera frames are available."))
        return "\n".join(lines)

    def _show_text_summary(self) -> None:
        """Show the requested values in the shared copyable text dialog."""
        from avialsync.ui.feedback.text_dialog import show_text

        show_text(
            self,
            tr("Current Values"),
            self.textual_summary(),
            lead=tr("Channel values and camera frames at the current playhead."),
        )

    def install_empty_action(self, action: QAction) -> None:
        """Offer the command that gives this page something to show."""
        self.empty_note.set_action(action)

    def _refresh_empty(self) -> None:
        has_values = bool(self._rows or self._cam_rows or self._delta_rows or self._stats_rows)
        self.empty_note.setVisible(not has_values)
        self._scroll.setVisible(has_values)
        self._toolbar.setVisible(bool(self._rows or self._cam_rows))

    def set_camera_states(self, states: list[tuple[str, float, float]]) -> None:
        """Update per-camera frame display.  states = [(label, time_pos, fps), ...]"""
        for row in self._cam_rows:
            self._cam_layout.removeWidget(row)
            row.deleteLater()
        self._cam_rows.clear()

        if not states:
            self._cam_box.setVisible(False)
            self._refresh_empty()
            return

        self._cam_box.setVisible(True)
        for label, time_pos, fps in states:
            row = _CameraRow(label, self._cam_box)
            row.set_state(time_pos, fps)
            self._cam_layout.addWidget(row)
            self._cam_rows.append(row)
        self._refresh_empty()

    def set_camera_frame_records(self, records: list[tuple[str, int, float]]) -> None:
        """Update camera rows from authoritative frame indices and media times."""
        labels = [label for label, _, _ in records]
        current_labels = [row._raw_label for row in self._cam_rows]
        if labels == current_labels:
            for row, (_, frame_index, media_time) in zip(self._cam_rows, records, strict=True):
                row.set_state(media_time, 0.0, frame_index)
            return

        for row in self._cam_rows:
            self._cam_layout.removeWidget(row)
            row.deleteLater()
        self._cam_rows.clear()
        if not records:
            self._cam_box.setVisible(False)
            self._refresh_empty()
            return

        self._cam_box.setVisible(True)
        for label, frame_index, media_time in records:
            row = _CameraRow(label, self._cam_box)
            row.set_state(media_time, 0.0, frame_index)
            self._cam_layout.addWidget(row)
            self._cam_rows.append(row)
        self._refresh_empty()

    def display_region_stats(self, stats_list: list[dict[str, float | str]]) -> None:
        """Display A/B-region statistics computed by a background worker."""
        self._content.setUpdatesEnabled(False)
        try:
            self._clear_stats()
            if not stats_list:
                self._refresh_empty()
                return
            self._stats_label.setVisible(True)
            self._extras_layout.addWidget(self._stats_label)
            for stats in stats_list[:_MAX_WIDGET_ROWS]:
                ch = str(stats.get("channel", "?"))
                short = compact_channel_label(ch)
                row = _StatsRow(short, self._extras_box)
                row._name_lbl.setToolTip(ch)
                row.set_stats(stats)
                self._extras_layout.addWidget(row)
                self._stats_rows[ch] = row
            self._refresh_empty()
        finally:
            self._content.setUpdatesEnabled(True)

    def show_delta(
        self,
        t_a: float,
        t_b: float,
        camera_states: list[tuple[str, float, float]] | None = None,
    ) -> None:
        """Show Δt and Δvalue per channel between measure points A and B."""
        self._content.setUpdatesEnabled(False)
        try:
            self._clear_delta()
            dt = t_b - t_a
            self._delta_label.setVisible(True)
            self._delta_t_lbl.setVisible(True)
            self._delta_t_lbl.setText(tr("Δt = {dt} s").format(dt=f"{dt:+.3f}"))
            self._extras_layout.addWidget(self._delta_label)
            self._extras_layout.addWidget(self._delta_t_lbl)

            labels = self._labels or disambiguate(list(self._rows))
            for idx, (key, (reader, _)) in enumerate(self._rows.items()):
                if idx >= _MAX_WIDGET_ROWS:
                    break
                unit = self._unit_for(key)
                try:
                    sample_a = _display_sample(reader, t_a)
                    sample_b = _display_sample(reader, t_b)
                    dv = None if sample_a is None or sample_b is None else sample_b[1] - sample_a[1]
                except Exception:
                    dv = None
                short = self._compact_labels.get(key) or compact_channel_label(key.channel_id)
                full = labels.get(key, key.channel_id)
                row = _DeltaRow(short, unit, self._extras_box, tooltip=full)
                row.set_delta(dv)
                self._extras_layout.addWidget(row)
                self._delta_rows[key] = row

            if len(self._rows) > _MAX_WIDGET_ROWS:
                more_lbl = QLabel(
                    tr("+{count} more channels").format(count=len(self._rows) - _MAX_WIDGET_ROWS),
                    self._extras_box,
                )
                more_lbl.setForegroundRole(QPalette.ColorRole.PlaceholderText)
                self._extras_layout.addWidget(more_lbl)
                self._delta_extra_widgets.append(more_lbl)

            if camera_states:
                fps_row = QLabel(tr("Frames between:"), self._extras_box)
                set_bold(fps_row)
                self._extras_layout.addWidget(fps_row)
                self._delta_extra_widgets.append(fps_row)
                for label, _tp, fps in camera_states:
                    n = int(round(dt * fps)) if fps > 0 else tr("—")
                    r = QLabel(
                        tr("  {label}: {count} frames").format(label=label, count=n),
                        self._extras_box,
                    )
                    self._extras_layout.addWidget(r)
                    self._delta_extra_widgets.append(r)
            self._refresh_empty()
        finally:
            self._content.setUpdatesEnabled(True)

    def clear_region_stats(self) -> None:
        self._clear_stats()
        self._refresh_empty()

    def clear_delta(self) -> None:
        self._clear_delta()
        self._refresh_empty()

    def _clear_stats(self) -> None:
        self._stats_label.setVisible(False)
        self._extras_layout.removeWidget(self._stats_label)
        for row in self._stats_rows.values():
            self._extras_layout.removeWidget(row)
            row.deleteLater()
        self._stats_rows.clear()

    def _clear_delta(self) -> None:
        self._delta_label.setVisible(False)
        self._delta_t_lbl.setVisible(False)
        self._extras_layout.removeWidget(self._delta_label)
        self._extras_layout.removeWidget(self._delta_t_lbl)
        for row in self._delta_rows.values():
            self._extras_layout.removeWidget(row)
            row.deleteLater()
        self._delta_rows.clear()
        for extra in self._delta_extra_widgets:
            self._extras_layout.removeWidget(extra)
            extra.deleteLater()
        self._delta_extra_widgets.clear()
