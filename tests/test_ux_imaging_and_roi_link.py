"""Tests for Domain 4: perceptual imaging colormaps, clipping, pixel readouts, and ROI linking."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPointF

from avialsync.core.channel_reader import ChannelKey
from avialsync.core.imaging_display import (
    PERCEPTUAL_COLORMAPS,
    ChannelView,
    ImagingView,
    compose,
)
from avialsync.core.pyramid import PyramidBuilder
from avialsync.core.source import ImagingMetadata, ImagingSource
from avialsync.ui.main_window import MainWindow
from avialsync.ui.roi_linking import extract_roi_token


@pytest.mark.parametrize("cmap", tuple(PERCEPTUAL_COLORMAPS))
def test_perceptual_colormaps_render_monotone_ramp_and_preserve_nan_black(cmap: str) -> None:
    plane = np.array([[np.nan, 0.0, 0.5, 1.0]], dtype=np.float32)
    view = ChannelView(color=cmap, auto_low=0.0, auto_high=1.0)
    out = compose([(plane, view)])
    assert out.shape == (1, 4, 3) and out.dtype == np.uint8
    # NaN pixel stays pure black even when LUT[0] is non-zero (e.g. Viridis dark purple)
    assert out[0, 0].tolist() == [0, 0, 0]
    assert out[0, 1].tolist() == PERCEPTUAL_COLORMAPS[cmap][0].tolist()
    assert out[0, 3].tolist() == PERCEPTUAL_COLORMAPS[cmap][255].tolist()


def test_clipping_overlay_highlights_underflow_and_saturation_and_round_trips() -> None:
    plane = np.array([[np.nan, 0.0, 0.5, 1.0]], dtype=np.float32)
    ch = ChannelView(color="grey", auto_low=0.1, auto_high=0.9)
    unclipped = compose([(plane, ch)], show_clipping=False)
    assert unclipped.ndim == 2

    clipped = compose([(plane, ch)], show_clipping=True)
    assert clipped.shape == (1, 4, 3)
    assert clipped[0, 0].tolist() == [0, 0, 0]  # NaN stays black
    assert clipped[0, 1].tolist() == [0, 170, 255]  # <= low -> cyan underflow
    assert clipped[0, 2].tolist() == [128, 128, 128]  # mid-range stays grey
    assert clipped[0, 3].tolist() == [255, 45, 45]  # >= high -> red saturation

    view = ImagingView(channels=(ChannelView(color="viridis"),), average=3, show_clipping=True)
    restored = ImagingView.from_dict(view.to_dict())
    assert restored == view
    assert restored.fitted(2).show_clipping is True


class _SyntheticRoiSource(ImagingSource):
    """In-memory 2x2 ROI mosaic source for deterministic UI & linking tests."""

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 1.0

    def open(self, path: Path, config: dict) -> ImagingMetadata:
        return ImagingMetadata(
            frame_count=5,
            height=20,
            width=20,
            dtype="float32",
            frame_times=np.arange(5, dtype=np.float64) * 0.1,
            timing_source="synthetic",
            channel_count=1,
            roi_boxes={
                "roi0": (0, 0, 9, 9),
                "roi1": (10, 0, 9, 9),
                "roi2": (0, 10, 9, 9),
                "roi3": (10, 10, 9, 9),
            },
        )

    def read_frame(self, index: int, channel: int = 0) -> np.ndarray:
        plane = np.full((20, 20), np.nan, dtype=np.float32)
        plane[0:9, 0:9] = 10.0 + index
        plane[0:9, 10:19] = 25.5 + index
        plane[10:19, 0:9] = 40.0 + index
        plane[10:19, 10:19] = 80.25 + index
        return plane

    def close(self) -> None:
        pass


def test_live_pixel_readout_and_bidirectional_roi_plot_linking(qtbot, tmp_path: Path) -> None:
    assert extract_roi_token("RoiResponseSeries.roi17") == "roi17"
    assert extract_roi_token("DfOverF_roi_3") == "roi3"
    assert extract_roi_token("wheel_speed") is None

    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1100, 720)
    window.show()

    # Load matching ROI traces into PlotPane
    cache_dir = tmp_path / "roi_traces"
    cache_dir.mkdir(parents=True, exist_ok=True)
    times = np.linspace(0.0, 0.4, 41, dtype=np.float64)
    channels = [f"DfOverF.roi{i}" for i in range(4)]
    for i, ch_name in enumerate(channels):
        PyramidBuilder(cache_dir, ch_name).build_and_save(times, np.sin(times) + i)

    window.clock.set_bounds(0.0, 0.4)
    window.plot_pane.set_timeline_bounds(0.0, 0.4)
    window.plot_pane.set_window_duration(0.4)
    window.plot_pane.load_channels(
        cache_dir,
        channels,
        source_id="session.nwb",
        visibility={"DfOverF.roi3": False},
    )
    window.plot_pane.wait_for_pending_rows()
    window.sidebar.add_sensor(
        "session.nwb",
        channels,
        channel_visibility={"DfOverF.roi3": False},
    )

    # Register synthetic ROI imaging stack
    meta = _SyntheticRoiSource().open(Path("rois.nwb"), {})
    window.imaging_pane.setVisible(True)
    window.imaging_pane.add_source(
        "rois.nwb",
        _SyntheticRoiSource,
        {},
        meta,
        view=ImagingView(channels=(ChannelView(color="viridis"),), show_clipping=True),
    )
    window.imaging_pane.set_cursor(0.0)
    qtbot.waitUntil(lambda: window.imaging_pane._image is not None, timeout=3000)
    qtbot.waitUntil(lambda: len(window.imaging_pane._current_planes) == 1, timeout=3000)

    # 1. Hovering pixel (12, 2) inside roi1 displays exact raw float32 value (25.5) and roi1
    window.imaging_pane._on_pixel_hovered((12, 2))
    text = window.imaging_pane.pixel_label.text()
    assert "(12, 2)" in text
    assert "25.5" in text
    assert "roi1" in text

    # 2. Clicking pixel (12, 12) inside hidden roi3 reveals DfOverF.roi3 in PlotPane
    assert not window.plot_pane.is_channel_visible(ChannelKey("session.nwb", "DfOverF.roi3"))
    window.imaging_pane._on_pixel_clicked(12, 12)
    assert window.plot_pane.is_channel_visible(ChannelKey("session.nwb", "DfOverF.roi3"))
    assert window.imaging_pane.frame_label._roi_highlight is not None
    assert window.imaging_pane.frame_label._roi_label == "roi3"

    # 3. Hovering DfOverF.roi2 in PlotPane updates ImagingFrameView's ROI highlight to roi2
    row_roi2 = next(ch for ch in window.plot_pane.channels if ch.name == "DfOverF.roi2")
    vb_rect = row_roi2.plot_item.vb.sceneBoundingRect()
    window.plot_pane._interactions.on_scene_moved(
        QPointF(vb_rect.center().x(), vb_rect.center().y()),
        window.plot_pane.graphics_layout.scene(),
    )
    assert window.imaging_pane.frame_label._roi_label == "roi2"

    window.plot_pane._interactions.clear_hover()
    assert window.imaging_pane.frame_label._roi_highlight is None

    # 4. VideoSurface pixel_at inspects exact RGB values without blocking
    from PySide6.QtGui import QColor, QImage

    from avialsync.ui.video_pane import VideoSurface

    surface = VideoSurface()
    qtbot.addWidget(surface)
    surface.resize(100, 100)
    surface.set_video_size(10, 10)
    vimg = QImage(10, 10, QImage.Format.Format_RGB888)
    vimg.fill(QColor(12, 34, 56))
    surface._image = vimg
    px_info = surface.pixel_at(QPointF(50.0, 50.0))
    assert px_info is not None
    assert px_info[2] == (12, 34, 56)

    window.imaging_pane.shutdown()
    window.plot_pane.clear_sources()
