"""Tests for ui.source_properties — as_plain_text() roundtrips."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    instance = QApplication.instance() or QApplication([])
    return instance


class TestVideoPropertiesPanel:
    def test_as_plain_text_contains_title(self, app):
        from unittest.mock import MagicMock

        from kinochronix.ui.source_properties import VideoPropertiesPanel

        loader = MagicMock()
        loader._container = "mp4"
        loader._codec = "h264"
        loader._profile = "High"
        loader._pix_fmt = "yuv420p"
        loader._width = 1920
        loader._height = 1080
        loader._fps = 29.97
        loader._frame_count = 1000
        loader._duration = 33.367
        loader._start_time = 1700000000.0
        loader._file_size = 50_000_000

        panel = VideoPropertiesPanel(loader)
        text = panel.as_plain_text()
        assert "Video Properties" in text

    def test_as_plain_text_contains_codec(self, app):
        from unittest.mock import MagicMock

        from kinochronix.ui.source_properties import VideoPropertiesPanel

        loader = MagicMock()
        loader._container = "mov"
        loader._codec = "prores"
        loader._profile = ""
        loader._pix_fmt = "yuv422p10le"
        loader._width = 3840
        loader._height = 2160
        loader._fps = 23.976
        loader._frame_count = None
        loader._duration = 120.0
        loader._start_time = None
        loader._file_size = 0

        panel = VideoPropertiesPanel(loader)
        text = panel.as_plain_text()
        assert "prores" in text

    def test_as_plain_text_resolution(self, app):
        from unittest.mock import MagicMock

        from kinochronix.ui.source_properties import VideoPropertiesPanel

        loader = MagicMock()
        loader._container = "mkv"
        loader._codec = "hevc"
        loader._profile = ""
        loader._pix_fmt = "yuv420p"
        loader._width = 1280
        loader._height = 720
        loader._fps = 60.0
        loader._frame_count = 600
        loader._duration = 10.0
        loader._start_time = None
        loader._file_size = 1_000_000

        panel = VideoPropertiesPanel(loader)
        text = panel.as_plain_text()
        assert "1280" in text
        assert "720" in text


class TestSensorPropertiesPanel:
    def test_as_plain_text_contains_title(self, app):
        from kinochronix.core.inspection import ImportReport, IntegrityFlags, SourceInspection
        from kinochronix.ui.source_properties import SensorPropertiesPanel

        ins = SourceInspection(
            path="/data/sensors.csv",
            loader_id="CSVLoader",
            import_config={},
            import_report=ImportReport(rows_parsed=1000, gap_count=2, nan_count=5),
            integrity_flags=IntegrityFlags(has_gaps=True),
        )
        panel = SensorPropertiesPanel(ins)
        text = panel.as_plain_text()
        assert "Sensor Properties" in text

    def test_as_plain_text_contains_path(self, app):
        from kinochronix.core.inspection import SourceInspection
        from kinochronix.ui.source_properties import SensorPropertiesPanel

        ins = SourceInspection(path="/data/my_sensor.csv", loader_id="CSVLoader")
        panel = SensorPropertiesPanel(ins)
        text = panel.as_plain_text()
        assert "/data/my_sensor.csv" in text

    def test_as_plain_text_contains_loader(self, app):
        from kinochronix.core.inspection import SourceInspection
        from kinochronix.ui.source_properties import SensorPropertiesPanel

        ins = SourceInspection(path="/data/x.csv", loader_id="NeoLoader")
        panel = SensorPropertiesPanel(ins)
        text = panel.as_plain_text()
        assert "NeoLoader" in text

    def test_as_plain_text_has_integrity_line(self, app):
        from kinochronix.core.inspection import IntegrityFlags, SourceInspection
        from kinochronix.ui.source_properties import SensorPropertiesPanel

        ins = SourceInspection(
            path="/x.csv",
            integrity_flags=IntegrityFlags(is_vfr=True),
        )
        panel = SensorPropertiesPanel(ins)
        text = panel.as_plain_text()
        assert "Integrity" in text
