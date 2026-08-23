# Graph Report - avialview  (2026-08-23)

## Corpus Check
- 260 files · ~402,866 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 6019 nodes · 11181 edges · 294 communities (268 shown, 26 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 942 edges (avg confidence: 0.6)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a494dbfa`
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
- Message
- test_hot_path.py
- PaintCanvas
- test_playback_smoothness.py
- test_pane_proportions.py
- TimeSeriesSource
- infer_skeleton
- Known Traps
- DemoLaunch
- AOLMetricLoader
- PyAVReader
- VideoStandardLoader
- NeoLoader
- PlotHeader
- ImportWorker
- test_cli_demo.py
- test_interaction_standard.py
- MappedChannelReader
- generate_guide_screenshots.py
- SweepWindowControl
- PyramidBuilder
- test_close_and_focus.py
- SessionState
- test_pyav_reader.py
- test_video_pane.py
- AvialSync — Project Blueprint (v1)
- MasterClock
- TimeMap
- test_frame_identity.py
- test_session_worker.py
- SeekGroup
- test_scrubbing.py
- MonkeyPatch
- importer.py
- test_theme_colors.py
- sync.py
- test_worker_lifetime.py
- PlotPane
- format_time
- CacheManager
- Path
- ._on_evidence_changed
- test_loaders_neo.py
- test_seek_backends.py
- MissingColumnError
- AOLVideoExtractionLoader
- VideoTimingMixin
- ndarray
- export.py
- test_workload_responsiveness.py
- _JobWorker
- import_controller.py
- test_ci_platform_config.py
- test_core_coverage_edges.py
- write_recording
- DummyVideoLoader
- SourceInspection
- test_ui_plot_row_geometry.py
- session_controller.py
- test_ui_sensor_mapping.py
- Player
- ReaderReference
- capture
- pyramid.py
- PlotInteractionController
- main_window.py
- ChannelKey
- color_for_point
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
- VideoMetadata
- AOLEncoderLoader
- make_fixtures.py
- test_ui_layout_resize.py
- extract_ttl_edges
- TimelineEvidence
- LoaderRegistry
- QPainter
- _pulses
- test_typed_source_errors.py
- Tracking3DPane
- SourceOpenError
- test_aol_pose_routing.py
- test_never_freeze.py
- test_ui_dialogs.py
- tracking_3d_pane.py
- theme.py
- video_standard.py
- test_frame_indexed.py
- write_video
- encode_proxy
- test_packaging_smoke.py
- _FakePane
- test_sync_golden.py
- load_video
- test_core_pyramid.py
- VideoPropertiesPanel
- AvialSync Plot UX Refinement Plan
- fit_exact_index_mapping
- SnapshotWorker
- UiHeartbeat
- TESTING.md
- test_ui_plot_sliced_refresh.py
- ARCHITECTURE.md
- ToyBinarySource
- ProxyWorker
- .__init__
- skeleton.py
- _press
- generate_demo_screenshots.py
- drop_controller.py
- test_bench_plot_pane.py
- test_demo_data.py
- test_transport_resize.py
- ImportReportDialog
- job_manager.py
- ChannelInfo
- test_aol_video_extraction_routing.py
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
- test_aol_metric_routing.py
- test_conda_recipe.py
- TestMeasureMarkers
- .__init__
- set_font_family
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
- test_a_rig_plugin_is_named_system_then_kind
- Job
- .eventFilter
- create_channel_plot
- .reset_view
- ._relayout
- test_headless_core.py
- PROMPTS.md — kickoff prompts per phase
- ReadoutPanel
- SyncWorker
- Video Extraction Toolbox — output schema for AvialSync
- VideoStandardProbe
- _ArrayReader
- ._refresh_status
- test_prepare_release.py
- Data Output Schema — for AvialSync integration
- no_startup_diagnostics
- 2026-07 · D-022 · Interaction standard — visible surface, depth in menus, shortcuts as accelerators
- 2. Evidence-based alignment from TTL or frame triggers
- .materialize
- fit_channel_y
- _QuickWorker
- TestShowDelta
- Plugin guide
- Troubleshooting
- Phase Status
- TimelineOverview
- _with_messages
- AnnotationStore
- _BulkLoader
- Quickstart
- Development and release
- User Guide
- Sessions, proxies, and the 3D view
- Performance Budgets (engineering-certified where ★)
- smoke_bundle
- AvialSync
- .open
- SyncWizard
- Architecture
- Tutorial: inspect a first session
- release
- Signal Wiring Map
- .update_plots
- ._apply_default_splitter_sizes
- DropScanWorker
- ._on_ab_in
- Path
- 2026-08 · D-081 · The video-extraction export is the ROI-metric surface, and it is HDF5
- Formats
- Licensing
- Tutorial: flag frames and export
- build_bundle
- .read_chunks
- .add_pane
- TestAOLSessionDetection
- .eventFilter
- TestPluginDiscovery
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
- build_gap_mask
- PointColorRegistry
- ndarray
- _PointArrays
- .closeEvent
- ._on_sensor_mapping_changed
- RuntimeError
- .exact_time_mapping
- 2026-07 · D-033 · Packaging inputs are explicit and CI artifact builds are a separate gate
- 2026-07 · D-034 · Themes are palette/font appearance, never interaction redesign
- 2026-07 · D-036 · PR and tag quality use one cross-platform test contract
- 2026-07 · D-038 · Windows video panes use libmpv's Qt OpenGL render API — SUPERSEDED by D-075
- 2026-07 · D-039 · Release bundles own the complete media runtime — AMENDED by D-075
- 2026-07 · D-040 · Sidecar writes use bounded concurrency and failures remain observable
- 2026-07 · D-042 · Plots use one fixed, shared oscilloscope sweep
- ShortcutsDialog
- _resolved_marker_color
- ._accept_sync_proposal
- .set_time
- .set_viewport
- ._on_pane_double_clicked
- default_skeleton
- test_bench_sync.py
- test_packaging_metadata.py
- test_worker_thread_teardown.py
- 2026-07 · D-023 · Benchmarks CI-gated; budget-assertion pattern; CI multiplier
- 2026-07 · D-029 · Separate GitHub workload correctness from local speed certification
- 2026-07 · D-030 · Test-level watchdog for cross-platform Qt verification
- 2026-07 · D-031 · Libmpv commands stay on the Qt-owning thread — SUPERSEDED by D-075
- SkeletonEstimate
- .resizeEvent
- .frame_records_at
- .set_sync_mapping
- conf.py
- commit-msg
- post-commit
- pre-commit
- make_appimage.sh
- make_dmg.sh
- avialsync
- Any
- build_manifest
- current_preference
- 2026-08 · D-082 · A skeleton is detected from geometry when the data declares none
- AOL2DTrack
- ProgressCallback
- QDialog
- QObject
- Slot
- QDragEnterEvent
- QDropEvent
- QMouseEvent
- QPaintEvent
- fixture

## God Nodes (most connected - your core abstractions)
1. `MainWindow` - 355 edges
2. `PlotPane` - 114 edges
3. `TimeMap` - 106 edges
4. `PyramidReader` - 102 edges
5. `LoaderRegistry` - 91 edges
6. `DECISIONS.md — lightweight ADR log` - 86 edges
7. `SourceOpenError` - 72 edges
8. `PyramidBuilder` - 70 edges
9. `VideoStandardLoader` - 69 edges
10. `Transport` - 69 edges

## Surprising Connections (you probably didn't know these)
- `test_frame_records_at_empty_grid()` --calls--> `VideoGrid`  [INFERRED]
  tests/test_annotation_frames.py → src/avialsync/ui/video_grid.py
- `test_frame_records_at_offset_applied()` --calls--> `VideoGrid`  [INFERRED]
  tests/test_annotation_frames.py → src/avialsync/ui/video_grid.py
- `test_frame_records_at_single_pane()` --calls--> `VideoGrid`  [INFERRED]
  tests/test_annotation_frames.py → src/avialsync/ui/video_grid.py
- `test_frame_records_at_two_panes()` --calls--> `VideoGrid`  [INFERRED]
  tests/test_annotation_frames.py → src/avialsync/ui/video_grid.py
- `test_manifest_finds_metric_files_regardless_of_data_root_name()` --calls--> `build_manifest()`  [INFERRED]
  tests/test_aol_metric_routing.py → src/avialsync/loaders/aol_session_loader.py

## Import Cycles
- None detected.

## Communities (294 total, 26 thin omitted)

### Community 0 - "MainWindow"
Cohesion: 0.02
Nodes (38): QMainWindow, build_next_video_pane(), on_video_opened(), on_video_pane_ready(), on_video_thread_finished(), Hold the probe result until this file's turn to build a native pane. Probes…, Build the next pane in request order, if one is ready and none is busy., Release the worker ownership after its thread has stopped on the UI thread. (+30 more)

### Community 1 - "test_loaders_open_ephys.py"
Cohesion: 0.04
Nodes (80): Path, Return per-frame exposure evidence from a ``frame_number,timestamp`` sidecar.…, read_frame_timestamps(), _drop(), _layout(), datetime, Path, Tests for the Open Ephys session plugin and the neo ingest path behind it.… (+72 more)

### Community 2 - "CSVLoader"
Cohesion: 0.06
Nodes (39): DataType, Series, The ``(source_id, channel_id)`` identity of this channel., FileUnreadableError, AvialSync exception hierarchy., Raised when a file cannot be read or parsed., CSVLoader, Any (+31 more)

### Community 3 - "Transport"
Cohesion: 0.04
Nodes (41): Parse HH:MM:SS.fff, MM:SS, or bare seconds., Transport bar: play/pause, frame step, scrub slider, A/B loop, rate control,…, The master-timeline extent currently displayed. Public because…, The currently displayed status message., Show compact, non-blocking status text beside Reset Zoom., Show accepted synchronization events in the overview strip., Show imported data gaps in the overview strip., Show messages the sources recorded in the overview strip. (+33 more)

### Community 4 - "export_controller.py"
Cohesion: 0.06
Nodes (41): QWidget, Grab a widget's current visual content as a QPixmap., snapshot_widget(), export_annotations(), export_data_slice(), export_snapshot(), export_snapshot_for_pane(), export_video_clip() (+33 more)

### Community 5 - "VideoPane"
Cohesion: 0.04
Nodes (34): Video grid layout manager., DecodeWorker, ndarray, QCloseEvent, QObject, setter, Slot, Decode the newest requested time, if one is still outstanding. (+26 more)

### Community 6 - "AOLEksLoader"
Cohesion: 0.13
Nodes (12): AOLEksLoader, Return one ChannelInfo per x/y/z coordinate. EKS rows are one video frame each,…, Tracking Data (2D/3D). Format: standard CSV with header row. Columns follow the…, EKS data is always frame-indexed., Detect EKS CSV by filename pattern and header structure., Path, EKS rows are one frame each, so rate_hz is the camera fps, not None., Reading before open() reports it instead of raising AttributeError. (+4 more)

### Community 7 - "PyramidReader"
Cohesion: 0.06
Nodes (43): PyramidReader, Reads pyramid queries dynamically from mmapped arrays., channel(), fixture, Edge behaviour of the pyramid reader and the loader registry. Both sit on paths…, A one-second channel sampled at 100 Hz, with a gap in the middle., `value_at` answers for any time; outside coverage the answer is NaN., Nearest-sample, not interpolation: the readout must not invent data. (+35 more)

### Community 8 - "open_ephys_session.py"
Cohesion: 0.06
Nodes (56): One file a session contributes, with the loader and config it needs. ``loader``…, What a recording folder contains, plus the settings that span it. Session-wide…, SessionItem, SessionLayout, anchor_epoch(), find_record_dir(), find_recordings(), is_recording_dir() (+48 more)

### Community 9 - "DECISIONS.md — lightweight ADR log"
Cohesion: 0.03
Nodes (64): 2026-07 · D-001 · Master time = float64 seconds, UTC epoch, 2026-07 · D-002 · Video playback = libmpv only — SUPERSEDED by D-075, 2026-07 · D-003 · License Apache-2.0; no GPL deps — SUPERSEDED by D-069, 2026-07 · D-004 · Sidecar cache format, 2026-07 · D-005 · Chunked ingest is the only ingest path, 2026-07 · D-006 · VideoSource conversion hook is first-class, 2026-07 · D-007 · Frame stepping uses actual frame timestamps, 2026-07 · D-008 · Cache key gets content-hash tail (+56 more)

### Community 10 - "aol_session_loader.py"
Cohesion: 0.14
Nodes (28): Any, SessionItem, SessionLayout, _add_root_videos(), _anchor_epoch(), AOLManifest, _eks_items(), _encoder_items() (+20 more)

### Community 11 - "Message"
Cohesion: 0.05
Nodes (55): Headless dataclasses for import statistics and source integrity (D-020). No…, bounded(), clean(), Message, Any, Free-text records the acquisition system stored alongside the data.…, One free-text record read from a source file. ``time`` is in the *source's* own…, Return *text* as a single-line, length-bounded message body. Embedded newlines… (+47 more)

### Community 12 - "test_hot_path.py"
Cohesion: 0.08
Nodes (22): overview(), fixture, QApplication, The 60 Hz tick keeps authoritative time but does not repaint everything. P3.5…, 100 000 events inside the window must collapse to at most one per column., A new lane must inherit the sorted index, not scan its events per frame. This…, A Player whose observers are all mocks, so calls can be counted., Authoritative time must not be throttled — only presentation is. (+14 more)

### Community 13 - "PaintCanvas"
Cohesion: 0.08
Nodes (30): OverlayTrack, PaintCanvas, Any, QWidget, Transparent tracking overlay used by :mod:`avialsync.ui.video_pane`., Move the overlay to *t*, repainting only if it has marks to move. A pane with…, One prediction source drawn over a camera's video. ``points`` maps a body-part…, Paint the current tracking points without obscuring video. (+22 more)

### Community 14 - "test_playback_smoothness.py"
Cohesion: 0.06
Nodes (48): SimpleNamespace, DecodingPane, _osd_pane(), _OsdPane, QApplication, Playback must not generate work proportional to the decoded frame rate. Each…, Drive the real tick for *seconds* of simulated playback. Returns ``(master_t,…, The new playback model, stated as an assertion. Under libmpv the player watched… (+40 more)

### Community 15 - "test_pane_proportions.py"
Cohesion: 0.06
Nodes (48): distribute(), _pane_minimums(), PaneProportions, QObject, QSplitter, Hold each pane's share of the workspace steady while the window is resized.…, Manage *splitters*, adopting each one's ratio the first time it lays out., Adopt *splitter*'s current pane ratio as the one to hold. A visible pane… (+40 more)

### Community 16 - "TimeSeriesSource"
Cohesion: 0.04
Nodes (45): ABC, _Capability, Protocol, Plugin registry and discovery., What every scored plugin has in common: it can rate a path., Return all discovered source loaders., default_display_name(), _Nameable (+37 more)

### Community 17 - "infer_skeleton"
Cohesion: 0.10
Nodes (35): frame_budget(), infer_skeleton(), Derive skeleton connectivity from how rigidly point pairs hold together. Args:…, Frames to sample for *point_count* points, bounded by the pairwise budget., Detecting bones on load must stay inside the UI-callback ceiling (D-082).…, test_bench_skeleton_detection(), _articulated_chain(), ndarray (+27 more)

### Community 18 - "Known Traps"
Cohesion: 0.04
Nodes (55): 0. Scheduled work that outlives its owner crashes rather than fails (D-062, D-064), 0a. A `QObject` moved to a `QThread` needs an owning Python reference, 0b. Building a widget list can free the widgets in it (D-065), 0b. Do NOT add the anchor date to AOL encoder timestamps (D-045), 0c. AOL pose data must not become plot rows (D-046), 0c-bis. Overlay data reaches the grid before most panes exist (D-077), 0d. `"_eks.csv".split("_")[0]` is `""` — and `"" in name` matches everything, 0e. A container's declared frame rate is a claim, not evidence (D-072) (+47 more)

### Community 19 - "DemoLaunch"
Cohesion: 0.07
Nodes (28): QDialog, QObject, QSettings, Slot, DemoGenerationWorker, DemoLaunch, DemoProgressDialog, MainWindow (+20 more)

### Community 20 - "AOLMetricLoader"
Cohesion: 0.07
Nodes (29): AOLMetricLoader, _column_names(), Any, Path, Extracted Metric (Optical Flow / MI). Format: single-variable `-v6` MAT file,…, Rows are frames with no stored time axis, same contract as EKS., Match the `<roi_id>__<metric>.mat` filename, then confirm the variable. The…, Load the single `roi_metric_data` array and resolve column names. (+21 more)

### Community 21 - "PyAVReader"
Cohesion: 0.05
Nodes (30): ndarray, Path, VideoStream, PyAVReader, Demux one pass to collect presentation timestamps and keyframes. Demux only —…, Presentation timestamps in source seconds, display order., Number of frames the container actually carries timestamps for., The decoded video stream, for callers building format metadata. (+22 more)

### Community 22 - "VideoStandardLoader"
Cohesion: 0.04
Nodes (53): main(), main(), _holds_video_stream(), Any, ndarray, Path, Return whether *path* opens as a container carrying real video. Header read…, Loads standard videos, probing metadata and frame timing with PyAV. (+45 more)

### Community 23 - "NeoLoader"
Cohesion: 0.07
Nodes (30): _fit_length(), NeoLoader, Any, ndarray, Path, Trim or NaN-pad *batch* to *expected* samples. Neo resolves a lazy…, Loads electrophysiology data using the neo library., Find the dataset root neo should be pointed at, or ``None``. Open Ephys… (+22 more)

### Community 24 - "PlotHeader"
Cohesion: 0.15
Nodes (10): PlotHeader, QWidget, Compact shared controls for the time-series plot stack., Expose one live-style, page, Y-fit, row-height, and reset control strip., Show a persisted live style without emitting a duplicate state transition., Return the effective presentation after playback/scrub state is applied., PlotPresentation, Shared fixed-window sweep state and controls for time-series plots. (+2 more)

### Community 25 - "ImportWorker"
Cohesion: 0.12
Nodes (34): ChannelStage, Append-only on-disk staging buffer for one float64 channel. An import worker…, Number of samples appended so far., ImportWorker, QObject, Background worker for parsing and building pyramids from time-series sources., fixture, MonkeyPatch (+26 more)

### Community 26 - "test_cli_demo.py"
Cohesion: 0.06
Nodes (46): AvialSync root module., _parse_args(), Namespace, Parse the supported AvialSync command-line arguments., Path, Tests for the installed ``avialsync demo`` command., The previous two-channel cache cannot silently downgrade the restored demo., The release smoke gate waits for this count, so it must be reachable. It was… (+38 more)

### Community 27 - "test_interaction_standard.py"
Cohesion: 0.06
Nodes (40): _all_shortcuts(), main_window(), fixture, parametrize, QApplication, D-022 interaction standard tests. Verifies: - New transport buttons emit the…, The reset-zoom action in the plot context menu must be the same object as the…, Collect the NativeText of every shortcut registered on the window. (+32 more)

### Community 28 - "MappedChannelReader"
Cohesion: 0.07
Nodes (32): MappedChannelReader, Replace the offset/drift mapping in place. Existing plot rows and readout rows…, Return this channel's master-time extent, or None when empty., A pyramid channel presented on the master clock through its ``TimeMap``., The underlying source-time reader., The source-to-master mapping applied by every method here., Open a fresh mmap reader owned by the calling thread., cache_dir() (+24 more)

### Community 29 - "generate_guide_screenshots.py"
Cohesion: 0.20
Nodes (16): _capture_all(), generate(), _load_session(), Path, QApplication, Capture the annotated screenshots used by the user guide and tutorials. Every…, Return the sidebar's per-video widget, whatever its concrete class., Open the sample video and signal through the ordinary code paths. (+8 more)

### Community 30 - "SweepWindowControl"
Cohesion: 0.08
Nodes (17): QWidget, Return the shared sweep duration in seconds., Return the absolute master time at the current sweep's left edge., Return the latest master-clock value supplied by the player., Set master bounds and anchor all future sweeps to their start., Set and emit a duration clamped to the current master bounds., Expand the sweep to the complete master timeline., Move the continuous slider one small step inward. (+9 more)

### Community 31 - "PyramidBuilder"
Cohesion: 0.07
Nodes (45): CacheError, Raised when the sidecar binary cache encounters an error., PyramidBuilder, Builds and serializes a multi-level pyramid to disk., Accepted synchronization evidence summary persisted in a session., SyncProvenance, ExactSyncFit, Piecewise exact target-time fit that honors nonlinear gaps/drops. (+37 more)

### Community 32 - "test_close_and_focus.py"
Cohesion: 0.12
Nodes (21): fixture, Path, _pyramid_channels(), The window always finishes closing, and the playhead keys always reach it. Two…, The grid used to be torn down before the session state was built., Whatever happens, the close event is accepted., Build *count* cheap channels in one cache directory., Row construction is ~10 ms each; 32 in one call is a third of a second frozen. (+13 more)

### Community 33 - "SessionState"
Cohesion: 0.06
Nodes (46): MarkerEntry, Any, Path, Session state and JSON serialization for .avv files., Deserialise from a parsed JSON dict (accepts v1 through v6)., Write session JSON and large exact mappings atomically. Small mappings remain…, Persisted state for one loaded video., Read a .avv session file and validate any exact-map sidecars. (+38 more)

### Community 34 - "test_pyav_reader.py"
Cohesion: 0.09
Nodes (29): long_gop_video(), fixture, MonkeyPatch, Path, TempPathFactory, Unit tests for the PyAV exact-frame reader. Frame *identity* is proven in…, The cache is a window on where the user just was, bounded by frames., Two float probes in one interval must be one entry, never two. (+21 more)

### Community 35 - "test_video_pane.py"
Cohesion: 0.09
Nodes (37): clip(), _opened_pane(), fixture, Path, QApplication, TempPathFactory, Video-pane construction, decoding, and teardown tests. Everything here used to…, End-to-end, through the real thread: the pixels must name the frame. (+29 more)

### Community 36 - "AvialSync — Project Blueprint (v1)"
Cohesion: 0.05
Nodes (36): AGENTS.md — AvialSync agent instructions (canonical), Architecture rules (violations = rejected PR), Coding standards, Definition of Done (every task), How to run things, Known traps (learned the hard way — do not rediscover), Naming & casing — BINDING (never invent variants), Task protocol for agents (+28 more)

### Community 37 - "MasterClock"
Cohesion: 0.07
Nodes (25): MasterClock, PlaybackState, Snapshot of current playback state., Single master clock for AvialSync. Time is driven externally via…, Register a callback that is fired on seek or playback advance., Set the absolute limits of the master timeline., Set playback rate, clamped between 0.01 and 10.0., Seek to a specific master time. (+17 more)

### Community 38 - "TimeMap"
Cohesion: 0.05
Nodes (29): given, ndarray, setter, Maps master timeline to a specific source timeline. t_source = t_master +…, Return the source-time rate relative to master time., Return the local source/master rate around ``t_master``. Exact frame-trigger…, Snap to the nearest accepted frame-trigger timestamp, if available., Return whether exact evidence covers ``t_master``. Affine mappings are… (+21 more)

### Community 39 - "test_frame_identity.py"
Cohesion: 0.13
Nodes (25): FixtureRequest, Convert a decoded frame to a contiguous ``(H, W, 3)`` uint8 RGB array. Costs…, to_rgb_array(), cfr_video(), _probe_times(), fixture, ndarray, parametrize (+17 more)

### Community 40 - "test_session_worker.py"
Cohesion: 0.11
Nodes (30): AnnotationExportWorker, Export annotation markers to CSV off the UI thread., Path, QObject, Slot, Background workers for session persistence. Architecture rule 3: the UI thread…, Serialize and write .avv + sidecars off the UI thread., Read and parse .avv + sidecars off the UI thread. Only parsing moves here.… (+22 more)

### Community 41 - "SeekGroup"
Cohesion: 0.10
Nodes (19): Asynchronous seek coordinator., Fan out non-blocking frame requests across video panes. ``VideoPane.seek``…, Request one pane's frame at a source time, without blocking., Request every active pane's frame at master time ``t``., Return True once every pane has painted the frame it was asked for., SeekGroup, Performance gates for timestamp-mapped multi-video command dispatch., Four 120-frame callback bursts must stay far below one UI tick. (+11 more)

### Community 42 - "test_scrubbing.py"
Cohesion: 0.05
Nodes (36): player_with_mocks(), fixture, Tests for live scrubbing coalescing behaviour in Player., Return a Player wired to mock collaborators (no Qt event loop needed)., _on_tick dispatches the pending scrub target once seeker settles., _on_tick does NOT flush while seeker is still busy., A stalled decoder may drop frames but cannot stop plots or 3D., Exact seek on release clears any pending coalesced target. (+28 more)

### Community 43 - "MonkeyPatch"
Cohesion: 0.10
Nodes (20): MonkeyPatch, parametrize, Dropped files route by registered source type, not a suffix allow-list., A generic directory falls back to capability-routing its direct children., Video workers need an explicit owner after being moved to a QThread., Metadata probes overlap up to the bound; they are independent per file.…, Probes finish out of order; panes must not (D-040)., One unreadable file must not strand every file queued behind it. (+12 more)

### Community 44 - "importer.py"
Cohesion: 0.09
Nodes (22): LoaderContractError, Raised when a source plugin violates the frozen v1 ingest contract. Distinct…, count_nan(), Count NaNs in a possibly mmap-backed array without a full-size temporary., _gap_locations(), Any, ndarray, Path (+14 more)

### Community 45 - "test_theme_colors.py"
Cohesion: 0.12
Nodes (31): _contrast(), _distance(), _palette(), parametrize, QColor, QPalette, Derived colours: legible on both surfaces, distinct, and following the accent.…, Derived means derived — change the accent and the lane moves with it. (+23 more)

### Community 46 - "sync.py"
Cohesion: 0.09
Nodes (34): Raised when synchronization evidence is malformed or insufficient., Raised when event evidence supports multiple equally valid alignments., SyncAmbiguityError, SyncEvidenceError, _candidate_indices(), _default_tolerance(), _evidence_indices(), _fit_affine() (+26 more)

### Community 47 - "test_worker_lifetime.py"
Cohesion: 0.07
Nodes (28): Behaviour extracted from :class:`~avialsync.ui.main_window.MainWindow`. Each…, _FakeFileDialog, main_window(), fixture, MonkeyPatch, Path, QApplication, QDropEvent (+20 more)

### Community 48 - "PlotPane"
Cohesion: 0.03
Nodes (49): PlotPane, InfiniteLine, QAction, QEvent, QResizeEvent, QWidget, Keep pyqtgraph's canvas aligned with an application palette change., Coalesce resize storms before selecting a new pyramid resolution. (+41 more)

### Community 49 - "format_time"
Cohesion: 0.08
Nodes (19): _fmt_relative(), format_time(), Enum, Time display mode enum and single formatting authority (D-020). All time-…, Format *t_seconds* according to *mode*. t_epoch is the Unix epoch of master-…, Format signed elapsed time without wrapping negative values by a day., TimeDisplayMode, _AnnotationLane (+11 more)

### Community 50 - "CacheManager"
Cohesion: 0.10
Nodes (25): CacheManager, is_cache_path(), Any, Path, Cache management for sidecar files., Get a temporary directory for writing cache. Ensure atomic swap later., Commit a replacement without discarding the last valid sidecar first., Replace a sidecar's contents without renaming the directory. Individual files… (+17 more)

### Community 51 - "Path"
Cohesion: 0.06
Nodes (11): Any, Path, QImage, QThread, Open a session file or a folder of recordings. Routes through the same scan a…, Show a per-pane context menu on video right-click (D-022)., Own a worker/thread pair for the whole life of a background job. Delegates to…, Forward to ReadoutPanel with accumulated units for known channels. (+3 more)

### Community 52 - "._on_evidence_changed"
Cohesion: 0.11
Nodes (13): _normalise_events(), ndarray, Return the sorted time column of *events* for binary search., Register one source coverage span, keyed for later replacement., Display accepted sync matches with inspectable provenance text., Display imported data gaps as red ticks., Display messages the sources recorded, with their text inspectable., Display point/range annotations in their stored colors. (+5 more)

### Community 53 - "test_loaders_neo.py"
Cohesion: 0.15
Nodes (16): Path, Tests for the NeoLoader ephys data plugin., NeoLoader must never claim .csv files., NeoLoader must return 0.0 for plain text files., NeoLoader must return 0.0 for files with a non-whitelisted extension., Directory containing structure.oebin is recognised as OpenEphys dataset., Directory with no ephys signatures should score 0.0., Verify .csv, .txt, .json, .py are not in the whitelist. (+8 more)

### Community 54 - "test_seek_backends.py"
Cohesion: 0.11
Nodes (32): _assert_within(), _bench_mpv(), camera_files(), _fanout(), _import_mpv(), _jump_targets(), _mpv_fanout(), mpv_players() (+24 more)

### Community 55 - "MissingColumnError"
Cohesion: 0.09
Nodes (21): AvialSyncError, CodecUnsupportedError, MissingColumnError, NonMonotonicTimeError, Any, Exception, Raised when time series timestamps go backwards., Raised when a video codec is not supported. (+13 more)

### Community 56 - "AOLVideoExtractionLoader"
Cohesion: 0.06
Nodes (36): AOLVideoExtractionLoader, False: this export carries its own time axis. The per-ROI v6 store has no time…, The camera this file belongs to, as the sidecar names it., Whether the loaded axis is absolute POSIX rather than recording-relative., Nominal frame rate the toolbox recorded, or ``0.0`` when absent., Claim a MAT file whose sidecar names this toolbox. Reads only the small JSON…, Extracted ROI Metrics (Video Extraction). One file is one camera. Each ``(ROI,…, export() (+28 more)

### Community 57 - "VideoTimingMixin"
Cohesion: 0.05
Nodes (36): adjacent_frame_time(), frame_index_at(), ndarray, Frame selection from presentation timestamps — the single authority. The frame…, Return the index of the presentation frame active at ``source_time``. Args:…, Return the neighbouring real presentation timestamp. Anchored on the frame…, Return the frame index presented at ``source_time``. The one resolution step in…, displayed_frame_rate() (+28 more)

### Community 58 - "ndarray"
Cohesion: 0.09
Nodes (18): _aggregate_gap_mask(), _aggregate_pyramid_level(), _nan_envelope(), ndarray, Aggregate one pyramid level from the preceding level's min/max envelopes., Carry raw discontinuity evidence into one coarser pyramid level. A gap marks…, Append one bounded chunk of samples., Build every level from in-memory arrays and write the full sidecar. (+10 more)

### Community 59 - "export.py"
Cohesion: 0.10
Nodes (27): QPixmap, The owning source's stable identifier (its path)., compute_region_stats(), export_data_slice_csv(), export_data_slice_parquet(), Any, ndarray, Path (+19 more)

### Community 60 - "test_workload_responsiveness.py"
Cohesion: 0.11
Nodes (30): _assert_no_stall_tail(), dense_source(), loaded_window(), _measure(), _measure_each(), _percentile(), fixture, parametrize (+22 more)

### Community 61 - "_JobWorker"
Cohesion: 0.09
Nodes (21): EventEvidenceSpec, Background TTL/event evidence extraction and alignment fitting., A cached signal channel from which TTL transitions are extracted., Native timestamp evidence, such as camera-frame trigger timestamps., SignalEvidenceSpec, _JobWorker, Protocol, Open evidence-based TTL/frame-event alignment for loaded sources. (+13 more)

### Community 62 - "import_controller.py"
Cohesion: 0.09
Nodes (28): enqueue_import(), on_import_error(), on_import_finished(), on_import_thread_finished(), Any, Path, Time-series import and pose routing. One import worker owns the modal progress…, Queue a source import so only one worker owns the import UI at a time. (+20 more)

### Community 63 - "test_ci_platform_config.py"
Cohesion: 0.07
Nodes (29): Regression checks for the shared cross-platform CI and release contract., An unpinned ffmpeg is both a CI flake and an unreproducible installer.…, Ubuntu 24.04 must provide AppImageTool's libfuse.so.2 runtime ABI., A version tag must not release a side branch or detached commit., Pushing a branch must never publish, and neither must a non-version tag.…, No job may build or publish without the tag having been verified., PyPI and the GitHub release must not publish two different versions. Nothing…, A PEP 440 pre-release tag must be marked as one on the release page. (+21 more)

### Community 64 - "test_core_coverage_edges.py"
Cohesion: 0.10
Nodes (28): channel(), _provenance(), fixture, Path, Edge paths in ``core/`` that no other test reached (P6.1, TESTING §1). TESTING…, Recovery is best-effort; failing to restore must not raise on a read path., Unequal arrays would silently mis-map frames on reload., A large mapping lives in a sidecar; a corrupt one must not load silently. (+20 more)

### Community 65 - "write_recording"
Cohesion: 0.10
Nodes (36): default_spec(), _message_manifest(), Path, Build a miniature Open Ephys binary recording for tests. Small enough to write…, Write *spec* under *root* and return the ``recording1`` directory., One continuous stream to write into the fixture., A TTL line to write as rising/falling edge pairs., Everything one ``recordingN`` directory should contain. (+28 more)

### Community 66 - "DummyVideoLoader"
Cohesion: 0.08
Nodes (19): patch, DummyVideoLoader, MonkeyPatch, Path, The `~/.avialsync/plugins/` drop-in path is a supported way to add a format., A broken plugin is otherwise indistinguishable from one never installed. Its…, Importable but useless is still a failure the author needs told about., One bad plugin must never take the application's own loaders with it. (+11 more)

### Community 67 - "SourceInspection"
Cohesion: 0.08
Nodes (23): ImportReport, IntegrityFlags, Any, All collected inspection data for one loaded source. Not frozen because…, Statistics collected by ImportWorker during one source import., Anomaly flags for one loaded source. Video flags (is_vfr, fps_mismatch) are set…, SourceInspection, create_video_pane() (+15 more)

### Community 68 - "test_ui_plot_row_geometry.py"
Cohesion: 0.33
Nodes (8): _pane_with_channels(), parametrize, Path, Plot rows must occupy the pane, not collapse to their minimum width. Rows are…, Every row's plot area must span the pane, whatever the size or row count., A second load must not leave the newest row collapsed beside settled ones., test_a_row_added_after_the_first_load_also_fills_the_pane(), test_rows_fill_the_pane_width()

### Community 69 - "session_controller.py"
Cohesion: 0.12
Nodes (25): autosave(), autosave_before_close(), on_session_load_error(), open_recent(), open_session(), Path, Session persistence, window geometry, autosave, and the recent-files menu.…, Load all sources from a SessionState object. (+17 more)

### Community 70 - "test_ui_sensor_mapping.py"
Cohesion: 0.10
Nodes (27): cache_dir(), fixture, Path, QApplication, Sensor offset/drift editing in the sidebar re-aligns plots without reimporting., Session restore holds the mapping until the async import finishes., set_mapping is display-only; it must not re-emit into the handler., The seam between the importer and the panel — and what session reload uses. A… (+19 more)

### Community 71 - "Player"
Cohesion: 0.12
Nodes (12): Return whether accepted per-frame evidence owns this mapping., Player, QObject, Stop UI ticks before the owning window tears down its panes., Start playback for programmatic callers such as the demo launcher., Use the first active exact mapping as the reference frame clock. This is…, Step to the neighbouring decoded frame across all video panes. The step size…, Set or clear the A/B loop region on the master clock. (+4 more)

### Community 72 - "ReaderReference"
Cohesion: 0.11
Nodes (18): DataExportWorker, Path, QImage, QObject, Calculate A/B-region statistics from worker-local pyramid readers., Calculate region statistics and tag the result with its request id., Run ffmpeg clipping jobs outside the Qt event loop., The stable information needed to open one mapped reader in a worker. The… (+10 more)

### Community 73 - "capture"
Cohesion: 0.19
Nodes (15): capture(), _load_session(), main(), Image, Path, QImage, quantize_to_shared_palette(), Capture a short looping animation of a real session folder opened through its… (+7 more)

### Community 74 - "pyramid.py"
Cohesion: 0.09
Nodes (17): build_pyramid_level(), Path, Pyramid module for decimation and plotting., Save quickly, retrying macOS interrupted writes through a memmap., Persist independent sidecar arrays with bounded storage concurrency., Build a decimation level for arrays t and v. Returns (t_decimated, v_min,…, _safe_save(), _save_arrays() (+9 more)

### Community 75 - "PlotInteractionController"
Cohesion: 0.11
Nodes (15): PlotInteractionController, Any, QAction, Refresh overlays whose X coordinates depend on the current page., Handle a right-click only when it lands inside a visible channel row., Own page-local overlay state while delegating semantic actions to PlotPane., Register shared QActions for the plot context menu., Place measurement pin A and publish a complete A/B interval. (+7 more)

### Community 76 - "main_window.py"
Cohesion: 0.07
Nodes (41): PlotItem, Master-clock presentation of a cached pyramid channel. A…, Master timeline and synchronization logic., Background workers for cached-data export and A/B-region statistics., Annotation markers: point and range, with list panel and CSV export., _quit_legacy_jobs(), Main window for AvialSync., Ask the pre-JobManager registries to stop, without blocking on them. These… (+33 more)

### Community 77 - "ChannelKey"
Cohesion: 0.08
Nodes (29): ChannelKey, disambiguate(), Path, Stable identity of one channel: its source plus its name. A channel name alone…, Return the display name, qualified by source only when it must be., Return display labels, qualifying only names owned by more than one source., Remove only this source's row — another file may use the same name., Replace displayed channels with a new list of readers. Rows are keyed by… (+21 more)

### Community 78 - "color_for_point"
Cohesion: 0.08
Nodes (26): color_for_point(), One palette, one name-to-colour rule, shared by the 2D overlay and 3D view. The…, Return the shared colour for the body part called *name*., QColor, QFont, QPainter, QPaintEvent, Draw every complete XY point of every track at the current source time. (+18 more)

### Community 79 - "test_plugin_discovery.py"
Cohesion: 0.14
Nodes (23): Path, Plugin API v1 discovery coverage., A drop-in plugin directory exposes a v1 source to the registry., They are hardcoded *and* declared as entry points; that must not duplicate., `can_open` is offered directories, so a lab can adopt its own folder layout.…, Claiming the folder must stop the scan recursing into its files. Otherwise the…, A lab adds its own folder layout by dropping in a file — no core change., The fan-out AOL uses must be reachable by any plugin, which is the point. (+15 more)

### Community 80 - "demo.py"
Cohesion: 0.10
Nodes (31): CancelledCallback, ProgressCallback, demo_data_dir(), _demo_frame(), _demo_frame_times(), DemoData, DemoWindow, ensure_demo_data() (+23 more)

### Community 81 - "prepare_release.py"
Cohesion: 0.16
Nodes (23): Pattern, dirty_paths(), ensure_preconditions(), main(), prepare_release(), Path, Prepare, validate, commit, tag, and push an AvialSync PyPI release. Run from…, Update version authorities and optionally create and publish the release tag. (+15 more)

### Community 82 - "Tracking3DCanvas"
Cohesion: 0.05
Nodes (34): QPainter, QPaintEvent, QWheelEvent, _nearest_index(), ndarray, _qcolor(), Custom-painted current-pose view with mouse orbit and wheel zoom., Number of complete XYZ points available to the view. (+26 more)

### Community 83 - "test_ui_follow.py"
Cohesion: 0.10
Nodes (6): fixture, Path, Tests for fixed-window oscilloscope plotting., A narrow spike remains visible instead of being averaged into a midpoint., sweep_pane(), test_decimated_plot_preserves_minimum_and_maximum_envelope()

### Community 84 - "test_aol_chunk_boundaries.py"
Cohesion: 0.16
Nodes (23): _collect(), fixture, ndarray, Path, AOL loaders honour the frozen ingest contract across batch boundaries (V-15,…, A 15-channel file must not read 45 columns to answer for one., Projection is an optimisation; it must not change a single sample., Shrink the batch size so a boundary is reachable in a small fixture. (+15 more)

### Community 85 - "test_engine_importer.py"
Cohesion: 0.11
Nodes (16): _BulkLoader, Path, Tests for the asynchronous time-series import pipeline., A loader that also carries what the experimenter typed during recording., A third-party loader whose message reader is broken., On a cache hit the loader is never opened, so the manifest must carry them.…, One-pass test loader whose legacy per-channel API must never be used., Losing the samples fails an import; losing a comment must not. (+8 more)

### Community 86 - "test_theme_tooltips.py"
Cohesion: 0.09
Nodes (21): Theme tests for appearance-only changes on all supported appearances., Tooltips remain readable through palette roles, not a global stylesheet., Collecting a cycle mid-snapshot frees widgets Qt has already handed over., Pausing collection around the snapshot must not outlive it., Rooting the snapshot in the window trees may not narrow what it covers., A custom OS accent must flow into links and interactive controls., A widget with no parent is a top-level window in Qt, so it is still covered., The demo must use the same saved appearance as the production app. (+13 more)

### Community 87 - "test_subprocess_no_window.py"
Cohesion: 0.12
Nodes (21): Call, skipif, no_window_kwargs(), NoWindowKwargs, Process-level runtime helpers. This module used to locate a media runtime —…, Subprocess keyword arguments that suppress a console window. A ``TypedDict``…, Return subprocess kwargs that keep a child process from opening a console. A…, _is_platform_guarded() (+13 more)

### Community 88 - "test_ui_shortcut_reach.py"
Cohesion: 0.10
Nodes (26): KeyboardModifier, _editor_rejects_text(), Return whether *widget* would refuse *text* as typed input. A numeric field…, Return whether a Qt validator refused the text outright.…, _validates_as_invalid(), _fires(), _focusable(), fixture (+18 more)

### Community 89 - "VideoMetadata"
Cohesion: 0.13
Nodes (17): Format-neutral video metadata exposed by every video source. Timestamp-derived…, VideoMetadata, QPaintEvent, QWidget, Paints the decoded frame, letterboxed. The geometry here must match…, Drop the displayed frame., Blit the frame centred, preserving aspect ratio., Create the paint canvas, name/OSD labels, and placeholder overlay. (+9 more)

### Community 90 - "AOLEncoderLoader"
Cohesion: 0.08
Nodes (18): AOLEncoderLoader, Any, Path, Return a single velocity channel. ``rate_hz`` stays ``None``: the logger writes…, Loads AOL encoder logs in bounded chunks. Format: space-separated, no header, 4…, Return high confidence for files matching the encoder log pattern., Validate the file and store config., MonkeyPatch (+10 more)

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
Cohesion: 0.18
Nodes (8): _ABPin, QFrame, QWidget, Titled, collapsible Data Streams shell for named TimelineOverview lanes., The currently displayed status message, without its label prefix., Show active work beside Reset Zoom and clear non-active messages shortly after., Thin vertical marker overlaid on the slider for A/B loop points., TimelineEvidence

### Community 95 - "LoaderRegistry"
Cohesion: 0.12
Nodes (14): LoaderRegistry, Add each built-in class in *specs*, reporting any that will not import. A…, Add every class published under *group*, skipping ones that fail. Deduplicates…, Load source classes exported by loose ``*.py`` plugin modules., Return all discovered session scanners., Discovers and loads source plugins., Return supported loose-plugin directories, in discovery order. BLUEPRINT Phase…, Find loaders and session scanners in their entry point groups. (+6 more)

### Community 97 - "_pulses"
Cohesion: 0.14
Nodes (12): _pulses(), ndarray, parametrize, An unsafe alignment must be refused, never guessed. `core/sync.py` decides…, Malformed timestamp arrays must be rejected before any fitting., Reordering evidence would fabricate a pairing the source never had., A repeated timestamp has no single position on the master clock., Refuse configurations that cannot produce a trustworthy fit. (+4 more)

### Community 98 - "test_typed_source_errors.py"
Cohesion: 0.14
Nodes (14): Any, Path, Loaders and the importer raise typed errors, not bare builtins (V-06). AGENTS…, Distinct from SourceOpenError: the fix is in the plugin, not the data., The UI cannot turn a bare builtin into an actionable dialog., One base means the UI can catch the whole family in a single handler., test_a_plugin_breaking_the_ingest_contract_is_named_as_such(), test_every_typed_error_shares_one_base() (+6 more)

### Community 99 - "Tracking3DPane"
Cohesion: 0.12
Nodes (36): PyramidReader, Timeline-synchronized 3D tracking pane., Tracking3DPane, _anatomical_readers(), Path, Tests for the timeline-synchronized 3D tracking pane., Build a pose whose vertical axis is Y and grows downward. Mirrors the real AOL…, The 3D view must orient anatomy head-up, not use a fixed Z-up axis. The… (+28 more)

### Community 100 - "SourceOpenError"
Cohesion: 0.11
Nodes (20): Raised when a media or data source fails to open., SourceOpenError, Headless exact-frame video reading on PyAV. This is the decoder the application…, Any, Path, Video-extraction-toolbox ROI metric loader. Reads one camera's extracted…, Read the sidecar, then every numeric array from the HDF5 file., Return what to add to the file's own axis to reach master time. Which… (+12 more)

### Community 101 - "test_aol_pose_routing.py"
Cohesion: 0.07
Nodes (48): fixture, SessionSource, AOLSessionSource, Lay out an AOL multi-camera experiment folder as a session. This is the…, aol_session(), _declare_skeleton(), _finish_import(), Path (+40 more)

### Community 102 - "test_never_freeze.py"
Cohesion: 0.14
Nodes (19): QApplication, The UI must stay responsive, visible, and closeable under any workload. This is…, The regression: closeEvent called event.ignore() and trapped the user., Abandoning jobs must not skip the session write., A worker that ignores cancellation, like a blocked syscall., A wedged job must not hold shutdown open., The grace period is a total budget, not per job., test_a_quiet_job_is_reported_as_not_responding() (+11 more)

### Community 103 - "test_ui_dialogs.py"
Cohesion: 0.08
Nodes (38): ImportWizard, Any, QDialog, Dialog for configuring CSV/time-series import parameters. Previews the file,…, Return the import configuration dict for the pipeline., QDialog, Missing-file relink dialog shown when session files cannot be found., Return {original_path: new_path} for files the user relocated. (+30 more)

### Community 104 - "tracking_3d_pane.py"
Cohesion: 0.08
Nodes (31): Enum, MappedChannelReader, _build_sources(), _coordinate_name(), detect_up_axis(), _mean_axis_position(), _PointChannels, Interactive 3D view for cached tracking-coordinate channels. (+23 more)

### Community 105 - "theme.py"
Cohesion: 0.16
Nodes (25): _accent(), accent_hue(), evidence_color(), _is_dark_palette(), loop_pin_color(), marker_color(), on_surface(), _palette_with_surfaces() (+17 more)

### Community 106 - "video_standard.py"
Cohesion: 0.14
Nodes (7): Neo-based electrophysiology loader — the single ingest path for ephys data.…, Standard Video Loader., Per-frame exposure evidence read from a capture sidecar., RecordedFrames, Main Window regression tests., generate_screenshots(), on_finished()

### Community 107 - "test_frame_indexed.py"
Cohesion: 0.14
Nodes (19): Path, Tests for frame-indexed source contract and DLC fps resolution (D-019)., _frame_indexed_sources accumulates provisional entries when no video is loaded., TimeSeriesSource.is_frame_indexed() should default to False., _rebind_frame_indexed_sources should clear the provisional list., After rebind, re-enqueued import uses the video fps, not the provisional fps., TrackingLoader.is_frame_indexed() must return True., Write a minimal two-bodypart DLC CSV to *path*. (+11 more)

### Community 108 - "write_video"
Cohesion: 0.14
Nodes (18): encode_frame_index(), ndarray, Frame strip encoder and decoder for robust video sync testing. We encode a…, Encode a 32-bit integer into the top-left pixels of the given frame (in-place).…, Test that we can perfectly round-trip integers through the encoder/decoder., Generate a tiny video, extract frames with ffmpeg, decode, assert indices., test_framestrip_in_memory(), test_framestrip_via_ffmpeg() (+10 more)

### Community 109 - "encode_proxy"
Cohesion: 0.15
Nodes (18): CancelCheck, InputContainer, _duration_seconds(), encode_proxy(), encode_video(), _even(), Fraction, ndarray (+10 more)

### Community 110 - "test_packaging_smoke.py"
Cohesion: 0.19
Nodes (18): CaptureFixture, _load_smoke_module(), ModuleType, MonkeyPatch, Path, Regression tests for built-bundle startup verification., Freezing a bundle is release-tag work, and it must be gated on startup., CI proves correctness on every push; only a tag builds and ships. Bundling on… (+10 more)

### Community 111 - "_FakePane"
Cohesion: 0.13
Nodes (15): _FakePane, fixture, Path, QWidget, Removing a video persists the session before the media client is torn down.…, Removal must not invent a session file for someone who never saved one., A real widget the grid's layout accepts, minus libmpv. A plain object cannot…, The signal is useless if it arrives after the teardown it guards. (+7 more)

### Community 112 - "test_sync_golden.py"
Cohesion: 0.14
Nodes (18): app_with_main_window(), _capture_frame(), _fixture_frame_time(), fixture, ndarray, QApplication, Golden sync testing for video playback., Test multi-camera golden sync with offsets. (+10 more)

### Community 113 - "load_video"
Cohesion: 0.33
Nodes (6): load_video(), on_video_open_error(), Any, Path, Show a source-open error without leaving a partially-created pane., Queue a video source for probing and, in request order, pane creation.

### Community 114 - "test_core_pyramid.py"
Cohesion: 0.16
Nodes (17): MonkeyPatch, Path, A valid short raw gap cannot disappear merely because the view is coarse., A background sidecar failure must fail the import, never look successful., A transient macOS EINTR takes the robust fallback without hiding data., A plot must get roughly one column per pixel, not one per fifteen. Stored…, The ceiling has to hold when even the coarsest stored level is too fine. The…, Below the budget the user must see real samples, not an envelope. (+9 more)

### Community 115 - "VideoPropertiesPanel"
Cohesion: 0.09
Nodes (15): _frame_count_text(), _PropertiesBase, Any, QGroupBox, QWidget, Collapsible source-properties panels for VideoInfoWidget and SensorInfoWidget…, Collapsible properties panel for one video source., Read the pane's current decode state; call when the panel is expanded. The rate… (+7 more)

### Community 116 - "AvialSync Plot UX Refinement Plan"
Cohesion: 0.12
Nodes (16): 10. Focus and keyboard contract, 11. Performance invariants, 12. Persistence and migration, 13. Implementation slices, 14. Required test evidence, 15. Definition of done, 1. Objective, 2. Compatibility ledger — nothing in this list may be lost (+8 more)

### Community 117 - "fit_exact_index_mapping"
Cohesion: 0.16
Nodes (12): fit_exact_index_mapping(), Create a deterministic exact index mapping, overriding affine limits. Frames…, Shifting past the end leaves nothing to pair., Video frame 0 maps to reference index N, the documented behaviour., The 1:1 frame mapping has its own overlap requirement., TestExactIndexMapping, parametrize, Ground-truth tests for exact index synchronization. (+4 more)

### Community 118 - "SnapshotWorker"
Cohesion: 0.13
Nodes (13): Slot, Trim every requested clip sequentially without blocking UI input., Encode UI-captured images without blocking the Qt event loop., Compose and save the immutable image copies on this worker thread., SnapshotWorker, QImage, Hand immutable UI captures to a background PNG encoder., start_snapshot_export() (+5 more)

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
Cohesion: 0.17
Nodes (8): Any, Path, A minimal external AvialSync Plugin API v1 implementation., Read ``.toybin`` records encoded as little-endian ``(time, value)`` pairs., Recognise the example file extension without opening the input., Store the path after validating whole-record alignment., Expose the single dimensionless signal channel., ToyBinarySource

### Community 124 - "ProxyWorker"
Cohesion: 0.17
Nodes (12): needs_proxy(), proxy_path_for(), ProxyWorker, Path, QObject, Proxy generation — re-encode videos to all-keyframe scrub-friendly proxies., Return the sidecar proxy path for a given video., Check if a proxy already exists and is newer than the source. (+4 more)

### Community 125 - ".__init__"
Cohesion: 0.04
Nodes (48): QTreeWidgetItem, QVBoxLayout, Register window-scoped QActions for all keyboard-only shortcuts (D-022). Rules…, _make_empty_inspection(), QFrame, QWidget, Left Sidebar / Inspector Pane., Set a channel checkbox and return whether this source owns it. (+40 more)

### Community 126 - "skeleton.py"
Cohesion: 0.16
Nodes (18): _component(), _finite_height(), _pair_statistics(), ndarray, Skeleton topology derived from the geometry of 3D pose points. Point *names*…, Return (cost, variation) matrices; ``inf`` marks a pair that cannot link., Prim's algorithm, restarted per component, over a dense cost matrix. Restarting…, Treat a missing height as the lowest possible, never as a winner. (+10 more)

### Community 127 - "_press"
Cohesion: 0.14
Nodes (19): _playhead_events(), _press(), Key, parametrize, QApplication, Merely holding focus is not an edit in progress., Correcting a timecode mid-entry must still work., No timecode or number contains a space, so Space is always playback. (+11 more)

### Community 128 - "generate_demo_screenshots.py"
Cohesion: 0.36
Nodes (7): generate_screenshots(), main(), _pin_appearance(), Path, QApplication, Capture the synchronization walkthrough used in the README. Run with ``conda…, Force the documented appearance without touching saved preferences.…

### Community 129 - "drop_controller.py"
Cohesion: 0.15
Nodes (21): QDragEnterEvent, QDropEvent, apply_session_layout(), drag_enter(), drop_event(), on_drop_scan_error(), on_drop_scan_finished(), on_drop_session_found() (+13 more)

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
Cohesion: 0.28
Nodes (5): ImportReportDialog, QDialog, QWidget, Scrollable plain-text view of an ImportReport with a Copy button., Show the full ImportReport dialog for a data source.

### Community 134 - "job_manager.py"
Cohesion: 0.17
Nodes (11): BackgroundWorker, _drop_finished_threads(), JobState, Enum, Protocol, QThread, One owner for every background job, so the UI can never be trapped. Three…, Release retained jobs whose threads have stopped. Never call this from a… (+3 more)

### Community 135 - "ChannelInfo"
Cohesion: 0.08
Nodes (18): ChannelInfo, Metadata for a single data channel., Return stable metadata for every importable channel., Return one ChannelInfo per ``(ROI, column)`` pair., Any, ndarray, Path, Tracking Data (DLC/LightningPose) Loader. (+10 more)

### Community 136 - "test_aol_video_extraction_routing.py"
Cohesion: 0.19
Nodes (17): fixture, Path, AOL session routing for video-extraction-toolbox exports. These are ordinary…, The per-ROI store still loads on its own when no export exists., No sidecar, no match: the tree holds MATLAB files from other tools., A two-camera session carrying a video-extraction export for each., Only the loader can tell which axis its file holds, so it gets both., The two hold the same numbers; importing both would plot every ROI twice. The… (+9 more)

### Community 137 - "VideoGrid"
Cohesion: 0.14
Nodes (9): QWidget, Manages N VideoPanes in either a horizontal strip or an NxN grid. Uses a single…, Stop every pane's decoder before their Qt parent is destroyed. Each pane is…, Update the time offset for a specific video., Defer relayout until end_batch_add(). Use for multi-file drops., Return a copy of the loaded video paths, parallel to self.panes., Return panes currently selected and displayed by the grid., Treat legacy directly-injected test panes as visible. (+1 more)

### Community 138 - "test_annotation_frames.py"
Cohesion: 0.15
Nodes (14): Path, Tests for frame-accurate annotation: VideoFrame, export, AnnotationPanel., Pane-owned decode threads must stop before Qt destroys the grid., Annotation frame numbers must never use t*fps arithmetic for VFR media., test_add_point_no_frames_defaults_to_empty(), test_export_csv_columns(), test_export_csv_marker_with_no_frames(), test_export_csv_one_row_per_video() (+6 more)

### Community 139 - "_MappingLoader"
Cohesion: 0.18
Nodes (11): _declared_exact_mapping(), Return per-frame timing the loader recorded, once it has been validated. A…, _MappingLoader, parametrize, Minimal stand-in for a VideoSource that declares per-frame timing., This arrives from a plugin, so it is checked rather than trusted. A mapping…, The fallback names any plugin that does not override, so it must read well. The…, test_derived_names_break_acronyms_correctly() (+3 more)

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

### Community 147 - "test_aol_metric_routing.py"
Cohesion: 0.22
Nodes (13): aol_session_with_metrics(), fixture, ndarray, Path, AOL extracted-metric routing: data_root MAT exports become plot rows. Unlike…, A data_root dropped without its sibling videos still loads, unaligned., An AOL session with one camera plus a nested data_root-style export., The metric file's start_epoch must match its camera's video, not 0. (+5 more)

### Community 148 - "test_conda_recipe.py"
Cohesion: 0.24
Nodes (13): _project_metadata(), The conda-forge recipe must describe the package this repository builds., A recipe pinned to a stale version publishes the wrong source archive., A missing run dependency is an import error on a user's first launch., The conda package is now the same shape as the wheel (D-075). Decoding,…, conda must not offer the package on a Python the project excludes., The console script conda installs must be the one the package defines., _recipe_text() (+5 more)

### Community 149 - "TestMeasureMarkers"
Cohesion: 0.15
Nodes (5): app(), plot_pane(), fixture, Tests for PlotPane measure markers and measure_changed signal., TestMeasureMarkers

### Community 150 - ".__init__"
Cohesion: 0.10
Nodes (16): QTableWidget, QTableWidgetItem, _guess_format(), _guess_time_column(), Path, QWidget, Timestamp import wizard with preview, format autodetect, and timezone handling., Return the index of the most likely timestamp column. (+8 more)

### Community 151 - "set_font_family"
Cohesion: 0.07
Nodes (34): Import Report dialog — shows ImportReport stats with a copy-as-text button., QAction, Apply the selected system-relative application font scale., _apply(), apply_font_size(), _apply_font_to_existing_widgets(), apply_theme(), _capture_widget_base_fonts() (+26 more)

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

### Community 163 - "test_a_rig_plugin_is_named_system_then_kind"
Cohesion: 0.17
Nodes (5): Kinds of data an acquisition recording carries besides the ephys. One…, One rig must read the same wherever it appears, beside the others. "Rig Camera…, One reader serves many kinds, so the type must not be the reader's name. Every…, test_a_rig_plugin_is_named_system_then_kind(), test_a_type_names_the_data_never_the_rig()

### Community 164 - "Job"
Cohesion: 0.18
Nodes (6): Job, One unit of background work, owned for its whole lifetime., Whether the worker offers a cooperative cancel., Jobs that have gone quiet for longer than the watchdog allows., Ask every cancellable job to stop; never blocks., Stop everything and return the labels that had to be abandoned. Always returns…

### Community 165 - ".eventFilter"
Cohesion: 0.15
Nodes (10): _is_mid_edit(), QDragEnterEvent, QDropEvent, QEvent, QObject, QWidget, Forward drops over child panes, and keep the playhead keys reserved., Return whether this key belongs to the playhead rather than the focus widget.… (+2 more)

### Community 166 - "create_channel_plot"
Cohesion: 0.13
Nodes (11): GraphicsLayoutWidget, Build queued rows in time slices, letting the event loop run between them. A…, create_channel_plot(), Path, Create one row without deciding shared X-axis ownership. The row always reads…, Any, Curve whose already-decimated data may be revealed by a moving sweep edge., Move the paint clip without rebuilding or re-querying curve data. (+3 more)

### Community 167 - ".reset_view"
Cohesion: 0.17
Nodes (6): QMouseEvent, Restore the default orbit and fit the current pose., Begin orbiting on a primary-button drag., Orbit around the stable scene bounds., Finish an orbit gesture., Fit the current pose on double click.

### Community 168 - "._relayout"
Cohesion: 0.18
Nodes (6): Switch between horizontal-strip and NxN grid layout., Remove a video pane by path., Show or hide a video pane without unloading it., Resume relayout after a batch add sequence., Remove all widgets from the grid and re-add them in the current arrangement…, Update camera labels, disambiguating duplicate filenames.

### Community 169 - "test_headless_core.py"
Cohesion: 0.20
Nodes (10): _production_trees(), Headless core guard test., Architecture rule 2 applies per module, not only to the package __init__.…, Catch the violation even when a lazy import hides it at runtime., Unexpected failures must be reported, not converted into blank UI state., Guard the UI-thread and cross-platform subprocess architecture rules., test_every_core_module_imports_without_pyside6(), test_no_core_module_imports_pyside6_statically() (+2 more)

### Community 170 - "PROMPTS.md — kickoff prompts per phase"
Cohesion: 0.18
Nodes (10): Debugging prompt template (any phase), Phase 0 prompts, Phase 1 prompts, Phase 2 prompts, Phase 3 prompts, Phase 4 prompts (one per feature, same pattern), Phase 5 prompts, Phase 6 prompts (+2 more)

### Community 171 - "ReadoutPanel"
Cohesion: 0.09
Nodes (23): QLabel, _CameraRow, _ChannelReadout, _DeltaRow, QGroupBox, QWidget, Cursor readout panel — per-channel values, camera frame numbers, Δ measurement., Show this camera's frame number and media time. Deliberately not called… (+15 more)

### Community 172 - "SyncWorker"
Cohesion: 0.22
Nodes (7): EvidenceSpec, ndarray, QObject, Slot, Build an evidence-based proposal without blocking the UI thread., Extract raw evidence and emit one deterministic fit proposal., SyncWorker

### Community 173 - "Video Extraction Toolbox — output schema for AvialSync"
Cohesion: 0.13
Nodes (14): 1. Where the files are, 2. File format, 3. HDF5 layout, 4. JSON sidecar, 5. Channel model, 6. Time base, 7. Session-level notes, 8. The per-ROI store (upstream of the export) (+6 more)

### Community 174 - "VideoStandardProbe"
Cohesion: 0.16
Nodes (11): BatchImportDialog, Path, QDialog, QWidget, Return what to call *path*: the session's own label, else its filename., Map semantic labels to actual loader classes., Presents dropped files to the user for type verification before loading., Read a fixture's frame count without duplicating the loader's ffprobe call. (+3 more)

### Community 175 - "_ArrayReader"
Cohesion: 0.22
Nodes (7): _ArrayReader, ndarray, Path, Performance guard for the 3D tracking cursor hot path., Minimal mmap-reader equivalent for isolating per-tick sampling cost., Sampling 128 XYZ points must leave room in the existing cursor budget., test_bench_tracking_3d_cursor()

### Community 176 - "._refresh_status"
Cohesion: 0.13
Nodes (8): Use complete XYZ channel triplets from the active cached readers., Say how many points are loaded, and where their bones came from. The provenance…, Reflect the canvas's current orientation without re-triggering it., Pin an explicit vertical axis chosen by the user., Pin which source axis renders upward (see :meth:`Tracking3DCanvas.set_up_axis`)., Set the connectivity the session declared; empty falls back to detection., Pin which skeleton the view draws (see :class:`BoneMode`)., Apply the skeleton mode the user chose in the header.

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

### Community 182 - ".materialize"
Cohesion: 0.33
Nodes (3): Close the staging handle; safe to call more than once., Close and delete the staging file without materialising it., Write staged samples to *target* as ``.npy`` and return its mmap. The copy runs…

### Community 183 - "fit_channel_y"
Cohesion: 0.11
Nodes (18): Fit the current bounded page once, then keep playback visually stable., Set one row's explicit Fit/Auto/Manual amplitude behaviour., Update the fixed channel gutter after import metadata is available., Update all known channel units without changing reader identity or data., fit_channel_y(), Fit a stable finite Y range from the currently loaded bounded page., Keep name, unit, and stable scale together in the fixed row gutter. Joined with…, _update_channel_gutter() (+10 more)

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

### Community 189 - "TimelineOverview"
Cohesion: 0.11
Nodes (14): QMouseEvent, QPaintEvent, Paint named, conditional timeline-evidence lanes without owning time state., Set the shared master-time range rendered by this overview., Return the distinct pixel columns of the events inside ``[t0, t1]``. Bounded by…, Return the event tuples behind one lane kind. A lookup rather than a…, Binary-search the nearest event of *kind*, or None outside tolerance., Return the currently populated lanes, in their rendered order. (+6 more)

### Community 190 - "_with_messages"
Cohesion: 0.25
Nodes (8): MessageSpec, The ``MessageCenter`` annotation stream — what the experimenter typed. Open…, Write the default recording plus a MessageCenter the experimenter typed., Reading the text must not resurrect the zero-filled trace it used to make., The notes belong to the recording, not to whichever stream was chosen. Gating…, test_message_center_is_still_not_a_plotted_channel(), test_messages_reach_a_signals_only_import(), _with_messages()

### Community 191 - "AnnotationStore"
Cohesion: 0.12
Nodes (12): AnnotationPanel, AnnotationStore, Path, QGroupBox, QObject, QWidget, Remove a marker by index., Write one row per (marker, video) — format for DLC/LightningPose retraining.… (+4 more)

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

### Community 201 - ".open"
Cohesion: 0.50
Nodes (3): Any, Path, Read headers and identify x/y/z channels.

### Community 202 - "SyncWizard"
Cohesion: 0.19
Nodes (7): QDialog, Slot, Return the proposal selected by the user after accepted execution., Return the target identifier associated with the accepted proposal., Provide an explicit fallback when evidence is sparse or ambiguous., Select evidence, inspect a fit, and explicitly accept a proposal., SyncWizard

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

### Community 207 - ".update_plots"
Cohesion: 0.13
Nodes (9): Path, Load multiple data sources from cache and build plot rows. Every row of one…, Re-align one time-series source against the master clock. The rows keep their…, Return the ``(offset, drift_ppm)`` currently applied to a source., Return one source's master-time coverage across all of its channels., Backwards compatibility for Phase 2 single-channel load., Refresh the current sweep from the decimation pyramid. ``sliced`` spreads the…, Requery one row and settle its once-only Y fit. (+1 more)

### Community 208 - "._apply_default_splitter_sizes"
Cohesion: 0.25
Nodes (4): QSplitter, Forbid collapsing a pane to nothing. Must be re-applied after ``restoreState``:…, Re-seed any splitter a previously-saved state left with a zero pane. A zero-…, Seed the first-run pane layout, as sizes now and as shares thereafter. Called…

### Community 209 - "DropScanWorker"
Cohesion: 0.19
Nodes (8): Return True if this source stores frame numbers instead of wall-clock time.…, DropScanWorker, Path, QObject, Slot, Lay out *path* with the session plugin that claims it, if any. Returns ``None``…, Scan dropped paths for importable sources off the UI thread., Collect paths and their best-guess loaders recursively, avoiding session files.

### Community 210 - "._on_ab_in"
Cohesion: 0.10
Nodes (12): QSlider, JumpSlider, QResizeEvent, Button click — set A/B out-point (button state managed here)., A QSlider that instantly jumps to the clicked position., Set the A/B loop in-point at the current slider position (public, D-022.1)., Set the A/B loop out-point at the current slider position (public, D-022.1)., Convert absolute time to a [0, 1] fraction within current bounds. (+4 more)

### Community 211 - "Path"
Cohesion: 0.19
Nodes (8): ModuleType, Path, Import one loose plugin module without adding its directory to ``sys.path``.…, Return the candidate scoring highest above zero on *path*. ``can_open`` is…, Return the loader with the highest can_open() score > 0., Return the session scanner claiming *path*, if any. Asked before per-file…, _T, test_a_broken_plugin_is_reported_not_silently_dropped()

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

### Community 217 - ".read_chunks"
Cohesion: 0.19
Nodes (7): ndarray, Convert HH:MM:SS:mmm to seconds since midnight., Yield bounded (time, value) chunks for the requested channel. Chunk boundaries…, Validate and de-duplicate one chunk, retaining its final sample. The retained…, Raise on backward time jumps (allowing duplicates for dedup)., Remove duplicate timestamps, keeping the last value., Return *raw_seconds* shifted onto the continuous master axis.

### Community 218 - ".add_pane"
Cohesion: 0.25
Nodes (5): Pass tracking data readers to all video panes for overlay rendering. Retained,…, Attach named 2D prediction tracks to the pane showing *path* only. 2D pose data…, Add a pane identified by original *path*, playing *media_path* if supplied., A dropped video must complete its real worker lifecycle without closing the app., test_drop_real_video_completes_async_open()

### Community 219 - "TestAOLSessionDetection"
Cohesion: 0.18
Nodes (5): is_aol_session(), Return True if the directory has AOL session signature files. An AOL session…, Root MP4s are the normal case., A session with only rendered videos must still open., TestAOLSessionDetection

### Community 220 - ".eventFilter"
Cohesion: 0.33
Nodes (4): QEvent, QObject, Repaint the lanes when the platform appearance changes. Lane colours are…, Reserve Space for playback while retaining ordinary Tab accessibility.

### Community 221 - "TestPluginDiscovery"
Cohesion: 0.24
Nodes (7): LogCaptureFixture, Path, A leading underscore marks a helper, not a plugin to import., A third-party plugin must never take the application down with it., Users are told to create ~/.avialsync/plugins; most never do., Silent failure made a broken plugin vanish with no way to tell why., TestPluginDiscovery

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

### Community 232 - "build_gap_mask"
Cohesion: 0.20
Nodes (8): build_gap_mask(), Return a boolean mask where True indicates a gap larger than 10x median dt.…, Verify subsampled gap_mask (stride 10k) detects correctly on clustered gaps…, test_pathological_gap_mask(), Repeated timestamps give a zero median interval, not a gap threshold. A stuck…, One sample yields no adjacent pair at all., Why dropped frames never appear as gap bars, and should not. A gap means "no…, test_single_frame_drops_are_far_below_the_gap_threshold()

### Community 233 - "PointColorRegistry"
Cohesion: 0.22
Nodes (6): PointColorRegistry, Hand out one stable colour per body-part name, decided at load time., Assign a colour to every name not seen before, in sorted order. Idempotent, so…, Return *name*'s colour, assigning one now if it was never registered. Painting…, Forget every assignment. For tests that need a known starting point., test_registry_rejects_an_empty_palette()

### Community 234 - "ndarray"
Cohesion: 0.22
Nodes (5): ndarray, Return ``(t_master, v, gap)`` for a bounded master-time range., Yield bounded ``(t_master, v)`` chunks., Decimated master-time query; the result is bounded by *max_points*., Return level-1 mmap views in **source** time. Kept unmapped on purpose:…

### Community 235 - "_PointArrays"
Cohesion: 0.22
Nodes (7): _PointArrays, ndarray, Protocol, The shape of one tracked point, as the 3D pane already holds it. Read-only…, Body-part name this point's channels were grouped under., Coordinate arrays, one per axis, in XYZ order., Per-axis masks marking samples the source never recorded.

### Community 236 - ".closeEvent"
Cohesion: 0.40
Nodes (3): QCloseEvent, Run one shutdown step; log and continue if it fails. Closing is the one path…, Always close. This used to ``event.ignore()`` while any background job was…

### Community 238 - "RuntimeError"
Cohesion: 0.22
Nodes (6): ndarray, Yield fixed-size, chronologically ordered chunks., RuntimeError, Detach Data Streams so the main workspace splitter can own its height., A raise used to abandon every later step, stranding libmpv event threads., test_a_failing_teardown_step_does_not_skip_the_rest()

### Community 239 - ".exact_time_mapping"
Cohesion: 0.22
Nodes (6): ndarray, Yield one-dimensional ``float64`` time/value chunks for *ch*. Chunks, including…, Per-frame timestamps if the container has them., Return per-frame ``(master_time, source_time)`` evidence, or ``None``. Additive…, The hook is additive: a frozen v1 video plugin must be unaffected by it., test_video_source_default_declares_no_exact_mapping()

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

### Community 247 - "ShortcutsDialog"
Cohesion: 0.33
Nodes (4): QDialog, Keyboard shortcuts reference dialog — derived from live QAction registry…, Modal dialog listing all keyboard shortcuts. Derives content entirely from live…, ShortcutsDialog

### Community 248 - "_resolved_marker_color"
Cohesion: 0.50
Nodes (3): Return the *index*-th marker colour against the application palette., Resolve this marker's colour against the current application palette., _resolved_marker_color()

### Community 253 - "default_skeleton"
Cohesion: 0.50
Nodes (4): default_skeleton(), _has_bodypart(), Bones between consecutive :data:`DEFAULT_SKELETON_CHAIN` parts that exist.…, Whether *name* is one of *bodyparts*, prefixed or not.

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

### Community 261 - "SkeletonEstimate"
Cohesion: 0.25
Nodes (5): Connectivity derived from pose geometry, with the flow it was rooted in.…, True when any connectivity was found., SkeletonEstimate, QWidget, The geometry-derived estimate for the loaded points.

### Community 286 - "build_manifest"
Cohesion: 0.11
Nodes (23): AOLMetricFile, AOLVideoExtraction, _append_config_entry(), build_manifest(), _camera_label_from_labeled(), _collect_2d_tracks(), _collect_extracted_metrics(), _eks_bodyparts() (+15 more)

### Community 288 - "current_preference"
Cohesion: 0.40
Nodes (4): current_preference(), is_dark(), Return the persisted preference, normalized for legacy settings., Return whether the currently resolved application appearance is dark.

### Community 292 - "2026-08 · D-082 · A skeleton is detected from geometry when the data declares none"
Cohesion: 0.40
Nodes (5): 2026-08 · D-082 · A skeleton is detected from geometry when the data declares none, Alternatives rejected, Consequences, Context, Decision

### Community 298 - "AOL2DTrack"
Cohesion: 0.50
Nodes (3): AOL2DTrack, The fused 2D pose prediction bound to the camera it was tracked on. Exactly one…, Whether this is the fused ensemble result rather than a single model.

## Knowledge Gaps
- **455 isolated node(s):** `2026-07 · D-051 · MainWindow may not be split into Qt-slot mixins`, `2026-07 · D-045 · Bounded reads, source TimeMaps, and scoped channel identity`, `2026-07 · D-046 · Session IO and annotation export never run on the UI thread`, `2026-07 · D-047 · Presentation is rate-limited; authoritative time is not`, `2026-07 · D-048 · Video probes run bounded-parallel; native panes stay serialized` (+450 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **26 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MainWindow` connect `MainWindow` to `generate_demo_screenshots.py`, `Transport`, `export_controller.py`, `ImportReportDialog`, `.resizeEvent`, `VideoGrid`, `Message`, `test_pane_proportions.py`, `TimeSeriesSource`, `JobManager`, `diagnostics.py`, `DemoLaunch`, `PyAVReader`, `VideoStandardLoader`, `set_font_family`, `VideoOpenWorker`, `test_cli_demo.py`, `test_interaction_standard.py`, `generate_guide_screenshots.py`, `PyramidBuilder`, `current_preference`, `SessionState`, `test_close_and_focus.py`, `MasterClock`, `TimeMap`, `.eventFilter`, `test_session_worker.py`, `ReadoutPanel`, `MonkeyPatch`, `sync.py`, `test_worker_lifetime.py`, `PlotPane`, `format_time`, `CacheManager`, `Path`, `_QuickWorker`, `test_workload_responsiveness.py`, `_JobWorker`, `import_controller.py`, `AnnotationStore`, `SourceInspection`, `session_controller.py`, `test_ui_sensor_mapping.py`, `Player`, `ReaderReference`, `capture`, `SyncWizard`, `main_window.py`, `ChannelKey`, `._apply_default_splitter_sizes`, `UiHeartbeat`, `test_ui_shortcut_reach.py`, `.add_pane`, `test_ui_layout_resize.py`, `LoaderRegistry`, `Tracking3DPane`, `test_aol_pose_routing.py`, `test_never_freeze.py`, `video_standard.py`, `test_frame_indexed.py`, `.closeEvent`, `._on_sensor_mapping_changed`, `_FakePane`, `test_sync_golden.py`, `load_video`, `SnapshotWorker`, `ShortcutsDialog`, `._accept_sync_proposal`, `ProxyWorker`, `.__init__`, `_press`?**
  _High betweenness centrality (0.235) - this node is a cross-community bridge._
- **Why does `LoaderRegistry` connect `LoaderRegistry` to `MainWindow`, `test_loaders_open_ephys.py`, `AOLEksLoader`, `PyramidReader`, `test_aol_video_extraction_routing.py`, `_MappingLoader`, `TimeSeriesSource`, `test_aol_loaders.py`, `test_aol_metric_routing.py`, `VideoOpenWorker`, `PyramidBuilder`, `VideoStandardProbe`, `test_loaders_neo.py`, `_JobWorker`, `test_core_coverage_edges.py`, `DummyVideoLoader`, `main_window.py`, `test_plugin_discovery.py`, `DropScanWorker`, `Path`, `AOLEncoderLoader`, `TestAOLSessionDetection`, `TestPluginDiscovery`, `test_aol_pose_routing.py`, `test_frame_indexed.py`, `.__init__`?**
  _High betweenness centrality (0.058) - this node is a cross-community bridge._
- **Why does `TimeSeriesSource` connect `TimeSeriesSource` to `MainWindow`, `CSVLoader`, `AOLEksLoader`, `ChannelInfo`, `Message`, `AOLMetricLoader`, `NeoLoader`, `VideoStandardProbe`, `Path`, `MissingColumnError`, `AOLVideoExtractionLoader`, `_JobWorker`, `import_controller.py`, `DummyVideoLoader`, `main_window.py`, `DropScanWorker`, `Path`, `AOLEncoderLoader`, `LoaderRegistry`, `SourceOpenError`, `video_standard.py`, `.exact_time_mapping`, `ToyBinarySource`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Are the 54 inferred relationships involving `MainWindow` (e.g. with `CacheManager` and `ChannelKey`) actually correct?**
  _`MainWindow` has 54 INFERRED edges - model-reasoned connections that need verification._
- **Are the 19 inferred relationships involving `PlotPane` (e.g. with `Player` and `_JobWorker`) actually correct?**
  _`PlotPane` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 40 inferred relationships involving `TimeMap` (e.g. with `ChannelKey` and `MappedChannelReader`) actually correct?**
  _`TimeMap` has 40 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `PyramidReader` (e.g. with `ChannelKey` and `MappedChannelReader`) actually correct?**
  _`PyramidReader` has 27 INFERRED edges - model-reasoned connections that need verification._