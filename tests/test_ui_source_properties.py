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
        from avialview.core.source import VideoMetadata
        from avialview.ui.source_properties import VideoPropertiesPanel

        class Loader:
            def video_metadata(self) -> VideoMetadata:
                return VideoMetadata(
                    container="mp4",
                    codec="h264",
                    profile="High",
                    pixel_format="yuv420p",
                    width=1920,
                    height=1080,
                    nominal_fps=29.97,
                    measured_fps=29.97,
                    frame_count=1000,
                    duration=33.367,
                    start_time=1700000000.0,
                    file_size_bytes=50_000_000,
                )

        panel = VideoPropertiesPanel(Loader())
        text = panel.as_plain_text()
        assert "Video Properties" in text

    def test_as_plain_text_contains_codec(self, app):
        from avialview.core.source import VideoMetadata
        from avialview.ui.source_properties import VideoPropertiesPanel

        class Loader:
            def video_metadata(self) -> VideoMetadata:
                return VideoMetadata(
                    container="mov",
                    codec="prores",
                    pixel_format="yuv422p10le",
                    width=3840,
                    height=2160,
                    nominal_fps=23.976,
                    measured_fps=23.976,
                    duration=120.0,
                )

        panel = VideoPropertiesPanel(Loader())
        text = panel.as_plain_text()
        assert "prores" in text

    def test_as_plain_text_resolution(self, app):
        from avialview.core.source import VideoMetadata
        from avialview.ui.source_properties import VideoPropertiesPanel

        class Loader:
            def video_metadata(self) -> VideoMetadata:
                return VideoMetadata(
                    container="mkv",
                    codec="hevc",
                    pixel_format="yuv420p",
                    width=1280,
                    height=720,
                    nominal_fps=60.0,
                    measured_fps=60.0,
                    frame_count=600,
                    duration=10.0,
                    file_size_bytes=1_000_000,
                )

        panel = VideoPropertiesPanel(Loader())
        text = panel.as_plain_text()
        assert "1280" in text
        assert "720" in text

    def test_vfr_rates_are_timestamp_derived(self, app):
        from avialview.core.source import VideoMetadata
        from avialview.ui.source_properties import VideoPropertiesPanel

        class Loader:
            def video_metadata(self) -> VideoMetadata:
                return VideoMetadata(
                    codec="h264",
                    nominal_fps=30.0,
                    measured_fps=24.0,
                    min_frame_rate=15.0,
                    max_frame_rate=30.0,
                    is_vfr=True,
                )

        text = VideoPropertiesPanel(Loader()).as_plain_text()

        assert "VFR" in text
        assert "15.000–30.000" in text
        assert "30.000 fps" in text


class TestSensorPropertiesPanel:
    def test_as_plain_text_contains_title(self, app):
        from avialview.core.inspection import ImportReport, IntegrityFlags, SourceInspection
        from avialview.ui.source_properties import SensorPropertiesPanel

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
        from avialview.core.inspection import SourceInspection
        from avialview.ui.source_properties import SensorPropertiesPanel

        ins = SourceInspection(path="/data/my_sensor.csv", loader_id="CSVLoader")
        panel = SensorPropertiesPanel(ins)
        text = panel.as_plain_text()
        assert "/data/my_sensor.csv" in text

    def test_as_plain_text_contains_loader(self, app):
        from avialview.core.inspection import SourceInspection
        from avialview.ui.source_properties import SensorPropertiesPanel

        ins = SourceInspection(path="/data/x.csv", loader_id="NeoLoader")
        panel = SensorPropertiesPanel(ins)
        text = panel.as_plain_text()
        assert "NeoLoader" in text

    def test_as_plain_text_has_integrity_line(self, app):
        from avialview.core.inspection import IntegrityFlags, SourceInspection
        from avialview.ui.source_properties import SensorPropertiesPanel

        ins = SourceInspection(
            path="/x.csv",
            integrity_flags=IntegrityFlags(is_vfr=True),
        )
        panel = SensorPropertiesPanel(ins)
        text = panel.as_plain_text()
        assert "Integrity" in text
