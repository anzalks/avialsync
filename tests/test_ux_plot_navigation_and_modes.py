"""Tests for Domain 2: direct plot navigation, crosshairs, measure callouts, pins, and modes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent

from avialsync.core.channel_reader import ChannelKey
from avialsync.core.pyramid import PyramidBuilder
from avialsync.ui.plot_crosshair import format_measure_delta
from avialsync.ui.plot_modes import PLOT_MODE_HEATMAP, PLOT_MODE_OVERLAY, PLOT_MODE_STACKED
from avialsync.ui.plot_pane import PlotPane


def _build_sensor_cache(tmp_path: Path) -> Path:
    cache_dir = tmp_path / "sensor_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    times = np.linspace(0.0, 20.0, 2001, dtype=np.float64)
    for idx, name in enumerate(("ttl_sync", "lfp_ch0", "lfp_ch1", "wheel_vel")):
        vals = np.sin(times * (idx + 1)) * (10.0 * (idx + 1)) + idx * 5.0
        PyramidBuilder(cache_dir, name).build_and_save(times, vals)
    return cache_dir


def _load_ready_pane(qtbot, tmp_path: Path) -> tuple[PlotPane, Path]:
    cache_dir = _build_sensor_cache(tmp_path)
    pane = PlotPane()
    qtbot.addWidget(pane)
    pane.resize(800, 480)
    pane.show()
    pane.set_timeline_bounds(0.0, 20.0)
    pane.set_window_duration(10.0)
    pane.load_channels(
        cache_dir,
        ["ttl_sync", "lfp_ch0", "lfp_ch1", "wheel_vel"],
        source_id="ephys.bin",
    )
    pane.wait_for_pending_rows()
    pane.set_channel_unit(ChannelKey("ephys.bin", "lfp_ch0"), "uV")
    qtbot.waitUntil(lambda: pane._last_installed_generation > 0, timeout=3000)
    return pane, cache_dir


def test_ctrl_wheel_zooms_around_cursor_and_drag_pans_horizontally(qtbot, tmp_path: Path) -> None:
    pane, _ = _load_ready_pane(qtbot, tmp_path)
    pane.set_cursor(2.0, immediate=True)
    assert abs(pane.window_duration - 10.0) < 1e-6
    assert pane.sweep_start == 0.0

    # Anchor zoom at 50% of the 10s window -> anchor_view_t = 5.0 s
    pane.zoom_around_cursor(4.0, anchor_view_t=5.0, fraction=0.5)
    assert abs(pane.window_duration - 4.0) < 1e-6
    assert abs((pane.sweep_start or 0.0) - 3.0) < 1e-6

    # Send a Ctrl+Wheel zoom-in event directly to graphics_layout.viewport()
    viewport = pane.graphics_layout.viewport()
    assert viewport is not None
    center = QPointF(viewport.width() * 0.5, viewport.height() * 0.3)
    wheel = QWheelEvent(
        center,
        viewport.mapToGlobal(center.toPoint()),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    handled = pane._navigator.eventFilter(viewport, wheel)
    assert handled
    assert pane.window_duration < 4.0

    # Middle-mouse drag pans horizontally without moving the playhead
    before_start = float(pane.sweep_start or 0.0)
    seeks: list[float] = []
    pane.seek_requested.connect(seeks.append)

    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(300.0, 80.0),
        viewport.mapToGlobal(QPoint(300, 80)),
        Qt.MouseButton.MiddleButton,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
    )
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(200.0, 80.0),
        viewport.mapToGlobal(QPoint(200, 80)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(200.0, 80.0),
        viewport.mapToGlobal(QPoint(200, 80)),
        Qt.MouseButton.MiddleButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert pane._navigator.eventFilter(viewport, press)
    assert pane._navigator.eventFilter(viewport, move)
    assert pane._navigator.eventFilter(viewport, release)
    assert float(pane.sweep_start or 0.0) > before_start
    assert seeks == []


def test_hover_crosshair_and_on_canvas_measure_callouts(qtbot, tmp_path: Path) -> None:
    pane, _ = _load_ready_pane(qtbot, tmp_path)
    hovered_times: list[object] = []
    pane.hover_time_changed.connect(hovered_times.append)

    ch = pane.channels[1]
    vb_rect = ch.plot_item.vb.sceneBoundingRect()
    target_pos = QPointF(vb_rect.center().x(), vb_rect.center().y())
    pane._interactions.on_scene_moved(target_pos, pane.graphics_layout.scene())

    assert hovered_times and isinstance(hovered_times[-1], float)
    assert pane._interactions._hover._pill is not None
    assert pane._interactions._hover._pill.isVisible()
    assert "uV" in pane._interactions._hover._pill.toPlainText()

    pane._interactions.clear_hover()
    assert hovered_times[-1] is None

    # Measure A & B render on-canvas interval shading and delta badges
    pane.set_measure_a(1.0)
    pane.set_measure_b(3.5)
    assert len(pane._interactions._measure_callout_items) == len(pane.channels) * 2
    delta_text = format_measure_delta(ch, 1.0, 3.5)
    assert "2.500 s" in delta_text
    assert "0.40 Hz" in delta_text
    assert "uV" in delta_text

    pane.clear_measure()
    assert pane._interactions._measure_callout_items == []


def test_pin_row_to_top_and_overlaid_and_heatmap_modes(qtbot, tmp_path: Path) -> None:
    pane, _ = _load_ready_pane(qtbot, tmp_path)
    assert not pane._pinned_layout.isVisible()

    # Pin ttl_sync to the sticky top stack
    key = ChannelKey("ephys.bin", "ttl_sync")
    pane.set_channel_pinned(key, True)
    assert pane._pinned_layout.isVisible()
    pinned_rows = [ch for ch in pane.channels if ch.pinned]
    assert len(pinned_rows) == 1 and pinned_rows[0].name == "ttl_sync"

    # Switch to Overlaid mode, then 2D Carpet Heatmap mode, then back to Stacked
    pane.set_view_mode(PLOT_MODE_OVERLAY)
    assert pane.view_mode == PLOT_MODE_OVERLAY
    assert pane._mode_view.isVisible()
    assert not pane._plot_scroll.isVisible()
    assert len(pane._mode_view._curves) == 4

    pane.set_view_mode(PLOT_MODE_HEATMAP)
    assert pane.view_mode == PLOT_MODE_HEATMAP
    assert pane._mode_view._image_item is not None

    pane.set_view_mode(PLOT_MODE_STACKED)
    assert pane._plot_scroll.isVisible()
    assert pane._pinned_layout.isVisible()

    # Unpin returns row to scroll stack and hides sticky header
    pane.set_channel_pinned(key, False)
    assert not pane._pinned_layout.isVisible()
    pane.clear_sources()
