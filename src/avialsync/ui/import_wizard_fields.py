"""The import wizard's channel-units table and its parsed-time check line.

Split from `import_wizard` to keep that module within its size budget; these
are the parts that read the whole form rather than one control.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from PySide6.QtCore import Qt, QTimeZone
from PySide6.QtWidgets import QGroupBox, QHeaderView, QTableWidgetItem, QVBoxLayout

from avialsync.ui.i18n import tr
from avialsync.ui.import_time_check import (
    ELAPSED_FORMAT,
    format_category,
    parse_sample_times,
    summarize_times,
    unit_from_header,
)
from avialsync.ui.tables import ThemedTable

if TYPE_CHECKING:
    from avialsync.ui.import_wizard import ImportWizard


def build_units_group(wizard: ImportWizard) -> QGroupBox:
    """The editable channel-to-unit table beside the preview."""
    # Units belong to the channels, so they sit beside the columns they
    # describe. A header such as `force (N)` fills its own; the plot
    # gutter and Values panel read them through `import_config["units"]`.
    units_group = QGroupBox(tr("Channel units"))
    units_layout = QVBoxLayout(units_group)
    wizard._units_table = ThemedTable()
    wizard._units_table.setColumnCount(2)
    wizard._units_table.setHorizontalHeaderLabels([tr("Channel"), tr("Unit")])
    wizard._units_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    wizard._units_table.verticalHeader().setVisible(False)
    wizard._units_table.setAccessibleName(tr("Channel units"))
    wizard._units_table.setAccessibleDescription(
        tr("Type the unit each channel was recorded in, for example mV or N.")
    )
    units_layout.addWidget(wizard._units_table)
    return units_group


def fill_units(wizard: ImportWizard) -> None:
    """One row per channel, keeping any unit the user already typed."""
    typed = units(wizard)
    time_col = wizard._time_col_combo.currentText()
    channels = [h.strip() for h in wizard._headers if h.strip() and h.strip() != time_col]
    wizard._units_table.setRowCount(len(channels))
    for row, name in enumerate(channels):
        item = QTableWidgetItem(name)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        wizard._units_table.setItem(row, 0, item)
        wizard._units_table.setItem(
            row, 1, QTableWidgetItem(typed.get(name, unit_from_header(name)))
        )


def units(wizard: ImportWizard) -> dict[str, str]:
    """Channel -> unit for every row with a unit filled in."""
    units: dict[str, str] = {}
    table = getattr(wizard, "_units_table", None)
    if table is None:
        return units
    for row in range(table.rowCount()):
        name, unit = table.item(row, 0), table.item(row, 1)
        if name is not None and unit is not None and unit.text().strip():
            units[name.text()] = unit.text().strip()
    return units


def refresh_time_check(wizard: ImportWizard) -> None:
    """Say what the preview rows will become, or that they will not parse."""
    if not hasattr(wizard, "_time_check"):
        return
    fmt = wizard._format_value()
    numeric = format_category(fmt) == "numeric"
    elapsed = fmt in ("", ELAPSED_FORMAT)
    wizard._unit_combo.setEnabled(numeric and elapsed)
    wizard._unit_combo.setToolTip(
        tr("The unit an elapsed-time number counts in.")
        if numeric and elapsed
        else tr("Set by the format: an epoch format names its unit.")
        if numeric
        else tr("Not used: text timestamps carry their own units.")
    )
    needed = wizard._timezone_needed()
    wizard._tz_combo.setEnabled(needed)
    wizard._tz_combo.setToolTip(
        tr("The zone these clock times were written in.")
        if needed
        else tr("Not used: these timestamps already fix the instant.")
    )
    values = wizard._time_values()
    if not values:
        wizard._time_check.setText("")
        return
    zone = str(wizard._tz_combo.currentData() or "") or "UTC"
    if zone == "local":
        zone = cast(bytes, QTimeZone.systemTimeZoneId()).decode("utf-8") or "UTC"
    summary = summarize_times(
        parse_sample_times(
            values,
            fmt,
            str(wizard._unit_combo.currentData()),
            zone,
            euro_decimal=wizard._euro_chk.isChecked(),
            anchor_date=(
                wizard._anchor_date.text().strip() if wizard._anchor_chk.isChecked() else ""
            ),
        ),
        fmt,
    )
    if summary is None:
        wizard._time_check.setText(
            tr("The time column does not parse with this format; check Format.")
        )
        return
    rate = 1.0 / summary.step_s if summary.step_s > 0 else 0.0
    text = tr("Reads as: starts {start} · {rows} rows span {span} s · step {step} ms").format(
        start=summary.start,
        rows=summary.rows,
        span=f"{summary.span_s:.6g}",
        step=f"{summary.step_s * 1e3:.6g}",
    )
    if rate:
        text += " " + tr("({rate} Hz)").format(rate=f"{rate:.6g}")
    wizard._time_check.setText(text)
