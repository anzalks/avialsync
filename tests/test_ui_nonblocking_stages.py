"""Regression and latency-budget tests for UI non-stalling guarantees across stages."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QPushButton, QWidget

from avialsync.core.channel_reader import ChannelKey
from avialsync.core.columns import RegularTimes
from avialsync.core.registry import LoaderRegistry
from avialsync.core.settings_schema import setting_for
from avialsync.core.source import TimeSeriesSource, VideoSource
from avialsync.core.timeline import TimeMap
from avialsync.loaders.tracking_loader import TrackingLoader
from avialsync.loaders.video_standard import VideoStandardLoader
from avialsync.ui import pose_overlay_extras, preferences_dialog, tracking_timing
from avialsync.ui.accessibility import apply_accessibility
from avialsync.ui.batch_import_dialog import BatchImportDialog
from avialsync.ui.controllers import gap_view, sources_controller
from avialsync.ui.plot_pane import PlotPane
from avialsync.ui.sidebar import SensorInfoWidget
from avialsync.ui.transport import TimelineOverview


def test_overlay_settings_are_cached_off_paint_path_and_invalidated_on_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paint-path helpers must not read QSettings repeatedly per frame."""
    pose_overlay_extras.invalidate_overlay_settings_cache()
    calls: list[str] = []
    real_read = preferences_dialog.read_setting

    def counted_read(setting: Any) -> Any:
        calls.append(setting.key)
        return real_read(setting)

    monkeypatch.setattr(pose_overlay_extras, "read_setting", counted_read)

    for _ in range(200):
        r = pose_overlay_extras.marker_radius()
        c = pose_overlay_extras.confidence_threshold()
        f = pose_overlay_extras.trail_frame_count()
        assert 2 <= r <= 12
        assert 0.0 <= c <= 1.0
        assert 1 <= f <= 120

    assert calls == [
        "overlays/marker_radius",
        "overlays/confidence_threshold",
        "overlays/trail_frames",
    ]

    radius_setting = setting_for("overlays/marker_radius")
    assert radius_setting is not None
    original = real_read(radius_setting)
    try:
        updated = 9 if int(original) != 9 else 7
        preferences_dialog.write_setting(radius_setting, updated)
        assert pose_overlay_extras.marker_radius() == updated
        assert calls.count("overlays/marker_radius") == 2
    finally:
        preferences_dialog.write_setting(radius_setting, original)


def test_plot_batch_visibility_and_gap_markers_avoid_quadratic_relayouts(
    qtbot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bulk channel toggles and gap updates relayout and redraw once, not per channel."""
    pane = PlotPane()
    qtbot.addWidget(pane)
    try:
        relayout_calls = 0
        gap_redraws = 0
        orig_relayout = pane._relayout_rows
        orig_gap_redraw = pane._interactions.redraw_gap_markers

        def count_relayout() -> None:
            nonlocal relayout_calls
            relayout_calls += 1
            orig_relayout()

        def count_gap_redraw() -> None:
            nonlocal gap_redraws
            gap_redraws += 1
            orig_gap_redraw()

        monkeypatch.setattr(pane, "_relayout_rows", count_relayout)
        monkeypatch.setattr(pane._interactions, "redraw_gap_markers", count_gap_redraw)

        from avialsync.ui.plot_row import create_channel_plot

        time_map = TimeMap()
        # Stub minimal rows without disk pyramids by mocking MappedChannelReader
        readers: list[Any] = []
        for idx in range(64):
            key = ChannelKey("src.mat", f"roi_{idx}")
            reader = SimpleNamespace(
                key=key,
                source_id="src.mat",
                channel_id=f"roi_{idx}",
                cache_dir=Path("/tmp/fake_cache"),
                time_map=time_map,
                coverage=lambda: (0.0, 10.0),
                available_sample_at=lambda _t: (0, 1.0),
                source_reader=SimpleNamespace(
                    close=lambda: None, cache_dir=Path("/tmp/fake_cache")
                ),
            )
            readers.append(reader)

        import avialsync.ui.plot_row as plot_row_mod

        monkeypatch.setattr(
            plot_row_mod,
            "PyramidReader",
            lambda cache_dir, name: SimpleNamespace(
                cache_dir=cache_dir, channel_id=name, close=lambda: None
            ),
        )
        monkeypatch.setattr(
            plot_row_mod,
            "MappedChannelReader",
            lambda pyr, _tm, source_id="": next(
                r for r in readers if r.channel_id == pyr.channel_id and r.source_id == source_id
            ),
        )
        pane.graphics_layout.setUpdatesEnabled(False)
        for idx in range(64):
            ch = create_channel_plot(
                pane.graphics_layout,
                idx,
                Path("/tmp/fake_cache"),
                f"roi_{idx}",
                idx,
                lambda *_: None,
                time_map,
                "src.mat",
                row_height=60,
                visible=True,
            )
            pane.channels.append(ch)
        pane.graphics_layout.setUpdatesEnabled(True)

        relayout_calls = 0
        pane.set_channels_visible({ChannelKey("src.mat", f"roi_{i}"): False for i in range(64)})
        assert relayout_calls == 1
        assert all(not ch.visible for ch in pane.channels)

        # Repeating identical visibility state does zero work.
        pane.set_channels_visible({ChannelKey("src.mat", f"roi_{i}"): False for i in range(64)})
        assert relayout_calls == 1

        gap_redraws = 0
        pane.set_gap_markers_bulk(
            {ChannelKey("src.mat", f"roi_{i}"): [1.5, 4.2] for i in range(64)}
        )
        assert gap_redraws == 1
        assert all(ch.gap_times == (1.5, 4.2) for ch in pane.channels)
    finally:
        pane.shutdown()


def test_sync_tracking_plot_skips_unplotted_pose_channels() -> None:
    """Importing a pose source with plot=False must not trigger per-channel plot relayouts."""
    set_calls: list[Any] = []
    window: Any = SimpleNamespace(
        _tracking_plot_sources={
            "pose.csv": (Path("/tmp/pose"), [f"pt_{i}_x" for i in range(120)], 0.0, 0.0)
        },
        _tracking_visibility={"pose.csv": {"overlay": True, "plot": False}},
        sidebar=SimpleNamespace(sensor_widget=lambda _p: None),
        plot_pane=SimpleNamespace(
            channels=[],
            set_channels_visible=lambda updates: set_calls.append(updates),
        ),
    )
    sources_controller.sync_tracking_plot(window, "pose.csv")
    assert set_calls == []


def test_hover_crosshair_rate_limits_high_frequency_pointer_bursts(
    qtbot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First move after idle is synchronous; 240 Hz bursts throttle to ~30 Hz + trailing flush."""
    import avialsync.ui.plot_interactions as pi_mod

    pane = PlotPane()
    qtbot.addWidget(pane)
    try:
        emitted: list[float | None] = []
        pane.hover_time_changed.connect(emitted.append)

        applied: list[QPointF] = []
        monkeypatch.setattr(
            pane._interactions,
            "_apply_scene_moved",
            lambda pos, _scene=None: (applied.append(pos), emitted.append(float(pos.x()))),
        )

        fake_now = 100.0
        monkeypatch.setattr(pi_mod, "_elapsed", lambda: fake_now)

        # First move after idle runs immediately synchronously.
        pane._interactions.on_scene_moved(QPointF(1.25, 10.0))
        assert len(applied) == 1
        assert emitted[-1] == pytest.approx(1.25)

        # Simulate 120 pointer events across 0.5 s (~240 Hz).
        for step in range(1, 121):
            fake_now = 100.0 + step * (0.5 / 120.0)
            pane._interactions.on_scene_moved(QPointF(1.25 + step * 0.01, 10.0))

        # Capped to ~15-17 synchronous updates over 0.5 s instead of 121.
        assert len(applied) <= 20
        # Trailing timer flushes the exact last pointer coordinate.
        qtbot.waitUntil(lambda: emitted[-1] == pytest.approx(2.45), timeout=500)
    finally:
        pane.shutdown()


def test_large_sensor_tree_and_batch_import_dialog_stay_fast(qtbot: Any, tmp_path: Path) -> None:
    """512-channel SensorInfoWidget uses uniformRowHeights and BatchImportDialog builds cleanly."""
    channels = [f"Neuropixels_{i // 16:02d}_ch{i:03d}" for i in range(512)]
    t0 = time.perf_counter()
    card = SensorInfoWidget(str(tmp_path / "probe.bin"), channels)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    qtbot.addWidget(card)
    assert card.tree.uniformRowHeights() is True
    assert len(card.checked_channels()) == 512
    # Generous CI ceiling to avoid runner noise while catching O(N^2) regressions (~400+ ms).
    assert elapsed_ms < 150.0

    registry = LoaderRegistry()
    candidates: list[tuple[Path, type[TimeSeriesSource | VideoSource] | None, dict | None]] = [
        (tmp_path / f"cam_{i}.mp4", VideoStandardLoader, None) for i in range(4)
    ] + [
        (tmp_path / f"cam_{i % 4}_pose_{i}.csv", TrackingLoader, {"role": "overlay2d"})
        for i in range(28)
    ]
    dlg = BatchImportDialog(candidates, registry=registry)
    qtbot.addWidget(dlg)
    assert len(dlg.get_selections()) == 32


def test_regular_times_overlay_calibration_runs_in_o1_without_array_materialization() -> None:
    """calibrate_overlay_timing slices RegularTimes analytically without materializing arrays."""
    n_frames = 250_000
    fps = 230.0
    reg = RegularTimes(0.0, fps, n_frames, stride=1)
    frame_times = np.linspace(1000.0, 1000.0 + (n_frames - 1) / fps, n_frames, dtype=np.float64)

    def forbid_array(*_args: Any, **_kwargs: Any) -> np.ndarray:
        raise AssertionError(
            "RegularTimes.__array__ must not be materialized for _matched_video_frames"
        )

    matched = tracking_timing._matched_video_frames(reg, fps, frame_times)
    assert matched is not None
    assert len(matched) == n_frames
    assert np.shares_memory(matched, frame_times)
    assert forbid_array is not None  # keep helper referenced for clarity

    pane_tm = TimeMap(offset=-1000.0, drift_ms_per_hour=0.0)
    reader_tm = TimeMap()
    plot_exact_calls: list[tuple[np.ndarray, np.ndarray]] = []
    reader = SimpleNamespace(
        source_id="pose_2d.csv",
        time_map=reader_tm,
        source_reader=SimpleNamespace(mapped_columns=lambda: (reg, reg, reg)),
    )
    window: Any = SimpleNamespace(
        video_grid=SimpleNamespace(
            pane_paths=lambda: ["cam0.mp4"],
            panes=[SimpleNamespace(time_map=pane_tm)],
        ),
        _video_frame_times={"cam0.mp4": frame_times},
        _overlay_sources={
            "cam0.mp4": {
                "pose_2d.csv": {
                    "frame_rate": fps,
                    "points": {"nose": (reader, reader)},
                }
            }
        },
        _pose_cache_dirs={"pose_2d.csv": Path("/tmp/pose_cache")},
        plot_pane=SimpleNamespace(
            set_source_exact_mapping=lambda _d, m, s: plot_exact_calls.append((m, s))
        ),
    )

    tracking_timing.calibrate_overlay_timing(window, "cam0.mp4")
    assert reader_tm.has_exact_mapping
    assert len(plot_exact_calls) == 1
    # Both TimeMap and PlotPane receive the exact same frozen buffer without re-copying.
    assert plot_exact_calls[0][0] is reader_tm._exact_master


def test_gap_view_caches_per_source_holes_across_incremental_loads(
    qtbot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unchanged sources must not re-slice mmaps across trial gaps when another source arrives."""
    overview = TimelineOverview()
    qtbot.addWidget(overview)
    overview.set_segments([(0.0, 5.0, "Trial 1"), (10.0, 15.0, "Trial 2"), (20.0, 25.0, "Trial 3")])
    overview.set_coverage("src_a", 0.0, 25.0, "data")

    query_counts: dict[str, int] = {}

    def fake_samples_between(
        _win: Any, source_id: str, _kind: str, a: float, b: float
    ) -> tuple[np.ndarray, float]:
        query_counts[source_id] = query_counts.get(source_id, 0) + 1
        return np.empty(0, dtype=np.float64), 0.01

    monkeypatch.setattr(gap_view, "samples_between", fake_samples_between)

    reader_a = SimpleNamespace(source_reader=object(), time_map=TimeMap())
    reader_b = SimpleNamespace(source_reader=object(), time_map=TimeMap())
    readers_map = {"src_a": [reader_a], "src_b": [reader_b]}

    window: Any = SimpleNamespace(
        transport=SimpleNamespace(
            overview=overview,
            set_coverage_holes=overview.set_holes,
            warp=overview.warp,
        ),
        plot_pane=SimpleNamespace(set_time_warp=lambda _w: None),
        source_readers=lambda sid: readers_map.get(sid, []),
    )

    gap_view.refresh_holes(window)
    first_a_queries = query_counts["src_a"]
    assert first_a_queries > 0

    # Adding src_b queries src_b only; src_a hits the per-source hole cache (0 new queries).
    overview.set_coverage("src_b", 0.0, 25.0, "data")
    gap_view.refresh_holes(window)
    assert query_counts["src_a"] == first_a_queries
    assert query_counts["src_b"] > 0


def test_accessibility_sweep_skips_already_swept_controls_and_names_new_ones(
    qtbot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated sweeps skip already-named controls in O(1) while naming newly added children."""
    import avialsync.ui.accessibility as a11y

    root = QWidget()
    qtbot.addWidget(root)
    for i in range(25):
        QPushButton(f"Action {i}", root)

    assert apply_accessibility(root) == 25

    derive_calls = 0
    real_derive = a11y.derive_name

    def counted_derive(w: QWidget) -> str:
        nonlocal derive_calls
        derive_calls += 1
        return real_derive(w)

    monkeypatch.setattr(a11y, "derive_name", counted_derive)

    assert apply_accessibility(root) == 0
    assert derive_calls == 0

    late = QPushButton("Newly Loaded Source", root)
    assert apply_accessibility(root) == 1
    assert derive_calls == 1
    assert late.accessibleName() == "Newly Loaded Source"
