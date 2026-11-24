"""Regression tests for source file sizes, gapped rate metadata, and narrow transport layout."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStyle, QStyleOptionSlider

from avialsync.core.registry import LoaderRegistry
from avialsync.core.source import source_size_bytes
from avialsync.loaders.aol_camera_join import AOLJoinedCameraSource
from avialsync.loaders.aol_microscope_session import AOLMicroscopeTrialSource
from avialsync.loaders.nwb_format import SeriesInfo
from avialsync.loaders.nwb_imaging import NWBImagingSource
from avialsync.ui.elided_label import ElidedLabel
from avialsync.ui.imaging_pane import ImagingPane
from avialsync.ui.plot_pane import PlotPane
from avialsync.ui.transport import Transport
from avialsync.ui.video_timing import instantaneous_frame_rate
from tests.test_aol_camera_join import _camera, _experiment


def test_source_size_bytes_handles_files_directories_containers_and_urls(tmp_path: Path) -> None:
    assert source_size_bytes(None) == 0
    assert source_size_bytes("https://dandiarchive.org/nwb/sample.nwb") == 0
    assert source_size_bytes(tmp_path / "missing.mp4") == 0

    link = tmp_path / "remote.nwb-link"
    link.write_text('{"url": "https://api.dandiarchive.org/api/assets/123/download/"}')
    assert source_size_bytes(link) == 0
    assert source_size_bytes(link / "acquisition" / "TwoPhotonSeries") == 0

    single = tmp_path / "session.nwb"
    single.write_bytes(b"x" * 2048)
    assert source_size_bytes(single) == 2048
    assert source_size_bytes(single / "acquisition" / "TwoPhotonSeries") == 2048

    zarr_dir = tmp_path / "recording.nwb.zarr"
    (zarr_dir / ".zgroup").parent.mkdir(parents=True)
    (zarr_dir / ".zgroup").write_bytes(b"{}")
    sub = zarr_dir / "acquisition" / "Series"
    sub.mkdir(parents=True)
    chunk = sub / "0.0.0"
    chunk.write_bytes(b"a" * 4096)
    hardlink = sub / "0.0.1"
    os.link(chunk, hardlink)

    expected_dir_bytes = 2 + 4096
    assert source_size_bytes(zarr_dir) == expected_dir_bytes
    assert source_size_bytes(zarr_dir / "acquisition" / "Series") == 4096
    assert source_size_bytes(zarr_dir / "acquisition" / "VirtualSeries") == expected_dir_bytes


def test_joined_trial_camera_reports_segment_bytes_and_excludes_inter_trial_gaps(
    tmp_path: Path,
) -> None:
    experiment, first, second = _experiment(tmp_path)
    cam1 = _camera(first, "FaceCam", 5, 10.0, 40)
    cam2 = _camera(second, "FaceCam", 5, 10.0, 140)
    layout = AOLMicroscopeTrialSource().scan(experiment, LoaderRegistry(plugin_dirs=[]))
    item = next(entry for entry in layout.items if entry.loader is AOLJoinedCameraSource)

    loader = AOLJoinedCameraSource()
    loader.open(item.path, dict(item.config))
    manifest = loader.prepare(lambda _fraction: None)
    assert manifest.name == "joined.segments.json"

    metadata = loader.video_metadata()
    expected_bytes = cam1.stat().st_size + cam2.stat().st_size
    assert metadata.file_size_bytes == expected_bytes
    assert metadata.file_size_bytes > manifest.stat().st_size
    assert metadata.is_vfr is False
    assert metadata.nominal_fps == pytest.approx(100.0)
    assert metadata.measured_fps == pytest.approx(100.0)
    assert metadata.min_frame_rate == pytest.approx(100.0)
    assert metadata.max_frame_rate == pytest.approx(100.0)

    # Instantaneous rate at the last frame before the 600 s inter-trial break
    # must reflect the trial's exposure interval, not 1 / 600 s = 0.0017 fps.
    frame_times = loader.frame_times()
    assert frame_times is not None
    assert instantaneous_frame_rate(frame_times, float(frame_times[2]), 100.0) == pytest.approx(
        100.0, rel=1e-2
    )
    assert instantaneous_frame_rate(np.array([0.0, 600.0]), 0.0, 100.0) == pytest.approx(100.0)


def test_nwb_imaging_video_metadata_handles_zarr_dir_remote_url_and_epoch_gaps(
    tmp_path: Path,
) -> None:
    zarr_dir = tmp_path / "imaging.nwb.zarr"
    zarr_dir.mkdir()
    (zarr_dir / "zarr.json").write_bytes(b"{}")
    (zarr_dir / "chunk0").write_bytes(b"z" * 8192)

    source = NWBImagingSource()
    source._path = zarr_dir
    source._info = SeriesInfo(
        path="/acquisition/TwoPhoton",
        name="TwoPhoton",
        neurodata_type="TwoPhotonSeries",
        kind="imaging",
        unit="n.a.",
        length=7,
        columns=(),
        rate=30.0,
        start=0.0,
        has_timestamps=True,
        frame_shape=(64, 80),
        dtype="uint16",
    )
    source._frame_times = np.array(
        [0.0, 1 / 30, 2 / 30, 3 / 30, 120.0, 120.0 + 1 / 30, 120.0 + 2 / 30],
        dtype=np.float64,
    )
    meta = source.video_metadata()
    assert meta.file_size_bytes == 2 + 8192
    assert meta.is_vfr is False
    assert meta.measured_fps == pytest.approx(30.0)
    assert meta.min_frame_rate == pytest.approx(30.0)

    link = tmp_path / "stream.nwb-link"
    link.write_text('{"url": "https://api.dandiarchive.org/api/assets/123/download/"}')
    source._path = link
    assert source.video_metadata().file_size_bytes == 0


def _expected_pin_x(transport: Transport, frac: float) -> int:
    opt = QStyleOptionSlider()
    transport.slider.initStyleOption(opt)
    groove = transport.slider.style().subControlRect(
        QStyle.ComplexControl.CC_Slider,
        opt,
        QStyle.SubControl.SC_SliderGroove,
        transport.slider,
    )
    g_global = transport.slider.mapToParent(groove.topLeft())
    return g_global.x() + int(frac * groove.width()) - 1


def test_transport_switches_cleanly_to_two_rows_without_overlap_at_narrow_width(qtbot) -> None:
    transport = Transport()
    qtbot.addWidget(transport)
    transport.detach_data_streams()
    transport.set_bounds(0.0, 600.0)
    transport.set_time(150.0)
    transport.ab_in()
    transport.set_time(450.0)
    transport.ab_out()

    transport.resize(500, 96)
    transport.show()
    qtbot.waitExposed(transport)
    qtbot.wait(20)

    assert transport._compact_timeline is True
    assert transport.slider.width() >= 200
    assert transport._time_edit.width() >= 110
    assert transport._end_time_label.width() >= 110
    assert transport.rate_combo.width() >= transport.rate_combo.minimumSizeHint().width()

    controls = [
        transport._time_edit,
        transport.slider,
        transport._end_time_label,
        *transport._playhead_buttons,
        *transport._loop_rate_controls,
    ]
    for idx, left in enumerate(controls):
        for right in controls[idx + 1 :]:
            assert not left.geometry().intersects(right.geometry()), (
                f"{left.accessibleName() or left.objectName()} overlaps "
                f"{right.accessibleName() or right.objectName()} at 500 px"
            )
    assert transport._pin_in.geometry().x() == _expected_pin_x(transport, 0.25)
    assert transport._pin_out.geometry().x() == _expected_pin_x(transport, 0.75)

    # Widening back restores single-row layout and keeps pins aligned.
    transport.resize(1000, 96)
    qtbot.wait(20)
    assert transport._compact_timeline is False
    assert transport._pin_in.geometry().x() == _expected_pin_x(transport, 0.25)
    assert transport._pin_out.geometry().x() == _expected_pin_x(transport, 0.75)


def test_plot_sweep_slider_and_imaging_status_keep_usable_narrow_presentation(qtbot) -> None:
    plot_pane = PlotPane()
    qtbot.addWidget(plot_pane)
    plot_pane.resize(500, 320)
    plot_pane.show()
    qtbot.waitExposed(plot_pane)
    assert plot_pane._sweep_control.slider.width() >= 84

    imaging = ImagingPane()
    qtbot.addWidget(imaging)
    imaging.resize(260, 360)
    imaging.show()
    qtbot.waitExposed(imaging)
    assert isinstance(imaging.status_label, ElidedLabel)
    full = "00:11:19.879 · f 2378 / 5342 · 480×408 · 32-bit float · 30.0 fps"
    imaging.status_label.setText(full)
    assert imaging.status_label.text() == full
    assert imaging.status_label.toolTip() == full
    assert imaging.status_label._mode == Qt.TextElideMode.ElideRight


def test_status_line_clears_transient_qstatusbar_message_to_prevent_double_painting(qtbot) -> None:
    from PySide6.QtWidgets import QStatusBar

    bar = QStatusBar()
    qtbot.addWidget(bar)
    transport = Transport()
    qtbot.addWidget(transport)
    bar.addWidget(transport.status_line, 1)
    bar.show()
    qtbot.waitExposed(bar)

    bar.showMessage("Compare raw model predictions against accepted identity swaps")
    assert bar.currentMessage() != ""
    transport.set_status("Ready")
    assert bar.currentMessage() == ""
    assert transport.status_line.isVisible()
