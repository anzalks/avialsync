"""One decimal-separator policy (D-173, INTERFACE_DESIGN_PLAN DS-10)."""

from __future__ import annotations

import pyqtgraph as pg
import pytest
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QDoubleSpinBox

from avialsync.ui.readout_panel import _ChannelReadout
from avialsync.ui.time_format import apply_number_locale, format_number, number_locale


@pytest.fixture
def comma_system_locale():
    """A decimal-comma operating system, as on the machine F-30 was seen on."""
    QLocale.setDefault(QLocale(QLocale.Language.German, QLocale.Country.Germany))
    yield
    apply_number_locale()


def test_spin_box_axis_and_readout_share_one_separator(comma_system_locale, qtbot) -> None:
    assert QLocale().decimalPoint() == ","
    apply_number_locale()
    spin = QDoubleSpinBox()
    qtbot.addWidget(spin)
    spin.setDecimals(6)
    spin.setRange(-1e6, 1e6)
    spin.setValue(1234.5)
    assert spin.text() == "1234.500000"
    assert spin.valueFromText("0.25") == pytest.approx(0.25)

    axis = pg.AxisItem("bottom")
    assert axis.tickStrings([0.5, 1.5], 1.0, 0.5) == ["0.5", "1.5"]
    assert format_number(1234.5, 2) == "1234.50"
    row = _ChannelReadout("signal", "mV")
    qtbot.addWidget(row)
    row.set_value(1.25)
    assert row._val_lbl.text() == "1.25 mV"


def test_the_number_locale_never_groups_digits() -> None:
    assert number_locale().toString(1234567.25, "f", 2) == "1234567.25"
    assert number_locale().decimalPoint() == "."
