# Graph Report - avialview  (2026-08-25)

## Corpus Check
- 263 files · ~416,616 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 6177 nodes · 11616 edges · 290 communities (266 shown, 24 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 1010 edges (avg confidence: 0.59)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3e2c0d07`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- MainWindow
- test_loaders_open_ephys.py
- .read_chunks
- .can_open
- AOLEncoderLoader
- VideoPane
- .resolved_mapping
- PyramidReader
- open_ephys_format.py
- DECISIONS.md — lightweight ADR log
- aol_session_loader.py
- sync.py
- test_hot_path.py
- test_core_coverage_edges.py
- test_playback_smoothness.py
- test_pane_proportions.py
- TimeSeriesSource
- infer_skeleton
- Known Traps
- plot_pane.py
- AOLMetricLoader
- export_controller.py
- Path
- NeoLoader
- VideoStandardLoader
- ImportWorker
- test_cli_demo.py
- test_interaction_standard.py
- MappedChannelReader
- generate_guide_screenshots.py
- SweepWindowControl
- SensorInfoWidget
- Message
- AnnotationStore
- LoaderRegistry
- test_video_pane.py
- AvialSync — Project Blueprint (v1)
- MasterClock
- test_aol_chunk_boundaries.py
- test_frame_identity.py
- test_session_worker.py
- test_pyav_reader.py
- test_scrubbing.py
- test_loaders_open_ephys_legacy.py
- ._build_channel_by_channel
- test_subprocess_no_window.py
- SyncWizard
- test_worker_lifetime.py
- PlotPane
- format_time
- VideoGrid
- Path
- TimelineOverview
- PyAVReader
- PyramidBuilder
- test_theme_colors.py
- AOLVideoExtractionLoader
- CSVLoader
- IntegrityFlags
- main_window.py
- test_workload_responsiveness.py
- pyramid.py
- SyncProvenance
- test_ci_platform_config.py
- test_seek_backends.py
- write_recording
- DummyVideoLoader
- SourceInspection
- test_ui_plot_row_geometry.py
- test_typed_source_errors.py
- test_ui_sensor_mapping.py
- Player
- PaintCanvas
- capture
- session_controller.py
- PlotInteractionController
- VideoSurface
- export.py
- color_for_point
- _with_messages
- demo.py
- prepare_release.py
- Tracking3DCanvas
- test_ui_follow.py
- VideoMetadata
- test_engine_importer.py
- test_theme_tooltips.py
- test_player_clock.py
- test_ui_shortcut_reach.py
- Transport
- AOLEksLoader
- make_fixtures.py
- test_ui_layout_resize.py
- .__init__
- import_controller.py
- TestShowDelta
- ImportWizard
- _pulses
- PlotHeader
- Tracking3DPane
- SourceOpenError
- build_manifest
- test_never_freeze.py
- test_ui_dialogs.py
- tracking_3d_pane.py
- test_aol_loaders.py
- .paintEvent
- test_frame_indexed.py
- write_video
- encode_proxy
- test_packaging_smoke.py
- _FakePane
- test_sync_golden.py
- test_ui_main.py
- test_core_sync.py
- VideoPropertiesPanel
- AvialSync Plot UX Refinement Plan
- test_bench_cursor_path
- session.py
- UiHeartbeat
- TESTING.md
- TestTtlExtraction
- ARCHITECTURE.md
- ToyBinarySource
- skeleton.py
- QTableWidgetItem
- test_diagnostics.py
- test_close_and_focus.py
- ChannelInfo
- TimelineEvidence
- test_bench_plot_pane.py
- test_demo_data.py
- test_transport_resize.py
- neo_loader.py
- job_manager.py
- Path
- AOLSessionSource
- ._relayout
- aol_metric_loader.py
- ._collect_drop_candidates
- Contributor Covenant Code of Conduct
- 2026-07 · D-020 · Inspection layer — what is surfaced where
- Data handling
- test_engine_layering.py
- diagnostics.py
- JobManager
- ._apply_default_splitter_sizes
- generate_demo_screenshots.py
- test_conda_recipe.py
- TestMeasureMarkers
- test_aol_metric_routing.py
- theme.py
- ProxyWorker
- VideoOpenWorker
- TimeMap
- test_video_grid.py
- generate_icons.py
- test_job_thread_lifetime.py
- Desktop installers
- Tutorial: import sensor and recording data
- AvialSync — Model Handout
- MIGRATION_PYAV.md — libmpv → PyAV, and a pip-only install
- capture
- ._refresh_status
- Job
- .eventFilter
- _PointArrays
- SeekGroup
- ShortcutsDialog
- test_headless_core.py
- PROMPTS.md — kickoff prompts per phase
- test_a_rig_plugin_is_named_system_then_kind
- plot_interactions.py
- Video Extraction Toolbox — output schema for AvialSync
- TestAOLSessionDetection
- _ArrayReader
- test_every_timing_module_samples_perf_counter
- test_prepare_release.py
- Data Output Schema — for AvialSync integration
- no_startup_diagnostics
- 2026-07 · D-022 · Interaction standard — visible surface, depth in menus, shortcuts as accelerators
- 2. Evidence-based alignment from TTL or frame triggers
- .add_pane
- SessionState
- _QuickWorker
- open_ephys_session.py
- Plugin guide
- Troubleshooting
- Phase Status
- _PaletteStyleFollower
- MissingColumnError
- .open
- ._refresh
- quickstart.md
- Quickstart
- Development and release
- User Guide
- Sessions, proxies, and the 3D view
- Performance Budgets (engineering-certified where ★)
- RuntimeError
- AvialSync
- fit_exact_index_mapping
- ImportReportDialog
- Architecture
- Tutorial: inspect a first session
- release
- Signal Wiring Map
- ._event_detail
- test_ui_plot_sliced_refresh.py
- .load
- test_transport_layout.py
- QSettings
- 2026-08 · D-081 · The video-extraction export is the ROI-metric surface, and it is HDF5
- Formats
- Licensing
- Tutorial: flag frames and export
- build_bundle
- 2026-08 · D-084 · A seek is answered by its own frame, not by any frame
- DemoLaunch
- test_annotation_frames.py
- .eventFilter
- .resizeEvent
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
- CacheManager
- .set_time
- DemoWindow
- .exact_time_mapping
- .closeEvent
- .coverage_group_for
- SessionLoadWorker
- TestPyramidLevelHelpers
- 2026-07 · D-033 · Packaging inputs are explicit and CI artifact builds are a separate gate
- 2026-07 · D-034 · Themes are palette/font appearance, never interaction redesign
- 2026-07 · D-036 · PR and tag quality use one cross-platform test contract
- 2026-07 · D-038 · Windows video panes use libmpv's Qt OpenGL render API — SUPERSEDED by D-075
- 2026-07 · D-039 · Release bundles own the complete media runtime — AMENDED by D-075
- 2026-07 · D-040 · Sidecar writes use bounded concurrency and failures remain observable
- 2026-07 · D-042 · Plots use one fixed, shared oscilloscope sweep
- test_a_type_names_the_data_never_the_rig
- _stalls_seen
- ._generate_proxy
- recording
- .set_viewport
- test_three_camera_four_stream_session_can_be_cached_and_queried
- .close
- ._recording_messages
- test_packaging_metadata.py
- test_worker_thread_teardown.py
- 2026-07 · D-023 · Benchmarks CI-gated; budget-assertion pattern; CI multiplier
- 2026-07 · D-029 · Separate GitHub workload correctness from local speed certification
- 2026-07 · D-030 · Test-level watchdog for cross-platform Qt verification
- 2026-07 · D-031 · Libmpv commands stay on the Qt-owning thread — SUPERSEDED by D-075
- ._on_pane_double_clicked
- .visible_panes
- .frame_records_at
- .set_sync_mapping
- conf.py
- commit-msg
- post-commit
- pre-commit
- make_appimage.sh
- make_dmg.sh
- avialsync
- test_anchor_epoch_is_zero_without_an_absolute_instant
- ModuleType
- Path
- DemoProgressDialog
- QLabel
- Protocol
- 2026-08 · D-082 · A skeleton is detected from geometry when the data declares none
- read_frame_timestamps
- _demo_frame
- 2026-08 · D-083 · Video-derived data is timed from the camera start, and shares one lane

## God Nodes (most connected - your core abstractions)
1. `MainWindow` - 377 edges
2. `PlotPane` - 116 edges
3. `TimeMap` - 111 edges
4. `PyramidReader` - 105 edges
5. `LoaderRegistry` - 92 edges
6. `DECISIONS.md — lightweight ADR log` - 90 edges
7. `SourceOpenError` - 73 edges
8. `Transport` - 71 edges
9. `PyramidBuilder` - 70 edges
10. `VideoStandardLoader` - 69 edges

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

## Communities (290 total, 24 thin omitted)

### Community 0 - "MainWindow"
Cohesion: 0.02
Nodes (35): QMainWindow, drag_enter(), on_drop_scan_error(), QDragEnterEvent, build_next_video_pane(), on_video_opened(), on_video_pane_ready(), on_video_thread_finished() (+27 more)

### Community 1 - "test_loaders_open_ephys.py"
Cohesion: 0.05
Nodes (69): _drop(), _layout(), datetime, Path, Tests for the Open Ephys session plugin and the neo ingest path behind it.…, The rig's timezone is derivable in-band, so nothing has to assume one., A near-miss is a coincidence; accepting it would shift every camera by an hour., A sidecar cache is named after its source path, so shared paths overwrite. Two… (+61 more)

### Community 2 - ".read_chunks"
Cohesion: 0.19
Nodes (7): ndarray, Convert HH:MM:SS:mmm to seconds since midnight., Yield bounded (time, value) chunks for the requested channel. Chunk boundaries…, Validate and de-duplicate one chunk, retaining its final sample. The retained…, Raise on backward time jumps (allowing duplicates for dedup)., Remove duplicate timestamps, keeping the last value., Return *raw_seconds* shifted onto the continuous master axis.

### Community 3 - ".can_open"
Cohesion: 0.12
Nodes (22): Return 1.0 for whitelisted ephys formats; 0.0 for everything else. Directories…, Path, Tests for the NeoLoader ephys data plugin., NeoLoader must never claim .csv files., NeoLoader must return 0.0 for plain text files., NeoLoader must return 0.0 for files with a non-whitelisted extension., Directory containing structure.oebin is recognised as OpenEphys dataset., Directory with no ephys signatures should score 0.0. (+14 more)

### Community 4 - "AOLEncoderLoader"
Cohesion: 0.08
Nodes (18): AOLEncoderLoader, Any, Path, Return a single velocity channel. ``rate_hz`` stays ``None``: the logger writes…, Loads AOL encoder logs in bounded chunks. Format: space-separated, no header, 4…, Return high confidence for files matching the encoder log pattern., Validate the file and store config., MonkeyPatch (+10 more)

### Community 5 - "VideoPane"
Cohesion: 0.04
Nodes (30): ndarray, QCloseEvent, setter, Slot, Record the newest wanted time and its id. Safe to call from the UI thread., Decode the newest requested time, if one is still outstanding., Close the reader on its own thread, where it was opened., Show a decoded ``(H, W, 3)`` uint8 RGB frame. (+22 more)

### Community 7 - "PyramidReader"
Cohesion: 0.06
Nodes (41): The underlying source-time reader., PyramidReader, Reads pyramid queries dynamically from mmapped arrays., channel(), fixture, Edge behaviour of the pyramid reader and the loader registry. Both sit on paths…, A one-second channel sampled at 100 Hz, with a gap in the middle., `value_at` answers for any time; outside coverage the answer is NaN. (+33 more)

### Community 8 - "open_ephys_format.py"
Cohesion: 0.09
Nodes (38): Raise if *path* is a recording neo will fail to parse, naming why. Only Open…, _reject_unreadable_recording(), _declared_entries(), _decode(), _event_seconds(), event_stream_defects(), EventStreamDefect, find_record_dir() (+30 more)

### Community 9 - "DECISIONS.md — lightweight ADR log"
Cohesion: 0.03
Nodes (66): 2026-07 · D-001 · Master time = float64 seconds, UTC epoch, 2026-07 · D-002 · Video playback = libmpv only — SUPERSEDED by D-075, 2026-07 · D-003 · License Apache-2.0; no GPL deps — SUPERSEDED by D-069, 2026-07 · D-004 · Sidecar cache format, 2026-07 · D-005 · Chunked ingest is the only ingest path, 2026-07 · D-006 · VideoSource conversion hook is first-class, 2026-07 · D-007 · Frame stepping uses actual frame timestamps, 2026-07 · D-008 · Cache key gets content-hash tail (+58 more)

### Community 10 - "aol_session_loader.py"
Cohesion: 0.07
Nodes (58): One file a session contributes, with the loader and config it needs. ``loader``…, What a recording folder contains, plus the settings that span it. Session-wide…, SessionItem, SessionLayout, _add_root_videos(), _anchor_epoch(), AOL2DTrack, AOLManifest (+50 more)

### Community 11 - "sync.py"
Cohesion: 0.07
Nodes (41): Edge, Raised when synchronization evidence is malformed or insufficient., Raised when event evidence supports multiple equally valid alignments., SyncAmbiguityError, SyncEvidenceError, _candidate_indices(), _default_tolerance(), _evidence_indices() (+33 more)

### Community 12 - "test_hot_path.py"
Cohesion: 0.08
Nodes (22): overview(), fixture, QApplication, The 60 Hz tick keeps authoritative time but does not repaint everything. P3.5…, 100 000 events inside the window must collapse to at most one per column., A new lane must inherit the sorted index, not scan its events per frame. This…, A Player whose observers are all mocks, so calls can be counted., Authoritative time must not be throttled — only presentation is. (+14 more)

### Community 13 - "test_core_coverage_edges.py"
Cohesion: 0.10
Nodes (29): channel(), _provenance(), fixture, Path, Edge paths in ``core/`` that no other test reached (P6.1, TESTING §1). TESTING…, Recovery is best-effort; failing to restore must not raise on a read path., Unequal arrays would silently mis-map frames on reload., A large mapping lives in a sidecar; a corrupt one must not load silently. (+21 more)

### Community 14 - "test_playback_smoothness.py"
Cohesion: 0.06
Nodes (48): SimpleNamespace, DecodingPane, _osd_pane(), _OsdPane, QApplication, Playback must not generate work proportional to the decoded frame rate. Each…, Drive the real tick for *seconds* of simulated playback. Returns ``(master_t,…, The new playback model, stated as an assertion. Under libmpv the player watched… (+40 more)

### Community 15 - "test_pane_proportions.py"
Cohesion: 0.06
Nodes (48): distribute(), _pane_minimums(), PaneProportions, QObject, QSplitter, Hold each pane's share of the workspace steady while the window is resized.…, Manage *splitters*, adopting each one's ratio the first time it lays out., Adopt *splitter*'s current pane ratio as the one to hold. A visible pane… (+40 more)

### Community 16 - "TimeSeriesSource"
Cohesion: 0.04
Nodes (68): ABC, Plugin registry and discovery., default_display_name(), _Nameable, Source plugin abstract base classes., Return the human-readable name for this format., Return extra labels this loader should also be offered under. For a general-…, Optional plugin contract for a whole recording folder. Additive to API v1 and… (+60 more)

### Community 17 - "infer_skeleton"
Cohesion: 0.10
Nodes (35): frame_budget(), infer_skeleton(), Derive skeleton connectivity from how rigidly point pairs hold together. Args:…, Frames to sample for *point_count* points, bounded by the pairwise budget., Detecting bones on load must stay inside the UI-callback ceiling (D-082).…, test_bench_skeleton_detection(), _articulated_chain(), ndarray (+27 more)

### Community 18 - "Known Traps"
Cohesion: 0.04
Nodes (55): 0. Scheduled work that outlives its owner crashes rather than fails (D-062, D-064), 0a. A `QObject` moved to a `QThread` needs an owning Python reference, 0b. Building a widget list can free the widgets in it (D-065), 0b. Do NOT add the anchor date to AOL encoder timestamps (D-045), 0c. AOL pose data must not become plot rows (D-046), 0c-bis. Overlay data reaches the grid before most panes exist (D-077), 0d. `"_eks.csv".split("_")[0]` is `""` — and `"" in name` matches everything, 0e. A container's declared frame rate is a claim, not evidence (D-072) (+47 more)

### Community 19 - "plot_pane.py"
Cohesion: 0.06
Nodes (46): GraphicsLayoutWidget, Compact shared controls for the time-series plot stack., Plot rendering pane using pyqtgraph and decimation pyramids., Load pyramid data for *channels* only, if a page is established., Resolve a channel reference to the rows it identifies. A :class:`ChannelKey`…, Refresh the current sweep from the decimation pyramid. ``sliced`` spreads the…, Requery one row and settle its once-only Y fit., Requery queued rows for one time slice, then yield to the event loop. The… (+38 more)

### Community 20 - "AOLMetricLoader"
Cohesion: 0.10
Nodes (21): AOLMetricLoader, Extracted Metric (Optical Flow / MI). Format: single-variable `-v6` MAT file,…, Rows are frames with no stored time axis, same contract as EKS., Match the `<roi_id>__<metric>.mat` filename, then confirm the variable. The…, fixture, MonkeyPatch, ndarray, Path (+13 more)

### Community 21 - "export_controller.py"
Cohesion: 0.04
Nodes (58): QPixmap, QWidget, Grab a widget's current visual content as a QPixmap., snapshot_widget(), DataExportWorker, Path, QImage, QObject (+50 more)

### Community 22 - "Path"
Cohesion: 0.14
Nodes (9): _holds_video_stream(), Any, ndarray, Path, Return whether *path* opens as a container carrying real video. Header read…, Read container and stream metadata with PyAV. This used to shell out to…, Adopt per-frame exposure times the acquisition system recorded, if given. A…, Return per-frame ``(master_time, source_time)`` evidence, if recorded. (+1 more)

### Community 23 - "NeoLoader"
Cohesion: 0.07
Nodes (30): _fit_length(), _is_numeric_label(), NeoLoader, Any, Exception, ndarray, Path, Return *name* reduced to characters legal in a cache filename everywhere. (+22 more)

### Community 24 - "VideoStandardLoader"
Cohesion: 0.06
Nodes (42): Loads standard videos, probing metadata and frame timing with PyAV., Score this file as standard video. Two gates, deliberately in this order. A…, Return whether decoded frame timestamps have variable intervals., Return the span the frames actually cover, in master-time seconds., Return ``(is_vfr, measured, min, max)`` from whichever timing is authoritative., Return timestamp-authoritative stream metadata for inspection and OSD. When the…, VideoStandardLoader, test_a_video_without_a_sidecar_reports_no_drops() (+34 more)

### Community 25 - "ImportWorker"
Cohesion: 0.09
Nodes (40): ChannelStage, Append-only on-disk staging buffer for one float64 channel. An import worker…, Number of samples appended so far., ImportWorker, QObject, Background worker for parsing and building pyramids from time-series sources., _BulkLoader, _LegacyLoader (+32 more)

### Community 26 - "test_cli_demo.py"
Cohesion: 0.06
Nodes (46): AvialSync root module., _parse_args(), Namespace, Parse the supported AvialSync command-line arguments., Path, Tests for the installed ``avialsync demo`` command., The previous two-channel cache cannot silently downgrade the restored demo., The release smoke gate waits for this count, so it must be reachable. It was… (+38 more)

### Community 27 - "test_interaction_standard.py"
Cohesion: 0.06
Nodes (40): _all_shortcuts(), main_window(), fixture, parametrize, QApplication, D-022 interaction standard tests. Verifies: - New transport buttons emit the…, The reset-zoom action in the plot context menu must be the same object as the…, Collect the NativeText of every shortcut registered on the window. (+32 more)

### Community 28 - "MappedChannelReader"
Cohesion: 0.06
Nodes (33): MappedChannelReader, ndarray, Path, Replace the offset/drift mapping in place. Existing plot rows and readout rows…, Return this channel's master-time extent, or None when empty., Return ``(t_master, v, gap)`` for a bounded master-time range., Yield bounded ``(t_master, v)`` chunks., Decimated master-time query; the result is bounded by *max_points*. (+25 more)

### Community 29 - "generate_guide_screenshots.py"
Cohesion: 0.20
Nodes (16): _capture_all(), generate(), _load_session(), Path, QApplication, Capture the annotated screenshots used by the user guide and tutorials. Every…, Return the sidebar's per-video widget, whatever its concrete class., Open the sample video and signal through the ordinary code paths. (+8 more)

### Community 30 - "SweepWindowControl"
Cohesion: 0.08
Nodes (17): QWidget, Return the shared sweep duration in seconds., Return the absolute master time at the current sweep's left edge., Return the latest master-clock value supplied by the player., Set master bounds and anchor all future sweeps to their start., Set and emit a duration clamped to the current master bounds., Expand the sweep to the complete master timeline., Move the continuous slider one small step inward. (+9 more)

### Community 31 - "SensorInfoWidget"
Cohesion: 0.07
Nodes (22): QTreeWidgetItem, Set a channel checkbox and return whether this source owns it., Show a restored mapping without re-emitting it back to the caller., Return the displayed ``(offset_s, drift_ppm)``., Return the layout's direct child widgets of *kind*, skipping empty slots.…, Add a sensor info widget to the sidebar., Mirror plot-row visibility to the owning channel checkbox. *source_id*…, Remove a sensor info widget. (+14 more)

### Community 32 - "Message"
Cohesion: 0.07
Nodes (48): QTableWidget, bounded(), Message, Any, One free-text record read from a source file. ``time`` is in the *source's* own…, Return *messages* sorted with untimed records first, capped at the limit.…, Return free-text records this file stores, or an empty list. Additive default,…, Return the loader's free-text records, bounded, never fatally. A format's prose… (+40 more)

### Community 33 - "AnnotationStore"
Cohesion: 0.07
Nodes (28): AnnotationPanel, AnnotationStore, Marker, Path, QGroupBox, QObject, QWidget, Add a range marker from *t_start* to *t_end*. (+20 more)

### Community 34 - "LoaderRegistry"
Cohesion: 0.04
Nodes (59): ModuleType, Path, Protocol, SessionSource, _Capability, LoaderRegistry, Add each built-in class in *specs*, reporting any that will not import. A…, Add every class published under *group*, skipping ones that fail. Deduplicates… (+51 more)

### Community 35 - "test_video_pane.py"
Cohesion: 0.08
Nodes (39): clip(), _opened_pane(), fixture, Path, QApplication, TempPathFactory, Video-pane construction, decoding, and teardown tests. Everything here used to…, End-to-end, through the real thread: the pixels must name the frame. (+31 more)

### Community 36 - "AvialSync — Project Blueprint (v1)"
Cohesion: 0.05
Nodes (36): AGENTS.md — AvialSync agent instructions (canonical), Architecture rules (violations = rejected PR), Coding standards, Definition of Done (every task), How to run things, Known traps (learned the hard way — do not rediscover), Naming & casing — BINDING (never invent variants), Task protocol for agents (+28 more)

### Community 37 - "MasterClock"
Cohesion: 0.07
Nodes (26): given, MasterClock, PlaybackState, Snapshot of current playback state., Single master clock for AvialSync. Time is driven externally via…, Register a callback that is fired on seek or playback advance., Set the absolute limits of the master timeline., Set playback rate, clamped between 0.01 and 10.0. (+18 more)

### Community 38 - "test_aol_chunk_boundaries.py"
Cohesion: 0.16
Nodes (23): _collect(), fixture, ndarray, Path, AOL loaders honour the frozen ingest contract across batch boundaries (V-15,…, A 15-channel file must not read 45 columns to answer for one., Projection is an optimisation; it must not change a single sample., Shrink the batch size so a boundary is reachable in a small fixture. (+15 more)

### Community 39 - "test_frame_identity.py"
Cohesion: 0.13
Nodes (25): FixtureRequest, Convert a decoded frame to a contiguous ``(H, W, 3)`` uint8 RGB array. Costs…, to_rgb_array(), cfr_video(), _probe_times(), fixture, ndarray, parametrize (+17 more)

### Community 40 - "test_session_worker.py"
Cohesion: 0.17
Nodes (24): AnnotationExportWorker, Export annotation markers to CSV off the UI thread., Serialize and write .avv + sidecars off the UI thread., SessionSaveWorker, Path, Session persistence and annotation export run off the UI thread. Architecture…, The worker deep-copies at construction, so later edits cannot leak in., A one-million-pair mapping must not stall the Qt event loop. The heartbeat… (+16 more)

### Community 41 - "test_pyav_reader.py"
Cohesion: 0.09
Nodes (29): long_gop_video(), fixture, MonkeyPatch, Path, TempPathFactory, Unit tests for the PyAV exact-frame reader. Frame *identity* is proven in…, The cache is a window on where the user just was, bounded by frames., Two float probes in one interval must be one entry, never two. (+21 more)

### Community 42 - "test_scrubbing.py"
Cohesion: 0.05
Nodes (36): player_with_mocks(), fixture, Tests for live scrubbing coalescing behaviour in Player., Return a Player wired to mock collaborators (no Qt event loop needed)., _on_tick dispatches the pending scrub target once seeker settles., _on_tick does NOT flush while seeker is still busy., A stalled decoder may drop frames but cannot stop plots or 3D., Exact seek on release clears any pending coalesced target. (+28 more)

### Community 43 - "test_loaders_open_ephys_legacy.py"
Cohesion: 0.11
Nodes (29): Path, Tests for the Open Ephys original-format message reader (D-085). neo reads…, Still something somebody wrote; the file just did not time it., Losing a comment must never fail an import (D-078)., neo's ``_segment_t_start`` is ``timestamp0 / rate``, with no subtraction.…, The plot/prose test must agree with itself on every numeric spelling.…, ``messages()`` must pick the reader by what the folder actually is. Driven…, ``None`` from the format readers means "use neo's event labels". (+21 more)

### Community 44 - "._build_channel_by_channel"
Cohesion: 0.14
Nodes (15): count_nan(), Count NaNs in a possibly mmap-backed array without a full-size temporary., _gap_locations(), Any, ndarray, Path, Build aligned channels from one loader pass, retaining shared timestamps once.…, Materialise staged samples into the sidecar; scopes every mmap locally. (+7 more)

### Community 45 - "test_subprocess_no_window.py"
Cohesion: 0.12
Nodes (21): Call, no_window_kwargs(), NoWindowKwargs, Process-level runtime helpers. This module used to locate a media runtime —…, Subprocess keyword arguments that suppress a console window. A ``TypedDict``…, Return subprocess kwargs that keep a child process from opening a console. A…, _is_platform_guarded(), Path (+13 more)

### Community 46 - "SyncWizard"
Cohesion: 0.07
Nodes (28): EventEvidenceSpec, EvidenceSpec, ndarray, QObject, Slot, Background TTL/event evidence extraction and alignment fitting., A cached signal channel from which TTL transitions are extracted., Native timestamp evidence, such as camera-frame trigger timestamps. (+20 more)

### Community 47 - "test_worker_lifetime.py"
Cohesion: 0.07
Nodes (28): Behaviour extracted from :class:`~avialsync.ui.main_window.MainWindow`. Each…, _FakeFileDialog, main_window(), fixture, MonkeyPatch, Path, QApplication, QDropEvent (+20 more)

### Community 48 - "PlotPane"
Cohesion: 0.02
Nodes (57): PlotPane, InfiniteLine, Path, QAction, QResizeEvent, Coalesce resize storms before selecting a new pyramid resolution., Load multiple data sources from cache and build plot rows. Every row of one…, Build queued rows in time slices, letting the event loop run between them. A… (+49 more)

### Community 49 - "format_time"
Cohesion: 0.10
Nodes (15): MappedMessage, Recorded messages: the store that maps them, and the panel that lists them. A…, One message placed on the master clock, with the file it came from., _fmt_relative(), format_time(), Enum, Time display mode enum and single formatting authority (D-020). All time-…, Format *t_seconds* according to *mode*. t_epoch is the Unix epoch of master-… (+7 more)

### Community 50 - "VideoGrid"
Cohesion: 0.18
Nodes (7): QWidget, Manages N VideoPanes in either a horizontal strip or an NxN grid. Uses a single…, Stop every pane's decoder before their Qt parent is destroyed. Each pane is…, Update the time offset for a specific video., Defer relayout until end_batch_add(). Use for multi-file drops., Return a copy of the loaded video paths, parallel to self.panes., VideoGrid

### Community 51 - "Path"
Cohesion: 0.06
Nodes (11): Any, ndarray, Path, QImage, Open a session file or a folder of recordings. Routes through the same scan a…, Show a per-pane context menu on video right-click (D-022)., Apply an explicitly accepted proposal and retain reproducible provenance., Forward to ReadoutPanel with accumulated units for known channels. (+3 more)

### Community 52 - "TimelineOverview"
Cohesion: 0.07
Nodes (27): _AnnotationLane, _CoverageLane, _EventLane, _normalise_events(), ndarray, QPaintEvent, Return the sorted time column of *events* for binary search., Paint named, conditional timeline-evidence lanes without owning time state. (+19 more)

### Community 53 - "PyAVReader"
Cohesion: 0.07
Nodes (20): ndarray, Path, VideoStream, PyAVReader, Demux one pass to collect presentation timestamps and keyframes. Demux only —…, Presentation timestamps in source seconds, display order., Number of frames the container actually carries timestamps for., The decoded video stream, for callers building format metadata. (+12 more)

### Community 54 - "PyramidBuilder"
Cohesion: 0.10
Nodes (26): PyramidBuilder, Builds and serializes a multi-level pyramid to disk., MonkeyPatch, Path, A valid short raw gap cannot disappear merely because the view is coarse., A background sidecar failure must fail the import, never look successful., A transient macOS EINTR takes the robust fallback without hiding data., A plot must get roughly one column per pixel, not one per fifteen. Stored… (+18 more)

### Community 55 - "test_theme_colors.py"
Cohesion: 0.12
Nodes (29): _contrast(), _distance(), _palette(), parametrize, QColor, QPalette, Derived colours: legible on both surfaces, distinct, and following the accent.…, Derived means derived — change the accent and the lane moves with it. (+21 more)

### Community 56 - "AOLVideoExtractionLoader"
Cohesion: 0.06
Nodes (39): AOLVideoExtractionLoader, Extracted ROI Metrics (Video Extraction). One file is one camera. Each ``(ROI,…, False: this export carries its own time axis. The per-ROI v6 store has no time…, The camera this file belongs to, as the sidecar names it., Whether the loaded axis is absolute POSIX rather than recording-relative., Nominal frame rate the toolbox recorded, or ``0.0`` when absent., Claim a MAT file whose sidecar names this toolbox. Reads only the small JSON…, export() (+31 more)

### Community 57 - "CSVLoader"
Cohesion: 0.07
Nodes (35): DataType, Series, CSVLoader, Any, ndarray, Path, Return the sampling rate when the sample proves it is regular.…, Map wizard format strings to internal categories. (+27 more)

### Community 58 - "IntegrityFlags"
Cohesion: 0.12
Nodes (11): ImportReport, IntegrityFlags, Any, Statistics collected by ImportWorker during one source import., Anomaly flags for one loaded source. Video flags (is_vfr, fps_mismatch) are set…, Unit tests for core.inspection dataclasses (ImportReport, IntegrityFlags,…, from_dict must tolerate a dict with only some keys (e.g. older data)., TestImportReport (+3 more)

### Community 59 - "main_window.py"
Cohesion: 0.05
Nodes (44): ChannelKey, disambiguate(), Master-clock presentation of a cached pyramid channel. A…, Stable identity of one channel: its source plus its name. A channel name alone…, Return the display name, qualified by source only when it must be., Return display labels, qualifying only names owned by more than one source., Master timeline and synchronization logic., Background workers for cached-data export and A/B-region statistics. (+36 more)

### Community 60 - "test_workload_responsiveness.py"
Cohesion: 0.11
Nodes (30): _assert_no_stall_tail(), dense_source(), loaded_window(), _measure(), _measure_each(), _percentile(), fixture, parametrize (+22 more)

### Community 61 - "pyramid.py"
Cohesion: 0.05
Nodes (42): _aggregate_gap_mask(), _aggregate_pyramid_level(), build_gap_mask(), build_pyramid_level(), _nan_envelope(), ndarray, Path, Pyramid module for decimation and plotting. (+34 more)

### Community 62 - "SyncProvenance"
Cohesion: 0.09
Nodes (28): Accepted synchronization evidence summary persisted in a session., SyncProvenance, ExactSyncFit, Piecewise exact target-time fit that honors nonlinear gaps/drops., _provenance(), LogCaptureFixture, MonkeyPatch, Behaviours on the last uncovered `core/` paths (BLUEPRINT.md Phase 6). Each of… (+20 more)

### Community 63 - "test_ci_platform_config.py"
Cohesion: 0.06
Nodes (33): Regression checks for the shared cross-platform CI and release contract., An unpinned ffmpeg is both a CI flake and an unreproducible installer.…, Ubuntu 24.04 must provide AppImageTool's libfuse.so.2 runtime ABI., A version tag must not release a side branch or detached commit., Pushing a branch must never publish, and neither must a non-version tag.…, No job may build or publish without the tag having been verified., PyPI and the GitHub release must not publish two different versions. Nothing…, A PEP 440 pre-release tag must be marked as one on the release page. (+25 more)

### Community 64 - "test_seek_backends.py"
Cohesion: 0.14
Nodes (21): _assert_within(), camera_files(), _fanout(), _jump_targets(), Any, fixture, Path, TempPathFactory (+13 more)

### Community 65 - "write_recording"
Cohesion: 0.11
Nodes (33): default_spec(), _message_manifest(), MessageSpec, Path, Build a miniature Open Ephys binary recording for tests. Small enough to write…, Write *spec* under *root* and return the ``recording1`` directory., One continuous stream to write into the fixture., A TTL line to write as rising/falling edge pairs. (+25 more)

### Community 66 - "DummyVideoLoader"
Cohesion: 0.08
Nodes (20): patch, DummyTimeSeriesLoader, DummyVideoLoader, MonkeyPatch, Path, The `~/.avialsync/plugins/` drop-in path is a supported way to add a format., A broken plugin is otherwise indistinguishable from one never installed. Its…, Importable but useless is still a failure the author needs told about. (+12 more)

### Community 67 - "SourceInspection"
Cohesion: 0.09
Nodes (15): All collected inspection data for one loaded source. Not frozen because…, SourceInspection, Return the sidecar manager scoped to loader identity and accepted config., Return a validated cache manifest without opening the source parser., Persist cache metadata required to reopen without parsing the source., Update badge and properties panel from a SourceInspection., Show badge if integrity flags are set., Forward SourceInspection to the VideoInfoWidget badge. (+7 more)

### Community 68 - "test_ui_plot_row_geometry.py"
Cohesion: 0.26
Nodes (12): _pane_with_channels(), parametrize, Path, Plot rows must occupy the pane, not collapse to their minimum width. Rows are…, Scrolling must not cost the ordinary case its full-height rows., Every row's plot area must span the pane, whatever the size or row count., A second load must not leave the newest row collapsed beside settled ones., More rows than fit must be reachable by scrolling, at full height. The… (+4 more)

### Community 69 - "test_typed_source_errors.py"
Cohesion: 0.11
Nodes (16): _BadLoader, Any, Path, Loaders and the importer raise typed errors, not bare builtins (V-06). AGENTS…, A plugin that violates the frozen v1 bulk-ingest contract., Distinct from SourceOpenError: the fix is in the plugin, not the data., The UI cannot turn a bare builtin into an actionable dialog., One base means the UI can catch the whole family in a single handler. (+8 more)

### Community 70 - "test_ui_sensor_mapping.py"
Cohesion: 0.10
Nodes (27): cache_dir(), fixture, Path, QApplication, Sensor offset/drift editing in the sidebar re-aligns plots without reimporting., Session restore holds the mapping until the async import finishes., set_mapping is display-only; it must not re-emit into the handler., The seam between the importer and the panel — and what session reload uses. A… (+19 more)

### Community 71 - "Player"
Cohesion: 0.12
Nodes (12): Return whether accepted per-frame evidence owns this mapping., Player, QObject, Stop UI ticks before the owning window tears down its panes., Start playback for programmatic callers such as the demo launcher., Use the first active exact mapping as the reference frame clock. This is…, Step to the neighbouring decoded frame across all video panes. The step size…, Set or clear the A/B loop region on the master clock. (+4 more)

### Community 72 - "PaintCanvas"
Cohesion: 0.07
Nodes (35): OverlayTrack, PaintCanvas, Any, QColor, QFont, QPainter, QPaintEvent, QWidget (+27 more)

### Community 73 - "capture"
Cohesion: 0.19
Nodes (15): capture(), _load_session(), main(), Image, Path, QImage, quantize_to_shared_palette(), Capture a short looping animation of a real session folder opened through its… (+7 more)

### Community 74 - "session_controller.py"
Cohesion: 0.12
Nodes (25): autosave(), autosave_before_close(), on_session_load_error(), open_recent(), open_session(), Path, Session persistence, window geometry, autosave, and the recent-files menu.…, Load all sources from a SessionState object. (+17 more)

### Community 75 - "PlotInteractionController"
Cohesion: 0.11
Nodes (15): PlotInteractionController, Any, QAction, Refresh overlays whose X coordinates depend on the current page., Handle a right-click only when it lands inside a visible channel row., Own page-local overlay state while delegating semantic actions to PlotPane., Register shared QActions for the plot context menu., Place measurement pin A and publish a complete A/B interval. (+7 more)

### Community 76 - "VideoSurface"
Cohesion: 0.19
Nodes (7): QPaintEvent, QWidget, Paints the decoded frame, letterboxed. The geometry here must match…, Drop the displayed frame., Blit the frame centred, preserving aspect ratio., Create the paint canvas, name/OSD labels, and placeholder overlay., VideoSurface

### Community 77 - "export.py"
Cohesion: 0.07
Nodes (35): compute_region_stats(), export_data_slice_csv(), export_data_slice_parquet(), Any, ndarray, Path, QImage, Export utilities: snapshot PNG, data slice CSV/Parquet, video clip. (+27 more)

### Community 78 - "color_for_point"
Cohesion: 0.08
Nodes (24): color_for_point(), PointColorRegistry, One palette, one name-to-colour rule, shared by the 2D overlay and 3D view. The…, Return the shared colour for the body part called *name*., Hand out one stable colour per body-part name, decided at load time., Assign a colour to every name not seen before, in sorted order. Idempotent, so…, Return *name*'s colour, assigning one now if it was never registered. Painting…, Forget every assignment. For tests that need a known starting point. (+16 more)

### Community 79 - "_with_messages"
Cohesion: 0.11
Nodes (21): _messages_dir(), The error a user sees must name the file they have to go and fix. neo decodes…, neo asserts on this one, which is not an error a user can act on., The check must stay quiet on the recordings a rig actually writes., neo warns and skips this one, so the recording still opens and must., Reading the prose ourselves is what makes the text survive the defect., neo picks one seconds-or-sample-numbers rule for the whole recording. The flag…, Write the default recording plus a MessageCenter the experimenter typed. (+13 more)

### Community 80 - "demo.py"
Cohesion: 0.17
Nodes (20): CancelledCallback, demo_data_dir(), _demo_frame_times(), ensure_demo_data(), _generate_video(), _has_header(), Path, ProgressCallback (+12 more)

### Community 81 - "prepare_release.py"
Cohesion: 0.16
Nodes (23): Pattern, dirty_paths(), ensure_preconditions(), main(), prepare_release(), Path, Prepare, validate, commit, tag, and push an AvialSync PyPI release. Run from…, Update version authorities and optionally create and publish the release tag. (+15 more)

### Community 82 - "Tracking3DCanvas"
Cohesion: 0.05
Nodes (31): QWheelEvent, Connectivity derived from pose geometry, with the flow it was rooted in.…, True when any connectivity was found., SkeletonEstimate, QMouseEvent, QWidget, Custom-painted current-pose view with mouse orbit and wheel zoom., Number of complete XYZ points available to the view. (+23 more)

### Community 83 - "test_ui_follow.py"
Cohesion: 0.08
Nodes (10): The owning source's stable identifier (its path)., fixture, Path, Tests for fixed-window oscilloscope plotting., The chosen row height must size the stack, not just the rows in it. This used…, A narrow spike remains visible instead of being averaged into a midpoint., sweep_pane(), test_decimated_plot_preserves_minimum_and_maximum_envelope() (+2 more)

### Community 84 - "VideoMetadata"
Cohesion: 0.05
Nodes (51): Format-neutral video metadata exposed by every video source. Timestamp-derived…, VideoMetadata, adjacent_frame_time(), frame_index_at(), ndarray, Frame selection from presentation timestamps — the single authority. The frame…, Return the index of the presentation frame active at ``source_time``. Args:…, Return the neighbouring real presentation timestamp. Anchored on the frame… (+43 more)

### Community 85 - "test_engine_importer.py"
Cohesion: 0.11
Nodes (16): _BulkLoader, Path, Tests for the asynchronous time-series import pipeline., A loader that also carries what the experimenter typed during recording., A third-party loader whose message reader is broken., On a cache hit the loader is never opened, so the manifest must carry them.…, One-pass test loader whose legacy per-channel API must never be used., Losing the samples fails an import; losing a comment must not. (+8 more)

### Community 86 - "test_theme_tooltips.py"
Cohesion: 0.08
Nodes (23): Theme tests for appearance-only changes on all supported appearances., Tooltips remain readable through palette roles, not a global stylesheet., Small/Medium/Large apply to existing controls, while System restores the base…, Collecting a cycle mid-snapshot frees widgets Qt has already handed over., Pausing collection around the snapshot must not outlive it., Rooting the snapshot in the window trees may not narrow what it covers., A custom OS accent must flow into links and interactive controls., A widget with no parent is a top-level window in Qt, so it is still covered. (+15 more)

### Community 87 - "test_player_clock.py"
Cohesion: 0.12
Nodes (20): _osd_pane(), _osd_rate_under(), _playhead_per_tick(), skipif, The playback clock is ``time.perf_counter``, and must stay that way.…, Return how far the playhead moved on each tick, given a clock. ``sample_at``…, The control case: a clock finer than the tick just works., The defect, stated as an assertion rather than as a comment. Quantising the… (+12 more)

### Community 88 - "test_ui_shortcut_reach.py"
Cohesion: 0.11
Nodes (26): KeyboardModifier, _fires(), _focusable(), _hold(), fixture, Key, parametrize, QWidget (+18 more)

### Community 89 - "Transport"
Cohesion: 0.05
Nodes (23): QResizeEvent, Reposition all visible A/B pins from stored times + current geometry., Set A/B in-point at current slider position., Button click — set A/B in-point (button state managed here)., Set A/B out-point at current slider position., Button click — set A/B out-point (button state managed here)., Parse HH:MM:SS.fff, MM:SS, or bare seconds., Transport bar: play/pause, frame step, scrub slider, A/B loop, rate control,… (+15 more)

### Community 90 - "AOLEksLoader"
Cohesion: 0.13
Nodes (12): AOLEksLoader, Return one ChannelInfo per x/y/z coordinate. EKS rows are one video frame each,…, Tracking Data (2D/3D). Format: standard CSV with header row. Columns follow the…, EKS data is always frame-indexed., Detect EKS CSV by filename pattern and header structure., Path, EKS rows are one frame each, so rate_hz is the camera fps, not None., Reading before open() reports it instead of raising AttributeError. (+4 more)

### Community 91 - "make_fixtures.py"
Cohesion: 0.14
Nodes (21): Path, Regression guard: make_fixtures._clean_generated() must never delete permanent…, Running _clean_generated twice must not error (no dirs to remove second time)., session_v1.avv, session_v2.avv, session_v3.avv must be committed in…, _clean_generated() deletes generated subdirs but leaves .avv files intact., test_clean_generated_is_idempotent(), test_clean_generated_preserves_session_files(), test_permanent_fixtures_exist_in_repo() (+13 more)

### Community 92 - "test_ui_layout_resize.py"
Cohesion: 0.12
Nodes (22): fixture, Path, QApplication, Window and pane resizing behaviour. Three defects motivated these tests: 1.…, A rigid minimum makes the window feel unresizable on a small screen., Dragging a handle must actually move it, not snap back. Two things made earlier…, The regression: plots used to be handed zero pixels on launch., saveState stores the collapsible flag; restoring must not undo the policy. (+14 more)

### Community 93 - ".__init__"
Cohesion: 0.07
Nodes (24): QVBoxLayout, Register window-scoped QActions for all keyboard-only shortcuts (D-022). Rules…, _make_empty_inspection(), QFrame, QWidget, Left Sidebar / Inspector Pane., Displays metadata and controls for a single loaded video., Attach the VideoStandardLoader for metadata display. (+16 more)

### Community 94 - "import_controller.py"
Cohesion: 0.09
Nodes (28): enqueue_import(), on_import_error(), on_import_finished(), on_import_thread_finished(), Any, Path, Time-series import and pose routing. One import worker owns the modal progress…, Queue a source import so only one worker owns the import UI at a time. (+20 more)

### Community 95 - "TestShowDelta"
Cohesion: 0.12
Nodes (6): app(), panel(), fixture, Tests for ReadoutPanel.show_delta and set_camera_states., TestSetCameraStates, TestShowDelta

### Community 96 - "ImportWizard"
Cohesion: 0.10
Nodes (17): _guess_format(), _guess_time_column(), ImportWizard, Any, Path, QDialog, QWidget, Timestamp import wizard with preview, format autodetect, and timezone handling. (+9 more)

### Community 97 - "_pulses"
Cohesion: 0.10
Nodes (16): _pulses(), ndarray, parametrize, An unsafe alignment must be refused, never guessed. `core/sync.py` decides…, Shifting past the end leaves nothing to pair., Video frame 0 maps to reference index N, the documented behaviour., Malformed timestamp arrays must be rejected before any fitting., Reordering evidence would fabricate a pairing the source never had. (+8 more)

### Community 98 - "PlotHeader"
Cohesion: 0.12
Nodes (12): PlotHeader, QWidget, Expose one live-style, page, Y-fit, row-height, and reset control strip., Show a persisted live style without emitting a duplicate state transition., QEvent, QWidget, Keep pyqtgraph's canvas aligned with an application palette change., Apply the active Qt palette to pyqtgraph's global canvas settings. (+4 more)

### Community 99 - "Tracking3DPane"
Cohesion: 0.11
Nodes (38): Timeline-synchronized 3D tracking pane., Pin an explicit vertical axis chosen by the user., Pin which source axis renders upward (see :meth:`Tracking3DCanvas.set_up_axis`)., Tracking3DPane, _anatomical_readers(), Path, Tests for the timeline-synchronized 3D tracking pane., Build a pose whose vertical axis is Y and grows downward. Mirrors the real AOL… (+30 more)

### Community 100 - "SourceOpenError"
Cohesion: 0.11
Nodes (20): Raised when a media or data source fails to open., SourceOpenError, Any, Path, Video-extraction-toolbox ROI metric loader. Reads one camera's extracted…, Read the sidecar, then every numeric array from the HDF5 file., Choose which recorded axis reaches master time, and how far to move it. The two…, Report how far the file's own absolute axis sits from the camera start. A… (+12 more)

### Community 101 - "build_manifest"
Cohesion: 0.08
Nodes (49): build_manifest(), Scan an AOL session folder and build a loading manifest. Priority for videos:…, apply_session_layout(), Adopt the settings a session plugin reported for the folder it laid out.…, aol_session(), _declare_skeleton(), _finish_import(), fixture (+41 more)

### Community 102 - "test_never_freeze.py"
Cohesion: 0.14
Nodes (19): QApplication, The UI must stay responsive, visible, and closeable under any workload. This is…, The regression: closeEvent called event.ignore() and trapped the user., Abandoning jobs must not skip the session write., A worker that ignores cancellation, like a blocked syscall., A wedged job must not hold shutdown open., The grace period is a total budget, not per job., test_a_quiet_job_is_reported_as_not_responding() (+11 more)

### Community 103 - "test_ui_dialogs.py"
Cohesion: 0.12
Nodes (30): QDialog, Missing-file relink dialog shown when session files cannot be found., Lets the user relocate missing files referenced by a session. Shows a table of…, RelinkDialog, csv_file(), Path, QApplication, Coverage for the four import/inspection dialogs (P6.1). `import_wizard`,… (+22 more)

### Community 104 - "tracking_3d_pane.py"
Cohesion: 0.08
Nodes (29): The source-to-master mapping applied by every method here., _build_sources(), _coordinate_name(), detect_up_axis(), _mean_axis_position(), _PointChannels, Interactive 3D view for cached tracking-coordinate channels., Group complete XYZ triplets by source cache and pre-warm their mmap arrays. (+21 more)

### Community 105 - "test_aol_loaders.py"
Cohesion: 0.16
Nodes (14): fixture, Tests for AOL loaders (encoder log, EKS 3D tracking, session detection)., Create a minimal encoder_log.txt fixture., Create a minimal EKS CSV fixture with x/y/z columns and fnum., Create an EKS CSV without a fnum column., A session emits four "_eks.csv" files that go to three different places. One is…, Create a minimal AOL session folder structure., `config` is hashed into the sidecar cache key; a display string must not be. (+6 more)

### Community 106 - ".paintEvent"
Cohesion: 0.11
Nodes (16): _nearest_index(), ndarray, QPainter, QPaintEvent, _qcolor(), Copy of the currently sampled XYZ positions, including NaN placeholders., Rotate world coordinates so the anatomical vertical is view +Z., Project world points to screen; the anatomical vertical maps to screen up. (+8 more)

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
Cohesion: 0.12
Nodes (14): _FakePane, fixture, Path, QWidget, Removal must not invent a session file for someone who never saved one., A real widget the grid's layout accepts, minus libmpv. A plain object cannot…, The signal is useless if it arrives after the teardown it guards., A snapshot taken here must describe the session without this video. (+6 more)

### Community 112 - "test_sync_golden.py"
Cohesion: 0.14
Nodes (18): app_with_main_window(), _capture_frame(), _fixture_frame_time(), fixture, ndarray, QApplication, Golden sync testing for video playback., Test multi-camera golden sync with offsets. (+10 more)

### Community 113 - "test_ui_main.py"
Cohesion: 0.07
Nodes (34): main_window(), fixture, MonkeyPatch, parametrize, QApplication, Main Window regression tests., Dropped files route by registered source type, not a suffix allow-list., A generic directory falls back to capability-routing its direct children. (+26 more)

### Community 114 - "test_core_sync.py"
Cohesion: 0.17
Nodes (11): Ground-truth tests for headless TTL/event synchronization., A rising edge split between chunks is emitted exactly once at its raw time., Unsound event evidence must never be silently reordered., Periodic TTLs recover the known mapping despite dropped target pulses., A single implausible edge is excluded and recorded as rejected evidence., Equal-quality periodic shifts require a user constraint, never auto-acceptance., test_extract_ttl_edges_preserves_chunk_boundaries(), test_extract_ttl_edges_rejects_non_monotonic_chunk_stream() (+3 more)

### Community 115 - "VideoPropertiesPanel"
Cohesion: 0.08
Nodes (18): _frame_count_text(), _PropertiesBase, Any, QGroupBox, QWidget, Collapsible source-properties panels for VideoInfoWidget and SensorInfoWidget…, Collapsible properties panel for one video source., Read the pane's current decode state; call when the panel is expanded. The rate… (+10 more)

### Community 116 - "AvialSync Plot UX Refinement Plan"
Cohesion: 0.12
Nodes (16): 10. Focus and keyboard contract, 11. Performance invariants, 12. Persistence and migration, 13. Implementation slices, 14. Required test evidence, 15. Definition of done, 1. Objective, 2. Compatibility ledger — nothing in this list may be lost (+8 more)

### Community 117 - "test_bench_cursor_path"
Cohesion: 0.19
Nodes (12): large_dataset(), fixture, Path, Pyramid and cursor-path benchmarks with local engineering budget gates.…, A committed shared-window change stays below the 30 ms UI budget., Generate 180M samples once per session to save time and memory., Pyramid build for 180M samples must complete within the ★ budget., Full per-tick cursor path: plot set_cursor + transport set_time + readout… (+4 more)

### Community 118 - "session.py"
Cohesion: 0.13
Nodes (16): MarkerEntry, Session state and JSON serialization for .avv files., Deserialise from a parsed JSON dict (accepts v1 through v6)., Persisted state for one loaded video., Persisted state for one loaded sensor CSV., Persisted annotation marker., SensorEntry, VideoEntry (+8 more)

### Community 119 - "UiHeartbeat"
Cohesion: 0.12
Nodes (9): QObject, Detect and report stalls of the UI thread itself. Background work being off-…, Measure UI-thread responsiveness and report stalls., The largest stall seen so far, for diagnostics., UiHeartbeat, Blocking the loop must be surfaced, not merely felt as lag., test_heartbeat_reports_a_blocked_ui_thread(), test_heartbeat_reset_clears_history() (+1 more)

### Community 120 - "TESTING.md"
Cohesion: 0.12
Nodes (15): 1. Test layers, 2. Fixtures — `tools/make_fixtures.py` (ground truth for everything), 3. Golden sync tests (`tests/test_sync_golden.py`), 3a. TTL/event synchronization golden tests (D-026), 4. Performance benchmarks (`tests/benchmarks/`), 5. GUI test conventions, 5a. Plot UX refinement gates (P4.6 / D-044), 6. Manual smoke checklist (human, end of each phase, on YOUR real field data) (+7 more)

### Community 121 - "TestTtlExtraction"
Cohesion: 0.29
Nodes (4): Raw edges are evidence; unusable input must not become empty evidence., Anonymous evidence cannot be attributed in saved provenance., A contact bounce is one transition, not several., TestTtlExtraction

### Community 122 - "ARCHITECTURE.md"
Cohesion: 0.12
Nodes (14): 1. Repository layout (complete — the authoritative map of what lives where), 2. Runtime dataflow, 2a. Synchronization dataflow (D-026), 2b. Timeline Evidence overview (D-027), 3. Threading model, 4. Plugin contract (frozen at Phase 5 as API v1), 5. Session file (.avv, JSON, schema_version field), 5b. Cache invalidation key (updates D-004) (+6 more)

### Community 123 - "ToyBinarySource"
Cohesion: 0.17
Nodes (8): Any, Path, A minimal external AvialSync Plugin API v1 implementation., Read ``.toybin`` records encoded as little-endian ``(time, value)`` pairs., Recognise the example file extension without opening the input., Store the path after validating whole-record alignment., Expose the single dimensionless signal channel., ToyBinarySource

### Community 124 - "skeleton.py"
Cohesion: 0.16
Nodes (18): _component(), _finite_height(), _pair_statistics(), ndarray, Skeleton topology derived from the geometry of 3D pose points. Point *names*…, Return (cost, variation) matrices; ``inf`` marks a pair that cannot link., Prim's algorithm, restarted per component, over a dense cost matrix. Restarting…, Treat a missing height as the lowest possible, never as a winner. (+10 more)

### Community 125 - "QTableWidgetItem"
Cohesion: 0.29
Nodes (3): QTableWidgetItem, QAction, QWidget

### Community 126 - "test_diagnostics.py"
Cohesion: 0.17
Nodes (11): Startup diagnostics lifecycle tests., A failed capability query must stay observable rather than raise., A bug report has to say what decoded the video, not what is installed., Concurrent app instances must not contend for one fixed probe filename., Repeated windows share one diagnostics probe instead of spawning threads., Informational only — software decode already meets every budget (D-075). PyAV…, test_diagnostics_report_names_the_decoder_actually_in_use(), test_disk_probe_uses_unique_file_and_cleans_it() (+3 more)

### Community 127 - "test_close_and_focus.py"
Cohesion: 0.07
Nodes (42): _playhead_events(), _press(), fixture, Key, parametrize, Path, QApplication, _pyramid_channels() (+34 more)

### Community 128 - "ChannelInfo"
Cohesion: 0.07
Nodes (20): ChannelInfo, Metadata for a single data channel., Return stable metadata for every importable channel., _MidnightUnwrapper, AOL Encoder Log Loader. Parses MATLAB-generated encoder_log.txt files with…, Turn wrapping seconds-since-midnight into a continuous axis. AOL video and EKS…, Return one ChannelInfo per column, at the camera's frame rate., Return one ChannelInfo per ``(ROI, column)`` pair. (+12 more)

### Community 129 - "TimelineEvidence"
Cohesion: 0.13
Nodes (11): QSlider, _ABPin, JumpSlider, QFrame, QWidget, A QSlider that instantly jumps to the clicked position., Titled, collapsible Data Streams shell for named TimelineOverview lanes., The currently displayed status message, without its label prefix. (+3 more)

### Community 130 - "test_bench_plot_pane.py"
Cohesion: 0.22
Nodes (15): _channel_cache(), _populated_pane(), parametrize, Path, Performance guards for the populated plot pane (BLUEPRINT.md budgets). P4.6's…, A drag resizes continuously; no single callback may pass the ceiling. 128…, One slice of row construction must not freeze the window. Rows are built in…, Build a field-shaped multi-channel pyramid cache. Sample depth is kept modest… (+7 more)

### Community 131 - "test_demo_data.py"
Cohesion: 0.17
Nodes (14): Path, Regression tests for generated, user-facing demo inputs., The demo tracking file must match the loader's three-row DLC contract., The compatibility script cannot drift from ``avialsync demo`` again., test_generated_pose_csv_is_importable_dlc_data(), test_tools_launcher_delegates_to_installed_application(), _is_dlc_pose_csv(), main() (+6 more)

### Community 132 - "test_transport_resize.py"
Cohesion: 0.17
Nodes (15): _expected_pin_x(), fixture, Regression tests: transport A/B pins must realign after window resize., Pin remains correctly positioned across consecutive resizes., Return the correct x for a pin at *frac* given the slider's current geometry., A/B in-pin must sit at the correct groove fraction after a resize., A/B out-pin realigns after resize (non-midpoint fraction)., Both A/B pins realign independently after a single resize. (+7 more)

### Community 133 - "neo_loader.py"
Cohesion: 0.10
Nodes (21): main(), main(), Headless dataclasses for import statistics and source integrity (D-020). No…, clean(), Free-text records the acquisition system stored alongside the data.…, Return *text* as a single-line, length-bounded message body. Embedded newlines…, Asynchronous data source importer pipeline., Neo-based electrophysiology loader — the single ingest path for ephys data.… (+13 more)

### Community 134 - "job_manager.py"
Cohesion: 0.17
Nodes (11): BackgroundWorker, _drop_finished_threads(), JobState, Enum, Protocol, QThread, One owner for every background job, so the UI can never be trapped. Three…, Release retained jobs whose threads have stopped. Never call this from a… (+3 more)

### Community 135 - "Path"
Cohesion: 0.12
Nodes (10): Any, Path, Return 0..1 confidence that *path* is a session this can lay out. Called with…, Return the session's contents and the settings that span them. ``registry``…, Return a confidence in ``[0.0, 1.0]`` without expensive I/O., Read metadata required for :meth:`channels` and :meth:`read_chunks`. ``config``…, Return 0..1 confidence that this loader can open the file., Probe source metadata; this method may perform blocking I/O. (+2 more)

### Community 136 - "AOLSessionSource"
Cohesion: 0.13
Nodes (25): AOLSessionSource, Lay out an AOL multi-camera experiment folder as a session. This is the…, fixture, Path, AOL session routing for video-extraction-toolbox exports. These are ordinary…, With no camera start to anchor to, the file's own axis is all there is., Seven files extracted from three videos cover one span, not seven. The cameras…, The two hold the same numbers; importing both would plot every ROI twice. The… (+17 more)

### Community 137 - "._relayout"
Cohesion: 0.18
Nodes (6): Switch between horizontal-strip and NxN grid layout., Remove a video pane by path., Show or hide a video pane without unloading it., Resume relayout after a batch add sequence., Remove all widgets from the grid and re-add them in the current arrangement…, Update camera labels, disambiguating duplicate filenames.

### Community 138 - "aol_metric_loader.py"
Cohesion: 0.22
Nodes (8): _column_names(), Any, Path, AOL Extracted-Metric MAT Loader. Reads the per-(ROI, metric) `-v6` MAT files an…, Load the single `roi_metric_data` array and resolve column names., Return column names read from the file, or ``None`` when it stored none. MATLAB…, Resolve column names for *metric*, falling back to generic ones. A mismatch…, _stored_column_names()

### Community 139 - "._collect_drop_candidates"
Cohesion: 0.22
Nodes (5): Return True if this source stores frame numbers instead of wall-clock time.…, Path, Slot, Lay out *path* with the session plugin that claims it, if any. Returns ``None``…, Collect paths and their best-guess loaders recursively, avoiding session files.

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

### Community 146 - "._apply_default_splitter_sizes"
Cohesion: 0.25
Nodes (4): QSplitter, Forbid collapsing a pane to nothing. Must be re-applied after ``restoreState``:…, Re-seed any splitter a previously-saved state left with a zero pane. A zero-…, Seed the first-run pane layout, as sizes now and as shares thereafter. Called…

### Community 147 - "generate_demo_screenshots.py"
Cohesion: 0.19
Nodes (9): generate_screenshots(), main(), _pin_appearance(), Path, QApplication, Capture the synchronization walkthrough used in the README. Run with ``conda…, Force the documented appearance without touching saved preferences.…, generate_screenshots() (+1 more)

### Community 148 - "test_conda_recipe.py"
Cohesion: 0.24
Nodes (13): _project_metadata(), The conda-forge recipe must describe the package this repository builds., A recipe pinned to a stale version publishes the wrong source archive., A missing run dependency is an import error on a user's first launch., The conda package is now the same shape as the wheel (D-075). Decoding,…, conda must not offer the package on a Python the project excludes., The console script conda installs must be the one the package defines., _recipe_text() (+5 more)

### Community 149 - "TestMeasureMarkers"
Cohesion: 0.15
Nodes (5): app(), plot_pane(), fixture, Tests for PlotPane measure markers and measure_changed signal., TestMeasureMarkers

### Community 150 - "test_aol_metric_routing.py"
Cohesion: 0.22
Nodes (13): aol_session_with_metrics(), fixture, ndarray, Path, AOL extracted-metric routing: data_root MAT exports become plot rows. Unlike…, A data_root dropped without its sibling videos still loads, unaligned., An AOL session with one camera plus a nested data_root-style export., The metric file's start_epoch must match its camera's video, not 0. (+5 more)

### Community 151 - "theme.py"
Cohesion: 0.12
Nodes (32): _accent(), accent_hue(), _apply(), evidence_color(), _is_dark_palette(), loop_pin_color(), marker_color(), on_surface() (+24 more)

### Community 152 - "ProxyWorker"
Cohesion: 0.17
Nodes (12): needs_proxy(), proxy_path_for(), ProxyWorker, Path, QObject, Proxy generation — re-encode videos to all-keyframe scrub-friendly proxies., Return the sidecar proxy path for a given video., Check if a proxy already exists and is newer than the source. (+4 more)

### Community 153 - "VideoOpenWorker"
Cohesion: 0.08
Nodes (15): Any, Path, QObject, Slot, Select, open, and optionally prepare one video source off the UI thread., Request cancellation between source operations., Open the selected source and emit a usable media path on success., Adapt the plugin's normalized progress callback to the UI signal. (+7 more)

### Community 154 - "TimeMap"
Cohesion: 0.04
Nodes (27): Return the equivalent master-to-target mapping., ndarray, setter, Maps master timeline to a specific source timeline. t_source = t_master +…, Return the source-time rate relative to master time., Return the local source/master rate around ``t_master``. Exact frame-trigger…, Snap to the nearest accepted frame-trigger timestamp, if available., Return whether exact evidence covers ``t_master``. Affine mappings are… (+19 more)

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
Cohesion: 0.29
Nodes (7): Importing several files at once, Missing values and decimal commas, Structure: how to split the file, Time: what the numbers mean, Timezone: state it, never assume it, Tutorial: import sensor and recording data, What happens after you accept

### Community 160 - "AvialSync — Model Handout"
Cohesion: 0.17
Nodes (11): Architecture Rules (violations = rejected PR), AvialSync — Model Handout, File, Marking, Module Map, Naming (binding), Playback, Run Commands (+3 more)

### Community 161 - "MIGRATION_PYAV.md — libmpv → PyAV, and a pip-only install"
Cohesion: 0.17
Nodes (11): 1. Goal, in one sentence, 2. Why — the measured case, 3. The invariant that outranks everything, 4. Steps — update the status column as you go, 5. Licensing — settled, 6. Rollback, 7. Environment notes for whoever picks this up, MIGRATION_PYAV.md — libmpv → PyAV, and a pip-only install (+3 more)

### Community 162 - "capture"
Cohesion: 0.24
Nodes (11): QRect, _bounds_in(), capture(), _draw_step_number(), Path, QPainter, QWidget, Shared capture helpers for the documentation screenshots. Two things every… (+3 more)

### Community 163 - "._refresh_status"
Cohesion: 0.18
Nodes (6): Use complete XYZ channel triplets from the active cached readers., Say how many points are loaded, and where their bones came from. The provenance…, Reflect the canvas's current orientation without re-triggering it., Set the connectivity the session declared; empty falls back to detection., Pin which skeleton the view draws (see :class:`BoneMode`)., Apply the skeleton mode the user chose in the header.

### Community 164 - "Job"
Cohesion: 0.18
Nodes (6): Job, One unit of background work, owned for its whole lifetime., Whether the worker offers a cooperative cancel., Jobs that have gone quiet for longer than the watchdog allows., Ask every cancellable job to stop; never blocks., Stop everything and return the labels that had to be abandoned. Always returns…

### Community 165 - ".eventFilter"
Cohesion: 0.11
Nodes (16): _editor_rejects_text(), _is_mid_edit(), QDragEnterEvent, QDropEvent, QEvent, QObject, QWidget, Return whether *widget* would refuse *text* as typed input. A numeric field… (+8 more)

### Community 166 - "_PointArrays"
Cohesion: 0.18
Nodes (9): _PointArrays, ndarray, Protocol, The shape of one tracked point, as the 3D pane already holds it. Read-only…, Body-part name this point's channels were grouped under., Coordinate arrays, one per axis, in XYZ order., Per-axis masks marking samples the source never recorded., A successfully probed video must not fall back to UNKNOWN in the sidebar. (+1 more)

### Community 167 - "SeekGroup"
Cohesion: 0.08
Nodes (22): Asynchronous seek coordinator., Fan out non-blocking frame requests across video panes. ``VideoPane.seek``…, Request one pane's frame at a source time, without blocking., Request every active pane's frame at master time ``t``., Return True once every pane has painted the frame it was asked for., SeekGroup, _FastPane, Performance gates for timestamp-mapped multi-video command dispatch. (+14 more)

### Community 168 - "ShortcutsDialog"
Cohesion: 0.33
Nodes (4): QDialog, Keyboard shortcuts reference dialog — derived from live QAction registry…, Modal dialog listing all keyboard shortcuts. Derives content entirely from live…, ShortcutsDialog

### Community 169 - "test_headless_core.py"
Cohesion: 0.20
Nodes (10): _production_trees(), Headless core guard test., Architecture rule 2 applies per module, not only to the package __init__.…, Catch the violation even when a lazy import hides it at runtime., Unexpected failures must be reported, not converted into blank UI state., Guard the UI-thread and cross-platform subprocess architecture rules., test_every_core_module_imports_without_pyside6(), test_no_core_module_imports_pyside6_statically() (+2 more)

### Community 170 - "PROMPTS.md — kickoff prompts per phase"
Cohesion: 0.18
Nodes (10): Debugging prompt template (any phase), Phase 0 prompts, Phase 1 prompts, Phase 2 prompts, Phase 3 prompts, Phase 4 prompts (one per feature, same pattern), Phase 5 prompts, Phase 6 prompts (+2 more)

### Community 172 - "plot_interactions.py"
Cohesion: 0.16
Nodes (16): PlotItem, Stateful interaction controller for plot measurements, markers, and menus., ContextChoice, Any, InfiniteLine, QAction, Overlay drawing and context-menu helpers for pyramid-backed plot rows., Draw retained gap evidence only where it intersects the visible page. (+8 more)

### Community 173 - "Video Extraction Toolbox — output schema for AvialSync"
Cohesion: 0.13
Nodes (14): 1. Where the files are, 2. File format, 3. HDF5 layout, 4. JSON sidecar, 5. Channel model, 6. Time base, 7. Session-level notes, 8. The per-ROI store (upstream of the export) (+6 more)

### Community 174 - "TestAOLSessionDetection"
Cohesion: 0.20
Nodes (5): is_aol_session(), Return True if the directory has AOL session signature files. An AOL session…, Root MP4s are the normal case., A session with only rendered videos must still open., TestAOLSessionDetection

### Community 175 - "_ArrayReader"
Cohesion: 0.22
Nodes (7): _ArrayReader, ndarray, Path, Performance guard for the 3D tracking cursor hot path., Minimal mmap-reader equivalent for isolating per-tick sampling cost., Sampling 128 XYZ points must leave room in the existing cursor budget., test_bench_tracking_3d_cursor()

### Community 176 - "test_every_timing_module_samples_perf_counter"
Cohesion: 0.40
Nodes (5): parametrize, The seams the rest of the suite fakes, pinned to their real clock., Fail loudly if ``time.monotonic`` is put back into a sub-second budget. All…, test_every_timing_module_samples_perf_counter(), test_no_timing_module_reaches_for_time_monotonic()

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

### Community 182 - ".add_pane"
Cohesion: 0.25
Nodes (5): Pass tracking data readers to all video panes for overlay rendering. Retained,…, Attach named 2D prediction tracks to the pane showing *path* only. 2D pose data…, Add a pane identified by original *path*, playing *media_path* if supplied., A dropped video must complete its real worker lifecycle without closing the app., test_drop_real_video_completes_async_open()

### Community 183 - "SessionState"
Cohesion: 0.13
Nodes (13): Any, Path, Write session JSON and large exact mappings atomically. Small mappings remain…, Complete serialisable state of a AvialSync session. Only stores paths and…, Serialise to a JSON-compatible dict (always writes version 6)., SessionState, Path, Exact arrays survive the asynchronous gap between restore and pane creation. (+5 more)

### Community 184 - "_QuickWorker"
Cohesion: 0.20
Nodes (8): QObject, Slot, _QuickWorker, A job that starts reporting again must stop being flagged., A QObject moved to a QThread with no Python reference never starts., test_a_registered_worker_actually_runs(), test_finished_jobs_are_dropped_from_the_registry(), test_progress_clears_a_not_responding_state()

### Community 185 - "open_ephys_session.py"
Cohesion: 0.08
Nodes (33): anchor_epoch(), Return the UTC epoch that acquisition-clock zero corresponds to. Master time…, _camera_items(), _event_items(), _first_sample_time(), _format_rate(), _match_folder(), _neo_streams() (+25 more)

### Community 186 - "Plugin guide"
Cohesion: 0.22
Nodes (9): Claiming a whole recording folder, Naming your format, Optional: messages the recording carries, Optional: single-pass bulk ingest, Plugin guide, Session plugins, Synchronization and future plugins, Time-series plugins (+1 more)

### Community 187 - "Troubleshooting"
Cohesion: 0.18
Nodes (11): A file does not open, A startup error naming numpy or quantities, A video says “No Footage”, An Open Ephys recording will not open, and the error names an event stream, The import wizard read my timestamps wrong, The Messages tab is empty, The plots look slow or too dense, The video pane stays blank (+3 more)

### Community 188 - "Phase Status"
Cohesion: 0.22
Nodes (9): Cross-platform pressure audit (D-040), Done — Inspection Layer (A–K, D-020), Done (Phase 4), Done (Phase 4 UX / loader fixes), Fixed (this PR — Phase 4 stabilization), Implemented — TTL/event synchronization baseline (D-026), mypy is clean — keep it that way (V-07), Pending (+1 more)

### Community 189 - "_PaletteStyleFollower"
Cohesion: 0.40
Nodes (4): _PaletteStyleFollower, QEvent, QObject, Re-runs a widget's stylesheet builder whenever its palette changes.

### Community 190 - "MissingColumnError"
Cohesion: 0.08
Nodes (26): AvialSyncError, CodecUnsupportedError, FileUnreadableError, LoaderContractError, MissingColumnError, NonMonotonicTimeError, Any, Exception (+18 more)

### Community 191 - ".open"
Cohesion: 0.50
Nodes (3): Any, Path, Read headers and identify x/y/z channels.

### Community 192 - "._refresh"
Cohesion: 0.14
Nodes (10): _display_names(), _path_tail(), Adopt the window's time display mode, like every other timed widget., Rebuild every row from the store, then apply the current filter. Called when…, Show the rows that match the filter, without rebuilding any of them., Return the file name of *source_id*, falling back to the id itself., Return the last *depth* segments of *source_id*., Return a short label per source, extended only as far as it must be. Two record… (+2 more)

### Community 194 - "Quickstart"
Cohesion: 0.25
Nodes (8): After installing, Align recordings, Before you start, Inspect one moment, Open files, Quickstart, Try it without your own data, Where to go next

### Community 195 - "Development and release"
Cohesion: 0.25
Nodes (8): Building the documentation, Connecting the Read the Docs project, Development and release, Releases, Signing, Source checkout, The demo session, Windows checkout

### Community 196 - "User Guide"
Cohesion: 0.22
Nodes (9): 3D tracking controls, Aligning recordings, Appearance and font size, Flagging and exporting, Main areas of the window, Messages the recording carries, Useful controls, User Guide (+1 more)

### Community 197 - "Sessions, proxies, and the 3D view"
Cohesion: 0.25
Nodes (8): Appearance, Keyboard shortcuts, Plot navigation, Proxies, Sessions, Sessions, proxies, and the 3D view, The 3D tracking view, When files have moved

### Community 198 - "Performance Budgets (engineering-certified where ★)"
Cohesion: 0.25
Nodes (8): 29. A built-in loader's dependencies can fail, and that must not be fatal, 30. The Windows `0xC0000005` was inside faulthandler — trigger removed with libmpv, 31. Connect a job's result signals in `configure`, never after `_run_job` returns, 8f. The pyramid query must fill the point budget, not merely fit under it, 8g. Shutdown steps are isolated and ordered; never let one raise skip the rest, 8h. Text editors steal the playhead keys unless they are explicitly reserved, 8i. Never build all plot rows in one call, Performance Budgets (engineering-certified where ★)

### Community 199 - "RuntimeError"
Cohesion: 0.18
Nodes (11): ndarray, Yield fixed-size, chronologically ordered chunks., bundle_executable(), main(), Path, Launch a built AvialSync bundle headlessly and require a clean shutdown., Return the platform executable in a PyInstaller one-directory bundle., Require the bundled Qt application to construct and close successfully.… (+3 more)

### Community 200 - "AvialSync"
Cohesion: 0.25
Nodes (7): AvialSync, Contributing, Documentation, First session, Install, Licence, What it gives you

### Community 201 - "fit_exact_index_mapping"
Cohesion: 0.31
Nodes (8): fit_exact_index_mapping(), Create a deterministic exact index mapping, overriding affine limits. Frames…, parametrize, Ground-truth tests for exact index synchronization., test_exact_index_mapping_bounds_display_evidence_but_keeps_full_mapping(), test_exact_index_mapping_preserves_raw_pairs_and_nonlinear_timestamps(), test_exact_index_offset_records_unmatched_reference_evidence(), test_exact_index_rejects_dense_samples_mistaken_for_frame_triggers()

### Community 202 - "ImportReportDialog"
Cohesion: 0.18
Nodes (8): ImportReportDialog, QDialog, QWidget, Import Report dialog — shows ImportReport stats with a copy-as-text button., Scrollable plain-text view of an ImportReport with a Copy button., Show the full ImportReport dialog for a data source., A v1 session carries no ImportReport; the dialog must still open., test_import_report_handles_a_source_with_no_report()

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

### Community 207 - "._event_detail"
Cohesion: 0.19
Nodes (5): QMouseEvent, Return the event tuples behind one lane kind. A lookup rather than a…, Binary-search the nearest event of *kind*, or None outside tolerance., Move the page while preserving the playhead's fractional page position., Return concise inspectable evidence nearest the pointer, if any.

### Community 208 - "test_ui_plot_sliced_refresh.py"
Cohesion: 0.13
Nodes (16): channel_cache(), pane(), fixture, Path, A span change requeries every row without holding the UI thread (D-063). The…, Built once: 128 pyramids are slow enough to matter per test., The callback must hand work back to the event loop, not finish it all., Deferring must not mean dropping. (+8 more)

### Community 209 - ".load"
Cohesion: 0.16
Nodes (18): Read a .avv session file and validate any exact-map sidecars., Path, Tests for SessionState serialisation and schema migrations., A v3 session must survive a save/load cycle with video_frames intact., Inspection fields and accepted synchronization provenance survive a round trip., An empty session should save and load without error., A v1 .avv file must load correctly after the v2-v5 schema changes., Loading a v1 session then saving it should produce a valid v5 file. (+10 more)

### Community 210 - "test_transport_layout.py"
Cohesion: 0.06
Nodes (31): Tests for the two-row timeline and status transport layout., Coverage, TTL, gaps, and annotations share one clickable master-time strip., Seek-row controls follow the compact visual-inspection workflow., Evidence is understandable in text and does not reserve empty lanes., Files that cover one span get one lane, positioned at the first member. Seven…, An empty span at the origin is a removal, not coverage from time zero., Hover details make sync evidence inspectable rather than colour-only., A recorded note is neither a sync match nor a defect, and reads as itself. (+23 more)

### Community 211 - "QSettings"
Cohesion: 0.18
Nodes (9): QSettings, restore_geometry(), save_geometry(), current_font_preference(), current_preference(), is_dark(), Return the persisted preference, normalized for legacy settings., Return the persisted font-size preference. (+1 more)

### Community 212 - "2026-08 · D-081 · The video-extraction export is the ROI-metric surface, and it is HDF5"
Cohesion: 0.40
Nodes (5): 2026-08 · D-081 · The video-extraction export is the ROI-metric surface, and it is HDF5, Alternatives rejected, Consequences, Context, Decision

### Community 213 - "Formats"
Cohesion: 0.29
Nodes (6): Acquisition recordings, Formats, Lab formats, Sensor and tracking data, Timing comes from the frames, not the container, Video

### Community 214 - "Licensing"
Cohesion: 0.33
Nodes (5): Bundled components, Contributing, Licensing, Plugins are your own work, What you can do

### Community 215 - "Tutorial: flag frames and export"
Cohesion: 0.33
Nodes (6): Export, Flag a frame, Mark a range, Review and label what you flagged, Tutorial: flag frames and export, What is not exported

### Community 216 - "build_bundle"
Cohesion: 0.40
Nodes (5): build_bundle(), main(), Path, Build a one-directory AvialSync bundle for the current platform. Nothing is…, Run PyInstaller over the project spec.

### Community 217 - "2026-08 · D-084 · A seek is answered by its own frame, not by any frame"
Cohesion: 0.50
Nodes (4): 2026-08 · D-084 · A seek is answered by its own frame, not by any frame, Consequences, Context, Decision

### Community 218 - "DemoLaunch"
Cohesion: 0.08
Nodes (34): DemoLaunch, Coordinate visible demo preparation with a worker thread., Show progress UI and start generation., main(), QAction, Apply the selected system-relative application font scale., apply_font_size(), _apply_font_to_existing_widgets() (+26 more)

### Community 219 - "test_annotation_frames.py"
Cohesion: 0.18
Nodes (10): Tests for frame-accurate annotation: VideoFrame, export, AnnotationPanel., Pane-owned decode threads must stop before Qt destroys the grid., Annotation frame numbers must never use t*fps arithmetic for VFR media., test_add_point_no_frames_defaults_to_empty(), test_frame_records_at_empty_grid(), test_frame_records_at_offset_applied(), test_frame_records_at_single_pane(), test_frame_records_at_two_panes() (+2 more)

### Community 220 - ".eventFilter"
Cohesion: 0.33
Nodes (4): QEvent, QObject, Reserve Space for playback while retaining ordinary Tab accessibility., Repaint the lanes when the platform appearance changes. Lane colours are…

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

### Community 232 - "CacheManager"
Cohesion: 0.07
Nodes (34): CacheManager, is_cache_path(), Any, Path, Cache management for sidecar files., Get a temporary directory for writing cache. Ensure atomic swap later., Commit a replacement without discarding the last valid sidecar first., Replace a sidecar's contents without renaming the directory. Individual files… (+26 more)

### Community 234 - "DemoWindow"
Cohesion: 0.24
Nodes (8): DemoData, DemoWindow, load_demo(), Any, Protocol, The source-loading surface the demo needs from the main window., Load the complete synchronized demo through normal asynchronous paths., Paths comprising the installed inspection demo.

### Community 235 - ".exact_time_mapping"
Cohesion: 0.22
Nodes (6): ndarray, Yield one-dimensional ``float64`` time/value chunks for *ch*. Chunks, including…, Per-frame timestamps if the container has them., Return per-frame ``(master_time, source_time)`` evidence, or ``None``. Additive…, The hook is additive: a frozen v1 video plugin must be unaffected by it., test_video_source_default_declares_no_exact_mapping()

### Community 236 - ".closeEvent"
Cohesion: 0.40
Nodes (3): QCloseEvent, Run one shutdown step; log and continue if it fails. Closing is the one path…, Always close. This used to ``event.ignore()`` while any background job was…

### Community 237 - ".coverage_group_for"
Cohesion: 0.33
Nodes (3): Re-align one time-series source against the master clock. This only changes the…, Return the shared Data Streams lane *path* belongs in, if any. Empty for…, Apply exact reader-derived bounds once every queued row exists. Rows are built…

### Community 238 - "SessionLoadWorker"
Cohesion: 0.25
Nodes (5): Path, QObject, Slot, Read and parse .avv + sidecars off the UI thread. Only parsing moves here.…, SessionLoadWorker

### Community 239 - "TestPyramidLevelHelpers"
Cohesion: 0.25
Nodes (5): Direct checks on the decimation helpers' degenerate inputs., The base level is not decimated; min and max are the sample., Repeated timestamps give a zero median interval, not a gap threshold. A stuck…, One sample yields no adjacent pair at all., TestPyramidLevelHelpers

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

### Community 247 - "test_a_type_names_the_data_never_the_rig"
Cohesion: 0.33
Nodes (3): Kinds of data an acquisition recording carries besides the ephys. One…, One reader serves many kinds, so the type must not be the reader's name. Every…, test_a_type_names_the_data_never_the_rig()

### Community 248 - "_stalls_seen"
Cohesion: 0.33
Nodes (6): Report a stall of *stall_s* to a fresh heartbeat, as *clock* would see it.…, The control case: 35 ms of blocking is over the 30 ms ceiling, so it counts., Why the stall detector cannot read ``time.monotonic`` either. A 100 ms interval…, _stalls_seen(), test_a_coarse_clock_loses_a_real_stall_entirely(), test_a_fine_clock_catches_a_stall_just_over_the_threshold()

### Community 250 - "recording"
Cohesion: 0.40
Nodes (5): fixture, A two-stream Open Ephys recording with one TTL line., A session folder: the record-node tree plus a camera recorded beside it., recording(), session_dir()

### Community 252 - "test_three_camera_four_stream_session_can_be_cached_and_queried"
Cohesion: 0.40
Nodes (4): Path, Cross-platform functional check for the representative scientific workload., Exercise the session shape scientists use without treating CI as a speed test., test_three_camera_four_stream_session_can_be_cached_and_queried()

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

### Community 283 - "DemoProgressDialog"
Cohesion: 0.12
Nodes (13): DemoGenerationWorker, DemoProgressDialog, QDialog, QObject, QWidget, Slot, Show demo generation progress and an inspectable activity log., Display a worker status event. (+5 more)

### Community 284 - "QLabel"
Cohesion: 0.14
Nodes (14): QLabel, _CameraRow, _ChannelReadout, _DeltaRow, QWidget, Show this camera's frame number and media time. Deliberately not called…, Shows Δvalue for one channel., Preserve a fixed-width family while inheriting the application font size. (+6 more)

### Community 292 - "2026-08 · D-082 · A skeleton is detected from geometry when the data declares none"
Cohesion: 0.40
Nodes (5): 2026-08 · D-082 · A skeleton is detected from geometry when the data declares none, Alternatives rejected, Consequences, Context, Decision

### Community 300 - "read_frame_timestamps"
Cohesion: 0.15
Nodes (13): Return per-frame exposure evidence from a ``frame_number,timestamp`` sidecar.…, read_frame_timestamps(), parametrize, Bad timing evidence costs exact timing; it must never cost the video., This arrives from a plugin, so it is checked rather than trusted. A mapping…, The fallback names any plugin that does not override, so it must read well. The…, The counter is the only proof they existed. Timestamps alone cannot tell "a…, test_a_restarting_counter_reports_no_drops_rather_than_nonsense() (+5 more)

### Community 301 - "_demo_frame"
Cohesion: 0.67
Nodes (3): _demo_frame(), ndarray, Draw one recognisable test frame. A moving bar over a static gradient, plus a…

### Community 315 - "2026-08 · D-083 · Video-derived data is timed from the camera start, and shares one lane"
Cohesion: 0.50
Nodes (4): 2026-08 · D-083 · Video-derived data is timed from the camera start, and shares one lane, Consequences, Context, Decision

## Knowledge Gaps
- **467 isolated node(s):** `avialsync-plugin-example`, `make_appimage.sh script`, `make_dmg.sh script`, `avialsync`, `What and why` (+462 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **24 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MainWindow` connect `MainWindow` to `sync.py`, `test_pane_proportions.py`, `TimeSeriesSource`, `JobManager`, `._apply_default_splitter_sizes`, `diagnostics.py`, `generate_demo_screenshots.py`, `export_controller.py`, `ProxyWorker`, `VideoOpenWorker`, `test_cli_demo.py`, `DemoProgressDialog`, `test_interaction_standard.py`, `generate_guide_screenshots.py`, `VideoStandardLoader`, `Message`, `AnnotationStore`, `LoaderRegistry`, `MasterClock`, `.eventFilter`, `_PointArrays`, `ShortcutsDialog`, `test_session_worker.py`, `SyncWizard`, `test_worker_lifetime.py`, `PlotPane`, `format_time`, `VideoGrid`, `Path`, `.add_pane`, `SessionState`, `_QuickWorker`, `main_window.py`, `test_workload_responsiveness.py`, `SyncProvenance`, `SourceInspection`, `test_ui_sensor_mapping.py`, `Player`, `capture`, `session_controller.py`, `ImportReportDialog`, `demo.py`, `QSettings`, `test_ui_shortcut_reach.py`, `Transport`, `DemoLaunch`, `test_ui_layout_resize.py`, `.__init__`, `import_controller.py`, `.resizeEvent`, `Tracking3DPane`, `build_manifest`, `test_never_freeze.py`, `CacheManager`, `DemoWindow`, `test_frame_indexed.py`, `.closeEvent`, `.coverage_group_for`, `_FakePane`, `test_sync_golden.py`, `test_ui_main.py`, `session.py`, `UiHeartbeat`, `._generate_proxy`, `test_close_and_focus.py`?**
  _High betweenness centrality (0.191) - this node is a cross-community bridge._
- **Why does `PlotPane` connect `PlotPane` to `MainWindow`, `test_bench_plot_pane.py`, `plot_pane.py`, `TestMeasureMarkers`, `TimeMap`, `SweepWindowControl`, `AnnotationStore`, `plot_interactions.py`, `format_time`, `main_window.py`, `test_ui_plot_row_geometry.py`, `Player`, `PlotInteractionController`, `test_ui_plot_sliced_refresh.py`, `test_ui_follow.py`, `test_theme_tooltips.py`, `.__init__`, `PlotHeader`, `test_bench_cursor_path`, `test_close_and_focus.py`?**
  _High betweenness centrality (0.080) - this node is a cross-community bridge._
- **Why does `LoaderRegistry` connect `LoaderRegistry` to `MainWindow`, `test_loaders_open_ephys.py`, `.can_open`, `AOLEncoderLoader`, `PyramidReader`, `AOLSessionSource`, `._collect_drop_candidates`, `test_core_coverage_edges.py`, `TimeSeriesSource`, `test_aol_metric_routing.py`, `VideoOpenWorker`, `TestAOLSessionDetection`, `PyramidBuilder`, `main_window.py`, `SyncProvenance`, `write_recording`, `DummyVideoLoader`, `AOLEksLoader`, `.__init__`, `build_manifest`, `CacheManager`, `test_aol_loaders.py`, `test_frame_indexed.py`, `TestPyramidLevelHelpers`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Are the 60 inferred relationships involving `MainWindow` (e.g. with `DemoData` and `DemoGenerationWorker`) actually correct?**
  _`MainWindow` has 60 INFERRED edges - model-reasoned connections that need verification._
- **Are the 19 inferred relationships involving `PlotPane` (e.g. with `Player` and `_JobWorker`) actually correct?**
  _`PlotPane` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 43 inferred relationships involving `TimeMap` (e.g. with `ChannelKey` and `MappedChannelReader`) actually correct?**
  _`TimeMap` has 43 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `PyramidReader` (e.g. with `ChannelKey` and `MappedChannelReader`) actually correct?**
  _`PyramidReader` has 27 INFERRED edges - model-reasoned connections that need verification._