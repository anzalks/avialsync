"""Regression and responsiveness tests for full-session scale-up & correctness fixes."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from avialsync.core import edit_program
from avialsync.core.channel_reader import ChannelKey
from avialsync.core.channel_store import safe_channel_stem
from avialsync.core.commands import SetChannelGroupVisibleCommand
from avialsync.core.identity_swaps import SwapEvent, SwapGroup, SwapStore
from avialsync.core.messages import Message
from avialsync.core.point_edits import PointEditStore, PointKey
from avialsync.core.pose import PosePoint, PoseSchema
from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.core.session import MarkerEntry, SessionState, SyncProvenance
from avialsync.core.session_io import exact_mapping_dir
from avialsync.core.skeleton import MAX_POINTS, infer_skeleton
from avialsync.core.source import TimeSeriesSource
from avialsync.core.timeline import PreparedExactMapping, TimeMap
from avialsync.core.triggers import TriggerKind, extract_pulses
from avialsync.engine.export_worker import DataExportWorker, ReaderReference, RegionStatsWorker
from avialsync.engine.importer import ImportWorker
from avialsync.engine.stimulus_grid_export import MAX_GRID_EVENTS
from avialsync.engine.sync_worker import SignalEvidenceSpec
from avialsync.loaders.csv_loader import CSVLoader
from avialsync.ui import recovery
from avialsync.ui.annotations import AnnotationStore
from avialsync.ui.batch_import_dialog import BatchImportDialog
from avialsync.ui.changes_panel import ChangesPanel
from avialsync.ui.main_window import MainWindow
from avialsync.ui.message_panel import MessageStore
from avialsync.ui.pose_suspects import find_suspects_in_cache
from avialsync.ui.stimulus_grid_dialog import StimulusChannelOption, StimulusGridDialog
from avialsync.ui.sync_acceptance import collect_sync_evidence
from avialsync.ui.sync_wizard import SyncWizard


@pytest.fixture(autouse=True)
def _isolated_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = tmp_path / "recovery_appdata"
    rec.mkdir(exist_ok=True)
    monkeypatch.setattr(recovery, "recovery_dir", lambda: rec)


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    yield win
    if isValid(win):
        win.close()


def test_sidebar_group_checkbox_batches_single_undo_and_preserves_channel_ids(
    window: MainWindow, tmp_path: Path
) -> None:
    """Toggling a 120-channel group with descriptions records 1 undo step and restores state."""
    cache_dir = tmp_path / "roi_cache"
    cache_dir.mkdir()
    times = np.linspace(0.0, 10.0, 200, dtype=np.float64)
    channels = [f"ROI_{i:03d}" for i in range(120)]
    for i, ch in enumerate(channels):
        PyramidBuilder(cache_dir, ch).build_and_save(times, np.sin(times + i * 0.1))

    src_path = str(tmp_path / "session_rois.nwb")
    visibility = {ch: (i < 40) for i, ch in enumerate(channels)}
    descriptions = {ch: f"Calcium fluorescence trace for cell {ch}" for ch in channels}

    window._sensor_cache_dirs[src_path] = cache_dir
    window.plot_pane.load_channels(cache_dir, channels, source_id=src_path, visibility=visibility)
    while window.plot_pane._pending_rows:
        window.plot_pane._build_pending_rows()
    window.sidebar.add_sensor(
        src_path,
        channels,
        channel_visibility=visibility,
        channel_descriptions=descriptions,
    )
    window.document.clear()

    card = window.sidebar.sensor_widget(src_path)
    assert card is not None
    roi_group = next(g for g in card._group_items if g.text(0) == "ROI")
    assert roi_group.checkState(0) == Qt.CheckState.PartiallyChecked

    # Simulate user clicking the group checkbox directly on the QTreeWidget.
    roi_group.setCheckState(0, Qt.CheckState.Checked)

    assert len(window.document) == 1
    cmd = list(window.document)[0]
    assert isinstance(cmd, SetChannelGroupVisibleCommand)
    assert set(cmd.before) == set(channels)
    assert window.plot_pane.is_channel_visible(ChannelKey(src_path, "ROI_000")) is True
    assert window.plot_pane.is_channel_visible(ChannelKey(src_path, "ROI_090")) is True

    # Single Ctrl+Z restores the exact mixed visibility before the group click.
    assert window.document.undo(window._mutations) is not None
    assert window.plot_pane.is_channel_visible(ChannelKey(src_path, "ROI_000")) is True
    assert window.plot_pane.is_channel_visible(ChannelKey(src_path, "ROI_090")) is False
    assert roi_group.checkState(0) == Qt.CheckState.PartiallyChecked


def test_sync_wizard_multichannel_targets_preserve_distinct_channels(
    window: MainWindow, tmp_path: Path
) -> None:
    """Refreshing sources in SyncWizard never overwrites earlier channels with the last channel."""
    cache_dir = tmp_path / "sync_sensor_cache"
    cache_dir.mkdir()
    times = np.linspace(0.0, 5.0, 500, dtype=np.float64)
    ch_names = ["ttl_cam0", "ttl_cam1", "analog_aux"]
    for ch in ch_names:
        PyramidBuilder(cache_dir, ch).build_and_save(
            times, (np.sin(times * 20.0) > 0).astype(float)
        )

    src_path = str(tmp_path / "ephys_sync.bin")
    window._sensor_cache_dirs[src_path] = cache_dir
    window.plot_pane.load_channels(cache_dir, ch_names, source_id=src_path)
    while window.plot_pane._pending_rows:
        window.plot_pane._build_pending_rows()

    references, targets = collect_sync_evidence(window)
    wizard = SyncWizard(references, targets, window)
    initial_channels = [t.channel_id for t in wizard._targets if isinstance(t, SignalEvidenceSpec)]
    assert initial_channels == ch_names

    wizard._refresh_sources()
    refreshed_channels = [
        t.channel_id for t in wizard._targets if isinstance(t, SignalEvidenceSpec)
    ]
    assert refreshed_channels == ch_names
    wizard.close()


def test_message_store_preserves_exact_timemap_and_shifts_on_mapping_edit() -> None:
    """MessageStore preserves nonlinear exact TimeMaps and shifts knots on scalar adjustment."""
    store = MessageStore()
    src = "/tmp/rig_recording.nwb"
    tm = TimeMap(offset=10.0, drift_ms_per_hour=0.0)
    tm.install_prepared_exact_mapping(
        PreparedExactMapping.prepare(
            np.array([10.0, 20.5, 31.2], dtype=np.float64),
            np.array([0.0, 10.0, 20.0], dtype=np.float64),
        )
    )
    store.set_source_time_map(src, tm)
    store.set_source_messages(
        src,
        (
            Message(text="trial_1", time=0.0),
            Message(text="trial_2", time=10.0),
            Message(text="trial_3", time=20.0),
        ),
    )
    mapped = [m.time for m in store.messages()]
    assert mapped == pytest.approx([10.0, 20.5, 31.2])

    store.set_source_mapping(src, offset=12.0, drift_ms_per_hour=0.0)
    shifted = [m.time for m in store.messages()]
    assert shifted == pytest.approx([8.0, 18.5, 29.2])


def test_session_sidecar_reuse_pruning_recovery_and_workspace_reset(
    window: MainWindow, qtbot, tmp_path: Path
) -> None:
    """Exact-sync .npz sidecars deduplicate/prune, survive recovery, and open resets state."""
    master = np.linspace(100.0, 700.0, 650, dtype=np.float64)
    source = np.linspace(0.0, 600.0, 650, dtype=np.float64)
    prov = SyncProvenance(
        reference_id="/tmp/ttl.csv",
        target_id="/tmp/cam0.mp4",
        offset=100.0,
        drift_ms_per_hour=0.0,
        rms_residual=0.00002,
        max_residual=0.00008,
        matched_count=650,
        rejected_count=0,
        tolerance=0.01,
        method="exact_index",
        exact_master=master.tolist(),
        exact_source=source.tolist(),
    )
    state = SessionState(
        markers=[MarkerEntry(t_start=4.0, t_end=None, label="SavedSessionMarker")],
        sync_provenance=[prov],
    )
    avv = tmp_path / "experiment.avv"
    state.save(avv)
    sidecars_1 = list(exact_mapping_dir(avv).glob("exact-sync-*.npz"))
    assert len(sidecars_1) == 1
    mtime_1 = sidecars_1[0].stat().st_mtime_ns

    # Saving again with identical arrays reuses the sidecar without rewriting or leaking.
    state.save(avv)
    sidecars_2 = list(exact_mapping_dir(avv).glob("exact-sync-*.npz"))
    assert [p.name for p in sidecars_2] == [p.name for p in sidecars_1]
    assert sidecars_2[0].stat().st_mtime_ns == mtime_1

    # Updating the exact mapping writes the new sidecar and prunes the superseded one.
    prov_updated = SyncProvenance(**{**prov.__dict__, "exact_master": (master + 1.5).tolist()})
    state_updated = SessionState(markers=state.markers, sync_provenance=[prov_updated])
    state_updated.save(avv)
    sidecars_3 = list(exact_mapping_dir(avv).glob("exact-sync-*.npz"))
    assert len(sidecars_3) == 1
    assert sidecars_3[0].name != sidecars_1[0].name
    reloaded = SessionState.load(avv)
    assert np.allclose(reloaded.sync_provenance[0].exact_master, master + 1.5)

    # Untitled recovery preserves >500-element exact arrays and recognizes imaging/edit-only work.
    assert recovery.is_empty_state({"imaging": [{"path": "stack.tif"}]}) is False
    assert recovery.is_empty_state({"point_edits": {"pose.csv": 3}}) is False
    assert recovery.is_empty_state({"identity_swaps": {"pose.csv": 1}}) is False
    recovery.write_recovery(state_updated.to_dict(), None, exact_pairs=state_updated.exact_pairs())
    snap = recovery.read_recovery()
    assert snap is not None
    recovered_state = recovery.decode_recovery_state(snap)
    assert len(recovered_state.sync_provenance[0].exact_master) == 650
    assert np.allclose(recovered_state.sync_provenance[0].exact_master, master + 1.5)
    recovery.clear_recovery()

    # Opening a .avv onto an active workspace resets existing markers instead of merging them.
    window.annotation_store.add_point(1.25, "StalePriorMarker")
    assert [m.label for m in window.annotation_store.markers] == ["StalePriorMarker"]
    window._start_session_load(avv)
    qtbot.waitUntil(
        lambda: window.session_runtime.path == avv and not window.session_runtime.restoring,
        timeout=5000,
    )
    assert [m.label for m in window.annotation_store.markers] == ["SavedSessionMarker"]
    assert window.document.is_dirty is False


def test_unsafe_channel_stems_and_fd_bounded_wide_import_and_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Channels containing '/' import cleanly, and 300-channel import/export stays FD-bounded."""
    monkeypatch.setenv("AVIALSYNC_CACHE_DIR", str(tmp_path / "cache_root"))
    assert safe_channel_stem("plain_ch0") == "plain_ch0"
    assert "/" not in safe_channel_stem("dF/F")
    assert safe_channel_stem("dF/F") != safe_channel_stem("dF_F")

    csv_path = tmp_path / "slashes.csv"
    csv_path.write_text("time,dF/F,probeA/ch0\n0.0,1.2,3.4\n0.1,1.5,3.8\n0.2,1.9,4.1\n")
    finished_slash: list[tuple] = []
    w_slash = ImportWorker(csv_path, {"time_col": "time"}, CSVLoader)
    w_slash.finished.connect(lambda *args: finished_slash.append(args))
    w_slash.run()
    assert len(finished_slash) == 1
    _, slash_cache, slash_channels, _, slash_insp = finished_slash[0]
    try:
        assert slash_channels == ["dF/F", "probeA/ch0"]
        r = PyramidReader(Path(slash_cache), "dF/F")
        try:
            assert r.sample_count() == 3
        finally:
            r.close()
    finally:
        slash_insp.release_cache_pin()

    class _WideBulkLoader(TimeSeriesSource):
        @classmethod
        def display_name(cls) -> str:
            return "Wide Synthetic"

        @classmethod
        def can_open(cls, path: Path) -> float:
            return 0.0

        def open(self, path: Path, config: dict) -> None:
            pass

        def channels(self):
            from avialsync.core.source import ChannelInfo

            return [
                ChannelInfo(name=f"ch_{i:03d}", unit="uV", dtype="Float64", rate_hz=100.0)
                for i in range(300)
            ]

        def read_chunks(self, ch: str):
            for chunk in self.read_all_chunks():
                yield chunk[ch]

        def read_all_chunks(self):
            for k in range(3):
                t = np.arange(k * 200, (k + 1) * 200, dtype=np.float64) * 0.01
                yield {f"ch_{i:03d}": (t, np.sin(t + i * 0.01)) for i in range(300)}

    dummy = tmp_path / "wide_300.dat"
    dummy.write_bytes(b"wide")
    done_wide: list[tuple] = []
    w_wide = ImportWorker(dummy, {}, _WideBulkLoader)
    w_wide.finished.connect(lambda *args: done_wide.append(args))
    w_wide.run()
    assert len(done_wide) == 1
    _, wide_cache, wide_channels, _, wide_insp = done_wide[0]
    try:
        assert len(wide_channels) == 300
        refs = [
            ReaderReference(cache_dir=Path(wide_cache), channel_id=ch, source_id=str(dummy))
            for ch in wide_channels
        ]
        stats_res: list = []
        sw = RegionStatsWorker(1, refs, 0.0, 5.0)
        sw.finished.connect(lambda _req_id, st: stats_res.append(st))
        sw.run()
        assert len(stats_res) == 1 and len(stats_res[0]) == 300

        out_csv = tmp_path / "exported_300.csv"
        exp_res: list = []
        ew = DataExportWorker(refs, 0.0, 1.0, out_csv)
        ew.finished.connect(exp_res.append)
        ew.run()
        assert exp_res == [str(out_csv)]
        exported_channels = sum(
            1
            for line in out_csv.read_text(encoding="utf-8").splitlines()
            if line.startswith("# Channel:")
        )
        assert exported_channels == 300
    finally:
        wide_insp.release_cache_pin()


def test_vectorized_extract_pulses_equivalence_and_speed() -> None:
    """Vectorized extract_pulses preserves gap/NaN/bounce rules and scans 4M samples fast."""
    t1 = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7], dtype=np.float64)
    v1 = np.array([0.0, 5.0, 5.0, 0.0, 5.0, np.nan, 5.0, 0.0], dtype=np.float64)
    g1 = np.array([False, False, False, False, False, False, False, False])
    train = extract_pulses(
        [(t1, v1, g1)],
        source_id="ttl",
        kind=TriggerKind.FRAME_STROBE,
        threshold=2.5,
        min_interval=0.05,
    )
    assert len(train.times) == 1
    assert train.incomplete_count == 1

    n = 4_000_000
    times = np.arange(n, dtype=np.float64) * 2e-5  # 50 kHz, 80 s
    vals = ((np.arange(n) % 1000) < 100).astype(np.float64) * 5.0
    t0 = time.perf_counter()
    fast_train = extract_pulses(
        [(times[:2_000_000], vals[:2_000_000]), (times[2_000_000:], vals[2_000_000:])],
        source_id="strobe_50khz",
        kind=TriggerKind.SPARSE_EVENTS,
        threshold=2.5,
        min_interval=0.01,
    )
    elapsed = time.perf_counter() - t0
    assert len(fast_train.times) == 3999  # first sample starts high without prior low
    assert elapsed < 1.0, f"extract_pulses took {elapsed:.3f}s on 4M samples"


def test_swap_store_linear_scaling_3d_meter_suspects_and_large_skeleton(tmp_path: Path) -> None:
    """EditProgram builds 2,000 swaps fast, 3D Z-jumps flag in meters, and >64-pt bones work."""
    src = "/tmp/multi_animal_pose.csv"
    swaps = SwapStore()
    parts = tuple(f"kp{i}" for i in range(10))
    members = tuple((lane, p, f"{lane}_{p}") for lane in ("mouseA", "mouseB") for p in parts)
    swaps.set_groups(
        src,
        [SwapGroup(name="mice", lanes=("mouseA", "mouseB"), parts=parts, members=members)],
    )
    for frame in range(10, 20_010, 10):  # 2,000 swaps
        swaps.add(src, SwapEvent(index=frame, group="mice", lanes=("mouseA", "mouseB")))

    t0 = time.perf_counter()
    prog = edit_program.build(src, swaps, PointEditStore())
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5, f"EditProgram.build took {elapsed:.3f}s for 2,000 swaps"
    assert len(prog.boundaries) == 2000
    all_pts = [f"{lane}_{p}" for lane in ("mouseA", "mouseB") for p in parts]
    for sample_idx in (0, 10, 20, 155, 19_995):
        from_prog = {
            pt: prog.source_of(pt, sample_idx)
            for pt in all_pts
            if prog.source_of(pt, sample_idx) != pt
        }
        assert from_prog == swaps.point_sources(src, sample_idx)

    # 3D pose in meters (0.25 m arena) with a Z-only +0.12 m teleport on frame 50.
    pose_cache = tmp_path / "pose3d_meters"
    pose_cache.mkdir()
    frames = 120
    t_pose = np.arange(frames, dtype=np.float64) / 60.0
    xs = 0.10 + 0.08 * np.cos(t_pose * 2.0)
    ys = 0.10 + 0.08 * np.sin(t_pose * 2.0)
    zs = np.full(frames, 0.03, dtype=np.float64)
    zs[50] = 0.16  # 13 cm vertical teleport in Z while X and Y stay smooth!
    PyramidBuilder(pose_cache, "snout_x").build_and_save(t_pose, xs)
    PyramidBuilder(pose_cache, "snout_y").build_and_save(t_pose, ys)
    PyramidBuilder(pose_cache, "snout_z").build_and_save(t_pose, zs)
    schema = PoseSchema(
        points=(PosePoint(individual="", bodypart="snout", axes=("x", "y", "z")),),
        frame_indexed=True,
    )
    suspects = find_suspects_in_cache(src, pose_cache, schema, TimeMap(), threshold=0.6)
    flagged_indices = {s.sample_index for s in suspects}
    assert 50 in flagged_indices or 51 in flagged_indices

    # Skeleton inference supports > 64 3D markers.
    assert MAX_POINTS >= 256
    n_pts = 96
    grid = np.zeros((40, n_pts, 3), dtype=np.float64)
    base_pos = np.stack([np.arange(n_pts) * 0.01, np.zeros(n_pts), np.zeros(n_pts)], axis=1)
    for f in range(40):
        grid[f] = base_pos + np.array([0.002 * f, 0.001 * np.sin(f), 0.0])
    est = infer_skeleton([f"m_{i}" for i in range(n_pts)], grid)
    assert len(est.edges) == n_pts - 1


def test_changes_search_zero_resolver_batch_import_stems_and_stimulus_cap(
    qapp: QApplication, qtbot, tmp_path: Path
) -> None:
    """Changes search skips resolver, BatchImport disambiguates folders, Stimulus caps rows."""
    annotations = AnnotationStore()
    edits = PointEditStore()
    swaps = SwapStore()
    resolver_calls = 0

    def _counting_resolver(key: PointKey) -> tuple[float, str, int]:
        nonlocal resolver_calls
        resolver_calls += 1
        return float(key.index) * 0.01, "cam0.mp4", key.index

    rows = [(i, "nose" if i % 2 == 0 else "tail_base", 10.0, 20.0, "") for i in range(300)]
    edits.load_source("/tmp/pose.csv", rows)
    panel = ChangesPanel(annotations, edits, swaps)
    qtbot.addWidget(panel)
    panel.set_correction_resolver(_counting_resolver)
    initial_calls = resolver_calls
    assert initial_calls == 300

    resolver_calls = 0
    panel.search_edit.setText("nose")
    assert resolver_calls == 0
    assert len(panel.rows) == 150

    # Multi-camera folder disambiguation when every camera is named video.mp4.
    cam0_dir = tmp_path / "cam00"
    cam1_dir = tmp_path / "cam01"
    cam0_dir.mkdir()
    cam1_dir.mkdir()
    v0 = cam0_dir / "video.mp4"
    v1 = cam1_dir / "video.mp4"
    p0 = cam0_dir / "video_DLC_resnet50.csv"
    p1 = cam1_dir / "video_DLC_resnet50.csv"
    for f in (v0, v1):
        f.write_bytes(b"mp4")
    dlc_header = "scorer,DLC,DLC\nbodyparts,nose,nose\ncoords,x,y\n0,10.0,20.0\n"
    p0.write_text(dlc_header, encoding="utf-8")
    p1.write_text(dlc_header, encoding="utf-8")

    from avialsync.loaders.tracking_loader import TrackingLoader

    candidates = [(p0, TrackingLoader, None), (p1, TrackingLoader, None)]
    dlg = BatchImportDialog(candidates, video_paths=[str(v0), str(v1)])
    qtbot.addWidget(dlg)
    decisions = {path: (cfg or {}).get("overlay_video") for path, _ldr, cfg in dlg.get_selections()}
    assert decisions[p0] == str(v0)
    assert decisions[p1] == str(v1)
    combo_texts = [dlg._role_combos[0].itemText(i) for i in range(dlg._role_combos[0].count())]
    assert any("cam00/video.mp4" in txt for txt in combo_texts)
    assert any("cam01/video.mp4" in txt for txt in combo_texts)

    # StimulusGridDialog caps mounted table rows when thousands of pulses arrive.
    stim_cache = tmp_path / "stim_cache"
    stim_cache.mkdir()
    t_stim = np.linspace(0.0, 10.0, 100, dtype=np.float64)
    PyramidBuilder(stim_cache, "stim").build_and_save(t_stim, np.zeros_like(t_stim))
    from avialsync.core.channel_reader import MappedChannelReader

    pr = PyramidReader(stim_cache, "stim")
    try:
        opt = StimulusChannelOption(
            label="stim",
            reference=ReaderReference(cache_dir=stim_cache, channel_id="stim", source_id="stim"),
            reader=MappedChannelReader(pr, TimeMap(), source_id="stim"),
        )
        stim_dlg = StimulusGridDialog([opt])
        qtbot.addWidget(stim_dlg)
        stim_dlg.set_events([i * 0.01 for i in range(5000)])
        assert stim_dlg.event_table.rowCount() <= 500
        assert len(stim_dlg.selected_events()) == MAX_GRID_EVENTS
    finally:
        pr.close()
