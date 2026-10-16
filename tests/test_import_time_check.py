"""The import wizard's time-column guesses and its parsed-time check."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from avialsync.ui.import_time_check import (
    ELAPSED_FORMAT,
    guess_format,
    guess_time_column,
    needs_timezone,
    parse_sample_times,
    summarize_times,
    unit_from_header,
)
from avialsync.ui.import_wizard import ImportWizard


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1789000000.5", "epoch_s"),
        ("1789000000500", "epoch_ms"),
        ("1789000000500000", "epoch_us"),
        ("1789000000500000000", "epoch_ns"),
        ("0.001", ELAPSED_FORMAT),
        ("12.5", ELAPSED_FORMAT),
        ("3600000", ELAPSED_FORMAT),
    ],
)
def test_numeric_magnitude_names_the_epoch_unit(value: str, expected: str) -> None:
    """Modern epochs were read one step too fine: seconds as milliseconds."""
    assert guess_format([value]) == expected


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (["frame", "nose_x", "tail_x", "time"], 3),
        (["Voltage", "Strobe", "Timestamp"], 2),
        (["t", "x"], 0),
        (["value", "Time (s)"], 1),
        (["frameTime", "x"], 0),
        (["force", "angle"], 0),
    ],
)
def test_time_column_matches_whole_words(headers: list[str], expected: int) -> None:
    """A substring `t` matched `tail_x` and `Voltage`."""
    assert guess_time_column(headers) == expected


def test_unit_is_read_from_a_trailing_bracket() -> None:
    assert unit_from_header("force (N)") == "N"
    assert unit_from_header("ch0 [mV]") == "mV"
    assert unit_from_header("angle") == ""


def test_timezone_is_needed_only_for_text_without_an_offset() -> None:
    assert not needs_timezone("epoch_s", ["1789000000"])
    assert not needs_timezone(ELAPSED_FORMAT, ["0.0"])
    assert needs_timezone("%Y-%m-%d %H:%M:%S", ["2026-01-15 10:30:00"])
    assert not needs_timezone("%Y-%m-%dT%H:%M:%S", ["2026-01-15T10:30:00+02:00"])
    assert needs_timezone("%H:%M:%S", ["10:30:00"])


def test_summary_states_start_span_and_step() -> None:
    seconds = parse_sample_times(["0.000", "0.001", "0.002"], ELAPSED_FORMAT, "s", "UTC")
    summary = summarize_times(seconds, ELAPSED_FORMAT)

    assert summary is not None
    assert summary.start == "0 s"
    assert summary.rows == 3
    assert summary.step_s == pytest.approx(0.001)


def test_epoch_summary_is_a_date() -> None:
    seconds = parse_sample_times(["1789000000", "1789000001"], "epoch_s", "s", "UTC")
    summary = summarize_times(seconds, "epoch_s")

    assert summary is not None
    assert summary.start.startswith("2026-")


def test_unparseable_rows_give_no_summary() -> None:
    assert parse_sample_times(["abc"], "%H:%M:%S", "s", "UTC") is None


# ── the wizard itself ────────────────────────────────────────────────


def _wizard(tmp_path: Path, text: str) -> ImportWizard:
    path = tmp_path / "rec.csv"
    path.write_text(text, encoding="utf-8")
    return ImportWizard(path, text.encode("utf-8"))


def test_wizard_reads_a_seconds_epoch_as_seconds(qapp: QApplication, qtbot, tmp_path) -> None:
    wizard = _wizard(tmp_path, "timestamp,v\n1789000000.0,1\n1789000000.5,2\n")
    qtbot.addWidget(wizard)

    config = wizard.config()

    assert config["time_format"] == "epoch_s"
    assert config["time_unit"] == "s"
    assert "2026-" in wizard._time_check.text()


def test_wizard_offers_elapsed_time_and_its_unit(qapp: QApplication, qtbot, tmp_path) -> None:
    wizard = _wizard(tmp_path, "time,v\n0.000,1\n0.001,2\n0.002,3\n")
    qtbot.addWidget(wizard)

    assert wizard.config()["time_format"] == ELAPSED_FORMAT
    assert wizard._unit_combo.isEnabled()
    assert wizard._tz_combo.isEnabled() is False
    assert "1000 Hz" in wizard._time_check.text()


def test_epoch_format_fixes_the_unit(qapp: QApplication, qtbot, tmp_path) -> None:
    """Format and Numeric unit could disagree, and one silently won."""
    wizard = _wizard(tmp_path, "time,v\n1789000000500,1\n")
    qtbot.addWidget(wizard)
    wizard._unit_combo.setCurrentIndex(wizard._unit_combo.findData("ns"))

    config = wizard.config()

    assert config["time_format"] == "epoch_ms"
    assert config["time_unit"] == "ms"
    assert wizard._unit_combo.isEnabled() is False


def test_text_times_without_a_zone_ask_for_one(qapp: QApplication, qtbot, tmp_path) -> None:
    """Never a silent UTC for clock text that does not state its zone."""
    wizard = _wizard(tmp_path, "time,v\n2026-01-15 10:30:00,1\n2026-01-15 10:30:01,2\n")
    qtbot.addWidget(wizard)

    assert wizard._ok_button.isEnabled() is False
    assert "time zone" in wizard._validation_label.text().lower()

    wizard._tz_combo.setCurrentIndex(wizard._tz_combo.findData("Europe/Berlin"))

    assert wizard._ok_button.isEnabled() is True
    assert wizard.config()["timezone"] == "Europe/Berlin"


def test_no_sentinel_is_converted_unless_asked(qapp: QApplication, qtbot, tmp_path) -> None:
    wizard = _wizard(tmp_path, "time,v\n0,1\n")
    qtbot.addWidget(wizard)

    assert wizard.config()["sentinel"] is None


def test_units_come_from_headers_and_reach_the_config(qapp: QApplication, qtbot, tmp_path) -> None:
    wizard = _wizard(tmp_path, "time,force (N),angle\n0,1,2\n")
    qtbot.addWidget(wizard)
    wizard._units_table.item(1, 1).setText("deg")

    assert wizard.config()["units"] == {"force (N)": "N", "angle": "deg"}


def test_a_new_time_column_reguesses_the_format(qapp: QApplication, qtbot, tmp_path) -> None:
    wizard = _wizard(tmp_path, "frame,unix\n0,1789000000\n1,1789000001\n")
    qtbot.addWidget(wizard)
    assert wizard.config()["time_col"] == "unix"
    assert wizard.config()["time_format"] == "epoch_s"

    wizard._time_col_combo.setCurrentIndex(0)

    assert wizard.config()["time_format"] == ELAPSED_FORMAT
