"""Clock drift is time gained per hour; rates read at one decimal (D-184, D-185)."""

from __future__ import annotations

import pytest

from avialsync.core.drift import (
    LEGACY_DRIFT_KEY,
    MS_PER_HOUR,
    describe_drift,
    drift_from_legacy_entry,
    drift_from_rate,
    rate_from_drift,
)
from avialsync.core.timeline import TimeMap
from avialsync.ui.drift_spin import DriftSpinBox
from avialsync.ui.time_format import format_rate


def test_a_drift_is_the_time_a_clock_gains_each_hour() -> None:
    mapping = TimeMap(offset=0.0, drift_ms_per_hour=54.0)
    assert mapping.to_source(3600.0) - 3600.0 == pytest.approx(0.054, abs=1e-12)
    assert rate_from_drift(54.0) == pytest.approx(54.0 / MS_PER_HOUR)
    assert drift_from_rate(rate_from_drift(54.0)) == pytest.approx(54.0)


@pytest.mark.parametrize(
    ("drift", "text"),
    [
        (0.0, "0 ms/h"),
        (54.0, "+54.0 ms/h"),
        (-7.25, "-7.2 ms/h"),
        (0.36, "+0.36 ms/h"),
        (3600.0, "+3.6 s/h"),
    ],
)
def test_drift_reads_as_time_per_hour(drift: float, text: str) -> None:
    assert describe_drift(drift) == text


def test_drift_also_reads_in_frames_when_the_rate_is_known() -> None:
    assert describe_drift(54.0, sample_rate_hz=30.0, samples="frames") == (
        "+54.0 ms/h (≈1.6 frames/h)"
    )


def test_an_older_session_drift_is_converted_once_on_read() -> None:
    assert drift_from_legacy_entry({"drift_ms_per_hour": 54.0}) == 54.0
    assert drift_from_legacy_entry({LEGACY_DRIFT_KEY: 15.0}) == pytest.approx(54.0)
    assert drift_from_legacy_entry({}) == 0.0


def test_the_drift_field_holds_what_it_shows(qtbot) -> None:
    spin = DriftSpinBox()
    qtbot.addWidget(spin)
    spin.setValue(54.0)
    assert spin.value() == 54.0
    assert spin.suffix() == " ms/h"
    assert spin.text() == "54.00 ms/h"


@pytest.mark.parametrize(
    ("rate", "text"),
    [(30.0, "30.0"), (29.97, "29.97"), (59.94, "59.94"), (230.0, "230.0"), (24.0, "24.0")],
)
def test_rates_read_at_one_decimal_unless_the_second_matters(rate: float, text: str) -> None:
    assert format_rate(rate) == text
