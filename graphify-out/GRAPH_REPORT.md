# Graph Report - avialview  (2026-08-22)

## Corpus Check
- 257 files · ~396,280 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 5842 nodes · 10975 edges · 284 communities (261 shown, 23 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 987 edges (avg confidence: 0.59)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `01879a81`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- MainWindow
- test_loaders_open_ephys.py
- CSVLoader
- Transport
- export_controller.py
- VideoPane
- AOLEksLoader
- PyramidReader
- open_ephys_session.py
- DECISIONS.md — lightweight ADR log
- aol_session_loader.py
- MessageStore
- TimelineOverview
- PaintCanvas
- test_playback_smoothness.py
- test_pane_proportions.py
- main_window.py
- test_core_pyramid.py
- Known Traps
- _apply
- AOLMetricLoader
- PyAVReader
- VideoStandardLoader
- NeoLoader
- plot_pane.py
- test_import_streaming.py
- test_cli_demo.py
- test_interaction_standard.py
- MappedChannelReader
- generate_guide_screenshots.py
- SweepWindowControl
- SessionState
- test_close_and_focus.py
- test_loaders_video.py
- test_pyav_reader.py
- test_video_pane.py
- AvialSync — Project Blueprint (v1)
- _parse_args
- TimeMap
- test_frame_identity.py
- session_controller.py
- SeekGroup
- test_scrubbing.py
- video_standard.py
- ImportWorker
- test_theme_colors.py
- sync.py
- test_worker_lifetime.py
- PlotPane
- format_time
- PyramidBuilder
- Path
- ._on_evidence_changed
- .can_open
- test_seek_backends.py
- SourceOpenError
- AOLVideoExtractionLoader
- VideoMetadata
- TimeDisplayMode
- export_worker.py
- test_workload_responsiveness.py
- _JobWorker
- import_controller.py
- test_ci_platform_config.py
- test_core_coverage_edges.py
- write_recording
- DummyVideoLoader
- SourceInspection
- test_ui_plot_row_geometry.py
- Message
- test_ui_sensor_mapping.py
- Player
- test_messages.py
- capture
- pyramid.py
- PlotInteractionController
- AnnotationStore
- ChannelKey
- PointColorRegistry
- test_plugin_discovery.py
- demo.py
- prepare_release.py
- Tracking3DCanvas
- test_ui_follow.py
- test_aol_chunk_boundaries.py
- test_engine_importer.py
- test_theme_tooltips.py
- test_subprocess_no_window.py
- test_ui_shortcut_reach.py
- LoaderRegistry
- Path
- make_fixtures.py
- test_ui_layout_resize.py
- extract_ttl_edges
- TimelineEvidence
- AOLEncoderLoader
- .paintEvent
- _pulses
- test_typed_source_errors.py
- Tracking3DPane
- .open
- test_aol_pose_routing.py
- test_never_freeze.py
- test_ui_dialogs.py
- tracking_3d_pane.py
- theme.py
- DemoLaunch
- test_frame_indexed.py
- write_video
- transcode.py
- test_packaging_smoke.py
- _FakePane
- test_sync_golden.py
- load_video
- ._load_level
- VideoPropertiesPanel
- AvialSync Plot UX Refinement Plan
- frame_index_at
- fit_exact_index_mapping
- UiHeartbeat
- TESTING.md
- test_ui_plot_sliced_refresh.py
- ARCHITECTURE.md
- ToyBinarySource
- DropScanWorker
- .__init__
- Path
- ProxyWorker
- generate_screenshots
- Path
- test_bench_plot_pane.py
- test_demo_data.py
- test_transport_resize.py
- ImportReportDialog
- job_manager.py
- open_ephys_format.py
- build_manifest
- VideoGrid
- test_annotation_frames.py
- _MappingLoader
- Contributor Covenant Code of Conduct
- 2026-07 · D-020 · Inspection layer — what is surfaced where
- Data handling
- test_engine_layering.py
- diagnostics.py
- JobManager
- test_aol_loaders.py
- AOLSessionSource
- test_conda_recipe.py
- TestMeasureMarkers
- .__init__
- BatchImportDialog
- ui/__init__.py
- VideoOpenWorker
- test_bench_cursor_path
- test_video_grid.py
- generate_icons.py
- test_job_thread_lifetime.py
- Desktop installers
- Tutorial: import sensor and recording data
- AvialSync — Model Handout
- MIGRATION_PYAV.md — libmpv → PyAV, and a pip-only install
- capture
- test_a_type_names_the_data_never_the_rig
- Job
- .eventFilter
- ._read_batches
- QMouseEvent
- ._relayout
- test_headless_core.py
- PROMPTS.md — kickoff prompts per phase
- QLabel
- SyncWorker
- Video Extraction Toolbox — output schema for AvialSync
- ._build_channel_by_channel
- _ArrayReader
- TestPluginDiscovery
- test_prepare_release.py
- Data Output Schema — for AvialSync integration
- no_startup_diagnostics
- 2026-07 · D-022 · Interaction standard — visible surface, depth in menus, shortcuts as accelerators
- 2. Evidence-based alignment from TTL or frame triggers
- .close
- ndarray
- _QuickWorker
- TestShowDelta
- Plugin guide
- Troubleshooting
- Phase Status
- VideoSurface
- _with_messages
- TestEmptyChannel
- _BulkLoader
- Quickstart
- Development and release
- User Guide
- Sessions, proxies, and the 3D view
- Performance Budgets (engineering-certified where ★)
- smoke_bundle
- AvialSync
- .can_open
- SyncProposal
- Architecture
- Tutorial: inspect a first session
- release
- Signal Wiring Map
- PlotHeader
- ._apply_default_splitter_sizes
- inspection.py
- .fit_current_pose
- ShortcutsDialog
- 2026-08 · D-081 · The video-extraction export is the ROI-metric surface, and it is HDF5
- Formats
- Licensing
- Tutorial: flag frames and export
- build_bundle
- .test_boundary_duplicate_is_collapsed
- .add_pane
- AOL2DTrack
- .eventFilter
- ._timestamp_dtype
- test_packaging_spec.py
- 2026-07 · D-032 · Headless CI uses null video, decoded-frame evidence, and explicit mpv ownership — AMENDED by D-075
- 2026-07 · D-037 · Releases require a tag reachable from main
- 2026-07 · D-043 · Presentation timestamps own video timing and exact interaction
- 2026-07 · D-044 · Plot presentation separates review, sweep, and scope
- 2026-07 · D-045 · The AOL encoder axis is seconds-since-midnight, unwrapped
- 2026-07 · D-046 · Pose data drives the overlay and 3D view, never plot rows
- 2026-08 · D-080 · AOL extracted-metric MAT files are detected by filename, not a fixed folder
- pull_request_template.md
- sign_notarize.sh
- .set_sync_mapping
- .read_all_chunks
- ._generate_proxy
- .reset_view
- .closeEvent
- ._on_sensor_mapping_changed
- DummyTimeSeriesLoader
- test_three_camera_four_stream_session_can_be_cached_and_queried
- 2026-07 · D-033 · Packaging inputs are explicit and CI artifact builds are a separate gate
- 2026-07 · D-034 · Themes are palette/font appearance, never interaction redesign
- 2026-07 · D-036 · PR and tag quality use one cross-platform test contract
- 2026-07 · D-038 · Windows video panes use libmpv's Qt OpenGL render API — SUPERSEDED by D-075
- 2026-07 · D-039 · Release bundles own the complete media runtime — AMENDED by D-075
- 2026-07 · D-040 · Sidecar writes use bounded concurrency and failures remain observable
- 2026-07 · D-042 · Plots use one fixed, shared oscilloscope sweep
- ._epoch_unit_from_format
- _resolved_marker_color
- _nearest_index
- .set_time
- .set_viewport
- ._on_pane_double_clicked
- .visible_panes
- test_bench_sync.py
- test_packaging_metadata.py
- test_worker_thread_teardown.py
- 2026-07 · D-023 · Benchmarks CI-gated; budget-assertion pattern; CI multiplier
- 2026-07 · D-029 · Separate GitHub workload correctness from local speed certification
- 2026-07 · D-030 · Test-level watchdog for cross-platform Qt verification
- 2026-07 · D-031 · Libmpv commands stay on the Qt-owning thread — SUPERSEDED by D-075
- .wheelEvent
- .resizeEvent
- .frame_records_at
- main_window
- conf.py
- commit-msg
- post-commit
- pre-commit
- make_appimage.sh
- make_dmg.sh
- avialsync
- set_video_coverage
- tiny_batches
- .count
- .display_aliases

## God Nodes (most connected - your core abstractions)
1. `MainWindow` - 371 edges
2. `PlotPane` - 114 edges
3. `TimeMap` - 111 edges
4. `PyramidReader` - 104 edges
5. `LoaderRegistry` - 89 edges
6. `DECISIONS.md — lightweight ADR log` - 85 edges
7. `SourceOpenError` - 72 edges
8. `PyramidBuilder` - 69 edges
9. `VideoStandardLoader` - 69 edges
10. `Transport` - 69 edges

## Surprising Connections (you probably didn't know these)
- `test_main_window_places_3d_view_beside_video_grid()` --calls--> `MainWindow`  [INFERRED]
  tests/test_ui_tracking_3d.py → src/avialsync/ui/main_window.py
- `test_frame_records_at_empty_grid()` --calls--> `VideoGrid`  [INFERRED]
  tests/test_annotation_frames.py → src/avialsync/ui/video_grid.py
- `test_frame_records_at_offset_applied()` --calls--> `VideoGrid`  [INFERRED]
  tests/test_annotation_frames.py → src/avialsync/ui/video_grid.py
- `test_frame_records_at_single_pane()` --calls--> `VideoGrid`  [INFERRED]
  tests/test_annotation_frames.py → src/avialsync/ui/video_grid.py
- `test_frame_records_at_two_panes()` --calls--> `VideoGrid`  [INFERRED]
  tests/test_annotation_frames.py → src/avialsync/ui/video_grid.py

## Import Cycles
- None detected.

## Communities (284 total, 23 thin omitted)

### Community 0 - "MainWindow"
Cohesion: 0.02
Nodes (53): QMainWindow, drag_enter(), on_drop_scan_error(), QDragEnterEvent, on_import_thread_finished(), Release the completed import and begin the next queued source., Re-import all provisional frame-indexed sources using the video fps., Feed the 3D view from registered pose sources plus any plotted XYZ. (+45 more)

### Community 1 - "test_loaders_open_ephys.py"
Cohesion: 0.05
Nodes (72): Path, Return per-frame exposure evidence from a ``frame_number,timestamp`` sidecar.…, read_frame_timestamps(), _drop(), _layout(), datetime, parametrize, Path (+64 more)

### Community 2 - "CSVLoader"
Cohesion: 0.14
Nodes (21): CSVLoader, Loads CSV files in chunks using polars., Path, `rate_hz=None` means irregular; a plainly 100 Hz file must not claim it., Claiming a rate for jittered data would be a false statement., The rate must be in Hz regardless of the column's unit., test_csv_loader_applies_selected_timezone(), test_csv_loader_basic() (+13 more)

### Community 3 - "Transport"
Cohesion: 0.04
Nodes (48): QResizeEvent, Button click — set A/B out-point (button state managed here)., Parse HH:MM:SS.fff, MM:SS, or bare seconds., Transport bar: play/pause, frame step, scrub slider, A/B loop, rate control,…, Set the A/B loop in-point at the current slider position (public, D-022.1)., Set the A/B loop out-point at the current slider position (public, D-022.1)., The master-timeline extent currently displayed. Public because…, The currently displayed status message. (+40 more)

### Community 4 - "export_controller.py"
Cohesion: 0.05
Nodes (48): QWidget, Grab a widget's current visual content as a QPixmap., snapshot_widget(), export_annotations(), export_data_slice(), export_snapshot(), export_snapshot_for_pane(), export_video_clip() (+40 more)

### Community 5 - "VideoPane"
Cohesion: 0.04
Nodes (33): DecodeWorker, ndarray, QCloseEvent, QObject, setter, Slot, Decode the newest requested time, if one is still outstanding., Close the reader on its own thread, where it was opened. (+25 more)

### Community 6 - "AOLEksLoader"
Cohesion: 0.13
Nodes (9): AOLEksLoader, Return one ChannelInfo per x/y/z coordinate. EKS rows are one video frame each,…, Tracking Data (2D/3D). Format: standard CSV with header row. Columns follow the…, EKS data is always frame-indexed., EKS rows are one frame each, so rate_hz is the camera fps, not None., Reading before open() reports it instead of raising AttributeError., Overlapping skeleton names must resolve identically regardless of hash order.…, A backward frame number straddling a batch boundary still raises. (+1 more)

### Community 7 - "PyramidReader"
Cohesion: 0.08
Nodes (35): The underlying source-time reader., PyramidReader, Reads pyramid queries dynamically from mmapped arrays., `value_at` answers for any time; outside coverage the answer is NaN., Nearest-sample, not interpolation: the readout must not invent data., A cursor a hair before t0 is a rounding artefact, not absent data., TestValueAtCoverageEdges, empty_reader() (+27 more)

### Community 8 - "open_ephys_session.py"
Cohesion: 0.07
Nodes (40): What a recording folder contains, plus the settings that span it. Session-wide…, Optional plugin contract for a whole recording folder. Additive to API v1 and…, Return the session's contents and the settings that span them. ``registry``…, SessionLayout, SessionSource, anchor_epoch(), find_recordings(), Return the UTC epoch that acquisition-clock zero corresponds to. Master time… (+32 more)

### Community 9 - "DECISIONS.md — lightweight ADR log"
Cohesion: 0.03
Nodes (64): 2026-07 · D-001 · Master time = float64 seconds, UTC epoch, 2026-07 · D-002 · Video playback = libmpv only — SUPERSEDED by D-075, 2026-07 · D-003 · License Apache-2.0; no GPL deps — SUPERSEDED by D-069, 2026-07 · D-004 · Sidecar cache format, 2026-07 · D-005 · Chunked ingest is the only ingest path, 2026-07 · D-006 · VideoSource conversion hook is first-class, 2026-07 · D-007 · Frame stepping uses actual frame timestamps, 2026-07 · D-008 · Cache key gets content-hash tail (+56 more)

### Community 10 - "aol_session_loader.py"
Cohesion: 0.10
Nodes (41): One file a session contributes, with the loader and config it needs. ``loader``…, SessionItem, _add_root_videos(), _anchor_epoch(), AOLManifest, AOLMetricFile, AOLVideoExtraction, _camera_label_from_labeled() (+33 more)

### Community 11 - "MessageStore"
Cohesion: 0.10
Nodes (15): QTableWidget, MessageStore, QObject, QWidget, Messages from every loaded source, on the master clock. Raw source times are…, Replace the messages attributed to *source_id*., Re-place one source's messages after its alignment changed., Re-aligning a source must not leave its notes behind on the old clock. (+7 more)

### Community 12 - "TimelineOverview"
Cohesion: 0.05
Nodes (40): _AnnotationLane, _CoverageLane, _EventLane, QMouseEvent, QPaintEvent, Paint named, conditional timeline-evidence lanes without owning time state., Set the shared master-time range rendered by this overview., Return the distinct pixel columns of the events inside ``[t0, t1]``. Bounded by… (+32 more)

### Community 13 - "PaintCanvas"
Cohesion: 0.07
Nodes (33): PaintCanvas, Any, QColor, QFont, QPainter, QPaintEvent, QWidget, Draw every complete XY point of every track at the current source time. (+25 more)

### Community 14 - "test_playback_smoothness.py"
Cohesion: 0.06
Nodes (46): SimpleNamespace, Four 120-frame callback bursts must stay far below one UI tick., test_bench_four_video_callback_bursts_are_coalesced(), DecodingPane, _osd_pane(), _OsdPane, QApplication, Playback must not generate work proportional to the decoded frame rate. Each… (+38 more)

### Community 15 - "test_pane_proportions.py"
Cohesion: 0.06
Nodes (48): distribute(), _pane_minimums(), PaneProportions, QObject, QSplitter, Hold each pane's share of the workspace steady while the window is resized.…, Manage *splitters*, adopting each one's ratio the first time it lays out., Adopt *splitter*'s current pane ratio as the one to hold. A visible pane… (+40 more)

### Community 16 - "main_window.py"
Cohesion: 0.04
Nodes (44): ABC, _Capability, Protocol, Plugin registry and discovery., What every scored plugin has in common: it can rate a path., Return all discovered source loaders., default_display_name(), _Nameable (+36 more)

### Community 17 - "test_core_pyramid.py"
Cohesion: 0.09
Nodes (27): build_gap_mask(), Return a boolean mask where True indicates a gap larger than 10x median dt.…, MonkeyPatch, Path, A valid short raw gap cannot disappear merely because the view is coarse., A background sidecar failure must fail the import, never look successful., A transient macOS EINTR takes the robust fallback without hiding data., Verify subsampled gap_mask (stride 10k) detects correctly on clustered gaps… (+19 more)

### Community 18 - "Known Traps"
Cohesion: 0.04
Nodes (55): 0. Scheduled work that outlives its owner crashes rather than fails (D-062, D-064), 0a. A `QObject` moved to a `QThread` needs an owning Python reference, 0b. Building a widget list can free the widgets in it (D-065), 0b. Do NOT add the anchor date to AOL encoder timestamps (D-045), 0c. AOL pose data must not become plot rows (D-046), 0c-bis. Overlay data reaches the grid before most panes exist (D-077), 0d. `"_eks.csv".split("_")[0]` is `""` — and `"" in name` matches everything, 0e. A container's declared frame rate is a claim, not evidence (D-072) (+47 more)

### Community 19 - "_apply"
Cohesion: 0.06
Nodes (39): QSettings, restore_geometry(), save_geometry(), QAction, Apply the selected system-relative application font scale., _apply(), apply_font_size(), _apply_font_to_existing_widgets() (+31 more)

### Community 20 - "AOLMetricLoader"
Cohesion: 0.07
Nodes (29): AOLMetricLoader, _column_names(), Any, Path, Extracted Metric (Optical Flow / MI). Format: single-variable `-v6` MAT file,…, Rows are frames with no stored time axis, same contract as EKS., Match the `<roi_id>__<metric>.mat` filename, then confirm the variable. The…, Load the single `roi_metric_data` array and resolve column names. (+21 more)

### Community 21 - "PyAVReader"
Cohesion: 0.06
Nodes (28): ndarray, Path, VideoStream, PyAVReader, Demux one pass to collect presentation timestamps and keyframes. Demux only —…, Presentation timestamps in source seconds, display order., Number of frames the container actually carries timestamps for., The decoded video stream, for callers building format metadata. (+20 more)

### Community 22 - "VideoStandardLoader"
Cohesion: 0.06
Nodes (30): Any, ndarray, Path, Loads standard videos, probing metadata and frame timing with PyAV., Read container and stream metadata with PyAV. This used to shell out to…, Adopt per-frame exposure times the acquisition system recorded, if given. A…, Return per-frame ``(master_time, source_time)`` evidence, if recorded., Build the presentation-timestamp table with the decoder's own code.… (+22 more)

### Community 23 - "NeoLoader"
Cohesion: 0.07
Nodes (28): main(), main(), _fit_length(), NeoLoader, Any, ndarray, Trim or NaN-pad *batch* to *expected* samples. Neo resolves a lazy…, Loads electrophysiology data using the neo library. (+20 more)

### Community 24 - "plot_pane.py"
Cohesion: 0.05
Nodes (47): GraphicsLayoutWidget, Compact shared controls for the time-series plot stack., Plot rendering pane using pyqtgraph and decimation pyramids., Build queued rows in time slices, letting the event loop run between them. A…, Load pyramid data for *channels* only, if a page is established., Resolve a channel reference to the rows it identifies. A :class:`ChannelKey`…, Refresh the current sweep from the decimation pyramid. ``sliced`` spreads the…, Requery one row and settle its once-only Y fit. (+39 more)

### Community 25 - "test_import_streaming.py"
Cohesion: 0.14
Nodes (30): ChannelStage, Append-only on-disk staging buffer for one float64 channel. An import worker…, fixture, MonkeyPatch, parametrize, Path, Bounded-memory import: staging buffers instead of complete-channel…, Streaming must not change a single stored sample. (+22 more)

### Community 26 - "test_cli_demo.py"
Cohesion: 0.10
Nodes (23): AvialSync root module., Path, Tests for the installed ``avialsync demo`` command., The previous two-channel cache cannot silently downgrade the restored demo., The release smoke gate waits for this count, so it must be reachable. It was…, First-run preparation is visible rather than appearing as a frozen window., The first run remains event-driven while FFmpeg creates every input., The installed CLI exposes a real demo subcommand. (+15 more)

### Community 27 - "test_interaction_standard.py"
Cohesion: 0.06
Nodes (40): _all_shortcuts(), main_window(), fixture, parametrize, QApplication, D-022 interaction standard tests. Verifies: - New transport buttons emit the…, The reset-zoom action in the plot context menu must be the same object as the…, Collect the NativeText of every shortcut registered on the window. (+32 more)

### Community 28 - "MappedChannelReader"
Cohesion: 0.08
Nodes (30): MappedChannelReader, ndarray, Replace the offset/drift mapping in place. Existing plot rows and readout rows…, Return this channel's master-time extent, or None when empty., Return ``(t_master, v, gap)`` for a bounded master-time range., Yield bounded ``(t_master, v)`` chunks., Decimated master-time query; the result is bounded by *max_points*., Return level-1 mmap views in **source** time. Kept unmapped on purpose:… (+22 more)

### Community 29 - "generate_guide_screenshots.py"
Cohesion: 0.20
Nodes (16): _capture_all(), generate(), _load_session(), Path, QApplication, Capture the annotated screenshots used by the user guide and tutorials. Every…, Return the sidebar's per-video widget, whatever its concrete class., Open the sample video and signal through the ordinary code paths. (+8 more)

### Community 30 - "SweepWindowControl"
Cohesion: 0.08
Nodes (17): QWidget, Return the shared sweep duration in seconds., Return the absolute master time at the current sweep's left edge., Return the latest master-clock value supplied by the player., Set master bounds and anchor all future sweeps to their start., Set and emit a duration clamped to the current master bounds., Expand the sweep to the complete master timeline., Move the continuous slider one small step inward. (+9 more)

### Community 31 - "SessionState"
Cohesion: 0.06
Nodes (49): MarkerEntry, Any, Path, Session state and JSON serialization for .avv files., Deserialise from a parsed JSON dict (accepts v1 through v6)., Write session JSON and large exact mappings atomically. Small mappings remain…, Persisted state for one loaded video., Read a .avv session file and validate any exact-map sidecars. (+41 more)

### Community 32 - "test_close_and_focus.py"
Cohesion: 0.07
Nodes (42): _playhead_events(), _press(), fixture, Key, parametrize, Path, QApplication, _pyramid_channels() (+34 more)

### Community 33 - "test_loaders_video.py"
Cohesion: 0.09
Nodes (31): _holds_video_stream(), Return whether *path* opens as a container carrying real video. Header read…, Score this file as standard video. Two gates, deliberately in this order. A…, MonkeyPatch, Path, CFR timestamps must not receive the VFR integrity warning., Variable presentation intervals win over a container's nominal CFR declaration., A second open mmaps the validated frame index instead of rebuilding it.… (+23 more)

### Community 34 - "test_pyav_reader.py"
Cohesion: 0.09
Nodes (29): long_gop_video(), fixture, MonkeyPatch, Path, TempPathFactory, Unit tests for the PyAV exact-frame reader. Frame *identity* is proven in…, The cache is a window on where the user just was, bounded by frames., Two float probes in one interval must be one entry, never two. (+21 more)

### Community 35 - "test_video_pane.py"
Cohesion: 0.08
Nodes (39): clip(), _opened_pane(), fixture, Path, QApplication, TempPathFactory, Video-pane construction, decoding, and teardown tests. Everything here used to…, End-to-end, through the real thread: the pixels must name the frame. (+31 more)

### Community 36 - "AvialSync — Project Blueprint (v1)"
Cohesion: 0.05
Nodes (36): AGENTS.md — AvialSync agent instructions (canonical), Architecture rules (violations = rejected PR), Coding standards, Definition of Done (every task), How to run things, Known traps (learned the hard way — do not rediscover), Naming & casing — BINDING (never invent variants), Task protocol for agents (+28 more)

### Community 37 - "_parse_args"
Cohesion: 0.12
Nodes (23): _parse_args(), Namespace, Parse the supported AvialSync command-line arguments., Path, Tests for the installed ``avialsync open`` command., The documented `avialsync open <session>` invocation is supported., AGENTS.md documents opening a sample-session folder, not only a file., `open` with nothing to open must not silently start an empty window. (+15 more)

### Community 38 - "TimeMap"
Cohesion: 0.03
Nodes (52): given, MasterClock, ndarray, setter, Maps master timeline to a specific source timeline. t_source = t_master +…, Return the source-time rate relative to master time., Return the local source/master rate around ``t_master``. Exact frame-trigger…, Snap to the nearest accepted frame-trigger timestamp, if available. (+44 more)

### Community 39 - "test_frame_identity.py"
Cohesion: 0.09
Nodes (35): FixtureRequest, Convert a decoded frame to a contiguous ``(H, W, 3)`` uint8 RGB array. Costs…, to_rgb_array(), cfr_video(), _probe_times(), fixture, ndarray, parametrize (+27 more)

### Community 40 - "session_controller.py"
Cohesion: 0.06
Nodes (55): AnnotationExportWorker, Export annotation markers to CSV off the UI thread., Path, QObject, Slot, Background workers for session persistence. Architecture rule 3: the UI thread…, Serialize and write .avv + sidecars off the UI thread., Read and parse .avv + sidecars off the UI thread. Only parsing moves here.… (+47 more)

### Community 41 - "SeekGroup"
Cohesion: 0.12
Nodes (16): Asynchronous seek coordinator., Fan out non-blocking frame requests across video panes. ``VideoPane.seek``…, Request one pane's frame at a source time, without blocking., Request every active pane's frame at master time ``t``., Return True once every pane has painted the frame it was asked for., SeekGroup, Per-pane isolation: pane 0 failing must not leave pane 1 running. The real…, test_one_bad_pane_does_not_strand_the_others() (+8 more)

### Community 42 - "test_scrubbing.py"
Cohesion: 0.05
Nodes (36): player_with_mocks(), fixture, Tests for live scrubbing coalescing behaviour in Player., Return a Player wired to mock collaborators (no Qt event loop needed)., _on_tick dispatches the pending scrub target once seeker settles., _on_tick does NOT flush while seeker is still busy., A stalled decoder may drop frames but cannot stop plots or 3D., Exact seek on release clears any pending coalesced target. (+28 more)

### Community 43 - "video_standard.py"
Cohesion: 0.06
Nodes (34): Asynchronous data source importer pipeline., Neo-based electrophysiology loader — the single ingest path for ephys data.…, Standard Video Loader., Path, test_exact_sync_flow(), MonkeyPatch, parametrize, Path (+26 more)

### Community 44 - "ImportWorker"
Cohesion: 0.15
Nodes (13): ImportWorker, Any, Path, QObject, Return the loader's free-text records, bounded, never fatally. A format's prose…, Return the sidecar manager scoped to loader identity and accepted config., Return a validated cache manifest without opening the source parser., Build aligned channels from one loader pass, retaining shared timestamps once.… (+5 more)

### Community 45 - "test_theme_colors.py"
Cohesion: 0.11
Nodes (33): _contrast(), _distance(), _palette(), parametrize, QColor, QPalette, Derived colours: legible on both surfaces, distinct, and following the accent.…, Derived means derived — change the accent and the lane moves with it. (+25 more)

### Community 46 - "sync.py"
Cohesion: 0.10
Nodes (29): Raised when synchronization evidence is malformed or insufficient., Raised when event evidence supports multiple equally valid alignments., SyncAmbiguityError, SyncEvidenceError, _candidate_indices(), _default_tolerance(), _evidence_indices(), _fit_affine() (+21 more)

### Community 47 - "test_worker_lifetime.py"
Cohesion: 0.07
Nodes (28): Behaviour extracted from :class:`~avialsync.ui.main_window.MainWindow`. Each…, _FakeFileDialog, main_window(), fixture, MonkeyPatch, Path, QApplication, QDropEvent (+20 more)

### Community 48 - "PlotPane"
Cohesion: 0.02
Nodes (58): PlotPane, InfiniteLine, Path, QAction, QEvent, QResizeEvent, QWidget, Keep pyqtgraph's canvas aligned with an application palette change. (+50 more)

### Community 49 - "format_time"
Cohesion: 0.13
Nodes (7): format_time(), Format *t_seconds* according to *mode*. t_epoch is the Unix epoch of master-…, Tests for ui.time_format — format_time() all three modes., TestFormatTimeEdgeCases, TestFormatTimeLocalTOD, TestFormatTimeRelative, TestFormatTimeUTC

### Community 50 - "PyramidBuilder"
Cohesion: 0.04
Nodes (66): CacheManager, is_cache_path(), Any, Path, Cache management for sidecar files., Get a temporary directory for writing cache. Ensure atomic swap later., Commit a replacement without discarding the last valid sidecar first., Replace a sidecar's contents without renaming the directory. Individual files… (+58 more)

### Community 51 - "Path"
Cohesion: 0.06
Nodes (11): Any, ndarray, Path, QImage, Open a session file or a folder of recordings. Routes through the same scan a…, Show a per-pane context menu on video right-click (D-022)., Apply an explicitly accepted proposal and retain reproducible provenance., Forward to ReadoutPanel with accumulated units for known channels. (+3 more)

### Community 52 - "._on_evidence_changed"
Cohesion: 0.11
Nodes (13): _normalise_events(), ndarray, Return the sorted time column of *events* for binary search., Register one source coverage span, keyed for later replacement., Display accepted sync matches with inspectable provenance text., Display imported data gaps as red ticks., Display messages the sources recorded, with their text inspectable., Display point/range annotations in their stored colors. (+5 more)

### Community 53 - ".can_open"
Cohesion: 0.10
Nodes (24): Path, Find the dataset root neo should be pointed at, or ``None``. Open Ephys…, Return whether *path* is a dataset rather than a session containing one. A…, Return 1.0 for whitelisted ephys formats; 0.0 for everything else. Directories…, Open *path*, optionally narrowed to one stream or to its events. Config keys:…, Path, Tests for the NeoLoader ephys data plugin., NeoLoader must never claim .csv files. (+16 more)

### Community 54 - "test_seek_backends.py"
Cohesion: 0.11
Nodes (32): _assert_within(), _bench_mpv(), camera_files(), _fanout(), _import_mpv(), _jump_targets(), _mpv_fanout(), mpv_players() (+24 more)

### Community 55 - "SourceOpenError"
Cohesion: 0.05
Nodes (47): AvialSyncError, CodecUnsupportedError, FileUnreadableError, LoaderContractError, MissingColumnError, NonMonotonicTimeError, Any, Exception (+39 more)

### Community 56 - "AOLVideoExtractionLoader"
Cohesion: 0.06
Nodes (37): AOLVideoExtractionLoader, False: this export carries its own time axis. The per-ROI v6 store has no time…, The camera this file belongs to, as the sidecar names it., Whether the loaded axis is absolute POSIX rather than recording-relative., Nominal frame rate the toolbox recorded, or ``0.0`` when absent., Claim a MAT file whose sidecar names this toolbox. Reads only the small JSON…, Return one ChannelInfo per ``(ROI, column)`` pair., Extracted ROI Metrics (Video Extraction). One file is one camera. Each ``(ROI,… (+29 more)

### Community 57 - "VideoMetadata"
Cohesion: 0.06
Nodes (39): Format-neutral video metadata exposed by every video source. Timestamp-derived…, VideoMetadata, Video rendering pane: decode with PyAV, blit with Qt. One path on every…, displayed_frame_rate(), format_video_osd(), human_file_size(), instantaneous_frame_rate(), ndarray (+31 more)

### Community 58 - "TimeDisplayMode"
Cohesion: 0.14
Nodes (12): MappedMessage, Recorded messages: the store that maps them, and the panel that lists them. A…, Adopt the window's time display mode, like every other timed widget., Return the file name of *source_id*, falling back to the id itself., One message placed on the master clock, with the file it came from., Return every message on the master clock, untimed notes first. A recording that…, _source_name(), _fmt_relative() (+4 more)

### Community 59 - "export_worker.py"
Cohesion: 0.06
Nodes (50): QPixmap, compute_region_stats(), export_data_slice_csv(), export_data_slice_parquet(), Any, ndarray, Path, QImage (+42 more)

### Community 60 - "test_workload_responsiveness.py"
Cohesion: 0.11
Nodes (30): _assert_no_stall_tail(), dense_source(), loaded_window(), _measure(), _measure_each(), _percentile(), fixture, parametrize (+22 more)

### Community 61 - "_JobWorker"
Cohesion: 0.08
Nodes (24): EventEvidenceSpec, Background TTL/event evidence extraction and alignment fitting., A cached signal channel from which TTL transitions are extracted., Native timestamp evidence, such as camera-frame trigger timestamps., SignalEvidenceSpec, _JobWorker, Protocol, Open evidence-based TTL/frame-event alignment for loaded sources. (+16 more)

### Community 62 - "import_controller.py"
Cohesion: 0.07
Nodes (38): enqueue_import(), on_import_error(), on_import_finished(), Any, Path, Time-series import and pose routing. One import worker owns the modal progress…, Queue a source import so only one worker owns the import UI at a time., Start the next queued background import. (+30 more)

### Community 63 - "test_ci_platform_config.py"
Cohesion: 0.07
Nodes (29): Regression checks for the shared cross-platform CI and release contract., An unpinned ffmpeg is both a CI flake and an unreproducible installer.…, Ubuntu 24.04 must provide AppImageTool's libfuse.so.2 runtime ABI., A version tag must not release a side branch or detached commit., Pushing a branch must never publish, and neither must a non-version tag.…, No job may build or publish without the tag having been verified., PyPI and the GitHub release must not publish two different versions. Nothing…, A PEP 440 pre-release tag must be marked as one on the release page. (+21 more)

### Community 64 - "test_core_coverage_edges.py"
Cohesion: 0.10
Nodes (29): channel(), _provenance(), fixture, Path, Edge paths in ``core/`` that no other test reached (P6.1, TESTING §1). TESTING…, Recovery is best-effort; failing to restore must not raise on a read path., Unequal arrays would silently mis-map frames on reload., A large mapping lives in a sidecar; a corrupt one must not load silently. (+21 more)

### Community 65 - "write_recording"
Cohesion: 0.11
Nodes (34): default_spec(), _message_manifest(), Path, Build a miniature Open Ephys binary recording for tests. Small enough to write…, Write *spec* under *root* and return the ``recording1`` directory., One continuous stream to write into the fixture., A TTL line to write as rising/falling edge pairs., Everything one ``recordingN`` directory should contain. (+26 more)

### Community 66 - "DummyVideoLoader"
Cohesion: 0.09
Nodes (19): patch, DummyVideoLoader, MonkeyPatch, Path, The `~/.avialsync/plugins/` drop-in path is a supported way to add a format., A broken plugin is otherwise indistinguishable from one never installed. Its…, Importable but useless is still a failure the author needs told about., One bad plugin must never take the application's own loaders with it. (+11 more)

### Community 67 - "SourceInspection"
Cohesion: 0.08
Nodes (20): ImportReport, IntegrityFlags, Any, All collected inspection data for one loaded source. Not frozen because…, Statistics collected by ImportWorker during one source import., Anomaly flags for one loaded source. Video flags (is_vfr, fps_mismatch) are set…, SourceInspection, create_video_pane() (+12 more)

### Community 68 - "test_ui_plot_row_geometry.py"
Cohesion: 0.33
Nodes (8): _pane_with_channels(), parametrize, Path, Plot rows must occupy the pane, not collapse to their minimum width. Rows are…, Every row's plot area must span the pane, whatever the size or row count., A second load must not leave the newest row collapsed beside settled ones., test_a_row_added_after_the_first_load_also_fills_the_pane(), test_rows_fill_the_pane_width()

### Community 69 - "Message"
Cohesion: 0.14
Nodes (15): bounded(), Message, Any, One free-text record read from a source file. ``time`` is in the *source's* own…, Return *messages* sorted with untimed records first, capped at the limit.…, Return free-text records this file stores, or an empty list. Additive default,…, A session fans one recording into several streams; the note is still one. Each…, Messages survive the sidecar, which is the only path a cache hit takes. (+7 more)

### Community 70 - "test_ui_sensor_mapping.py"
Cohesion: 0.10
Nodes (27): cache_dir(), fixture, Path, QApplication, Sensor offset/drift editing in the sidebar re-aligns plots without reimporting., Session restore holds the mapping until the async import finishes., set_mapping is display-only; it must not re-emit into the handler., The seam between the importer and the panel — and what session reload uses. A… (+19 more)

### Community 71 - "Player"
Cohesion: 0.12
Nodes (12): Return whether accepted per-frame evidence owns this mapping., Player, QObject, Stop UI ticks before the owning window tears down its panes., Start playback for programmatic callers such as the demo launcher., Use the first active exact mapping as the reference frame clock. This is…, Step to the neighbouring decoded frame across all video panes. The step size…, Set or clear the A/B loop region on the master clock. (+4 more)

### Community 72 - "test_messages.py"
Cohesion: 0.18
Nodes (16): MessagePanel, QGroupBox, Chronological list of recorded messages; a row seeks the timeline. Read-only by…, Recorded messages: the core record, the store that maps them, and the panel., The text belongs to the source file; an editable cell would invite a lie., A header has no time, so it must not occupy a sorted time column., The contract hook is additive: a frozen v1 loader must still satisfy it., A manifest written before this feature must still open, with no messages. This… (+8 more)

### Community 73 - "capture"
Cohesion: 0.19
Nodes (15): capture(), _load_session(), main(), Image, Path, QImage, quantize_to_shared_palette(), Capture a short looping animation of a real session folder opened through its… (+7 more)

### Community 74 - "pyramid.py"
Cohesion: 0.08
Nodes (26): _aggregate_gap_mask(), _aggregate_pyramid_level(), build_pyramid_level(), _nan_envelope(), ndarray, Path, Pyramid module for decimation and plotting., Aggregate one pyramid level from the preceding level's min/max envelopes. (+18 more)

### Community 75 - "PlotInteractionController"
Cohesion: 0.11
Nodes (15): PlotInteractionController, Any, QAction, Refresh overlays whose X coordinates depend on the current page., Handle a right-click only when it lands inside a visible channel row., Own page-local overlay state while delegating semantic actions to PlotPane., Register shared QActions for the plot context menu., Place measurement pin A and publish a complete A/B interval. (+7 more)

### Community 76 - "AnnotationStore"
Cohesion: 0.06
Nodes (32): PlotItem, AnnotationPanel, AnnotationStore, Path, QGroupBox, QObject, QWidget, Annotation markers: point and range, with list panel and CSV export. (+24 more)

### Community 77 - "ChannelKey"
Cohesion: 0.07
Nodes (30): ChannelKey, disambiguate(), Path, Master-clock presentation of a cached pyramid channel. A…, Stable identity of one channel: its source plus its name. A channel name alone…, Return the display name, qualified by source only when it must be., Return display labels, qualifying only names owned by more than one source., The ``(source_id, channel_id)`` identity of this channel. (+22 more)

### Community 78 - "PointColorRegistry"
Cohesion: 0.22
Nodes (6): PointColorRegistry, Hand out one stable colour per body-part name, decided at load time., Assign a colour to every name not seen before, in sorted order. Idempotent, so…, Return *name*'s colour, assigning one now if it was never registered. Painting…, Forget every assignment. For tests that need a known starting point., test_registry_rejects_an_empty_palette()

### Community 79 - "test_plugin_discovery.py"
Cohesion: 0.11
Nodes (28): ModuleType, Import one loose plugin module without adding its directory to ``sys.path``.…, Path, Plugin API v1 discovery coverage., A drop-in plugin directory exposes a v1 source to the registry., They are hardcoded *and* declared as entry points; that must not duplicate., `can_open` is offered directories, so a lab can adopt its own folder layout.…, Claiming the folder must stop the scan recursing into its files. Otherwise the… (+20 more)

### Community 80 - "demo.py"
Cohesion: 0.10
Nodes (32): CancelledCallback, RuntimeError, demo_data_dir(), _demo_frame(), _demo_frame_times(), DemoData, DemoWindow, ensure_demo_data() (+24 more)

### Community 81 - "prepare_release.py"
Cohesion: 0.16
Nodes (23): Pattern, dirty_paths(), ensure_preconditions(), main(), prepare_release(), Path, Prepare, validate, commit, tag, and push an AvialSync PyPI release. Run from…, Update version authorities and optionally create and publish the release tag. (+15 more)

### Community 82 - "Tracking3DCanvas"
Cohesion: 0.16
Nodes (8): QWidget, Custom-painted current-pose view with mouse orbit and wheel zoom., Number of complete XYZ points available to the view., Names of complete XYZ coordinate triplets., Index of the world axis currently rendered upward., Whether larger values on :attr:`up_axis` render downward., Set explicit skeleton edges between named points. Each edge is a ``(name_a,…, Tracking3DCanvas

### Community 83 - "test_ui_follow.py"
Cohesion: 0.09
Nodes (8): The owning source's stable identifier (its path)., fixture, Path, Tests for fixed-window oscilloscope plotting., A narrow spike remains visible instead of being averaged into a midpoint., sweep_pane(), test_decimated_plot_preserves_minimum_and_maximum_envelope(), test_row_close_hides_plot_and_unchecks_sidebar_channel()

### Community 84 - "test_aol_chunk_boundaries.py"
Cohesion: 0.19
Nodes (20): _collect(), ndarray, Path, AOL loaders honour the frozen ingest contract across batch boundaries (V-15,…, A 15-channel file must not read 45 columns to answer for one., Projection is an optimisation; it must not change a single sample., Frame 3 follows frame 9 across the boundary; that must not pass silently., The in-batch case must behave identically — same guarantee, same error. (+12 more)

### Community 85 - "test_engine_importer.py"
Cohesion: 0.11
Nodes (16): _BulkLoader, Path, Tests for the asynchronous time-series import pipeline., A loader that also carries what the experimenter typed during recording., A third-party loader whose message reader is broken., On a cache hit the loader is never opened, so the manifest must carry them.…, One-pass test loader whose legacy per-channel API must never be used., Losing the samples fails an import; losing a comment must not. (+8 more)

### Community 86 - "test_theme_tooltips.py"
Cohesion: 0.08
Nodes (23): Theme tests for appearance-only changes on all supported appearances., Tooltips remain readable through palette roles, not a global stylesheet., Small/Medium/Large apply to existing controls, while System restores the base…, Collecting a cycle mid-snapshot frees widgets Qt has already handed over., Pausing collection around the snapshot must not outlive it., Rooting the snapshot in the window trees may not narrow what it covers., A custom OS accent must flow into links and interactive controls., A widget with no parent is a top-level window in Qt, so it is still covered. (+15 more)

### Community 87 - "test_subprocess_no_window.py"
Cohesion: 0.12
Nodes (21): Call, skipif, no_window_kwargs(), NoWindowKwargs, Process-level runtime helpers. This module used to locate a media runtime —…, Subprocess keyword arguments that suppress a console window. A ``TypedDict``…, Return subprocess kwargs that keep a child process from opening a console. A…, _is_platform_guarded() (+13 more)

### Community 88 - "test_ui_shortcut_reach.py"
Cohesion: 0.10
Nodes (26): KeyboardModifier, _editor_rejects_text(), Return whether *widget* would refuse *text* as typed input. A numeric field…, Return whether a Qt validator refused the text outright.…, _validates_as_invalid(), _fires(), _focusable(), fixture (+18 more)

### Community 89 - "LoaderRegistry"
Cohesion: 0.11
Nodes (17): LoaderRegistry, Path, Add each built-in class in *specs*, reporting any that will not import. A…, Add every class published under *group*, skipping ones that fail. Deduplicates…, Load source classes exported by loose ``*.py`` plugin modules., Return the candidate scoring highest above zero on *path*. ``can_open`` is…, Return the loader with the highest can_open() score > 0., Return the session scanner claiming *path*, if any. Asked before per-file… (+9 more)

### Community 90 - "Path"
Cohesion: 0.09
Nodes (15): Return high confidence for files matching the encoder log pattern., is_aol_session(), Return True if the directory has AOL session signature files. An AOL session…, Path, Unknown channels raise the typed core error, not a bare KeyError., Using the source before open() reports it, instead of raising AttributeError., Malformed input raises the typed core error with actionable text., The encoder must stay on the anchor-reduced axis video and EKS use. This is the… (+7 more)

### Community 91 - "make_fixtures.py"
Cohesion: 0.14
Nodes (21): Path, Regression guard: make_fixtures._clean_generated() must never delete permanent…, Running _clean_generated twice must not error (no dirs to remove second time)., session_v1.avv, session_v2.avv, session_v3.avv must be committed in…, _clean_generated() deletes generated subdirs but leaves .avv files intact., test_clean_generated_is_idempotent(), test_clean_generated_preserves_session_files(), test_permanent_fixtures_exist_in_repo() (+13 more)

### Community 92 - "test_ui_layout_resize.py"
Cohesion: 0.12
Nodes (22): fixture, Path, QApplication, Window and pane resizing behaviour. Three defects motivated these tests: 1.…, A rigid minimum makes the window feel unresizable on a small screen., Dragging a handle must actually move it, not snap back. Two things made earlier…, The regression: plots used to be handed zero pixels on launch., saveState stores the collapsible flag; restoring must not undo the policy. (+14 more)

### Community 93 - "extract_ttl_edges"
Cohesion: 0.10
Nodes (18): Edge, extract_ttl_edges(), Extract raw TTL transitions from chronological signal chunks. Args: chunks:…, Raw edges are evidence; unusable input must not become empty evidence., Anonymous evidence cannot be attributed in saved provenance., A contact bounce is one transition, not several., TestTtlExtraction, Ground-truth tests for headless TTL/event synchronization. (+10 more)

### Community 94 - "TimelineEvidence"
Cohesion: 0.12
Nodes (12): QSlider, _ABPin, JumpSlider, QFrame, QWidget, A QSlider that instantly jumps to the clicked position., Titled, collapsible Data Streams shell for named TimelineOverview lanes., The currently displayed status message, without its label prefix. (+4 more)

### Community 95 - "AOLEncoderLoader"
Cohesion: 0.12
Nodes (13): AOLEncoderLoader, Any, ndarray, Path, Return a single velocity channel. ``rate_hz`` stays ``None``: the logger writes…, Convert HH:MM:SS:mmm to seconds since midnight., Yield bounded (time, value) chunks for the requested channel. Chunk boundaries…, Validate and de-duplicate one chunk, retaining its final sample. The retained… (+5 more)

### Community 96 - ".paintEvent"
Cohesion: 0.23
Nodes (8): QPainter, QPaintEvent, _qcolor(), Draw a bounded current pose; trajectory history is never rendered here., Draw explicit edges between connected named points., Draw a light ground-plane grid behind the pose., Draw a compact orientation indicator in the bottom-left corner., Construct QColor from an RGB tuple.

### Community 97 - "_pulses"
Cohesion: 0.14
Nodes (12): _pulses(), ndarray, parametrize, An unsafe alignment must be refused, never guessed. `core/sync.py` decides…, Malformed timestamp arrays must be rejected before any fitting., Reordering evidence would fabricate a pairing the source never had., A repeated timestamp has no single position on the master clock., Refuse configurations that cannot produce a trustworthy fit. (+4 more)

### Community 98 - "test_typed_source_errors.py"
Cohesion: 0.14
Nodes (14): Any, Path, Loaders and the importer raise typed errors, not bare builtins (V-06). AGENTS…, Distinct from SourceOpenError: the fix is in the plugin, not the data., The UI cannot turn a bare builtin into an actionable dialog., One base means the UI can catch the whole family in a single handler., test_a_plugin_breaking_the_ingest_contract_is_named_as_such(), test_every_typed_error_shares_one_base() (+6 more)

### Community 99 - "Tracking3DPane"
Cohesion: 0.13
Nodes (23): Timeline-synchronized 3D tracking pane., Use complete XYZ channel triplets from the active cached readers., Reflect the canvas's current orientation without re-triggering it., Pin an explicit vertical axis chosen by the user., Pin which source axis renders upward (see :meth:`Tracking3DCanvas.set_up_axis`)., Set explicit skeleton connectivity for the 3D view., Tracking3DPane, _anatomical_readers() (+15 more)

### Community 100 - ".open"
Cohesion: 0.12
Nodes (16): Any, Path, Read the sidecar, then every numeric array from the HDF5 file., Return what to add to the file's own axis to reach master time. Which…, Prefer the absolute POSIX axis; fall back to recording-relative.…, Load every ``metrics/<metric>`` array, declining ragged ones., Reject a decreasing axis; well-formed exports never have one., Map one channel name to each ``(metric, roi, column)`` triple. Names are built… (+8 more)

### Community 101 - "test_aol_pose_routing.py"
Cohesion: 0.13
Nodes (25): aol_session(), _finish_import(), fixture, Path, AOL pose routing: 2D overlays per camera, 3D to the 3D view, neither plotted.…, _eks.csv' has an empty leading token; it must not match by empty substring., Complete one import through the routing path, without the worker/dialog.…, 2D pose reaches only its own camera's overlay, and creates no plot rows. (+17 more)

### Community 102 - "test_never_freeze.py"
Cohesion: 0.14
Nodes (19): QApplication, The UI must stay responsive, visible, and closeable under any workload. This is…, The regression: closeEvent called event.ignore() and trapped the user., Abandoning jobs must not skip the session write., A worker that ignores cancellation, like a blocked syscall., A wedged job must not hold shutdown open., The grace period is a total budget, not per job., test_a_quiet_job_is_reported_as_not_responding() (+11 more)

### Community 103 - "test_ui_dialogs.py"
Cohesion: 0.09
Nodes (36): ImportWizard, Any, QDialog, Dialog for configuring CSV/time-series import parameters. Previews the file,…, Return the import configuration dict for the pipeline., QDialog, Missing-file relink dialog shown when session files cannot be found., Return {original_path: new_path} for files the user relocated. (+28 more)

### Community 104 - "tracking_3d_pane.py"
Cohesion: 0.10
Nodes (20): The source-to-master mapping applied by every method here., PlaybackState, Master timeline and synchronization logic., Snapshot of current playback state., _build_sources(), _coordinate_name(), detect_up_axis(), _mean_axis_position() (+12 more)

### Community 105 - "theme.py"
Cohesion: 0.09
Nodes (39): Import Report dialog — shows ImportReport stats with a copy-as-text button., Left Sidebar / Inspector Pane., _accent(), accent_hue(), evidence_color(), follow_palette(), loop_pin_color(), marker_color() (+31 more)

### Community 106 - "DemoLaunch"
Cohesion: 0.09
Nodes (20): DemoGenerationWorker, DemoLaunch, DemoProgressDialog, QDialog, QObject, QWidget, Slot, Show demo generation progress and an inspectable activity log. (+12 more)

### Community 107 - "test_frame_indexed.py"
Cohesion: 0.14
Nodes (19): Path, Tests for frame-indexed source contract and DLC fps resolution (D-019)., _frame_indexed_sources accumulates provisional entries when no video is loaded., TimeSeriesSource.is_frame_indexed() should default to False., _rebind_frame_indexed_sources should clear the provisional list., After rebind, re-enqueued import uses the video fps, not the provisional fps., TrackingLoader.is_frame_indexed() must return True., Write a minimal two-bodypart DLC CSV to *path*. (+11 more)

### Community 108 - "write_video"
Cohesion: 0.25
Nodes (10): _detail_planes(), _identity_frame(), Fraction, ndarray, Path, PyAV fixture writers for frame-exactness and seek-latency tests. Every fixture…, Build the static pixel content once per resolution. Rebuilding this per frame…, Build one RGB frame carrying ``index`` in flat black/white blocks. ``detail``… (+2 more)

### Community 109 - "transcode.py"
Cohesion: 0.15
Nodes (18): CancelCheck, InputContainer, _duration_seconds(), encode_proxy(), encode_video(), _even(), Fraction, ndarray (+10 more)

### Community 110 - "test_packaging_smoke.py"
Cohesion: 0.19
Nodes (18): CaptureFixture, _load_smoke_module(), ModuleType, MonkeyPatch, Path, Regression tests for built-bundle startup verification., Freezing a bundle is release-tag work, and it must be gated on startup., CI proves correctness on every push; only a tag builds and ships. Bundling on… (+10 more)

### Community 111 - "_FakePane"
Cohesion: 0.12
Nodes (14): _FakePane, fixture, Path, QWidget, Removal must not invent a session file for someone who never saved one., A real widget the grid's layout accepts, minus libmpv. A plain object cannot…, The signal is useless if it arrives after the teardown it guards., A snapshot taken here must describe the session without this video. (+6 more)

### Community 112 - "test_sync_golden.py"
Cohesion: 0.14
Nodes (18): app_with_main_window(), _capture_frame(), _fixture_frame_time(), fixture, ndarray, QApplication, Golden sync testing for video playback., Test multi-camera golden sync with offsets. (+10 more)

### Community 113 - "load_video"
Cohesion: 0.33
Nodes (6): load_video(), on_video_open_error(), Any, Path, Show a source-open error without leaving a partially-created pane., Queue a video source for probing and, in request order, pane creation.

### Community 114 - "._load_level"
Cohesion: 0.13
Nodes (7): Return this channel's ``(t_first, t_last)`` extent, or None when empty., Return the number of stored full-resolution samples., Return the ``(index, value)`` of the last sample at or before *t_target*.…, Return ``(t, v, gap)`` mmap views bounded to ``[t0, t1]``. Slicing an mmap…, Yield chronological ``(t, v)`` views of at most *chunk_size* samples. This is…, Return the level-1 ``(t, v, gap)`` mmap views without copying. Reserved for…, Return the exact value at the given time `t_target` using the highest…

### Community 115 - "VideoPropertiesPanel"
Cohesion: 0.09
Nodes (15): _frame_count_text(), _PropertiesBase, Any, QGroupBox, QWidget, Collapsible source-properties panels for VideoInfoWidget and SensorInfoWidget…, Collapsible properties panel for one video source., Read the pane's current decode state; call when the panel is expanded. The rate… (+7 more)

### Community 116 - "AvialSync Plot UX Refinement Plan"
Cohesion: 0.12
Nodes (16): 10. Focus and keyboard contract, 11. Performance invariants, 12. Persistence and migration, 13. Implementation slices, 14. Required test evidence, 15. Definition of done, 1. Objective, 2. Compatibility ledger — nothing in this list may be lost (+8 more)

### Community 117 - "frame_index_at"
Cohesion: 0.16
Nodes (11): adjacent_frame_time(), frame_index_at(), ndarray, Frame selection from presentation timestamps — the single authority. The frame…, Return the index of the presentation frame active at ``source_time``. Args:…, Return the neighbouring real presentation timestamp. Anchored on the frame…, Headless exact-frame video reading on PyAV. This is the decoder the application…, Return the frame index presented at ``source_time``. The one resolution step in… (+3 more)

### Community 118 - "fit_exact_index_mapping"
Cohesion: 0.16
Nodes (12): fit_exact_index_mapping(), Create a deterministic exact index mapping, overriding affine limits. Frames…, Shifting past the end leaves nothing to pair., Video frame 0 maps to reference index N, the documented behaviour., The 1:1 frame mapping has its own overlap requirement., TestExactIndexMapping, parametrize, Ground-truth tests for exact index synchronization. (+4 more)

### Community 119 - "UiHeartbeat"
Cohesion: 0.12
Nodes (9): QObject, Detect and report stalls of the UI thread itself. Background work being off-…, Measure UI-thread responsiveness and report stalls., The largest stall seen so far, for diagnostics., UiHeartbeat, Blocking the loop must be surfaced, not merely felt as lag., test_heartbeat_reports_a_blocked_ui_thread(), test_heartbeat_reset_clears_history() (+1 more)

### Community 120 - "TESTING.md"
Cohesion: 0.12
Nodes (15): 1. Test layers, 2. Fixtures — `tools/make_fixtures.py` (ground truth for everything), 3. Golden sync tests (`tests/test_sync_golden.py`), 3a. TTL/event synchronization golden tests (D-026), 4. Performance benchmarks (`tests/benchmarks/`), 5. GUI test conventions, 5a. Plot UX refinement gates (P4.6 / D-044), 6. Manual smoke checklist (human, end of each phase, on YOUR real field data) (+7 more)

### Community 121 - "test_ui_plot_sliced_refresh.py"
Cohesion: 0.13
Nodes (16): channel_cache(), pane(), fixture, Path, A span change requeries every row without holding the UI thread (D-063). The…, Built once: 128 pyramids are slow enough to matter per test., The callback must hand work back to the event loop, not finish it all., Deferring must not mean dropping. (+8 more)

### Community 122 - "ARCHITECTURE.md"
Cohesion: 0.12
Nodes (14): 1. Repository layout (complete — the authoritative map of what lives where), 2. Runtime dataflow, 2a. Synchronization dataflow (D-026), 2b. Timeline Evidence overview (D-027), 3. Threading model, 4. Plugin contract (frozen at Phase 5 as API v1), 5. Session file (.avv, JSON, schema_version field), 5b. Cache invalidation key (updates D-004) (+6 more)

### Community 123 - "ToyBinarySource"
Cohesion: 0.13
Nodes (10): Any, ndarray, Path, A minimal external AvialSync Plugin API v1 implementation., Read ``.toybin`` records encoded as little-endian ``(time, value)`` pairs., Recognise the example file extension without opening the input., Store the path after validating whole-record alignment., Expose the single dimensionless signal channel. (+2 more)

### Community 124 - "DropScanWorker"
Cohesion: 0.19
Nodes (8): Return True if this source stores frame numbers instead of wall-clock time.…, DropScanWorker, Path, QObject, Slot, Lay out *path* with the session plugin that claims it, if any. Returns ``None``…, Scan dropped paths for importable sources off the UI thread., Collect paths and their best-guess loaders recursively, avoiding session files.

### Community 125 - ".__init__"
Cohesion: 0.04
Nodes (41): QTreeWidgetItem, QVBoxLayout, Register window-scoped QActions for all keyboard-only shortcuts (D-022). Rules…, _make_empty_inspection(), QFrame, QWidget, Set a channel checkbox and return whether this source owns it., Show a restored mapping without re-emitting it back to the caller. (+33 more)

### Community 126 - "Path"
Cohesion: 0.13
Nodes (9): Any, Path, Return 0..1 confidence that *path* is a session this can lay out. Called with…, Return a confidence in ``[0.0, 1.0]`` without expensive I/O., Read metadata required for :meth:`channels` and :meth:`read_chunks`. ``config``…, Return 0..1 confidence that this loader can open the file., Probe source metadata; this method may perform blocking I/O., Produce a playable cached proxy and report progress in ``[0, 1]``. (+1 more)

### Community 127 - "ProxyWorker"
Cohesion: 0.17
Nodes (12): needs_proxy(), proxy_path_for(), ProxyWorker, Path, QObject, Proxy generation — re-encode videos to all-keyframe scrub-friendly proxies., Return the sidecar proxy path for a given video., Check if a proxy already exists and is newer than the source. (+4 more)

### Community 128 - "generate_screenshots"
Cohesion: 0.22
Nodes (8): generate_screenshots(), main(), _pin_appearance(), Path, QApplication, Force the documented appearance without touching saved preferences.…, generate_screenshots(), on_finished()

### Community 129 - "Path"
Cohesion: 0.17
Nodes (12): apply_session_layout(), drop_event(), on_drop_scan_finished(), on_drop_session_found(), process_drop_candidates(), Path, QDropEvent, Present the batch import dialog and route accepted items. (+4 more)

### Community 130 - "test_bench_plot_pane.py"
Cohesion: 0.22
Nodes (15): _channel_cache(), _populated_pane(), parametrize, Path, Performance guards for the populated plot pane (BLUEPRINT.md budgets). P4.6's…, A drag resizes continuously; no single callback may pass the ceiling. 128…, One slice of row construction must not freeze the window. Rows are built in…, Build a field-shaped multi-channel pyramid cache. Sample depth is kept modest… (+7 more)

### Community 131 - "test_demo_data.py"
Cohesion: 0.17
Nodes (14): Path, Regression tests for generated, user-facing demo inputs., The demo tracking file must match the loader's three-row DLC contract., The compatibility script cannot drift from ``avialsync demo`` again., test_generated_pose_csv_is_importable_dlc_data(), test_tools_launcher_delegates_to_installed_application(), _is_dlc_pose_csv(), main() (+6 more)

### Community 132 - "test_transport_resize.py"
Cohesion: 0.17
Nodes (15): _expected_pin_x(), fixture, Regression tests: transport A/B pins must realign after window resize., Pin remains correctly positioned across consecutive resizes., Return the correct x for a pin at *frac* given the slider's current geometry., A/B in-pin must sit at the correct groove fraction after a resize., A/B out-pin realigns after resize (non-midpoint fraction)., Both A/B pins realign independently after a single resize. (+7 more)

### Community 133 - "ImportReportDialog"
Cohesion: 0.22
Nodes (7): ImportReportDialog, QDialog, QWidget, Scrollable plain-text view of an ImportReport with a Copy button., Show the full ImportReport dialog for a data source., A v1 session carries no ImportReport; the dialog must still open., test_import_report_handles_a_source_with_no_report()

### Community 134 - "job_manager.py"
Cohesion: 0.17
Nodes (11): BackgroundWorker, _drop_finished_threads(), JobState, Enum, Protocol, QThread, One owner for every background job, so the UI can never be trapped. Three…, Release retained jobs whose threads have stopped. Never call this from a… (+3 more)

### Community 135 - "open_ephys_format.py"
Cohesion: 0.18
Nodes (17): find_record_dir(), is_recording_dir(), parse_record_dir_time(), parse_software_epoch(), datetime, Path, Wall-clock and layout evidence an Open Ephys recording carries outside neo.…, Return the continuous-stream directory names the manifest declares. Each stream… (+9 more)

### Community 136 - "build_manifest"
Cohesion: 0.18
Nodes (19): build_manifest(), Scan an AOL session folder and build a loading manifest. Priority for videos:…, fixture, Path, AOL session routing for video-extraction-toolbox exports. These are ordinary…, The per-ROI store still loads on its own when no export exists., No sidecar, no match: the tree holds MATLAB files from other tools., A two-camera session carrying a video-extraction export for each. (+11 more)

### Community 137 - "VideoGrid"
Cohesion: 0.18
Nodes (7): QWidget, Manages N VideoPanes in either a horizontal strip or an NxN grid. Uses a single…, Stop every pane's decoder before their Qt parent is destroyed. Each pane is…, Update the time offset for a specific video., Defer relayout until end_batch_add(). Use for multi-file drops., Return a copy of the loaded video paths, parallel to self.panes., VideoGrid

### Community 138 - "test_annotation_frames.py"
Cohesion: 0.16
Nodes (13): Path, Tests for frame-accurate annotation: VideoFrame, export, AnnotationPanel., Pane-owned decode threads must stop before Qt destroys the grid., Annotation frame numbers must never use t*fps arithmetic for VFR media., test_export_csv_columns(), test_export_csv_marker_with_no_frames(), test_export_csv_one_row_per_video(), test_frame_records_at_empty_grid() (+5 more)

### Community 139 - "_MappingLoader"
Cohesion: 0.29
Nodes (7): _declared_exact_mapping(), Return per-frame timing the loader recorded, once it has been validated. A…, _MappingLoader, Minimal stand-in for a VideoSource that declares per-frame timing., This arrives from a plugin, so it is checked rather than trusted. A mapping…, test_invalid_declared_mappings_are_refused(), test_valid_declared_mapping_is_accepted()

### Community 140 - "Contributor Covenant Code of Conduct"
Cohesion: 0.14
Nodes (13): 1. Correction, 2. Warning, 3. Temporary Ban, 4. Permanent Ban, Attribution, Contributor Covenant Code of Conduct, Enforcement, Enforcement Guidelines (+5 more)

### Community 141 - "2026-07 · D-020 · Inspection layer — what is surfaced where"
Cohesion: 0.14
Nodes (14): 2026-07 · D-020 · Inspection layer — what is surfaced where, Copy as text, Delta measurement: distinct measure points on PlotPane, Demo data extensions, Gap markers on plot, Import Report access, ImportWorker.finished signal change, Integrity badge (+6 more)

### Community 142 - "Data handling"
Cohesion: 0.14
Nodes (12): Data handling, Gaps and missing values, Identity and export correctness, Required ground-truth workloads, Sessions and provenance, Source files and caches, Time and precision, Audit status (2026-07-29) (+4 more)

### Community 143 - "test_engine_layering.py"
Cohesion: 0.18
Nodes (12): Module, stmt, _is_type_checking_guard(), The engine layer must not depend on the UI layer (V-13, ARCHITECTURE §1).…, Whether an `if` statement is the `if TYPE_CHECKING:` guard., Return ``(module_scope_linenos, deferred_linenos)`` for `avialsync.ui` imports., Guard the guard: if the scan matched nothing the test above is vacuous., `player` read `transport._bounds`; Transport now publishes `bounds`. (+4 more)

### Community 144 - "diagnostics.py"
Cohesion: 0.15
Nodes (11): format_diagnostics(), probe_disk_speed(), probe_hwdec(), _pyav_version(), Diagnostics module for AvialSync. Reports hardware decode capability and disk…, Return the installed PyAV version, for a copyable bug report., Format diagnostics dict as a copyable text block., Report which hardware decoders FFmpeg was built against. Informational only.… (+3 more)

### Community 145 - "JobManager"
Cohesion: 0.16
Nodes (7): JobManager, QObject, Owns every background worker/thread pair and reports their state., Every job currently owned, newest last., A one-line summary for the transport status area., Refresh the watchdog clock for whichever job reported., Drop finished threads without relying on sender() identity (D-051).

### Community 146 - "test_aol_loaders.py"
Cohesion: 0.16
Nodes (14): fixture, Tests for AOL loaders (encoder log, EKS 3D tracking, session detection)., Create a minimal encoder_log.txt fixture., Create a minimal EKS CSV fixture with x/y/z columns and fnum., Create an EKS CSV without a fnum column., A session emits four "_eks.csv" files that go to three different places. One is…, Create a minimal AOL session folder structure., `config` is hashed into the sidecar cache key; a display string must not be. (+6 more)

### Community 147 - "AOLSessionSource"
Cohesion: 0.13
Nodes (17): AOLSessionSource, Lay out an AOL multi-camera experiment folder as a session. This is the…, aol_session_with_metrics(), fixture, ndarray, Path, AOL extracted-metric routing: data_root MAT exports become plot rows. Unlike…, A data_root dropped without its sibling videos still loads, unaligned. (+9 more)

### Community 148 - "test_conda_recipe.py"
Cohesion: 0.24
Nodes (13): _project_metadata(), The conda-forge recipe must describe the package this repository builds., A recipe pinned to a stale version publishes the wrong source archive., A missing run dependency is an import error on a user's first launch., The conda package is now the same shape as the wheel (D-075). Decoding,…, conda must not offer the package on a Python the project excludes., The console script conda installs must be the one the package defines., _recipe_text() (+5 more)

### Community 149 - "TestMeasureMarkers"
Cohesion: 0.15
Nodes (5): app(), plot_pane(), fixture, Tests for PlotPane measure markers and measure_changed signal., TestMeasureMarkers

### Community 150 - ".__init__"
Cohesion: 0.10
Nodes (15): QTableWidgetItem, _guess_format(), _guess_time_column(), Path, QWidget, Timestamp import wizard with preview, format autodetect, and timezone handling., Return the index of the most likely timestamp column., Heuristic: guess the timestamp format from sample values. (+7 more)

### Community 151 - "BatchImportDialog"
Cohesion: 0.21
Nodes (9): BatchImportDialog, Path, QDialog, QWidget, Return what to call *path*: the session's own label, else its filename., Map semantic labels to actual loader classes., Presents dropped files to the user for type verification before loading., test_dialog_preselects_the_declared_kind() (+1 more)

### Community 152 - "ui/__init__.py"
Cohesion: 0.15
Nodes (11): Startup diagnostics lifecycle tests., A failed capability query must stay observable rather than raise., A bug report has to say what decoded the video, not what is installed., Concurrent app instances must not contend for one fixed probe filename., Repeated windows share one diagnostics probe instead of spawning threads., Informational only — software decode already meets every budget (D-075). PyAV…, test_diagnostics_report_names_the_decoder_actually_in_use(), test_disk_probe_uses_unique_file_and_cleans_it() (+3 more)

### Community 153 - "VideoOpenWorker"
Cohesion: 0.08
Nodes (15): Any, Path, QObject, Slot, Select, open, and optionally prepare one video source off the UI thread., Request cancellation between source operations., Open the selected source and emit a usable media path on success., Adapt the plugin's normalized progress callback to the UI signal. (+7 more)

### Community 154 - "test_bench_cursor_path"
Cohesion: 0.19
Nodes (12): large_dataset(), fixture, Path, Pyramid and cursor-path benchmarks with local engineering budget gates.…, A committed shared-window change stays below the 30 ms UI budget., Generate 180M samples once per session to save time and memory., Pyramid build for 180M samples must complete within the ★ budget., Full per-tick cursor path: plot set_cursor + transport set_time + readout… (+4 more)

### Community 155 - "test_video_grid.py"
Cohesion: 0.11
Nodes (16): QWidget, Video-grid native lifecycle tests., Tiny media may load synchronously; the readiness event must not be lost., Holding tracks must not turn into broadcasting them., The loose-reader path has the same ordering hazard as named tracks., Held tracks own readers over mmap'd pyramids; a removed pane frees them., Grid/fullscreen layout changes must not override the sidebar checkbox., A pane that records what the grid handed it, without opening media. (+8 more)

### Community 156 - "generate_icons.py"
Cohesion: 0.21
Nodes (12): generate(), main(), parse_args(), Image, Namespace, Path, Generate AvialSync's platform icon assets from its canonical raster source., Return a high-quality square icon without stretching or cropping artwork. (+4 more)

### Community 157 - "test_job_thread_lifetime.py"
Cohesion: 0.30
Nodes (11): CompletedProcess, _assert_no_abort(), A running QThread must outlive whatever started it. Qt aborts the process…, A job that ends normally must not accumulate in the module registry., The crash: a manager discarded without shutdown, while a job still runs., The documented path still works: shutdown abandons, drain reclaims., _run(), test_a_finished_job_leaves_nothing_retained() (+3 more)

### Community 158 - "Desktop installers"
Cohesion: 0.17
Nodes (12): 1. Create the environment, 2. Keep per-user packages out of the environment, 3. Run it, Check the installation, Desktop installers, First-launch security warnings, Install with pip (recommended), Installation (+4 more)

### Community 159 - "Tutorial: import sensor and recording data"
Cohesion: 0.18
Nodes (8): Technical reference, Importing several files at once, Missing values and decimal commas, Structure: how to split the file, Time: what the numbers mean, Timezone: state it, never assume it, Tutorial: import sensor and recording data, What happens after you accept

### Community 160 - "AvialSync — Model Handout"
Cohesion: 0.17
Nodes (11): Architecture Rules (violations = rejected PR), AvialSync — Model Handout, File, Marking, Module Map, Naming (binding), Playback, Run Commands (+3 more)

### Community 161 - "MIGRATION_PYAV.md — libmpv → PyAV, and a pip-only install"
Cohesion: 0.17
Nodes (11): 1. Goal, in one sentence, 2. Why — the measured case, 3. The invariant that outranks everything, 4. Steps — update the status column as you go, 5. Licensing — settled, 6. Rollback, 7. Environment notes for whoever picks this up, MIGRATION_PYAV.md — libmpv → PyAV, and a pip-only install (+3 more)

### Community 162 - "capture"
Cohesion: 0.24
Nodes (11): QRect, _bounds_in(), capture(), _draw_step_number(), Path, QPainter, QWidget, Shared capture helpers for the documentation screenshots. Two things every… (+3 more)

### Community 163 - "test_a_type_names_the_data_never_the_rig"
Cohesion: 0.33
Nodes (3): Kinds of data an acquisition recording carries besides the ephys. One…, One reader serves many kinds, so the type must not be the reader's name. Every…, test_a_type_names_the_data_never_the_rig()

### Community 164 - "Job"
Cohesion: 0.18
Nodes (6): Job, One unit of background work, owned for its whole lifetime., Whether the worker offers a cooperative cancel., Jobs that have gone quiet for longer than the watchdog allows., Ask every cancellable job to stop; never blocks., Stop everything and return the labels that had to be abandoned. Always returns…

### Community 165 - ".eventFilter"
Cohesion: 0.15
Nodes (10): _is_mid_edit(), QDragEnterEvent, QDropEvent, QEvent, QObject, QWidget, Forward drops over child panes, and keep the playhead keys reserved., Return whether this key belongs to the playhead rather than the focus widget.… (+2 more)

### Community 166 - "._read_batches"
Cohesion: 0.24
Nodes (6): Series, ndarray, Resolve the wizard's explicit timezone to an IANA-compatible name., Yield every channel from one parser pass with strict chunk boundaries., Yield aligned channel chunks from a single CSV parser pass., Yield one channel while retaining the same boundary guarantees as bulk ingest.

### Community 167 - "QMouseEvent"
Cohesion: 0.29
Nodes (4): QMouseEvent, Begin orbiting on a primary-button drag., Orbit around the stable scene bounds., Finish an orbit gesture.

### Community 168 - "._relayout"
Cohesion: 0.18
Nodes (6): Switch between horizontal-strip and NxN grid layout., Remove a video pane by path., Show or hide a video pane without unloading it., Resume relayout after a batch add sequence., Remove all widgets from the grid and re-add them in the current arrangement…, Update camera labels, disambiguating duplicate filenames.

### Community 169 - "test_headless_core.py"
Cohesion: 0.20
Nodes (10): _production_trees(), Headless core guard test., Architecture rule 2 applies per module, not only to the package __init__.…, Catch the violation even when a lazy import hides it at runtime., Unexpected failures must be reported, not converted into blank UI state., Guard the UI-thread and cross-platform subprocess architecture rules., test_every_core_module_imports_without_pyside6(), test_no_core_module_imports_pyside6_statically() (+2 more)

### Community 170 - "PROMPTS.md — kickoff prompts per phase"
Cohesion: 0.18
Nodes (10): Debugging prompt template (any phase), Phase 0 prompts, Phase 1 prompts, Phase 2 prompts, Phase 3 prompts, Phase 4 prompts (one per feature, same pattern), Phase 5 prompts, Phase 6 prompts (+2 more)

### Community 171 - "QLabel"
Cohesion: 0.09
Nodes (22): QLabel, _CameraRow, _ChannelReadout, _DeltaRow, QGroupBox, QWidget, Show this camera's frame number and media time. Deliberately not called…, Shows Δvalue for one channel. (+14 more)

### Community 172 - "SyncWorker"
Cohesion: 0.22
Nodes (7): EvidenceSpec, ndarray, QObject, Slot, Build an evidence-based proposal without blocking the UI thread., Extract raw evidence and emit one deterministic fit proposal., SyncWorker

### Community 173 - "Video Extraction Toolbox — output schema for AvialSync"
Cohesion: 0.13
Nodes (14): 1. Where the files are, 2. File format, 3. HDF5 layout, 4. JSON sidecar, 5. Channel model, 6. Time base, 7. Session-level notes, 8. The per-ROI store (upstream of the export) (+6 more)

### Community 174 - "._build_channel_by_channel"
Cohesion: 0.20
Nodes (9): count_nan(), Count NaNs in a possibly mmap-backed array without a full-size temporary., _gap_locations(), ndarray, Build legacy plugin channels while keeping compatibility with v1 loaders. Each…, Return up to :data:`MAX_GAP_LOCATIONS` gap timestamps as bounded evidence., test_count_nan_is_chunked_and_exact(), test_gap_locations_are_capped_while_the_count_stays_exact() (+1 more)

### Community 175 - "_ArrayReader"
Cohesion: 0.22
Nodes (7): _ArrayReader, ndarray, Path, Performance guard for the 3D tracking cursor hot path., Minimal mmap-reader equivalent for isolating per-tick sampling cost., Sampling 128 XYZ points must leave room in the existing cursor budget., test_bench_tracking_3d_cursor()

### Community 176 - "TestPluginDiscovery"
Cohesion: 0.24
Nodes (7): LogCaptureFixture, Path, A leading underscore marks a helper, not a plugin to import., A third-party plugin must never take the application down with it., Users are told to create ~/.avialsync/plugins; most never do., Silent failure made a broken plugin vanish with no way to tell why., TestPluginDiscovery

### Community 177 - "test_prepare_release.py"
Cohesion: 0.27
Nodes (10): parametrize, Path, Unit coverage for the local release-preparation helper., The helper accepts normal final and prerelease version forms., Tags and PyPI metadata must use a single canonical version spelling., Version authority updates cannot silently replace unrelated quoted text., _release_tool(), test_replace_declared_version_updates_only_the_expected_declaration() (+2 more)

### Community 178 - "Data Output Schema — for AvialSync integration"
Cohesion: 0.20
Nodes (9): 1. Two layers, only one is machine-readable, 2. `data_root` folder layout, 3. Contents of a `<roi_id>__<metric>.mat` file, 4. Timestamps are not in `data_root` — reconstruct them, 5. What `data_root` does *not* give you, 6. Suggested AvialSync `SessionSource` mapping, 7. Stability / cleanup notes, Data Output Schema — for AvialSync integration (+1 more)

### Community 179 - "no_startup_diagnostics"
Cohesion: 0.20
Nodes (9): Config, hookimpl, no_startup_diagnostics(), fixture, MonkeyPatch, pytest_configure(), Pytest configuration., Re-arm faulthandler without its all-threads walk on Windows. pytest enables… (+1 more)

### Community 180 - "2026-07 · D-022 · Interaction standard — visible surface, depth in menus, shortcuts as accelerators"
Cohesion: 0.20
Nodes (10): 1. Single authority — one QAction (or one transport signal) per action, 2026-07 · D-022 · Interaction standard — visible surface, depth in menus, shortcuts as accelerators, 2. StandardKey over hardcoded strings wherever a platform standard exists, 3. macOS menuRoles required, 4. J/K/L shuttle semantics, 5. A/B button active state, 6. Shortcuts dialog rendering, 7. Open Video → Ctrl+Shift+V, Open Data → Ctrl+Shift+D (+2 more)

### Community 181 - "2. Evidence-based alignment from TTL or frame triggers"
Cohesion: 0.20
Nodes (10): 1. A fixed offset, when one recording is simply early or late, 2. Evidence-based alignment from TTL or frame triggers, 3. Check the result, Before you start, Choose the strategy, Choose what to compare, Or set the mapping by hand, Preview first, then accept (+2 more)

### Community 183 - "ndarray"
Cohesion: 0.27
Nodes (5): ndarray, Copy of the currently sampled XYZ positions, including NaN placeholders., Rotate world coordinates so the anatomical vertical is view +Z., Project world points to screen; the anatomical vertical maps to screen up., Project points already expressed in view space (see :meth:`_to_view`).

### Community 184 - "_QuickWorker"
Cohesion: 0.20
Nodes (8): QObject, Slot, _QuickWorker, A job that starts reporting again must stop being flagged., A QObject moved to a QThread with no Python reference never starts., test_a_registered_worker_actually_runs(), test_finished_jobs_are_dropped_from_the_registry(), test_progress_clears_a_not_responding_state()

### Community 185 - "TestShowDelta"
Cohesion: 0.12
Nodes (6): app(), panel(), fixture, Tests for ReadoutPanel.show_delta and set_camera_states., TestSetCameraStates, TestShowDelta

### Community 186 - "Plugin guide"
Cohesion: 0.22
Nodes (9): Claiming a whole recording folder, Naming your format, Optional: messages the recording carries, Optional: single-pass bulk ingest, Plugin guide, Session plugins, Synchronization and future plugins, Time-series plugins (+1 more)

### Community 187 - "Troubleshooting"
Cohesion: 0.22
Nodes (9): A file does not open, A startup error naming numpy or quantities, A video says “No Footage”, The import wizard read my timestamps wrong, The plots look slow or too dense, The video pane stays blank, Troubleshooting, Video does not play after `pip install` (+1 more)

### Community 188 - "Phase Status"
Cohesion: 0.22
Nodes (9): Cross-platform pressure audit (D-040), Done — Inspection Layer (A–K, D-020), Done (Phase 4), Done (Phase 4 UX / loader fixes), Fixed (this PR — Phase 4 stabilization), Implemented — TTL/event synchronization baseline (D-026), mypy is clean — keep it that way (V-07), Pending (+1 more)

### Community 189 - "VideoSurface"
Cohesion: 0.21
Nodes (7): QPaintEvent, QWidget, Paints the decoded frame, letterboxed. The geometry here must match…, Drop the displayed frame., Blit the frame centred, preserving aspect ratio., Create the paint canvas, name/OSD labels, and placeholder overlay., VideoSurface

### Community 190 - "_with_messages"
Cohesion: 0.20
Nodes (10): MessageSpec, The ``MessageCenter`` annotation stream — what the experimenter typed. Open…, Write the default recording plus a MessageCenter the experimenter typed., The annotation stream has no logic level to plot, and prose to read. Declining…, Reading the text must not resurrect the zero-filled trace it used to make., The notes belong to the recording, not to whichever stream was chosen. Gating…, test_message_center_is_still_not_a_plotted_channel(), test_message_center_text_is_read_not_discarded() (+2 more)

### Community 191 - "TestEmptyChannel"
Cohesion: 0.22
Nodes (6): channel(), fixture, Edge behaviour of the pyramid reader and the loader registry. Both sit on paths…, A one-second channel sampled at 100 Hz, with a gap in the middle., A channel with no samples must answer, not raise, on every query., TestEmptyChannel

### Community 192 - "_BulkLoader"
Cohesion: 0.18
Nodes (6): _BulkLoader, _LegacyLoader, Any, ndarray, Loader exposing the one-pass bulk chunk API used by CSV/tracking., Loader with only the frozen v1 ``read_chunks`` contract.

### Community 194 - "Quickstart"
Cohesion: 0.25
Nodes (8): After installing, Align recordings, Before you start, Inspect one moment, Open files, Quickstart, Try it without your own data, Where to go next

### Community 195 - "Development and release"
Cohesion: 0.25
Nodes (8): Building the documentation, Connecting the Read the Docs project, Development and release, Releases, Signing, Source checkout, The demo session, Windows checkout

### Community 196 - "User Guide"
Cohesion: 0.25
Nodes (8): 3D tracking controls, Aligning recordings, Appearance and font size, Flagging and exporting, Main areas of the window, Useful controls, User Guide, Where the detail lives

### Community 197 - "Sessions, proxies, and the 3D view"
Cohesion: 0.25
Nodes (8): Appearance, Keyboard shortcuts, Plot navigation, Proxies, Sessions, Sessions, proxies, and the 3D view, The 3D tracking view, When files have moved

### Community 198 - "Performance Budgets (engineering-certified where ★)"
Cohesion: 0.25
Nodes (8): 29. A built-in loader's dependencies can fail, and that must not be fatal, 30. The Windows `0xC0000005` was inside faulthandler — trigger removed with libmpv, 31. Connect a job's result signals in `configure`, never after `_run_job` returns, 8f. The pyramid query must fill the point budget, not merely fit under it, 8g. Shutdown steps are isolated and ordered; never let one raise skip the rest, 8h. Text editors steal the playhead keys unless they are explicitly reserved, 8i. Never build all plot rows in one call, Performance Budgets (engineering-certified where ★)

### Community 199 - "smoke_bundle"
Cohesion: 0.36
Nodes (7): bundle_executable(), main(), Path, Launch a built AvialSync bundle headlessly and require a clean shutdown., Return the platform executable in a PyInstaller one-directory bundle., Require the bundled Qt application to construct and close successfully.…, smoke_bundle()

### Community 200 - "AvialSync"
Cohesion: 0.25
Nodes (7): AvialSync, Contributing, Documentation, First session, Install, Licence, What it gives you

### Community 201 - ".can_open"
Cohesion: 0.22
Nodes (4): Any, Path, Detect EKS CSV by filename pattern and header structure., Read headers and identify x/y/z channels.

### Community 202 - "SyncProposal"
Cohesion: 0.20
Nodes (7): A deterministic synchronization proposal with bounded display evidence., Whether this proposal is unambiguous and within its fit tolerance., SyncProposal, Return the proposal selected by the user after accepted execution., Provide an explicit fallback when evidence is sparse or ambiguous., A user-accepted proposal changes only the target TimeMap and is persisted., test_accepted_sync_mapping_updates_video_and_session()

### Community 203 - "Architecture"
Cohesion: 0.29
Nodes (6): Architecture, Loading and viewing a source, Main parts, Master timeline, Session and extension boundaries, Synchronization design

### Community 204 - "Tutorial: inspect a first session"
Cohesion: 0.29
Nodes (7): 1. Load the camera, 2. Load the recording, 3. Find an event, 4. Mark it, 5. Save an observation, Next, Tutorial: inspect a first session

### Community 205 - "release"
Cohesion: 0.29
Nodes (6): Event, drain_abandoned(), Wait for retained threads to finish. For tests and orderly interpreter exit.…, fixture, Unblock and drain every wedged worker before the test process moves on.…, release()

### Community 206 - "Signal Wiring Map"
Cohesion: 0.29
Nodes (7): Import pipeline (updated, D-020), PlotPane / Player → downstream, Sidebar → MainWindow → subsystems, Signal Wiring Map, Source properties + integrity (D-020), Time display mode (D-020), Transport → Player → subsystems

### Community 207 - "PlotHeader"
Cohesion: 0.18
Nodes (8): PlotHeader, QWidget, Expose one live-style, page, Y-fit, row-height, and reset control strip., Show a persisted live style without emitting a duplicate state transition., Return the effective presentation after playback/scrub state is applied., PlotPresentation, The plot presentation selected from one authoritative master clock., StrEnum

### Community 208 - "._apply_default_splitter_sizes"
Cohesion: 0.25
Nodes (4): QSplitter, Forbid collapsing a pane to nothing. Must be re-applied after ``restoreState``:…, Re-seed any splitter a previously-saved state left with a zero pane. A zero-…, Seed the first-run pane layout, as sizes now and as shares thereafter. Called…

### Community 209 - "inspection.py"
Cohesion: 0.29
Nodes (5): Headless dataclasses for import statistics and source integrity (D-020). No…, clean(), Free-text records the acquisition system stored alongside the data.…, Return *text* as a single-line, length-bounded message body. Embedded newlines…, test_clean_folds_newlines_and_bounds_length()

### Community 210 - ".fit_current_pose"
Cohesion: 0.25
Nodes (3): Choose which world axis renders upward, and its direction. Setting this…, Fit the camera to the valid points at the current master time., Update from the same master-clock value used by video and 2D plots.

### Community 211 - "ShortcutsDialog"
Cohesion: 0.33
Nodes (4): QDialog, Keyboard shortcuts reference dialog — derived from live QAction registry…, Modal dialog listing all keyboard shortcuts. Derives content entirely from live…, ShortcutsDialog

### Community 212 - "2026-08 · D-081 · The video-extraction export is the ROI-metric surface, and it is HDF5"
Cohesion: 0.40
Nodes (5): 2026-08 · D-081 · The video-extraction export is the ROI-metric surface, and it is HDF5, Alternatives rejected, Consequences, Context, Decision

### Community 213 - "Formats"
Cohesion: 0.33
Nodes (5): Formats, Lab formats, Sensor and tracking data, Timing comes from the frames, not the container, Video

### Community 214 - "Licensing"
Cohesion: 0.33
Nodes (5): Bundled components, Contributing, Licensing, Plugins are your own work, What you can do

### Community 215 - "Tutorial: flag frames and export"
Cohesion: 0.33
Nodes (6): Export, Flag a frame, Mark a range, Review and label what you flagged, Tutorial: flag frames and export, What is not exported

### Community 216 - "build_bundle"
Cohesion: 0.40
Nodes (5): build_bundle(), main(), Path, Build a one-directory AvialSync bundle for the current platform. Nothing is…, Run PyInstaller over the project spec.

### Community 217 - ".test_boundary_duplicate_is_collapsed"
Cohesion: 0.29
Nodes (4): MonkeyPatch, A duplicate timestamp straddling a chunk boundary keeps the last value., A backward jump straddling a chunk boundary still raises., A duplicate frame number straddling a batch boundary keeps the last value.

### Community 218 - ".add_pane"
Cohesion: 0.33
Nodes (3): Pass tracking data readers to all video panes for overlay rendering. Retained,…, Attach named 2D prediction tracks to the pane showing *path* only. 2D pose data…, Add a pane identified by original *path*, playing *media_path* if supplied.

### Community 219 - "AOL2DTrack"
Cohesion: 0.25
Nodes (7): AOL2DTrack, _collect_2d_tracks(), _match_camera(), The fused 2D pose prediction bound to the camera it was tracked on. Exactly one…, Find the fused per-camera 2D pose CSV under ``predictions/``. Layout produced…, Resolve a file stem to one of the session's cameras. Longest label first so…, Whether this is the fused ensemble result rather than a single model.

### Community 220 - ".eventFilter"
Cohesion: 0.33
Nodes (4): QEvent, QObject, Repaint the lanes when the platform appearance changes. Lane colours are…, Reserve Space for playback while retaining ordinary Tab accessibility.

### Community 221 - "._timestamp_dtype"
Cohesion: 0.40
Nodes (3): DataType, Map wizard format strings to internal categories., Return the explicit parser dtype required by the chosen time format.

### Community 222 - "test_packaging_spec.py"
Cohesion: 0.33
Nodes (5): Regression checks for the PyInstaller specification., The bundle carries no separately-staged media runtime (D-075). PyInstaller…, SPECPATH is the packaging directory, not the spec-file path., test_spec_resolves_the_project_root_from_packaging_directory(), test_spec_stages_no_media_of_its_own()

### Community 223 - "2026-07 · D-032 · Headless CI uses null video, decoded-frame evidence, and explicit mpv ownership — AMENDED by D-075"
Cohesion: 0.40
Nodes (5): 2026-07 · D-032 · Headless CI uses null video, decoded-frame evidence, and explicit mpv ownership — AMENDED by D-075, Consequences, Context, Decision, macOS render-client teardown amendment

### Community 224 - "2026-07 · D-037 · Releases require a tag reachable from main"
Cohesion: 0.40
Nodes (5): 2026-07 · D-037 · Releases require a tag reachable from main, Consequences, Context, Decision, Ubuntu AppImageTool amendment

### Community 225 - "2026-07 · D-043 · Presentation timestamps own video timing and exact interaction"
Cohesion: 0.40
Nodes (5): 2026-07 · D-043 · Presentation timestamps own video timing and exact interaction, Alternatives rejected, Consequences, Context, Decision

### Community 226 - "2026-07 · D-044 · Plot presentation separates review, sweep, and scope"
Cohesion: 0.40
Nodes (5): 2026-07 · D-044 · Plot presentation separates review, sweep, and scope, Alternatives rejected, Consequences, Context, Decision

### Community 227 - "2026-07 · D-045 · The AOL encoder axis is seconds-since-midnight, unwrapped"
Cohesion: 0.40
Nodes (5): 2026-07 · D-045 · The AOL encoder axis is seconds-since-midnight, unwrapped, Alternatives rejected, Consequences, Context, Decision

### Community 228 - "2026-07 · D-046 · Pose data drives the overlay and 3D view, never plot rows"
Cohesion: 0.40
Nodes (5): 2026-07 · D-046 · Pose data drives the overlay and 3D view, never plot rows, Alternatives rejected, Consequences, Context, Decision

### Community 229 - "2026-08 · D-080 · AOL extracted-metric MAT files are detected by filename, not a fixed folder"
Cohesion: 0.40
Nodes (5): 2026-08 · D-080 · AOL extracted-metric MAT files are detected by filename, not a fixed folder, Alternatives rejected, Consequences, Context, Decision

### Community 230 - "pull_request_template.md"
Cohesion: 0.40
Nodes (4): Anything reviewers should look at closely, Checklist, How it was verified, What and why

### Community 231 - "sign_notarize.sh"
Cohesion: 0.80
Nodes (4): notarize_dmg(), require_env(), sign_notarize.sh script, sign_app()

### Community 233 - ".read_all_chunks"
Cohesion: 0.50
Nodes (3): ndarray, Yield (time, value) chunks for one channel. Compatibility path for the frozen…, Yield x/y/z channels from a single CSV pass. ``channels`` restricts the…

### Community 236 - ".closeEvent"
Cohesion: 0.40
Nodes (3): QCloseEvent, Run one shutdown step; log and continue if it fails. Closing is the one path…, Always close. This used to ``event.ignore()`` while any background job was…

### Community 239 - "test_three_camera_four_stream_session_can_be_cached_and_queried"
Cohesion: 0.40
Nodes (4): Path, Cross-platform functional check for the representative scientific workload., Exercise the session shape scientists use without treating CI as a speed test., test_three_camera_four_stream_session_can_be_cached_and_queried()

### Community 240 - "2026-07 · D-033 · Packaging inputs are explicit and CI artifact builds are a separate gate"
Cohesion: 0.50
Nodes (4): 2026-07 · D-033 · Packaging inputs are explicit and CI artifact builds are a separate gate, Consequences, Context, Decision

### Community 241 - "2026-07 · D-034 · Themes are palette/font appearance, never interaction redesign"
Cohesion: 0.50
Nodes (4): 2026-07 · D-034 · Themes are palette/font appearance, never interaction redesign, Consequences, Context, Decision

### Community 242 - "2026-07 · D-036 · PR and tag quality use one cross-platform test contract"
Cohesion: 0.50
Nodes (4): 2026-07 · D-036 · PR and tag quality use one cross-platform test contract, Consequences, Context, Decision

### Community 243 - "2026-07 · D-038 · Windows video panes use libmpv's Qt OpenGL render API — SUPERSEDED by D-075"
Cohesion: 0.50
Nodes (4): 2026-07 · D-038 · Windows video panes use libmpv's Qt OpenGL render API — SUPERSEDED by D-075, Consequences, Context, Decision

### Community 244 - "2026-07 · D-039 · Release bundles own the complete media runtime — AMENDED by D-075"
Cohesion: 0.50
Nodes (4): 2026-07 · D-039 · Release bundles own the complete media runtime — AMENDED by D-075, Consequences, Context, Decision

### Community 245 - "2026-07 · D-040 · Sidecar writes use bounded concurrency and failures remain observable"
Cohesion: 0.50
Nodes (4): 2026-07 · D-040 · Sidecar writes use bounded concurrency and failures remain observable, Consequences, Context, Decision

### Community 246 - "2026-07 · D-042 · Plots use one fixed, shared oscilloscope sweep"
Cohesion: 0.50
Nodes (4): 2026-07 · D-042 · Plots use one fixed, shared oscilloscope sweep, Consequences, Context, Decision

### Community 248 - "_resolved_marker_color"
Cohesion: 0.50
Nodes (3): Return the *index*-th marker colour against the application palette., Resolve this marker's colour against the current application palette., _resolved_marker_color()

### Community 249 - "_nearest_index"
Cohesion: 0.50
Nodes (3): _nearest_index(), Sample and display the pose nearest to the master-clock time., Find the nearest timestamp without scanning a trajectory.

### Community 254 - "test_bench_sync.py"
Cohesion: 0.50
Nodes (3): Performance gate for deterministic TTL/event alignment previews., A 10,000-event preview must remain interactive and deterministic., test_bench_sync_fit_preview()

### Community 255 - "test_packaging_metadata.py"
Cohesion: 0.50
Nodes (3): Tests for published-package compatibility metadata., Published metadata supports exactly the tested Python range., test_package_caps_python_at_3_12()

### Community 256 - "test_worker_thread_teardown.py"
Cohesion: 0.50
Nodes (3): Regression checks for how background workers are destroyed (D-062)., A worker moved onto a QThread must not be ``deleteLater``-ed from it. Both…, test_no_worker_is_destroyed_inside_its_own_thread()

### Community 257 - "2026-07 · D-023 · Benchmarks CI-gated; budget-assertion pattern; CI multiplier"
Cohesion: 0.67
Nodes (3): 2026-07 · D-023 · Benchmarks CI-gated; budget-assertion pattern; CI multiplier, Context, Decisions

### Community 258 - "2026-07 · D-029 · Separate GitHub workload correctness from local speed certification"
Cohesion: 0.67
Nodes (3): 2026-07 · D-029 · Separate GitHub workload correctness from local speed certification, Context, Decision

### Community 259 - "2026-07 · D-030 · Test-level watchdog for cross-platform Qt verification"
Cohesion: 0.67
Nodes (3): 2026-07 · D-030 · Test-level watchdog for cross-platform Qt verification, Context, Decision

### Community 260 - "2026-07 · D-031 · Libmpv commands stay on the Qt-owning thread — SUPERSEDED by D-075"
Cohesion: 0.67
Nodes (3): 2026-07 · D-031 · Libmpv commands stay on the Qt-owning thread — SUPERSEDED by D-075, Context, Decision

### Community 264 - "main_window"
Cohesion: 0.67
Nodes (3): main_window(), fixture, QApplication

### Community 274 - "set_video_coverage"
Cohesion: 0.67
Nodes (3): ndarray, Project media bounds through its TimeMap before drawing master-time coverage., set_video_coverage()

### Community 281 - "tiny_batches"
Cohesion: 0.67
Nodes (3): fixture, Shrink the batch size so a boundary is reachable in a small fixture., tiny_batches()

## Knowledge Gaps
- **451 isolated node(s):** `avialsync-plugin-example`, `make_appimage.sh script`, `make_dmg.sh script`, `avialsync`, `What and why` (+446 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **23 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MainWindow` connect `MainWindow` to `generate_screenshots`, `Path`, `Transport`, `export_controller.py`, `ImportReportDialog`, `.resizeEvent`, `main_window`, `VideoGrid`, `MessageStore`, `test_pane_proportions.py`, `main_window.py`, `JobManager`, `set_video_coverage`, `_apply`, `diagnostics.py`, `PyAVReader`, `VideoStandardLoader`, `VideoOpenWorker`, `test_interaction_standard.py`, `generate_guide_screenshots.py`, `SessionState`, `test_close_and_focus.py`, `.eventFilter`, `TimeMap`, `_parse_args`, `session_controller.py`, `QLabel`, `video_standard.py`, `test_worker_lifetime.py`, `PlotPane`, `PyramidBuilder`, `Path`, `_QuickWorker`, `TimeDisplayMode`, `export_worker.py`, `test_workload_responsiveness.py`, `_JobWorker`, `import_controller.py`, `SourceInspection`, `test_ui_sensor_mapping.py`, `Player`, `test_messages.py`, `capture`, `SyncProposal`, `AnnotationStore`, `ChannelKey`, `demo.py`, `._apply_default_splitter_sizes`, `ShortcutsDialog`, `test_ui_shortcut_reach.py`, `LoaderRegistry`, `test_ui_layout_resize.py`, `Tracking3DPane`, `test_aol_pose_routing.py`, `test_never_freeze.py`, `DemoLaunch`, `._generate_proxy`, `.closeEvent`, `._on_sensor_mapping_changed`, `test_frame_indexed.py`, `_FakePane`, `test_sync_golden.py`, `load_video`, `UiHeartbeat`, `.__init__`, `ProxyWorker`?**
  _High betweenness centrality (0.215) - this node is a cross-community bridge._
- **Why does `PlotPane` connect `PlotPane` to `MainWindow`, `test_bench_plot_pane.py`, `main_window.py`, `TestMeasureMarkers`, `plot_pane.py`, `test_bench_cursor_path`, `SweepWindowControl`, `test_close_and_focus.py`, `TimeMap`, `TimeDisplayMode`, `_JobWorker`, `test_ui_plot_row_geometry.py`, `Player`, `PlotInteractionController`, `AnnotationStore`, `ChannelKey`, `PlotHeader`, `test_ui_follow.py`, `test_theme_tooltips.py`, `tracking_3d_pane.py`, `test_ui_plot_sliced_refresh.py`, `.__init__`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Why does `TimeSeriesSource` connect `main_window.py` to `MainWindow`, `CSVLoader`, `AOLEksLoader`, `AOLMetricLoader`, `NeoLoader`, `BatchImportDialog`, `video_standard.py`, `Path`, `SourceOpenError`, `AOLVideoExtractionLoader`, `_JobWorker`, `import_controller.py`, `DummyVideoLoader`, `Message`, `LoaderRegistry`, `AOLEncoderLoader`, `DummyTimeSeriesLoader`, `ToyBinarySource`, `DropScanWorker`, `Path`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Are the 58 inferred relationships involving `MainWindow` (e.g. with `DemoData` and `DemoGenerationWorker`) actually correct?**
  _`MainWindow` has 58 INFERRED edges - model-reasoned connections that need verification._
- **Are the 19 inferred relationships involving `PlotPane` (e.g. with `Player` and `_JobWorker`) actually correct?**
  _`PlotPane` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 43 inferred relationships involving `TimeMap` (e.g. with `ChannelKey` and `MappedChannelReader`) actually correct?**
  _`TimeMap` has 43 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `PyramidReader` (e.g. with `ChannelKey` and `MappedChannelReader`) actually correct?**
  _`PyramidReader` has 27 INFERRED edges - model-reasoned connections that need verification._