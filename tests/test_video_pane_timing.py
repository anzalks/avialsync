"""Timestamp-derived video readout tests."""

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from avialview.core.source import VideoMetadata
from avialview.core.timeline import TimeMap
from avialview.ui.video_pane import PaintCanvas
from avialview.ui.video_timing import (
    VideoTimingMixin,
    displayed_frame_rate,
    format_video_osd,
    instantaneous_frame_rate,
)


def test_vfr_readout_reports_the_current_frame_interval() -> None:
    """VFR readout must not collapse variable intervals into one average FPS."""
    frame_times = np.array([0.0, 1 / 30, 2 / 30, 4 / 30])

    assert instantaneous_frame_rate(frame_times, 0.04, 0.0) == pytest.approx(30.0)
    assert instantaneous_frame_rate(frame_times, 0.08, 0.0) == pytest.approx(15.0)


def test_cfr_readout_stays_at_the_nominal_rate() -> None:
    """CFR video must not fluctuate because an observer fires between frames."""
    frame_times = np.array([0.0, 1 / 30, 2 / 30, 3 / 30])

    assert displayed_frame_rate(frame_times, 0.048, False, 30.0, 58.0) == 30.0


def test_vfr_osd_shows_timestamp_range_nominal_rate_codec_and_size() -> None:
    metadata = VideoMetadata(
        codec="h264",
        nominal_fps=30.0,
        measured_fps=24.0,
        min_frame_rate=15.0,
        max_frame_rate=30.0,
        is_vfr=True,
        file_size_bytes=52_428_800,
    )

    text = format_video_osd(1.25, 15.0, metadata)

    assert "Time: 00:00:01.250" in text
    assert "VFR: 15.0–30.0 fps · now 15.0" in text
    assert "Nominal CFR: 30.0 fps" in text
    assert "Codec: H264 · Size: 50.0 MB" in text


def test_cfr_osd_shows_measured_timestamp_rate() -> None:
    metadata = VideoMetadata(
        codec="hevc",
        nominal_fps=29.97,
        measured_fps=29.969,
        is_vfr=False,
        file_size_bytes=1_500,
    )

    text = format_video_osd(0.0, 29.97, metadata)

    assert "CFR: 29.970 fps · measured 29.969" in text
    assert "Codec: HEVC · Size: 1.5 KB" in text


def test_exact_seek_settles_only_after_state_and_target_evidence() -> None:
    class _Harness(VideoTimingMixin):
        def _apply_rate(self) -> None:
            pass

    timing = _Harness()
    timing._frame_times = np.array([0.0, 1 / 30, 2 / 30])
    timing._seek_pending = True
    timing._seek_exact = True
    timing._seek_target = 1 / 30
    timing._mpv_seeking = True
    timing.is_seeking = True
    timing.time_pos = 0.0

    timing._observe_seeking(False)
    assert timing.is_seeking is True

    timing.time_pos = 1 / 30
    timing._maybe_finish_seek()
    assert timing.is_seeking is False


def test_frame_step_and_annotation_use_real_exact_mapping_timestamps() -> None:
    class _Harness(VideoTimingMixin):
        def _apply_rate(self) -> None:
            pass

    timing = _Harness()
    timing._frame_times = np.array([0.0, 0.033, 0.100])
    timing._nominal_fps = 30.0
    timing._decoder_fps = 0.0
    timing.time_map = TimeMap()
    timing.time_map.set_exact_mapping(
        np.array([10.0, 10.1, 10.3]),
        timing._frame_times,
    )

    assert timing.frame_step_master_target(10.1, 1) == pytest.approx(10.3)
    assert timing.frame_step_master_target(10.3, -1) == pytest.approx(10.1)
    assert timing.frame_record_at(10.25) == (1, pytest.approx(0.033))


def test_tracking_overlay_is_visually_transparent(qapp: QApplication) -> None:
    """An idle tracking layer must not cover the native mpv child surface."""
    canvas = PaintCanvas()

    assert canvas.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert canvas.testAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
    assert not canvas.autoFillBackground()
