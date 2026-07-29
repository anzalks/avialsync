"""Timestamp import wizard with preview, format autodetect, and timezone handling."""

from __future__ import annotations

import codecs
import csv
import io
import re
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_COMMON_FORMATS = [
    ("Auto-detect", ""),
    ("ISO 8601 (2024-01-15T10:30:00)", "%Y-%m-%dT%H:%M:%S"),
    ("ISO 8601 with ms", "%Y-%m-%dT%H:%M:%S.%f"),
    ("Date + time (2024-01-15 10:30:00)", "%Y-%m-%d %H:%M:%S"),
    ("Date + time with ms", "%Y-%m-%d %H:%M:%S.%f"),
    ("US date (01/15/2024 10:30:00)", "%m/%d/%Y %H:%M:%S"),
    ("EU date (15.01.2024 10:30:00)", "%d.%m.%Y %H:%M:%S"),
    ("Time only (10:30:00.000)", "%H:%M:%S.%f"),
    ("Time only no ms (10:30:00)", "%H:%M:%S"),
    ("Unix epoch (seconds)", "epoch_s"),
    ("Unix epoch (milliseconds)", "epoch_ms"),
    ("Unix epoch (microseconds)", "epoch_us"),
    ("Unix epoch (nanoseconds)", "epoch_ns"),
    ("Custom…", "custom"),
]

_SEPARATORS = [
    ("Comma (,)", ","),
    ("Semicolon (;)", ";"),
    ("Tab", "\t"),
    ("Space", " "),
    ("Pipe (|)", "|"),
]

_TIME_UNITS = [
    ("seconds (s)", "s"),
    ("milliseconds (ms)", "ms"),
    ("microseconds (µs)", "us"),
    ("nanoseconds (ns)", "ns"),
]

_TIMEZONES = [
    ("UTC", "UTC"),
    ("Local system time", "local"),
    ("US/Eastern (ET)", "US/Eastern"),
    ("US/Central (CT)", "US/Central"),
    ("US/Pacific (PT)", "US/Pacific"),
    ("Europe/London (GMT/BST)", "Europe/London"),
    ("Europe/Berlin (CET/CEST)", "Europe/Berlin"),
    ("Asia/Tokyo (JST)", "Asia/Tokyo"),
    ("Asia/Kolkata (IST)", "Asia/Kolkata"),
    ("Australia/Sydney (AEST)", "Australia/Sydney"),
]

# Sentinel values commonly used in logger data
_SENTINEL_PRESETS = [
    ("-9999", "-9999"),
    ("NaN", "NaN"),
    ("NA", "NA"),
    ("#N/A", "#N/A"),
    ("", ""),
    ("Custom…", "custom"),
]


def _sniff_separator(lines: list[str]) -> str:
    """Guess the CSV separator from a few lines."""
    for sep in [",", ";", "\t", "|"]:
        counts = [line.count(sep) for line in lines if line.strip()]
        if counts and min(counts) > 0 and max(counts) == min(counts):
            return sep
    return ","


def _sniff_encoding(raw: bytes) -> str:
    """Detect BOM or fall back to utf-8."""
    if raw.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        return "utf-16"
    return "utf-8"


def _guess_time_column(headers: list[str]) -> int:
    """Return the index of the most likely timestamp column."""
    time_patterns = re.compile(r"(time|timestamp|date|t|epoch|unix|seconds|elapsed)", re.IGNORECASE)
    for i, h in enumerate(headers):
        if time_patterns.search(h.strip()):
            return i
    return 0


def _guess_format(sample_values: list[str]) -> str:
    """Heuristic: guess the timestamp format from sample values."""
    if not sample_values:
        return ""

    v = sample_values[0].strip()

    # Epoch-like: purely numeric (possibly with decimal)
    try:
        val = float(v)
        if val > 1e15:
            return "epoch_ns"
        if val > 1e12:
            return "epoch_us"
        if val > 1e9:
            return "epoch_ms"
        return "epoch_s"
    except ValueError:
        pass

    # ISO-ish patterns
    if re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+", v):
        return "%Y-%m-%dT%H:%M:%S.%f"
    if re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", v):
        return "%Y-%m-%dT%H:%M:%S"
    if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+", v):
        return "%Y-%m-%d %H:%M:%S.%f"
    if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", v):
        return "%Y-%m-%d %H:%M:%S"

    # EU date: dd.mm.yyyy
    if re.match(r"\d{1,2}\.\d{1,2}\.\d{4}", v):
        return "%d.%m.%Y %H:%M:%S"

    # US date: mm/dd/yyyy
    if re.match(r"\d{1,2}/\d{1,2}/\d{4}", v):
        return "%m/%d/%Y %H:%M:%S"

    # Time only
    if re.match(r"\d{1,2}:\d{2}:\d{2}\.\d+", v):
        return "%H:%M:%S.%f"
    if re.match(r"\d{1,2}:\d{2}:\d{2}", v):
        return "%H:%M:%S"

    return ""


class ImportWizard(QDialog):
    """Dialog for configuring CSV/time-series import parameters.

    Previews the file, lets the user pick the time column, format,
    separator, timezone, sentinel values, and unit. Returns a config
    dict usable by the import pipeline.
    """

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Import — {path.name}")
        self.setMinimumSize(750, 550)
        self._path = path

        # Read raw bytes for encoding detection, then decode
        raw = path.read_bytes()[: 64 * 1024]
        self._encoding = _sniff_encoding(raw)
        text = raw.decode(self._encoding, errors="replace")
        self._raw_lines = text.splitlines()[:200]

        sep = _sniff_separator(self._raw_lines[:10])
        reader = csv.reader(io.StringIO("\n".join(self._raw_lines[:50])), delimiter=sep)
        rows = list(reader)

        self._headers: list[str] = rows[0] if rows else []
        self._sample_rows: list[list[str]] = rows[1:21] if len(rows) > 1 else []

        time_col_idx = _guess_time_column(self._headers)
        sample_time_vals = [r[time_col_idx] for r in self._sample_rows if len(r) > time_col_idx]
        guessed_fmt = _guess_format(sample_time_vals)

        # ── Layout ───────────────────────────────────────────────────
        main_layout = QVBoxLayout(self)

        # Preview table
        preview_group = QGroupBox("Preview (first 20 rows)")
        preview_layout = QVBoxLayout(preview_group)

        self._has_headers = True
        self._has_headers_cb = QCheckBox("File has headers")
        self._has_headers_cb.setChecked(self._has_headers)
        self._has_headers_cb.toggled.connect(self._on_has_headers_toggled)
        preview_layout.addWidget(self._has_headers_cb)

        self._preview_table = QTableWidget()
        self._preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        preview_layout.addWidget(self._preview_table)
        main_layout.addWidget(preview_group)

        # Config form
        config_group = QGroupBox("Import Settings")
        self._form = QFormLayout(config_group)

        # Separator
        self._sep_combo = QComboBox()
        for label, val in _SEPARATORS:
            self._sep_combo.addItem(label, val)
        for i, (_, val) in enumerate(_SEPARATORS):
            if val == sep:
                self._sep_combo.setCurrentIndex(i)
                break
        self._sep_combo.currentIndexChanged.connect(self._on_separator_changed)
        self._form.addRow("Separator:", self._sep_combo)

        # Time column
        self._time_col_combo = QComboBox()
        self._form.addRow("Time column:", self._time_col_combo)

        # Timestamp format
        self._fmt_combo = QComboBox()
        for label, val in _COMMON_FORMATS:
            self._fmt_combo.addItem(label, val)
        self._select_format(guessed_fmt)
        self._form.addRow("Format:", self._fmt_combo)

        # Custom format input
        self._custom_fmt = QLineEdit()
        self._custom_fmt.setPlaceholderText("e.g. %Y-%m-%d %H:%M:%S.%f")
        self._custom_fmt.setVisible(False)
        self._fmt_combo.currentIndexChanged.connect(self._on_format_changed)
        self._form.addRow("", self._custom_fmt)

        # Time unit
        self._unit_combo = QComboBox()
        for label, val in _TIME_UNITS:
            self._unit_combo.addItem(label, val)

        self._form.addRow("Numeric unit:", self._unit_combo)

        # Timezone
        self._tz_combo = QComboBox()
        for label, val in _TIMEZONES:
            self._tz_combo.addItem(label, val)
        self._form.addRow("Timezone:", self._tz_combo)

        # Anchor date (for time-only formats)
        anchor_row = QHBoxLayout()
        self._anchor_date = QLineEdit()
        self._anchor_date.setPlaceholderText("YYYY-MM-DD (for time-only data)")
        self._anchor_chk = QCheckBox("Use anchor date")
        self._anchor_chk.toggled.connect(self._anchor_date.setEnabled)
        self._anchor_date.setEnabled(False)
        anchor_row.addWidget(self._anchor_chk)
        anchor_row.addWidget(self._anchor_date, stretch=1)
        self._form.addRow("Anchor:", anchor_row)

        # Sentinel → NaN mapping
        sentinel_row = QHBoxLayout()
        self._sentinel_combo = QComboBox()
        for label, val in _SENTINEL_PRESETS:
            self._sentinel_combo.addItem(label, val)
        self._sentinel_custom = QLineEdit()
        self._sentinel_custom.setPlaceholderText("value to treat as NaN")
        self._sentinel_custom.setVisible(False)
        self._sentinel_combo.currentIndexChanged.connect(self._on_sentinel_changed)
        sentinel_row.addWidget(self._sentinel_combo)
        sentinel_row.addWidget(self._sentinel_custom)
        self._form.addRow("Sentinel → NaN:", sentinel_row)

        # Euro decimal (comma as decimal separator)
        self._euro_chk = QCheckBox("European decimals (comma = decimal separator)")
        self._form.addRow("", self._euro_chk)

        main_layout.addWidget(config_group)

        # Buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._validate_and_accept)
        btn_box.rejected.connect(self.reject)
        main_layout.addWidget(btn_box)

        # Populate initial preview and column choices
        self._on_separator_changed(0)

    def _select_format(self, fmt: str) -> None:
        """Select the matching format in the combo, or fall back to auto."""
        for i in range(self._fmt_combo.count()):
            if self._fmt_combo.itemData(i) == fmt:
                self._fmt_combo.setCurrentIndex(i)
                return
        # If the guessed format isn't in the list, set custom
        if fmt:
            for i in range(self._fmt_combo.count()):
                if self._fmt_combo.itemData(i) == "custom":
                    self._fmt_combo.setCurrentIndex(i)
                    self._custom_fmt.setText(fmt)
                    self._custom_fmt.setVisible(True)
                    return

    def _on_format_changed(self, idx: int) -> None:
        val = self._fmt_combo.currentData()
        self._custom_fmt.setVisible(val == "custom")

    def _on_separator_changed(self, _idx: int) -> None:
        sep = self._sep_combo.currentData()
        reader = csv.reader(io.StringIO("\n".join(self._raw_lines[:50])), delimiter=sep)
        rows = list(reader)
        if self._has_headers:
            self._headers = rows[0] if rows else []
            self._sample_rows = rows[1:21] if len(rows) > 1 else []
        else:
            ncols = len(rows[0]) if rows else 0
            self._headers = [f"column_{i + 1}" for i in range(ncols)]
            self._sample_rows = rows[:20]

        ncols = len(self._headers)
        self._preview_table.setColumnCount(ncols)
        self._preview_table.setHorizontalHeaderLabels(self._headers)
        self._preview_table.setRowCount(min(20, len(self._sample_rows)))

        for r, row_data in enumerate(self._sample_rows[:20]):
            for c in range(ncols):
                val = row_data[c].strip() if c < len(row_data) else ""
                self._preview_table.setItem(r, c, QTableWidgetItem(val))

        # Refresh time column combo
        self._time_col_combo.clear()
        for h in self._headers:
            self._time_col_combo.addItem(h.strip())
        time_col_idx = _guess_time_column(self._headers)
        self._time_col_combo.setCurrentIndex(time_col_idx)

    def _on_has_headers_toggled(self, checked: bool) -> None:
        self._has_headers = checked
        self._on_separator_changed(0)

    def _on_sentinel_changed(self, idx: int) -> None:
        val = self._sentinel_combo.currentData()
        self._sentinel_custom.setVisible(val == "custom")

    def _validate_and_accept(self) -> None:
        if not self._headers:
            QMessageBox.warning(self, "Import Error", "No columns detected in file.")
            return

        time_col = self._time_col_combo.currentText()
        if not time_col:
            QMessageBox.warning(self, "Import Error", "Please select a time column.")
            return

        if self._anchor_chk.isChecked() and not self._anchor_date.text().strip():
            QMessageBox.warning(self, "Import Error", "Please enter an anchor date.")
            return

        self.accept()

    def config(self) -> dict[str, Any]:
        """Return the import configuration dict for the pipeline."""
        fmt_val = self._fmt_combo.currentData()
        if fmt_val == "custom":
            fmt_val = self._custom_fmt.text().strip()

        sentinel = self._sentinel_combo.currentData()
        if sentinel == "custom":
            sentinel = self._sentinel_custom.text().strip()

        return {
            "separator": self._sep_combo.currentData(),
            "has_headers": self._has_headers,
            "time_col": self._time_col_combo.currentText(),
            "time_format": fmt_val,
            "time_unit": self._unit_combo.currentData(),
            "timezone": self._tz_combo.currentData(),
            "anchor_date": self._anchor_date.text().strip() if self._anchor_chk.isChecked() else "",
            "sentinel": sentinel if sentinel else None,
            "euro_decimal": self._euro_chk.isChecked(),
        }
