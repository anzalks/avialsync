"""Timestamp import wizard with preview, format autodetect, and timezone handling."""

from __future__ import annotations

import codecs
import csv
import io
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QTimeZone
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui import import_wizard_fields
from avialsync.ui.i18n import tr
from avialsync.ui.import_time_check import (
    ELAPSED_FORMAT,
    guess_format,
    guess_time_column,
    needs_timezone,
)
from avialsync.ui.tables import ThemedTable


def _common_formats() -> list[tuple[str, str]]:
    """Format choices, translated where they are read."""
    return [
        (tr("Auto-detect"), ""),
        (tr("Elapsed time (number counted from the start)"), ELAPSED_FORMAT),
        (tr("Unix epoch (seconds)"), "epoch_s"),
        (tr("Unix epoch (milliseconds)"), "epoch_ms"),
        (tr("Unix epoch (microseconds)"), "epoch_us"),
        (tr("Unix epoch (nanoseconds)"), "epoch_ns"),
        (tr("ISO 8601 with time zone (Z or +02:00)"), "iso8601"),
        (tr("ISO 8601 (2024-01-15T10:30:00)"), "%Y-%m-%dT%H:%M:%S"),
        (tr("ISO 8601 with ms"), "%Y-%m-%dT%H:%M:%S.%f"),
        (tr("Date + time (2024-01-15 10:30:00)"), "%Y-%m-%d %H:%M:%S"),
        (tr("Date + time with ms"), "%Y-%m-%d %H:%M:%S.%f"),
        (tr("US date (01/15/2024 10:30:00)"), "%m/%d/%Y %H:%M:%S"),
        (tr("EU date (15.01.2024 10:30:00)"), "%d.%m.%Y %H:%M:%S"),
        (tr("Time only (10:30:00.000)"), "%H:%M:%S.%f"),
        (tr("Time only no ms (10:30:00)"), "%H:%M:%S"),
        (tr("Custom…"), "custom"),
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


def _sentinel_presets() -> list[tuple[str, str]]:
    """Sentinel choices; the first is none, because nothing converts unasked."""
    return [
        (tr("None (keep every value)"), ""),
        ("-9999", "-9999"),
        ("NaN", "NaN"),
        ("NA", "NA"),
        ("#N/A", "#N/A"),
        (tr("Custom…"), "custom"),
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
    return guess_time_column(headers)


def _guess_format(sample_values: list[str]) -> str:
    """Heuristic: guess the timestamp format from sample values."""
    return guess_format(sample_values)


class ImportWizard(QDialog):
    """Dialog for configuring CSV/time-series import parameters.

    Previews the file, lets the user pick the time column, format,
    separator, timezone, sentinel values, and unit. Returns a config
    dict usable by the import pipeline.
    """

    _units_table: ThemedTable

    def __init__(self, path: Path, preview: bytes, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Import — {name}").format(name=path.name))
        self.setMinimumSize(750, 550)
        self._path = path

        # The registered preview worker supplies this bounded prefix. A dialog
        # constructor must never open the recording on the UI thread.
        self._encoding = _sniff_encoding(preview)
        text = preview.decode(self._encoding, errors="replace")
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
        preview_group = QGroupBox(tr("Preview (first 20 rows)"))
        preview_layout = QVBoxLayout(preview_group)

        self._has_headers = True
        self._has_headers_cb = QCheckBox(tr("File has headers"))
        self._has_headers_cb.setChecked(self._has_headers)
        self._has_headers_cb.toggled.connect(self._on_has_headers_toggled)
        preview_layout.addWidget(self._has_headers_cb)

        self._preview_table = ThemedTable()
        self._preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        preview_layout.addWidget(self._preview_table)

        units_group = import_wizard_fields.build_units_group(self)
        top_row = QHBoxLayout()
        top_row.addWidget(preview_group, 3)
        top_row.addWidget(units_group, 1)
        main_layout.addLayout(top_row)

        # Config form
        config_group = QGroupBox(tr("Import Settings"))
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
        self._form.addRow(tr("Separator:"), self._sep_combo)

        # Time column
        self._time_col_combo = QComboBox()
        self._form.addRow(tr("Time column:"), self._time_col_combo)

        # Timestamp format
        self._fmt_combo = QComboBox()
        for label, val in _common_formats():
            self._fmt_combo.addItem(label, val)
        self._format_chosen_by_user = False
        self._form.addRow(tr("Format:"), self._fmt_combo)

        # Custom format input
        self._custom_fmt = QLineEdit()
        self._custom_fmt.setPlaceholderText(tr("e.g. %Y-%m-%d %H:%M:%S.%f"))
        self._custom_fmt.setVisible(False)
        self._form.addRow("", self._custom_fmt)
        self._select_format(guessed_fmt)
        self._fmt_combo.currentIndexChanged.connect(self._on_format_changed)
        self._fmt_combo.activated.connect(self._on_format_chosen)
        self._custom_fmt.textChanged.connect(lambda _text: self._refresh_time_check())

        # Time unit: only an elapsed number needs one. An epoch format names
        # its own unit, and offering a second control that silently lost to it
        # (or silently won, for seconds) let the two disagree.
        self._unit_combo = QComboBox()
        for label, val in _TIME_UNITS:
            self._unit_combo.addItem(tr(label), val)
        self._unit_combo.currentIndexChanged.connect(lambda _i: self._refresh_time_check())
        self._form.addRow(tr("Numeric unit:"), self._unit_combo)

        # Timezone: an explicit choice whenever it decides the instant, never
        # a silent UTC (AGENTS trap: 1-2 h "corruption" reports).
        self._tz_combo = QComboBox()
        self._tz_combo.addItem(tr("Choose a time zone…"), "")
        for label, val in _TIMEZONES:
            self._tz_combo.addItem(tr(label), val)
        self._tz_combo.currentIndexChanged.connect(lambda _i: self._refresh_validity())
        self._form.addRow(tr("Timezone:"), self._tz_combo)

        # Anchor date (for time-only formats)
        anchor_row = QHBoxLayout()
        self._anchor_date = QLineEdit()
        self._anchor_date.setPlaceholderText(tr("YYYY-MM-DD (for time-only data)"))
        self._anchor_chk = QCheckBox(tr("Use anchor date"))
        self._anchor_chk.toggled.connect(self._anchor_date.setEnabled)
        self._anchor_date.setEnabled(False)
        anchor_row.addWidget(self._anchor_chk)
        anchor_row.addWidget(self._anchor_date, stretch=1)
        self._form.addRow(tr("Anchor:"), anchor_row)

        # Sentinel → NaN mapping
        sentinel_row = QHBoxLayout()
        self._sentinel_combo = QComboBox()
        for label, val in _sentinel_presets():
            self._sentinel_combo.addItem(label, val)
        self._sentinel_custom = QLineEdit()
        self._sentinel_custom.setPlaceholderText(tr("value to treat as NaN"))
        self._sentinel_custom.setVisible(False)
        self._sentinel_combo.currentIndexChanged.connect(self._on_sentinel_changed)
        sentinel_row.addWidget(self._sentinel_combo)
        sentinel_row.addWidget(self._sentinel_custom)
        self._form.addRow(tr("Sentinel → NaN:"), sentinel_row)

        # Euro decimal (comma as decimal separator)
        self._euro_chk = QCheckBox(tr("European decimals (comma = decimal separator)"))
        self._euro_chk.toggled.connect(lambda _checked: self._refresh_time_check())
        self._form.addRow("", self._euro_chk)

        main_layout.addWidget(config_group)

        # What the preview rows become with these settings, read before Import
        # rather than discovered on the timeline. A 1000x epoch error or a
        # wrong zone is obvious in a date; it is invisible in a raw number.
        self._time_check = QLabel("")
        self._time_check.setWordWrap(True)
        self._time_check.setAccessibleName(tr("How the time column will be read"))
        main_layout.addWidget(self._time_check)

        # What is missing, said in place rather than in a modal on top of a
        # modal. The three "Import Error" message boxes this replaces
        # made the user click OK to get back to the field they had to fix, and
        # said nothing at all until they had already pressed Import.
        self._validation_label = QLabel("")
        self._validation_label.setWordWrap(True)
        self._validation_label.setAccessibleName(tr("Why this file cannot be imported yet"))
        self._validation_label.setVisible(False)
        main_layout.addWidget(self._validation_label)

        # Buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._validate_and_accept)
        btn_box.rejected.connect(self.reject)
        main_layout.addWidget(btn_box)
        self._ok_button = btn_box.button(QDialogButtonBox.StandardButton.Ok)

        # Populate initial preview and column choices
        self._on_separator_changed(0)

        # Re-check whenever any of the three inputs the check reads changes, so
        # the button state is always an answer about the current form.
        self._time_col_combo.currentTextChanged.connect(self._on_time_column_changed)
        self._anchor_chk.toggled.connect(lambda _checked: self._refresh_validity())
        self._anchor_date.textChanged.connect(lambda _text: self._refresh_validity())
        self._fill_units()
        self._refresh_validity()

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
        self._refresh_validity()

    def _on_format_chosen(self, _idx: int) -> None:
        """A format the user picked is theirs; a new time column keeps it."""
        self._format_chosen_by_user = True

    def _on_time_column_changed(self, _text: str) -> None:
        if not self._format_chosen_by_user:
            self._select_format(_guess_format(self._time_values()))
        self._fill_units()
        self._refresh_validity()

    def _time_values(self) -> list[str]:
        """The preview's values in the chosen time column."""
        index = self._time_col_combo.currentIndex()
        if index < 0:
            return []
        return [row[index] for row in self._sample_rows if len(row) > index]

    def _format_value(self) -> str:
        value = str(self._fmt_combo.currentData() or "")
        return self._custom_fmt.text().strip() if value == "custom" else value

    def _fill_units(self) -> None:
        import_wizard_fields.fill_units(self)

    def _units(self) -> dict[str, str]:
        return import_wizard_fields.units(self)

    def _timezone_needed(self) -> bool:
        return needs_timezone(self._format_value(), self._time_values())

    def _refresh_time_check(self) -> None:
        import_wizard_fields.refresh_time_check(self)

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

    def _blocking_reason(self) -> str:
        """Why Import cannot proceed yet, or an empty string when it can.

        One function, read by both the button's enabled state and the message
        beside it, so the two can never disagree about whether the form is
        ready.
        """
        if not self._headers:
            return tr("No columns were detected in this file. Check the separator and encoding.")
        if not self._time_col_combo.currentText():
            return tr("Choose which column holds the timestamps.")
        if self._anchor_chk.isChecked() and not self._anchor_date.text().strip():
            return tr("Enter the anchor date, or turn off “Use anchor date”.")
        if self._timezone_needed() and not self._tz_combo.currentData():
            return tr(
                "Choose the time zone these clock times were written in: "
                "the timestamps do not state one."
            )
        return ""

    def _refresh_validity(self) -> None:
        """Show what is missing, and let Import run only when nothing is."""
        if not hasattr(self, "_validation_label"):
            return
        self._refresh_time_check()
        reason = self._blocking_reason()
        self._validation_label.setText(reason)
        self._validation_label.setVisible(bool(reason))
        if self._ok_button is not None:
            self._ok_button.setEnabled(not reason)

    def _validate_and_accept(self) -> None:
        # Re-checked here as well as on every edit: the button is the ordinary
        # route, but a dialog can also be accepted by Return.
        self._refresh_validity()
        if self._blocking_reason():
            return
        self.accept()

    def config(self) -> dict[str, Any]:
        """Return the import configuration dict for the pipeline."""
        fmt_val = self._format_value()
        # An epoch format names its own unit; say so in the config too, so the
        # loader's unit and the format can never disagree.
        time_unit = str(self._unit_combo.currentData())
        if fmt_val.startswith("epoch_"):
            time_unit = fmt_val.removeprefix("epoch_")

        sentinel = self._sentinel_combo.currentData()
        if sentinel == "custom":
            sentinel = self._sentinel_custom.text().strip()

        # A numeric clock does not depend on a zone; UTC is recorded only so
        # the config always names a concrete one.
        timezone = str(self._tz_combo.currentData() or "") or "UTC"
        if timezone == "local":
            system_id = cast(bytes, QTimeZone.systemTimeZoneId()).decode("utf-8")
            timezone = system_id or "UTC"

        config: dict[str, Any] = {
            "separator": self._sep_combo.currentData(),
            "has_headers": self._has_headers,
            "time_col": self._time_col_combo.currentText(),
            "time_format": fmt_val,
            "time_unit": time_unit,
            "timezone": timezone,
            "anchor_date": self._anchor_date.text().strip() if self._anchor_chk.isChecked() else "",
            "sentinel": sentinel if sentinel else None,
            "euro_decimal": self._euro_chk.isChecked(),
        }
        # Only when one was typed, so an unchanged import keeps its cache key.
        units = self._units()
        if units:
            config["units"] = units
        return config
