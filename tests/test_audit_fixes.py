"""Regression tests for comprehensive audit fixes (markers, plot modes, suspect frames, reset)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core.pyramid import PyramidBuilder
from avialsync.ui import recovery
from avialsync.ui.annotations import AnnotationStore, VideoFrame
from avialsync.ui.app_settings import app_settings
from avialsync.ui.plot_modes import PLOT_MODE_HEATMAP, PLOT_MODE_OVERLAY
from avialsync.ui.plot_overlays import _resolve_region_drag
from avialsync.ui.plot_pane import PlotPane, PlotPresentation


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    store = app_settings()
    store.clear()
    store.sync()
    yield
    store.clear()
    store.sync()


@pytest.fixture(autouse=True)
def isolated_recovery(tmp_path, monkeypatch):
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setattr(recovery, "recovery_dir", lambda: target)
    yield target


def test_clipped_range_marker_drag_preserves_offpage_endpoints() -> None:
    """Dragging one visible handle of a multi-page range marker must not truncate the other."""
    # Page spans [0.0, 10.0], marker spans [2.0, 25.0] -> clipped to (2.0, 10.0)
    master_at = lambda x: float(x)  # noqa: E731
    x_of = lambda t: float(t)  # noqa: E731

    # 1. Drag left handle from 2.0 -> 3.5; right clipped handle remains at 10.0
    s, e = _resolve_region_drag(2.0, 25.0, (2.0, 10.0), (3.5, 10.0), master_at, x_of)
    assert s == pytest.approx(3.5)
    assert e == pytest.approx(25.0)

    # 2. Page spans [10.0, 20.0]: marker [2.0, 15.0] -> clipped to (0.0, 5.0)
    master_at_p2 = lambda x: 10.0 + float(x)  # noqa: E731
    x_of_p2 = lambda t: float(t) - 10.0  # noqa: E731
    s2, e2 = _resolve_region_drag(2.0, 15.0, (0.0, 5.0), (0.0, 7.2), master_at_p2, x_of_p2)
    assert s2 == pytest.approx(2.0)
    assert e2 == pytest.approx(17.2)

    # 3. Full-body drag by +1.25s while clipped shifts both true endpoints
    s3, e3 = _resolve_region_drag(2.0, 25.0, (2.0, 10.0), (3.25, 11.25), master_at, x_of)
    assert s3 == pytest.approx(3.25)
    assert e3 == pytest.approx(26.25)


def test_moving_marker_recomputes_video_frames() -> None:
    """Moving a marker updates its exported VideoFrame records to the new master time."""
    store = AnnotationStore()
    store.frame_resolver = lambda t: [
        VideoFrame(path="/cam0.mp4", frame_index=int(round(t * 30)), media_timestamp=t)
    ]
    marker = store.add_point(
        2.0,
        "flag",
        video_frames=[VideoFrame(path="/cam0.mp4", frame_index=60, media_timestamp=2.0)],
    )
    assert marker.video_frames[0].frame_index == 60

    store.set_span(0, 8.0, None)
    assert marker.t_start == pytest.approx(8.0)
    assert marker.video_frames[0].frame_index == 240
    assert marker.video_frames[0].media_timestamp == pytest.approx(8.0)


def test_plot_mode_canvas_syncs_on_hide_clear_pause_and_annotations(
    qapp: QApplication, qtbot, tmp_path: Path
) -> None:
    """Overlaid and Heatmap modes update immediately when channels hide, clear, or pause."""
    times = np.linspace(0.0, 10.0, 201)
    PyramidBuilder(tmp_path, "ch0").build_and_save(times, np.sin(times))
    PyramidBuilder(tmp_path, "ch1").build_and_save(times, np.cos(times))

    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(900, 500)
    pane.show()
    pane.set_timeline_bounds(0.0, 10.0)
    pane.set_window_duration(10.0)
    store = AnnotationStore()
    pane.set_annotation_store(store)
    store.add_point(3.0, "stim")

    pane.load_channels(tmp_path, ["ch0", "ch1"], source_id=str(tmp_path))
    pane.wait_for_pending_rows()
    pane.set_cursor(2.0, immediate=True)
    qtbot.waitUntil(lambda: pane._last_installed_generation > 0)

    # Switch to Overlaid mode: 2 curves + annotation drawn on _mode_view
    pane.set_view_mode(PLOT_MODE_OVERLAY)
    assert len(pane._mode_view._curves) == 2
    assert any(
        item[0] is pane._mode_view.plot_item for item in pane._interactions._annotation_items
    )

    # Hide ch1 -> Overlaid canvas immediately drops to 1 curve
    pane.set_channel_visible("ch1", False)
    assert len(pane._mode_view._curves) == 1

    # Start playing in Scope, then pause -> curve reveal switches off immediately
    pane._live_presentation = PlotPresentation.SCOPE
    pane.set_playing(True)
    assert pane._mode_view._curves[0]._reveal_enabled is True
    pane.set_playing(False)
    assert pane._mode_view._curves[0]._reveal_enabled is False

    # Switch to Heatmap, then clear_sources -> image_item is cleared immediately
    pane.set_view_mode(PLOT_MODE_HEATMAP)
    assert pane._mode_view._image_item is not None
    pane.clear_sources()
    assert pane._mode_view._image_item is None
    assert pane._mode_view._curves == []
    if isValid(pane):
        pane.close()


def test_plot_pane_deferred_pinned_channels_apply_on_load(
    qapp: QApplication, qtbot, tmp_path: Path
) -> None:
    """Deferred pinned_channels from session restore pin rows automatically once built."""
    times = np.linspace(0.0, 5.0, 51)
    PyramidBuilder(tmp_path, "sig0").build_and_save(times, np.sin(times))
    PyramidBuilder(tmp_path, "sig1").build_and_save(times, np.cos(times))

    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(800, 400)
    pane.show()
    pane.apply_pinned_channels([{"source_id": str(tmp_path), "channel": "sig1"}])
    pane.load_channels(tmp_path, ["sig0", "sig1"], source_id=str(tmp_path))
    pane.wait_for_pending_rows()

    by_name = {ch.name: ch for ch in pane.channels}
    assert by_name["sig1"].pinned is True
    assert by_name["sig1"].pinned_in_layout is True
    assert by_name["sig0"].pinned is False
    if isValid(pane):
        pane.close()
