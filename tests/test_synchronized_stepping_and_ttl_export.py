"""Regression tests for synchronized multi-camera/multi-view stepping and TTL/event video export."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import av
import numpy as np
import pytest

from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.errors import ExportError
from avialsync.core.messages import Message
from avialsync.core.pyramid import PyramidBuilder, PyramidReader
from avialsync.core.timeline import TimeMap
from avialsync.core.video_timing import adjacent_frame_time, frame_index_at
from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.stimulus_grid_export import (
    GridLabels,
    GridVideo,
    _reader_bounds,
    export_stimulus_grid,
    plan_grid,
)
from avialsync.engine.stimulus_grid_worker import StimulusEventScanWorker
from avialsync.engine.transcode import encode_video, remux_clip
from avialsync.ui import stimulus_grid_sources as sources
from avialsync.ui.main_window import MainWindow
from avialsync.ui.stimulus_grid_dialog import (
    StimulusGridDialog,
)
from avialsync.ui.stimulus_grid_rows import GridRowsPanel
from avialsync.ui.tracking_3d_pane import Tracking3DPane


def test_adjacent_frame_time_steps_cleanly_from_mid_interval_and_before_start() -> None:
    """Backward step from inside frame k's interval must land on k - 1, never stay on k."""
    table = np.array([1.0, 1.04, 1.08, 1.12], dtype=np.float64)

    # Before first frame: both forward and backward land on frame 0.
    assert adjacent_frame_time(table, 0.5, 1) == pytest.approx(1.0)
    assert adjacent_frame_time(table, 0.5, -1) == pytest.approx(1.0)

    # Mid-interval inside frame 2 ([1.08, 1.12)): frame 2 is on screen.
    assert frame_index_at(table, 1.095) == 2
    assert adjacent_frame_time(table, 1.095, -1) == pytest.approx(1.04)
    assert adjacent_frame_time(table, 1.095, 1) == pytest.approx(1.12)

    # Clamping at ends.
    assert adjacent_frame_time(table, 1.0, -1) == pytest.approx(1.0)
    assert adjacent_frame_time(table, 1.12, 1) == pytest.approx(1.12)


def test_utc_epoch_and_drifted_roundtrip_never_drops_pose_or_readout_samples(
    tmp_path: Path,
) -> None:
    """Float64 TimeMap round-trips at UTC epoch must resolve the exact frame sample."""
    cache = tmp_path / "utc_pose"
    cache.mkdir()
    times = np.arange(60, dtype=np.float64) / 30.0
    values = np.arange(60, dtype=np.float64) * 10.0
    # Mark a gap after sample 10 to verify +ULP drift at sample 10 is not rejected as in-gap.
    times_with_gap = times.copy()
    times_with_gap[11:] += 1.0
    PyramidBuilder(cache, "nose_x").build_and_save(times_with_gap, values)

    tm = TimeMap(offset=1_700_000_000.123456, drift_ms_per_hour=15.0)
    reader = MappedChannelReader(PyramidReader(cache, "nose_x"), tm, "pose.csv")

    for idx in (0, 1, 2, 10, 11, 59):
        t_master = tm.to_master(float(times_with_gap[idx]))
        sample = reader.sample_at(t_master)
        avail = reader.available_sample_at(t_master)
        assert sample is not None and sample[0] == idx
        assert avail is not None and avail == (idx, float(values[idx]))


def test_coexposed_cameras_and_all_views_step_one_frame_together(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Co-exposed cameras with sub-ms skew + 3D + 2D overlay + plots step in lockstep."""
    monkeypatch.setattr(MainWindow, "_run_diagnostics", lambda _self: None)
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1100, 760)
    window.show()

    paths = [Path(f"tests/fixtures/videos/camera_{i}.mp4").resolve() for i in (1, 2)]
    for path in paths:
        window._load_video(path)

    # Build matching 30 Hz 3D tracking + plot channels.
    pose_cache = tmp_path / "pose3d"
    pose_cache.mkdir()
    cam1_path, cam2_path = str(paths[0]), str(paths[1])
    try:
        qtbot.waitUntil(
            lambda: (
                cam1_path in window._video_frame_times and cam2_path in window._video_frame_times
            ),
            timeout=15000,
        )
        pane_paths = window.video_grid.pane_paths()
        pane1 = window.video_grid.panes[pane_paths.index(cam1_path)]
        pane2 = window.video_grid.panes[pane_paths.index(cam2_path)]

        # Give camera 2 a +0.35 ms master-time co-exposure skew.
        pane2.time_map.offset = -0.00035
        times = np.asarray(window._video_frame_times[cam1_path][:30], dtype=np.float64)
        for axis_idx, axis in enumerate("xyz"):
            PyramidBuilder(pose_cache, f"nose_{axis}").build_and_save(
                times, np.arange(len(times), dtype=np.float64) + axis_idx * 100.0
            )
            PyramidBuilder(pose_cache, f"tail_{axis}").build_and_save(
                times, np.arange(len(times), dtype=np.float64) + 50.0 + axis_idx * 100.0
            )
        window.plot_pane.load_channels(pose_cache, ["nose_x", "nose_y", "nose_z"])
        window.plot_pane.wait_for_pending_rows()
        window.tracking_3d_pane.set_readers(
            [PyramidReader(pose_cache, f"{pt}_{ax}") for pt in ("nose", "tail") for ax in "xyz"]
        )
        window.tracking_3d_pane.show()
        window.clock.set_bounds(0.0, float(times[-1]))
        window.plot_pane.set_timeline_bounds(0.0, float(times[-1]))
        qtbot.waitUntil(
            lambda: (
                window.plot_pane._page_worker is None
                and window.plot_pane._last_installed_generation == window.plot_pane._page_generation
            ),
            timeout=10000,
        )

        # Even when camera 1 is selected, stepping advances BOTH co-exposed cameras together.
        window._select_video(cam1_path)
        window.player.seek(float(times[0]) + 0.00035, exact=True, snap_to_evidence=False)
        initial_page_gen = window.plot_pane._page_generation

        for expected_frame in (1, 2, 3, 4):
            window.player.step_frame(1)
            t_now = window.clock.state.t
            assert pane1.frame_record_at(t_now)[0] == expected_frame
            assert pane2.frame_record_at(t_now)[0] == expected_frame
            assert window.tracking_3d_pane.canvas.positions[0, 0] == pytest.approx(
                float(expected_frame)
            )
            # Stepping inside the same 10 s sweep page never respawns PlotPageWorker.
            assert window.plot_pane._page_generation == initial_page_gen

        # Scrub mid-interval inside frame 4, then step backward frame-by-frame:
        # the very first backward step must reach frame 3 on both cameras (not stay on 4).
        mid_frame_4 = float(times[4]) + 0.015
        window.player.seek(mid_frame_4, exact=True, snap_to_evidence=False)
        assert pane1.frame_record_at(window.clock.state.t)[0] == 4
        assert pane2.frame_record_at(window.clock.state.t)[0] == 4

        for expected_frame in (3, 2, 1, 0):
            window.player.step_frame(-1)
            t_now = window.clock.state.t
            assert pane1.frame_record_at(t_now)[0] == expected_frame
            assert pane2.frame_record_at(t_now)[0] == expected_frame
            assert window.tracking_3d_pane.canvas.positions[0, 0] == pytest.approx(
                float(expected_frame)
            )
    finally:
        window.close()


def test_tracking_3d_uses_causal_sample_and_live_time_map_and_fine_slider(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """3D pose holds sample k across [t_k, t_{k+1}) and follows live TimeMap offset edits."""
    cache = tmp_path / "causal_3d"
    cache.mkdir()
    times = np.array([0.0, 0.5, 1.0], dtype=np.float64)
    tm = TimeMap()
    readers = []
    for axis_idx, axis in enumerate("xyz"):
        PyramidBuilder(cache, f"head_{axis}").build_and_save(
            times, np.array([10.0, 20.0, 30.0]) + axis_idx
        )
        readers.append(MappedChannelReader(PyramidReader(cache, f"head_{axis}"), tm, "pose3d"))

    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.set_readers(readers)

    # At t = 0.45 (90% through frame 0's interval), causal selection still shows frame 0 (10.0),
    # rather than jumping early to frame 1 (20.0).
    pane.set_cursor(0.45)
    assert pane.canvas.positions[0, 0] == pytest.approx(10.0)

    # Live TimeMap mutation shifts the 3D view immediately without re-preparing readers.
    tm.offset = -1.0
    pane.set_cursor(tm.to_master(0.5))
    assert pane.canvas.positions[0, 0] == pytest.approx(20.0)

    # Transport A/B loop pins record exact frame-stepped timestamps on a 1-hour timeline
    # instead of quantizing [ and ] to 1/10000th of 3600 s (360 ms = 11 frames).
    monkeypatch.setattr(MainWindow, "_run_diagnostics", lambda _self: None)
    window = MainWindow()
    qtbot.addWidget(window)
    window.transport.set_bounds(0.0, 3600.0)
    window.transport.set_time(1234.567)
    window.transport._on_ab_in()
    window.transport.set_time(1235.901)
    window.transport._on_ab_out()
    assert window.transport.ab_range() == pytest.approx((1234.567, 1235.901), abs=1e-9)
    window.close()


def test_falling_edge_active_low_ttl_and_gap_aware_stimulus_scan(tmp_path: Path) -> None:
    """Active-low TTL lines (idle 5 V -> 0 V pulse) and gapped channels scan accurately."""
    cache = tmp_path / "active_low_ttl"
    cache.mkdir()
    times = np.arange(0.0, 4.0, 0.001, dtype=np.float64)
    # Idle high at 5.0 V; active-low pulses at 0.800 s, 1.900 s, and 3.100 s.
    values = np.full_like(times, 5.0)
    for onset in (0.8, 1.9, 3.1):
        mask = (times >= onset) & (times < onset + 0.05)
        values[mask] = 0.0
    PyramidBuilder(cache, "stim_active_low").build_and_save(times, values)

    ref = ReaderReference(cache, "stim_active_low")
    found: list[tuple[float, ...]] = []
    worker = StimulusEventScanWorker(ref, threshold=2.5, min_interval=0.1, falling_edge=True)
    worker.finished.connect(found.append)
    worker.run()

    assert len(found) == 1
    assert found[0] == pytest.approx((0.8, 1.9, 3.1), abs=0.002)

    # Also verify gap handling: a rising onset before a gap is kept, while a jump
    # from low->high *across* an unrecorded gap is ignored as an unmeasured onset.
    # Real rise at 0.1 s in segment 1; segment 2 starts high after gap, then rises at 5.3 s.
    t_seg1 = np.array([0.0, 0.1, 0.2, 0.3], dtype=np.float64)
    v_seg1 = np.array([0.0, 1.0, 1.0, 0.0], dtype=np.float64)
    t_seg2 = np.array([5.0, 5.1, 5.2, 5.3], dtype=np.float64)
    v_seg2 = np.array([1.0, 1.0, 0.0, 1.0], dtype=np.float64)
    PyramidBuilder(cache, "gapped_ttl").build_and_save(
        np.concatenate([t_seg1, t_seg2]), np.concatenate([v_seg1, v_seg2])
    )
    gapped_found: list[tuple[float, ...]] = []
    gapped_worker = StimulusEventScanWorker(
        ReaderReference(cache, "gapped_ttl"), threshold=0.5, min_interval=0.05
    )
    gapped_worker.finished.connect(gapped_found.append)
    gapped_worker.run()
    assert gapped_found[0] == pytest.approx((0.1, 5.3), abs=1e-6)


def test_session_event_sources_pending_channels_and_per_event_clip_export(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TTL sync events, trials, messages, annotations, pending rows, and clip export all work."""
    monkeypatch.setattr(MainWindow, "_run_diagnostics", lambda _self: None)
    window = MainWindow()
    qtbot.addWidget(window)

    video_path = tmp_path / "cam.mp4"
    colors = [(220, 40, 40), (40, 220, 60), (40, 80, 220), (220, 200, 40)]
    frames = [
        (np.full((48, 64, 3), colors[(idx // 10) % len(colors)], dtype=np.uint8), idx / 10.0)
        for idx in range(40)
    ]
    encode_video(video_path, frames, rate=Fraction(10, 1))
    window._load_video(video_path)
    qtbot.waitUntil(lambda: bool(window.video_grid.panes), timeout=10000)

    # Populate session event sources (without any plotted channel yet).
    window.transport.overview.set_ttl_events([(0.5, "TTL 1"), (1.5, "TTL 2"), (2.5, "TTL 3")])
    window.transport.overview.set_segments([(0.4, 1.2, "Trial 1"), (1.8, 2.8, "Trial 2")])
    window.message_store.set_source_messages(
        "rig",
        (
            Message(text="StimOn", time=0.6, channel="Stimulus"),
            Message(text="Note", time=1.6, channel="Notes"),
        ),
    )
    window.annotation_store.add_point(2.2, "Flagged")

    assert sources.has_stimulus_inputs(window)
    ev_sources = sources.event_sources(window)
    labels = [opt.label for opt in ev_sources]
    assert any("TTL" in lbl for lbl in labels)
    assert any("Trials" in lbl for lbl in labels)
    assert any("Recorded Messages" in lbl for lbl in labels)
    assert any("Messages — Stimulus" in lbl for lbl in labels)
    assert any("Annotations" in lbl for lbl in labels)

    # Also verify a channel queued in plot_pane._pending_rows is surfaced by sensor_groups.
    pending_cache = tmp_path / "pending_nwb"
    pending_cache.mkdir()
    PyramidBuilder(pending_cache, "ttl_pending").build_and_save(
        np.array([0.0, 1.0, 2.0]), np.array([0.0, 1.0, 0.0])
    )
    window.plot_pane._pending_rows.append(
        (pending_cache, "ttl_pending", TimeMap(), str(pending_cache), True)
    )
    groups, ch_triggers = sources.sensor_groups(window)
    assert any(ch.label == "ttl_pending" for ch in ch_triggers)
    assert len(groups) == 1
    window.plot_pane._pending_rows.clear()

    # Open dialog with ONLY discrete event sources (no sensor channels): immediately ready!
    rows = GridRowsPanel(sources.camera_rows(window), [])
    dialog = StimulusGridDialog([], window, rows, event_sources=ev_sources)
    qtbot.addWidget(dialog)
    assert dialog.selected_events() == pytest.approx((0.5, 1.5, 2.5))
    assert not dialog.threshold_spin.isEnabled()
    assert dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled()

    # Switch to per-event trimmed clips mode and verify > 12 events are selectable.
    dialog.export_mode_combo.setCurrentIndex(dialog.export_mode_combo.findData("clips"))
    assert dialog.export_mode() == "clips"
    many_events = tuple(0.1 * idx for idx in range(1, 16))
    dialog.set_events(many_events)
    assert len(dialog.selected_events()) == 15

    # Export actual per-event clips (including an event whose pre-roll crosses t < 0).
    clips_dir = tmp_path / "event_clips"
    clips_dir.mkdir()
    clip_specs = sources.event_clips(
        window, rows.camera_keys(), (0.1, 1.5), before=0.25, after=0.35, out_dir=clips_dir
    )
    assert len(clip_specs) == 2
    for media_src, s0, s1, out_file in clip_specs:
        assert remux_clip(media_src, out_file, s0, s1)
        with av.open(str(out_file)) as container:
            decoded = list(container.decode(video=0))
        assert len(decoded) >= 1

    window.close()


def test_remux_clip_preserves_b_frames_up_to_cut_end(tmp_path: Path) -> None:
    """H.264 stream copy with B-frames must not drop B-frames after a P-frame with PTS > end."""
    src = tmp_path / "bframes.mp4"
    dst = tmp_path / "trimmed_bframes.mp4"
    fps = 30
    with av.open(str(src), mode="w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width = 64
        stream.height = 48
        stream.pix_fmt = "yuv420p"
        stream.time_base = Fraction(1, 90_000)
        stream.codec_context.time_base = Fraction(1, 90_000)
        stream.codec_context.max_b_frames = 3
        stream.codec_context.gop_size = 30
        stream.options = {"preset": "fast", "crf": "18", "b-adapt": "0"}
        for idx in range(30):
            arr = np.full((48, 64, 3), (idx * 8 % 255, 80, 140), dtype=np.uint8)
            vf = av.VideoFrame.from_ndarray(arr, format="rgb24").reformat(format="yuv420p")
            vf.pts = idx * 3000
            vf.time_base = Fraction(1, 90_000)
            for pkt in stream.encode(vf):
                container.mux(pkt)
        for pkt in stream.encode(None):
            container.mux(pkt)

    end_t = 10 / 30.0
    assert remux_clip(src, dst, 0.0, end_t)
    with av.open(str(dst)) as out_container:
        out_stream = out_container.streams.video[0]
        tb = float(out_stream.time_base)
        pts_seconds = sorted(
            float(frame.pts * tb)
            for frame in out_container.decode(out_stream)
            if frame.pts is not None
        )
    # Every frame up to frame 10 (0.3333 s) must be present without B-frame tail truncation.
    assert max(pts_seconds) >= end_t - 1e-3
    assert len([t for t in pts_seconds if t <= end_t + 1e-3]) >= 11


def test_stimulus_grid_respects_exact_timemap_and_intertrial_gaps(tmp_path: Path, qapp) -> None:
    """Camera tiles render 'No footage' outside exact TimeMap coverage and inside FrameGaps."""
    # Empty frame_times raises ExportError instead of IndexError.
    empty_reader = SimpleNamespace(frame_times=np.empty(0, dtype=np.float64), stream=None)
    with pytest.raises(ExportError):
        _reader_bounds(empty_reader, TimeMap())  # type: ignore[arg-type]

    # Create a video with a large unfilmed inter-trial gap between t=0.2 and t=5.0 s.
    video_path = tmp_path / "gapped_cam.mp4"
    bright = np.full((48, 64, 3), (240, 220, 200), dtype=np.uint8)
    encode_video(
        video_path,
        [(bright, 0.0), (bright, 0.1), (bright, 0.2), (bright, 5.0), (bright, 5.1)],
        rate=Fraction(10, 1),
    )
    out = tmp_path / "gap_grid.mp4"
    labels = GridLabels(
        title="Grid",
        event="Event {index}",
        no_footage="No footage",
        ruler="{before:.2f} .. +{after:.2f}",
        current="{time:+.2f} s",
        no_signal="No signal",
        frame="Frame {index}",
    )
    # Event at t=2.5 s sits squarely inside the [0.2, 5.0] unrecorded gap.
    export_stimulus_grid(
        [GridVideo(video_path, "Cam")],
        [2.5],
        before=0.0,
        after=0.2,
        destination=out,
        labels=labels,
        fps=5,
    )
    with av.open(str(out)) as container:
        img = next(container.decode(video=0)).to_ndarray(format="rgb24")
    cell = plan_grid(1, 1, 0.0, 0.2).cell_rect(0, 0)
    tile = img[cell.y() + 4 : cell.bottom() - 4, cell.x() + 4 : cell.right() - 4]
    # Dark 'No footage' background (#20292b) instead of the bright (240, 220, 200) frozen frame!
    assert float(tile.mean()) < 100.0
