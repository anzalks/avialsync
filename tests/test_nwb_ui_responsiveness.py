"""Regression and UI-responsiveness tests for multi-ROI NWB & dense multi-plot sessions."""

from __future__ import annotations

import gc
import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

pytest.importorskip("h5py")

import h5py  # noqa: E402

from avialsync.core import channel_store  # noqa: E402
from avialsync.core.pyramid import PyramidReader  # noqa: E402
from avialsync.engine.importer import ImportWorker  # noqa: E402
from avialsync.loaders import nwb_roi_grid  # noqa: E402
from avialsync.loaders.nwb_loader import NWBLoader  # noqa: E402
from avialsync.loaders.nwb_roi_grid import NWBRoiGridSource, find_roi_grids  # noqa: E402
from avialsync.loaders.roi_grid_layout import pack  # noqa: E402
from avialsync.ui import recovery  # noqa: E402
from avialsync.ui.main_window import MainWindow  # noqa: E402
from avialsync.ui.plot_modes import (  # noqa: E402
    PLOT_MODE_HEATMAP,
    PLOT_MODE_OVERLAY,
    PLOT_MODE_STACKED,
)
from avialsync.ui.readout_panel import _MAX_WIDGET_ROWS  # noqa: E402
from avialsync.ui.roi_linking import _on_roi_clicked  # noqa: E402
from tests.nwb_fixture import (  # noqa: E402
    NWBSpec,
    _column,
    _imaging_plane,
    _region,
    _series,
    _table,
    write_nwb,
)


@pytest.fixture(autouse=True)
def _isolated_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = tmp_path / "recovery"
    rec.mkdir(exist_ok=True)
    monkeypatch.setattr(recovery, "recovery_dir", lambda: rec)


def _write_multi_roi_nwb(
    path: Path,
    *,
    n_rois: int,
    n_frames: int = 600,
    with_raw_movie: bool = False,
    with_fluorescence: bool = True,
) -> Path:
    spec = NWBSpec(
        ephys=False,
        position=True,
        imaging=False,
        fluorescence=False,
        intervals=False,
        trials=True,
        units=False,
        annotations=False,
    )
    write_nwb(path, spec)
    rng = np.random.default_rng(7)
    with h5py.File(path, "a") as handle:
        plane = _imaging_plane(handle)
        if with_raw_movie:
            frames = rng.integers(100, 2000, (40, 128, 128), dtype=np.uint16)
            movie = _series(
                handle["acquisition"],
                "TwoPhotonSeries",
                "TwoPhotonSeries",
                frames,
                "n.a.",
                rate=20.0,
                start=0.0,
            )
            movie["imaging_plane"] = h5py.SoftLink(plane.name)

        ophys = handle["processing"].require_group("ophys")
        seg = ophys.create_group("ImageSegmentation")
        seg.attrs["neurodata_type"] = "ImageSegmentation"
        ps = _table(seg, "PlaneSegmentation", "PlaneSegmentation", n_rois, ["image_mask"])
        masks = np.zeros((n_rois, 128, 128), dtype=np.float32)
        for idx in range(n_rois):
            r = (idx * 9) % 112
            c = (idx * 13) % 112
            masks[idx, r : r + 8, c : c + 8] = 0.5 + 0.5 * ((idx % 3) / 2.0)
        _column(ps, "image_mask", masks)
        ps["id"][...] = np.arange(n_rois, dtype=np.int64)
        ps["imaging_plane"] = h5py.SoftLink(plane.name)

        interfaces = ("DfOverF", "Fluorescence") if with_fluorescence else ("DfOverF",)
        for iface in interfaces:
            grp = ophys.create_group(iface)
            grp.attrs["neurodata_type"] = iface
            traces = rng.normal(0.0, 1.0, (n_frames, n_rois)).astype(np.float32)
            rs = _series(
                grp,
                "RoiResponseSeries",
                "RoiResponseSeries",
                traces,
                "a.u.",
                rate=20.0,
                start=0.0,
            )
            _region(rs, "rois", ps, list(range(n_rois)))
    return path


def test_external_array_shares_single_base_memmap_and_releases_on_close(tmp_path: Path) -> None:
    """200 in-place NWB ROI columns share one OS memmap and release it when readers close."""
    nwb_path = _write_multi_roi_nwb(
        tmp_path / "shared_mmap.nwb", n_rois=200, n_frames=500, with_fluorescence=False
    )
    worker = ImportWorker(nwb_path, {}, NWBLoader)
    delivered: list[tuple] = []
    worker.finished.connect(lambda *args: delivered.append(args))
    worker.run()
    assert delivered
    _src, cache_dir, channels, _bounds, _insp = delivered[0]
    roi_channels = [ch for ch in channels if ch.startswith("ophys.DfOverF.")]
    assert len(roi_channels) == 200

    readers = [PyramidReader(Path(cache_dir), name) for name in roi_channels]
    bases: set[int] = set()
    first_raw = getattr(readers[0]._load_level(1)[1], "raw", readers[0]._load_level(1)[1])
    for idx, reader in enumerate(readers):
        sample = reader.sample_at(0.5)
        assert sample is not None
        _t, values, _, _ = reader._load_level(1)
        raw = getattr(values, "raw", values)
        mmap_handle = getattr(raw, "_mmap", None) or getattr(raw.base, "_mmap", None)
        assert mmap_handle is not None
        bases.add(id(mmap_handle))
        if idx > 0:
            assert not np.array_equal(raw[:8], first_raw[:8])
    assert len(bases) == 1, "Every column of one 2D NWB dataset must share one OS mmap handle"

    resolved = str(nwb_path.resolve())
    matching_keys = [k for k in channel_store._SHARED_MEMMAPS if k[0] == resolved]
    assert len(matching_keys) == 1

    for reader in readers:
        reader.close()
    del readers, first_raw, values, raw, mmap_handle
    gc.collect()

    remaining = [k for k in channel_store._SHARED_MEMMAPS if k[0] == resolved]
    assert remaining == [], "Closing all PyramidReaders must release the shared base memmap"


def test_wide_nwb_loader_caps_default_shown_columns_while_keeping_all_channels(
    tmp_path: Path,
) -> None:
    """Wide 2D ROI matrices import all channels while keeping initial shown rows bounded."""
    nwb_path = _write_multi_roi_nwb(tmp_path / "wide.nwb", n_rois=80, n_frames=200)
    loader = NWBLoader()
    loader.open(nwb_path, {})
    infos = loader.channels()
    by_name = {info.name: info for info in infos}

    assert len(infos) == 80 + 80 + 2 + 1  # DfOverF + Fluorescence + Position(x,y) + trials
    assert by_name["Position.SpatialSeries.x"].shown is True
    assert by_name["Position.SpatialSeries.y"].shown is True
    dff_shown = [info for info in infos if info.name.startswith("ophys.DfOverF.") and info.shown]
    fluo_shown = [
        info for info in infos if info.name.startswith("ophys.Fluorescence.") and info.shown
    ]
    assert len(dff_shown) == 16
    assert len(fluo_shown) == 0


def test_nwb_roi_grid_caches_masks_and_composes_vectorized_frames_identically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovery, probe, and reader reuse extracted masks once and compose exact float32 tiles."""
    orig_masks = nwb_roi_grid._masks
    calls = 0

    def counted_masks(table):
        nonlocal calls
        calls += 1
        return orig_masks(table)

    monkeypatch.setattr(nwb_roi_grid, "_masks", counted_masks)

    for mode, raw_movie in (("response", False), ("raw", True)):
        nwb_path = _write_multi_roi_nwb(
            tmp_path / f"grid_{mode}.nwb",
            n_rois=36,
            n_frames=40,
            with_raw_movie=raw_movie,
        )
        nwb_roi_grid._MASK_CACHE.clear()
        calls = 0

        grids = find_roi_grids(nwb_path)
        assert len(grids) == 1 and grids[0].mode == mode
        obj_path = Path(f"{nwb_path}/{grids[0].path.lstrip('/')}")

        probe_src = NWBRoiGridSource()
        probe_src.open(obj_path, {})
        probe_src.close()

        read_src = NWBRoiGridSource()
        meta = read_src.open(obj_path, {})
        try:
            assert calls == 1, f"Expected 1 mask extraction for {mode}, got {calls}"
            assert len(meta.roi_boxes) == 36
            frame = read_src.read_frame(3)
            assert frame.shape == (meta.height, meta.width)
            assert frame.dtype == np.float32

            # Reference tile composition check
            stored = int(read_src._frames[3])
            if mode == "raw":
                raw = nwb_roi_grid.nwb_read.read_frames(
                    read_src._handle, read_src._info, stored, stored + 1
                )[0]
                ref_tiles = [
                    raw[top : top + crop.shape[0], left : left + crop.shape[1]].astype(np.float32)
                    for crop, (top, left) in zip(read_src._crops, read_src._corners, strict=True)
                ]
            else:
                vals = nwb_roi_grid.nwb_read.read_values(
                    read_src._handle, read_src._info, stored, stored + 1
                )[0]
                ref_tiles = [
                    crop * np.float32(vals[col])
                    for crop, col in zip(read_src._crops, read_src._columns, strict=True)
                ]
            expected = pack(ref_tiles, read_src._grid, read_src._tile, read_src._shape)
            np.testing.assert_allclose(frame, expected, equal_nan=True)
        finally:
            read_src.close()


def test_multi_roi_nwb_ui_workflows_stay_responsive(
    qapp: QApplication, qtbot, tmp_path: Path
) -> None:
    """150-ROI NWB (300+ channels) loads in slices and handles all UI modes without stalling."""
    nwb_path = _write_multi_roi_nwb(tmp_path / "ui_150roi.nwb", n_rois=150, n_frames=400)
    worker = ImportWorker(nwb_path, {}, NWBLoader)
    delivered: list[tuple] = []
    worker.finished.connect(lambda *args: delivered.append(args))
    worker.run()
    src_path, cache_dir, channels, bounds, inspection = delivered[0]

    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1280, 820)
    window.show()
    qapp.processEvents()

    try:
        pending_counts: list[int] = []
        window.plot_pane.rows_pending.connect(pending_counts.append)

        window._on_import_finished(src_path, cache_dir, channels, bounds, inspection)
        qtbot.waitUntil(
            lambda: (
                len(window.plot_pane.channels) == len(channels)
                and not window.plot_pane._pending_rows
            ),
            timeout=15_000,
        )
        qtbot.waitUntil(lambda: window.plot_pane._page_worker is None, timeout=10_000)
        assert len(pending_counts) >= 2, "Wide channel load must yield across multiple slices"

        # Clicking a hidden ROI (roi120) reveals and scrolls to its trace
        hidden_row = next(ch for ch in window.plot_pane.channels if ch.name.endswith(".roi120"))
        assert not hidden_row.visible
        _on_roi_clicked(window, "roi120")
        assert hidden_row.visible

        # Show Values tab: only visible channels appear in Values (no hidden-ROI dump),
        # and dense ROI groups collapse to a summary row by default.
        window._left_tabs.setCurrentWidget(window.readout_panel)
        qapp.processEvents()
        visible_count = sum(1 for ch in window.plot_pane.channels if ch.visible)
        assert visible_count < len(channels)
        assert len(window.readout_panel._rows) == visible_count

        # Bulk Show all -> all 300+ channels visible; mounted widgets stay bounded
        card = window.sidebar.sensor_widget(src_path)
        assert card is not None
        t0 = time.perf_counter()
        card._on_bulk_visibility(True)
        qapp.processEvents()
        assert (time.perf_counter() - t0) < 1.5
        assert all(ch.visible for ch in window.plot_pane.channels)
        assert len(window.readout_panel._rows) == len(channels)
        mounted_rows = sum(1 for _, r in window.readout_panel._rows.values() if r is not None)
        assert mounted_rows == _MAX_WIDGET_ROWS
        qtbot.waitUntil(lambda: window.plot_pane._page_worker is None, timeout=10_000)

        # Measure A/B across 300+ visible channels stays fast and only builds onscreen callouts
        t0 = time.perf_counter()
        window.plot_pane.set_measure_a(1.0)
        window.plot_pane.set_measure_b(4.0)
        qapp.processEvents()
        assert (time.perf_counter() - t0) < 0.5
        assert 0 < len(window.plot_pane._interactions._measure_callout_items) < len(channels)
        assert len(window.readout_panel._delta_rows) == _MAX_WIDGET_ROWS

        summary = window.readout_panel.textual_summary()
        assert "roi149" in summary

        window.plot_pane.clear_measure()
        assert window.readout_panel._delta_rows == {}
        assert window.readout_panel._delta_extra_widgets == []

        # Hover over onscreen row updates crosshair without touching culled offscreen rows
        scene = window.plot_pane.graphics_layout.scene()
        onscreen_row = next(ch for ch in window.plot_pane.channels if ch.visible and not ch.culled)
        vb_rect = onscreen_row.plot_item.vb.sceneBoundingRect()
        window.plot_pane._interactions._last_hover_at = 0.0
        window.plot_pane._interactions.on_scene_moved(vb_rect.center(), scene)
        assert 0 < len(window.plot_pane._interactions._hover._lines) < len(channels)

        # Overlaid mode batches >12 channels into compact NaN-separated pen groups
        window.plot_pane.set_view_mode(PLOT_MODE_OVERLAY)
        assert 0 < len(window.plot_pane._mode_view._curves) <= 32
        window.plot_pane.set_view_mode(PLOT_MODE_HEATMAP)
        assert window.plot_pane._mode_view._image_item is not None
        window.plot_pane.set_view_mode(PLOT_MODE_STACKED)

        # Undo Show all restores mixed visibility in one batched step
        t0 = time.perf_counter()
        window.document.undo(window._mutations)
        qapp.processEvents()
        assert (time.perf_counter() - t0) < 1.5
        assert not all(ch.visible for ch in window.plot_pane.channels)

        # Remove entire 300+-channel source cleanly
        t0 = time.perf_counter()
        window._on_sensor_remove_requested(src_path)
        qapp.processEvents()
        assert (time.perf_counter() - t0) < 1.5
        assert window.plot_pane.channels == []
    finally:
        if isValid(window):
            window.close()
