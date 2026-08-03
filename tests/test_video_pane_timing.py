"""Timestamp-derived video readout tests."""

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from avialsync.core.source import VideoMetadata
from avialsync.core.timeline import TimeMap
from avialsync.ui.video_pane import PaintCanvas
from avialsync.ui.video_timing import (
    VideoTimingMixin,
    adjacent_frame_time,
    displayed_frame_rate,
    format_video_osd,
    frame_index_at,
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


def test_osd_frame_number_comes_from_the_decoded_timestamps() -> None:
    """The overlay frame must be the decoded one, matching exported annotations."""

    class _Harness(VideoTimingMixin):
        def _apply_rate(self) -> None:
            pass

    timing = _Harness()
    timing._frame_times = np.array([0.0, 0.033, 0.100])
    timing._nominal_fps = 30.0
    timing._decoder_fps = 0.0

    assert timing._source_frame(0.050) == (1, 3)
    assert format_video_osd(0.05, 30.0, VideoMetadata(), timing._source_frame(0.05)).splitlines()[
        1
    ] == ("Frame: 1 / 2")


def test_frame_lookup_survives_the_frame_table_being_rounded_to_microseconds() -> None:
    """ffprobe rounds pts_time to 6 decimals; libmpv does not.

    A frame's own decoder timestamp can land just below its own table entry, so
    a strict search named the previous frame and a forward step returned the
    frame already on screen — arrow keys that did nothing.
    """
    table = np.round(np.arange(300) / 30.0, 6)  # what ffprobe emits
    for k in (1, 2, 5, 150, 298):
        decoder_time = k / 30.0  # what libmpv reports for that same frame

        assert frame_index_at(table, decoder_time) == k
        assert adjacent_frame_time(table, decoder_time, 1) == table[k + 1]
        assert adjacent_frame_time(table, decoder_time, -1) == table[k - 1]


def test_osd_frame_number_is_withheld_when_no_rate_is_known() -> None:
    """A guessed frame number would be indistinguishable from a measured one."""

    class _Harness(VideoTimingMixin):
        def _apply_rate(self) -> None:
            pass

    timing = _Harness()
    timing._frame_times = None
    timing._nominal_fps = 0.0
    timing._decoder_fps = 0.0

    assert timing._source_frame(12.5) is None
    assert "Frame: —" in format_video_osd(12.5, 0.0, VideoMetadata(), None)


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


# ── Overlay point labels (AOL 2D pose) ────────────────────────────────


class _FixedReader:
    """A pose reader that always reports the same coordinate."""

    def __init__(self, value: float) -> None:
        self._value = value

    def value_at(self, _t: float) -> float:
        return self._value


def _one_track():
    from avialsync.ui.video_overlay import OverlayTrack

    return OverlayTrack(
        label="eks",
        points={
            "nose": (_FixedReader(40.0), _FixedReader(50.0)),
            "left_toe": (_FixedReader(120.0), _FixedReader(150.0)),
        },
    )


def _draw_and_capture_text(canvas, track) -> list[str]:
    """Draw one track onto an off-screen image, recording every string written."""
    from PySide6.QtGui import QImage, QPainter

    written: list[str] = []
    original = QPainter.drawText

    def record(self, *args):
        if args and isinstance(args[-1], str):
            written.append(args[-1])
        return original(self, *args)

    image = QImage(320, 240, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    QPainter.drawText = record
    try:
        canvas._draw_track(painter, track, scale=1.0, offset_x=0.0, offset_y=0.0)
    finally:
        QPainter.drawText = original
        painter.end()
    return written


def test_overlay_names_each_tracked_point(qapp: QApplication) -> None:
    """A bare dot says something was tracked, not which body part it is."""
    from avialsync.ui.video_overlay import PaintCanvas

    canvas = PaintCanvas()

    written = _draw_and_capture_text(canvas, _one_track())

    assert "nose" in written
    assert "left_toe" in written


def test_overlay_point_labels_can_be_hidden(qapp: QApplication) -> None:
    from avialsync.ui.video_overlay import PaintCanvas

    canvas = PaintCanvas()
    canvas.set_point_labels_visible(False)

    written = _draw_and_capture_text(canvas, _one_track())

    assert written == []


def test_overlay_draws_each_label_twice_for_legibility(qapp: QApplication) -> None:
    """An outline pass sits under the coloured text so it survives pale footage."""
    from avialsync.ui.video_overlay import PaintCanvas

    canvas = PaintCanvas()

    written = _draw_and_capture_text(canvas, _one_track())

    assert written.count("nose") == 2
    assert written.count("left_toe") == 2


def test_overlay_skips_labels_for_points_with_no_coordinate(qapp: QApplication) -> None:
    """An untracked frame must not leave a floating name at the origin."""
    import numpy as np

    from avialsync.ui.video_overlay import OverlayTrack, PaintCanvas

    track = OverlayTrack(
        label="eks",
        points={"nose": (_FixedReader(np.nan), _FixedReader(np.nan))},
    )

    written = _draw_and_capture_text(PaintCanvas(), track)

    assert written == []
