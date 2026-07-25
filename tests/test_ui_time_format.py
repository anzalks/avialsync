"""Tests for ui.time_format — format_time() all three modes."""

from __future__ import annotations

import datetime

from kinochronix.ui.time_format import TimeDisplayMode, format_time


class TestFormatTimeRelative:
    def test_zero(self):
        assert format_time(0.0, TimeDisplayMode.RELATIVE) == "00:00:00.000"

    def test_simple(self):
        assert format_time(90.5, TimeDisplayMode.RELATIVE) == "00:01:30.500"

    def test_hours(self):
        result = format_time(3661.0, TimeDisplayMode.RELATIVE)
        assert result.startswith("01:01:01")

    def test_millisecond_precision(self):
        result = format_time(1.001, TimeDisplayMode.RELATIVE)
        assert "001" in result

    def test_no_epoch_falls_back_to_relative(self):
        result = format_time(60.0, TimeDisplayMode.UTC, t_epoch=0.0)
        assert ":" in result
        assert "UTC" not in result


class TestFormatTimeUTC:
    def _epoch(self) -> float:
        dt = datetime.datetime(2024, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
        return dt.timestamp()

    def test_utc_suffix(self):
        result = format_time(0.0, TimeDisplayMode.UTC, t_epoch=self._epoch())
        assert result.endswith("UTC")

    def test_utc_time_value(self):
        result = format_time(0.0, TimeDisplayMode.UTC, t_epoch=self._epoch())
        assert "12:00:00" in result

    def test_utc_offset(self):
        result = format_time(3600.0, TimeDisplayMode.UTC, t_epoch=self._epoch())
        assert "13:00:00" in result


class TestFormatTimeLocalTOD:
    def _epoch(self) -> float:
        return datetime.datetime(2024, 6, 15, 10, 0, 0, tzinfo=datetime.UTC).timestamp()

    def test_no_utc_suffix(self):
        result = format_time(0.0, TimeDisplayMode.LOCAL_TOD, t_epoch=self._epoch())
        assert "UTC" not in result

    def test_has_colon_separator(self):
        result = format_time(0.0, TimeDisplayMode.LOCAL_TOD, t_epoch=self._epoch())
        assert ":" in result

    def test_milliseconds_present(self):
        result = format_time(1.5, TimeDisplayMode.LOCAL_TOD, t_epoch=self._epoch())
        assert "." in result


class TestFormatTimeEdgeCases:
    def test_fractional_millis(self):
        result = format_time(0.999, TimeDisplayMode.RELATIVE)
        assert "999" in result

    def test_large_t(self):
        result = format_time(86399.0, TimeDisplayMode.RELATIVE)
        assert "23:59:59" in result
