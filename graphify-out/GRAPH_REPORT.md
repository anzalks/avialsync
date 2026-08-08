# Graph Report - .  (2026-08-08)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 5247 nodes · 9764 edges · 253 communities (235 shown, 18 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 946 edges (avg confidence: 0.6)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `5eac07c4`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- LoaderRegistry
- MainWindow
- test_loaders_open_ephys.py
- SensorInfoWidget
- Transport
- SourceOpenError
- PlotPane
- VideoMetadata
- DECISIONS.md — lightweight ADR log
- CacheManager
- test_playback_smoothness.py
- AOLEksLoader
- open_ephys_session.py
- aol_session_loader.py
- VideoGrid
- test_pane_proportions.py
- PaintCanvas
- VideoStandardLoader
- ImportWorker
- Known Traps
- SourceInspection
- VideoPane
- PyramidReader
- AOLEncoderLoader
- test_interaction_standard.py
- CSVLoader
- MappedChannelReader
- PyramidBuilder
- export_controller.py
- TimelineOverview
- Troubleshooting
- plot_pane.py
- SweepWindowControl
- test_close_and_focus.py
- AvialSync — Project Blueprint (v1)
- NeoLoader
- ndarray
- test_ui_main.py
- TimeMap
- AnnotationStore
- VideoPropertiesPanel
- pyramid.py
- test_video_pane.py
- timeline.py
- ReaderReference
- test_worker_lifetime.py
- DummyVideoLoader
- sync.py
- test_seek_backends.py
- SyncEvidenceError
- SessionState
- SyncWizard
- PyAVReader
- Path
- export_worker.py
- test_plugin_discovery.py
- import_controller.py
- TrackingLoader
- ._set_sweep_for_time
- format_time
- write_recording
- test_pyav_reader.py
- test_workload_responsiveness.py
- test_ci_platform_config.py
- test_scrubbing.py
- DropScanWorker
- Player
- .can_open
- session_controller.py
- PlotInteractionController
- _parse_args
- test_core_coverage_edges.py
- sync_worker.py
- main_window.py
- test_frame_identity.py
- prepare_release.py
- test_session_worker.py
- PlotHeader
- test_tracking_colors.py
- test_theme_tooltips.py
- ChannelKey
- test_ui_sensor_mapping.py
- test_cli_demo.py
- test_aol_chunk_boundaries.py
- test_aol_pose_routing.py
- make_fixtures.py
- test_subprocess_no_window.py
- demo.py
- extract_ttl_edges
- Tracking3DCanvas
- .paintEvent
- test_never_freeze.py
- test_ui_layout_resize.py
- MasterClock
- .eventFilter
- TimeDisplayMode
- Tracking3DPane
- cfr_times
- test_ui_dialogs.py
- annotations.py
- .load
- test_channel_identity.py
- test_ui_follow.py
- write_video
- transcode.py
- test_packaging_smoke.py
- test_ui_shortcut_reach.py
- test_diagnostics.py
- TimelineEvidence
- ._on_evidence_changed
- Path
- DemoLaunch
- test_demo_data.py
- _FakePane
- test_sync_golden.py
- AvialSync Plot UX Refinement Plan
- UiHeartbeat
- TESTING.md
- test_core_timeline.py
- ARCHITECTURE.md
- Plugin guide
- ToyBinarySource
- theme.py
- ProxyWorker
- QApplication
- tracking_3d_pane.py
- DecodeWorker
- test_ui_plot_sliced_refresh.py
- TestShowDelta
- generate_session_screenshot.py
- create_channel_plot
- QLabel
- job_manager.py
- test_bench_plot_pane.py
- test_transport_resize.py
- Contributor Covenant Code of Conduct
- 2026-07 · D-020 · Inspection layer — what is surfaced where
- Data handling
- test_engine_layering.py
- AnnotationPanel
- JobManager
- ReadoutPanel
- test_conda_recipe.py
- _BulkLoader
- ImportReportDialog
- .__init__
- ImportWizard
- RelinkDialog
- TestMeasureMarkers
- generate_icons.py
- AvialSync — Model Handout
- MIGRATION_PYAV.md — libmpv → PyAV, and a pip-only install
- QSettings
- build_gap_mask
- DemoData
- SessionSaveWorker
- Job
- .reset_view
- test_bench_cursor_path
- TestPluginDiscovery
- test_headless_core.py
- _PreparedVideo
- test_job_thread_lifetime.py
- PROMPTS.md — kickoff prompts per phase
- DemoProgressDialog
- .load_channels
- _ArrayReader
- test_core_cache.py
- 2026-07 · D-022 · Interaction standard — visible surface, depth in menus, shortcuts as accelerators
- .fit_current_pose
- test_prepare_release.py
- Phase Status
- .exact_time_mapping
- .test_both_paths_failing_reports_both_causes
- generate_screenshots
- no_startup_diagnostics
- Performance Budgets (engineering-certified where ★)
- smoke_bundle
- AvialSync
- fit_exact_index_mapping
- ._apply_default_splitter_sizes
- apply_theme
- .set_readers
- _QuickWorker
- test_ui_plot_row_geometry.py
- Architecture
- Signal Wiring Map
- Licensing
- Tutorial: align recordings
- User Guide
- release
- build_bundle
- default_display_name
- test_a_type_names_the_data_never_the_rig
- test_packaging_spec.py
- 2026-07 · D-032 · Headless CI uses null video, decoded-frame evidence, and explicit mpv ownership — AMENDED by D-075
- 2026-07 · D-037 · Releases require a tag reachable from main
- 2026-07 · D-043 · Presentation timestamps own video timing and exact interaction
- 2026-07 · D-044 · Plot presentation separates review, sweep, and scope
- 2026-07 · D-045 · The AOL encoder axis is seconds-since-midnight, unwrapped
- 2026-07 · D-046 · Pose data drives the overlay and 3D view, never plot rows
- pull_request_template.md
- Q: the window adjust metns are slow for the tim, put a limit region eg: n (s)dropdown so that user can define in seconds or minutes or millisecond and hours as units so that we can select the scale and then the slider pick the units if corse adjustment is needed. currently the plotting is very wonky, and dot dyanmic with the scale adjustments when i change windows. adfter a bit of playing things things freeze. fix these issues too things needs to be extreamly fast as possible
- Q: the window adjust metns are slow for the tim, put a limit region eg: n (s)dropdown so that user can define in seconds or minutes or millisecond and hours as units so that we can select the scale and then the slider pick the units if corse adjustment is needed. currently the plotting is very wonky, and dot dyanmic with the scale adjustments when i change windows. adfter a bit of playing things things freeze. fix these issues too things needs to be extreamly fast as possible
- Q: commit current changes; fix closed or unchecked plots reappearing on resize and streams (video, plots, 3d) freezing or becoming unsmooth after a while
- Q: have you checked the focus of keybaord issues ? the focus mut be for the play pause seen kind a things i think right now it stays with the timewindow input area, once i enter a value the focus never goes away form it. but if user already entered the value thats enough to take off the focus from that to play area
- Q: Where can AvialView be made freeze-free and faster while preserving accurate data streaming?
- Q: Implement the performance-audit hardening and commit it
- Q: Make planning-file changes for the approved plot UX refinement without code changes, preserving all current functionality.
- sign_notarize.sh
- .closeEvent
- set_font_family
- ._generate_proxy
- ._on_sensor_mapping_changed
- _DeltaRow
- 2026-07 · D-033 · Packaging inputs are explicit and CI artifact builds are a separate gate
- 2026-07 · D-034 · Themes are palette/font appearance, never interaction redesign
- 2026-07 · D-036 · PR and tag quality use one cross-platform test contract
- 2026-07 · D-038 · Windows video panes use libmpv's Qt OpenGL render API — SUPERSEDED by D-075
- 2026-07 · D-039 · Release bundles own the complete media runtime — AMENDED by D-075
- 2026-07 · D-040 · Sidecar writes use bounded concurrency and failures remain observable
- 2026-07 · D-042 · Plots use one fixed, shared oscilloscope sweep
- .eventFilter
- .set_time
- .set_viewport
- test_packaging_metadata.py
- test_worker_thread_teardown.py
- 2026-07 · D-023 · Benchmarks CI-gated; budget-assertion pattern; CI multiplier
- 2026-07 · D-029 · Separate GitHub workload correctness from local speed certification
- 2026-07 · D-030 · Test-level watchdog for cross-platform Qt verification
- 2026-07 · D-031 · Libmpv commands stay on the Qt-owning thread — SUPERSEDED by D-075
- PlaybackState
- _demo_frame
- .resizeEvent
- conf.py
- post-commit
- pre-commit
- make_appimage.sh
- make_dmg.sh
- avialsync
- test_seek_hides_and_skips_video_panes_without_master_time_coverage
- test_exact_scrub_snaps_master_clock_to_accepted_frame_trigger
- test_frame_step_does_nothing_without_a_timestamp_table
- test_dispatch_immediately_when_seeker_free
- .set_loader

## God Nodes (most connected - your core abstractions)
1. `MainWindow` - 360 edges
2. `PlotPane` - 115 edges
3. `TimeMap` - 106 edges
4. `PyramidReader` - 104 edges
5. `LoaderRegistry` - 83 edges
6. `DECISIONS.md — lightweight ADR log` - 80 edges
7. `PyramidBuilder` - 69 edges
8. `VideoStandardLoader` - 69 edges
9. `CSVLoader` - 67 edges
10. `Transport` - 67 edges

## Surprising Connections (you probably didn't know these)
- `test_main_window_places_3d_view_beside_video_grid()` --indirect_call--> `MainWindow`  [INFERRED]
  tests/test_ui_tracking_3d.py → src/avialsync/ui/main_window.py
- `plot_pane()` --calls--> `PlotPane`  [INFERRED]
  tests/test_ui_plot_measure.py → src/avialsync/ui/plot_pane.py
- `panel()` --calls--> `ReadoutPanel`  [INFERRED]
  tests/test_ui_readout_delta.py → src/avialsync/ui/readout_panel.py
- `ToyBinarySource` --uses--> `ChannelInfo`  [INFERRED]
  examples/plugins/avialsync-plugin-example/src/avialsync_plugin_example/__init__.py → src/avialsync/core/source.py
- `ToyBinarySource` --uses--> `TimeSeriesSource`  [INFERRED]
  examples/plugins/avialsync-plugin-example/src/avialsync_plugin_example/__init__.py → src/avialsync/core/source.py

## Import Cycles
- None detected.

## Communities (253 total, 18 thin omitted)

### Community 0 - "LoaderRegistry"
Cohesion: 0.03
Nodes (82): ABC, _Capability, LoaderRegistry, Path, Protocol, Plugin registry and discovery., Add each built-in class in *specs*, reporting any that will not import., Add every class published under *group*, skipping ones that fail.          Dedup (+74 more)

### Community 1 - "MainWindow"
Cohesion: 0.02
Nodes (39): QMainWindow, drag_enter(), on_drop_scan_error(), QDragEnterEvent, build_next_video_pane(), on_video_opened(), on_video_pane_ready(), on_video_thread_finished() (+31 more)

### Community 2 - "test_loaders_open_ephys.py"
Cohesion: 0.04
Nodes (77): Path, Return per-frame exposure evidence from a ``frame_number,timestamp`` sidecar., read_frame_timestamps(), _drop(), _layout(), datetime, Path, Tests for the Open Ephys session plugin and the neo ingest path behind it.  Ever (+69 more)

### Community 3 - "SensorInfoWidget"
Cohesion: 0.04
Nodes (43): QTreeWidgetItem, QVBoxLayout, The owning source's stable identifier (its path)., Register window-scoped QActions for all keyboard-only shortcuts (D-022)., _make_empty_inspection(), QFrame, QWidget, Left Sidebar / Inspector Pane. (+35 more)

### Community 4 - "Transport"
Cohesion: 0.04
Nodes (43): QResizeEvent, Transport bar: play/pause, frame step, scrub slider,     A/B loop, rate control,, Set the A/B loop in-point at the current slider position (public, D-022.1)., Set the A/B loop out-point at the current slider position (public, D-022.1)., The master-timeline extent currently displayed.          Public because ``engine, The currently displayed status message., Show compact, non-blocking status text beside Reset Zoom., Show accepted synchronization events in the overview strip. (+35 more)

### Community 5 - "SourceOpenError"
Cohesion: 0.05
Nodes (51): AvialSyncError, CodecUnsupportedError, FileUnreadableError, LoaderContractError, MissingColumnError, NonMonotonicTimeError, Any, Exception (+43 more)

### Community 6 - "PlotPane"
Cohesion: 0.03
Nodes (35): PlotPane, InfiniteLine, QAction, Abandon queued row building.          Called when the window closes. A queued sl, Compatibility alias for setting the shared continuous window., Set the fixed sweep duration shared by every plot row., Retain the legacy state flag without creating another navigation model., Set the shared sweep window to the full master-timeline duration. (+27 more)

### Community 7 - "VideoMetadata"
Cohesion: 0.05
Nodes (48): Format-neutral video metadata exposed by every video source.      Timestamp-deri, VideoMetadata, adjacent_frame_time(), frame_index_at(), ndarray, Frame selection from presentation timestamps — the single authority.  The frame, Return the index of the presentation frame active at ``source_time``.      Args:, Return the neighbouring real presentation timestamp.      Anchored on the frame (+40 more)

### Community 8 - "DECISIONS.md — lightweight ADR log"
Cohesion: 0.03
Nodes (61): 2026-07 · D-001 · Master time = float64 seconds, UTC epoch, 2026-07 · D-002 · Video playback = libmpv only — SUPERSEDED by D-075, 2026-07 · D-003 · License Apache-2.0; no GPL deps — SUPERSEDED by D-069, 2026-07 · D-004 · Sidecar cache format, 2026-07 · D-005 · Chunked ingest is the only ingest path, 2026-07 · D-006 · VideoSource conversion hook is first-class, 2026-07 · D-007 · Frame stepping uses actual frame timestamps, 2026-07 · D-008 · Cache key gets content-hash tail (+53 more)

### Community 9 - "CacheManager"
Cohesion: 0.06
Nodes (45): CacheManager, is_cache_path(), Any, Path, Cache management for sidecar files., Get a temporary directory for writing cache. Ensure atomic swap later., Commit a replacement without discarding the last valid sidecar first., Replace a sidecar's contents without renaming the directory.          Individual (+37 more)

### Community 10 - "test_playback_smoothness.py"
Cohesion: 0.06
Nodes (48): SimpleNamespace, DecodingPane, _osd_pane(), _OsdPane, QApplication, Playback must not generate work proportional to the decoded frame rate.  Each pa, Drive the real tick for *seconds* of simulated playback.      Returns ``(master_, The new playback model, stated as an assertion.      Under libmpv the player wat (+40 more)

### Community 11 - "AOLEksLoader"
Cohesion: 0.06
Nodes (33): AOLEksLoader, Any, Path, Return one ChannelInfo per x/y/z coordinate.          EKS rows are one video fra, Tracking Data (2D/3D).      Format: standard CSV with header row. Columns follow, EKS data is always frame-indexed., Detect EKS CSV by filename pattern and header structure., Read headers and identify x/y/z channels. (+25 more)

### Community 12 - "open_ephys_session.py"
Cohesion: 0.06
Nodes (49): anchor_epoch(), find_record_dir(), find_recordings(), is_recording_dir(), parse_record_dir_time(), parse_software_epoch(), datetime, Path (+41 more)

### Community 13 - "aol_session_loader.py"
Cohesion: 0.07
Nodes (49): One file a session contributes, with the loader and config it needs.      ``load, What a recording folder contains, plus the settings that span it.      Session-w, SessionItem, SessionLayout, _add_root_videos(), _anchor_epoch(), AOL2DTrack, AOLManifest (+41 more)

### Community 14 - "VideoGrid"
Cohesion: 0.05
Nodes (35): Any, ndarray, QWidget, Pass tracking data readers to all video panes for overlay rendering., Attach named 2D prediction tracks to the pane showing *path* only.          2D p, Switch between horizontal-strip and NxN grid layout., Add a pane identified by original *path*, playing *media_path* if supplied., Remove a video pane by path. (+27 more)

### Community 15 - "test_pane_proportions.py"
Cohesion: 0.06
Nodes (47): distribute(), _pane_minimums(), PaneProportions, QObject, QSplitter, Hold each pane's share of the workspace steady while the window is resized.  ``Q, Manage *splitters*, adopting each one's ratio the first time it lays out., Adopt *splitter*'s current pane ratio as the one to hold.          A visible pan (+39 more)

### Community 16 - "PaintCanvas"
Cohesion: 0.06
Nodes (39): color_for_point(), One palette, one name-to-colour rule, shared by the 2D overlay and 3D view.  The, Return the shared colour for the body part called *name*., OverlayTrack, PaintCanvas, Any, QColor, QFont (+31 more)

### Community 17 - "VideoStandardLoader"
Cohesion: 0.06
Nodes (28): main(), main(), Any, ndarray, Path, Read container and stream metadata with PyAV.          This used to shell out to, Adopt per-frame exposure times the acquisition system recorded, if given., Return per-frame ``(master_time, source_time)`` evidence, if recorded. (+20 more)

### Community 18 - "ImportWorker"
Cohesion: 0.08
Nodes (41): ChannelStage, Append-only on-disk staging buffer for one float64 channel.      An import worke, Number of samples appended so far., Close the staging handle; safe to call more than once., Close and delete the staging file without materialising it., Write staged samples to *target* as ``.npy`` and return its mmap.          The c, ImportWorker, QObject (+33 more)

### Community 19 - "Known Traps"
Cohesion: 0.04
Nodes (52): 0. Scheduled work that outlives its owner crashes rather than fails (D-062, D-064), 0a. A `QObject` moved to a `QThread` needs an owning Python reference, 0b. Building a widget list can free the widgets in it (D-065), 0b. Do NOT add the anchor date to AOL encoder timestamps (D-045), 0c. AOL pose data must not become plot rows (D-046), 0d. `"_eks.csv".split("_")[0]` is `""` — and `"" in name` matches everything, 0e. A container's declared frame rate is a claim, not evidence (D-072), 0f. `*.xml` matches `settings.xml`, two levels above the samples (D-070) (+44 more)

### Community 20 - "SourceInspection"
Cohesion: 0.08
Nodes (21): ImportReport, IntegrityFlags, Any, Headless dataclasses for import statistics and source integrity (D-020).  No PyS, All collected inspection data for one loaded source.      Not frozen because imp, Statistics collected by ImportWorker during one source import., Anomaly flags for one loaded source.      Video flags (is_vfr, fps_mismatch) are, SourceInspection (+13 more)

### Community 21 - "VideoPane"
Cohesion: 0.05
Nodes (25): ndarray, QPaintEvent, QWidget, Paints the decoded frame, letterboxed.      The geometry here must match :meth:`, Show a decoded ``(H, W, 3)`` uint8 RGB frame., Drop the displayed frame., Blit the frame centred, preserving aspect ratio., Video rendering pane.      Decodes with PyAV on a per-pane worker thread and bli (+17 more)

### Community 22 - "PyramidReader"
Cohesion: 0.07
Nodes (38): PyramidReader, Reads pyramid queries dynamically from mmapped arrays., channel(), Edge behaviour of the pyramid reader and the loader registry.  Both sit on paths, A one-second channel sampled at 100 Hz, with a gap in the middle., `value_at` answers for any time; outside coverage the answer is NaN., Nearest-sample, not interpolation: the readout must not invent data., A cursor a hair before t0 is a rounding artefact, not absent data. (+30 more)

### Community 23 - "AOLEncoderLoader"
Cohesion: 0.06
Nodes (25): AOLEncoderLoader, Any, ndarray, Path, Return a single velocity channel.          ``rate_hz`` stays ``None``: the logge, Convert HH:MM:SS:mmm to seconds since midnight., Yield bounded (time, value) chunks for the requested channel.          Chunk bou, Validate and de-duplicate one chunk, retaining its final sample.          The re (+17 more)

### Community 24 - "test_interaction_standard.py"
Cohesion: 0.05
Nodes (44): QAction, QDialog, QWidget, Keyboard shortcuts reference dialog — derived from live QAction registry (D-022., Modal dialog listing all keyboard shortcuts.      Derives content entirely from, ShortcutsDialog, _all_shortcuts(), main_window() (+36 more)

### Community 25 - "CSVLoader"
Cohesion: 0.07
Nodes (33): DataType, Series, CSVLoader, ndarray, Return the sampling rate when the sample proves it is regular.          ``Channe, Map wizard format strings to internal categories., Extract epoch unit from wizard format like 'epoch_ms'., Return the explicit parser dtype required by the chosen time format. (+25 more)

### Community 26 - "MappedChannelReader"
Cohesion: 0.06
Nodes (34): MappedChannelReader, ndarray, Replace the offset/drift mapping in place.          Existing plot rows and reado, Return this channel's master-time extent, or None when empty., Return ``(t_master, v, gap)`` for a bounded master-time range., Yield bounded ``(t_master, v)`` chunks., Decimated master-time query; the result is bounded by *max_points*., Return level-1 mmap views in **source** time.          Kept unmapped on purpose: (+26 more)

### Community 27 - "PyramidBuilder"
Cohesion: 0.06
Nodes (39): build_pyramid_level(), PyramidBuilder, Builds and serializes a multi-level pyramid to disk., Build a decimation level for arrays t and v.      Returns (t_decimated, v_min, v, MonkeyPatch, Path, A valid short raw gap cannot disappear merely because the view is coarse., A background sidecar failure must fail the import, never look successful. (+31 more)

### Community 28 - "export_controller.py"
Cohesion: 0.05
Nodes (46): QWidget, Grab a widget's current visual content as a QPixmap., snapshot_widget(), Run ffmpeg clipping jobs outside the Qt event loop., VideoClipWorker, export_annotations(), export_data_slice(), export_snapshot() (+38 more)

### Community 29 - "TimelineOverview"
Cohesion: 0.06
Nodes (28): QMouseEvent, QPaintEvent, Paint named, conditional timeline-evidence lanes without owning time state., Set the shared master-time range rendered by this overview., Return the distinct pixel columns of the events inside ``[t0, t1]``.          Bo, Return the currently populated lanes, in their rendered order., Return the clipped timeline span, excluding the source-label gutter., Move the page while preserving the playhead's fractional page position. (+20 more)

### Community 30 - "Troubleshooting"
Cohesion: 0.04
Nodes (41): 1. Create the environment, 2. Keep per-user packages out of the environment, 3. Run it, Check the installation, Desktop installers (recommended), First-launch security warnings, Install from PyPI, Installation (+33 more)

### Community 31 - "plot_pane.py"
Cohesion: 0.08
Nodes (34): Plot rendering pane using pyqtgraph and decimation pyramids., Load pyramid data for *channels* only, if a page is established., Resolve a channel reference to the rows it identifies.          A :class:`Channe, Refresh the current sweep from the decimation pyramid.          ``sliced`` sprea, Requery one row and settle its once-only Y fit., Requery queued rows for one time slice, then yield to the event loop.          T, Show or hide the plot row(s) identified by *channel*., Update the fixed channel gutter after import metadata is available. (+26 more)

### Community 32 - "SweepWindowControl"
Cohesion: 0.08
Nodes (17): QWidget, Return the shared sweep duration in seconds., Return the absolute master time at the current sweep's left edge., Return the latest master-clock value supplied by the player., Set master bounds and anchor all future sweeps to their start., Set and emit a duration clamped to the current master bounds., Expand the sweep to the complete master timeline., Move the continuous slider one small step inward. (+9 more)

### Community 33 - "test_close_and_focus.py"
Cohesion: 0.07
Nodes (40): _playhead_events(), _press(), Key, Path, QApplication, _pyramid_channels(), The window always finishes closing, and the playhead keys always reach it.  Two, Merely holding focus is not an edit in progress. (+32 more)

### Community 34 - "AvialSync — Project Blueprint (v1)"
Cohesion: 0.05
Nodes (36): AGENTS.md — AvialSync agent instructions (canonical), Architecture rules (violations = rejected PR), Coding standards, Definition of Done (every task), How to run things, Known traps (learned the hard way — do not rediscover), Naming & casing — BINDING (never invent variants), Task protocol for agents (+28 more)

### Community 35 - "NeoLoader"
Cohesion: 0.09
Nodes (22): _fit_length(), NeoLoader, Any, ndarray, Loads electrophysiology data using the neo library., Open *path*, optionally narrowed to one stream or to its events.          Config, Describe every selected analogue channel and note whether one clock spans them., Return one name per column of *asig*, preferring neo's own labels. (+14 more)

### Community 36 - "ndarray"
Cohesion: 0.07
Nodes (23): _aggregate_gap_mask(), _aggregate_pyramid_level(), _nan_envelope(), ndarray, Path, Aggregate one pyramid level from the preceding level's min/max envelopes., Carry raw discontinuity evidence into one coarser pyramid level.      A gap mark, Append one bounded chunk of samples. (+15 more)

### Community 37 - "test_ui_main.py"
Cohesion: 0.08
Nodes (26): Neo-based electrophysiology loader — the single ingest path for ephys data.  Eve, Standard Video Loader., Per-frame exposure evidence read from a capture sidecar., RecordedFrames, MonkeyPatch, Main Window regression tests., Dropped files route by registered source type, not a suffix allow-list., A generic directory falls back to capability-routing its direct children. (+18 more)

### Community 38 - "TimeMap"
Cohesion: 0.06
Nodes (17): The source-to-master mapping applied by every method here., ndarray, Maps master timeline to a specific source timeline.      t_source = t_master + o, Return the source-time rate relative to master time., Return the local source/master rate around ``t_master``.          Exact frame-tr, Snap to the nearest accepted frame-trigger timestamp, if available., Return whether exact evidence covers ``t_master``.          Affine mappings are, Vectorised :meth:`to_master` for an already-bounded array.          Only ever ca (+9 more)

### Community 39 - "AnnotationStore"
Cohesion: 0.07
Nodes (23): Return the frame index presented at ``source_time``.          The one resolution, Return the frame whose presentation interval contains ``source_time``., Return frame ``index``, decoding only what is not already cached.          Raise, Decode forward until ``target`` has been produced, caching the walk.          Fr, AnnotationStore, QObject, QWidget, Per-video frame snapshot stored with an annotation marker. (+15 more)

### Community 40 - "VideoPropertiesPanel"
Cohesion: 0.09
Nodes (14): _frame_count_text(), _PropertiesBase, Any, QGroupBox, QWidget, Collapsible source-properties panels for VideoInfoWidget and SensorInfoWidget (D, Collapsible properties panel for one video source., Read the pane's current decode state; call when the panel is expanded. (+6 more)

### Community 41 - "pyramid.py"
Cohesion: 0.08
Nodes (23): count_nan(), Pyramid module for decimation and plotting., Count NaNs in a possibly mmap-backed array without a full-size temporary., _gap_locations(), Any, ndarray, Path, Asynchronous data source importer pipeline. (+15 more)

### Community 42 - "test_video_pane.py"
Cohesion: 0.09
Nodes (34): clip(), _opened_pane(), Path, QApplication, TempPathFactory, Video-pane construction, decoding, and teardown tests.  Everything here used to, End-to-end, through the real thread: the pixels must name the frame., ``time_pos`` is evidence about what is on screen, not an echo. (+26 more)

### Community 43 - "timeline.py"
Cohesion: 0.08
Nodes (23): Master timeline and synchronization logic., Asynchronous seek coordinator., Fan out non-blocking frame requests across video panes.      ``VideoPane.seek``, Request one pane's frame at a source time, without blocking., Request every active pane's frame at master time ``t``., Return True once every pane has painted the frame it was asked for., SeekGroup, _FastPane (+15 more)

### Community 44 - "ReaderReference"
Cohesion: 0.09
Nodes (24): DataExportWorker, Path, QImage, QObject, Calculate A/B-region statistics from worker-local pyramid readers., Calculate region statistics and tag the result with its request id., Encode UI-captured images without blocking the Qt event loop., Compose and save the immutable image copies on this worker thread. (+16 more)

### Community 45 - "test_worker_lifetime.py"
Cohesion: 0.08
Nodes (27): Behaviour extracted from :class:`~avialsync.ui.main_window.MainWindow`.  Each mo, _FakeFileDialog, main_window(), MonkeyPatch, Path, QApplication, QDropEvent, Background job lifetime regression tests.  A QObject moved to a QThread with no (+19 more)

### Community 46 - "DummyVideoLoader"
Cohesion: 0.08
Nodes (19): DummyTimeSeriesLoader, DummyVideoLoader, MonkeyPatch, Path, The `~/.avialsync/plugins/` drop-in path is a supported way to add a format., A broken plugin is otherwise indistinguishable from one never installed.      It, Importable but useless is still a failure the author needs told about., One bad plugin must never take the application's own loaders with it. (+11 more)

### Community 47 - "sync.py"
Cohesion: 0.10
Nodes (27): Raised when event evidence supports multiple equally valid alignments., SyncAmbiguityError, _candidate_indices(), _default_tolerance(), _evidence_indices(), _fit_affine(), fit_sync_events(), _initial_scale() (+19 more)

### Community 48 - "test_seek_backends.py"
Cohesion: 0.11
Nodes (31): _assert_within(), _bench_mpv(), camera_files(), _fanout(), _import_mpv(), _jump_targets(), _mpv_fanout(), mpv_players() (+23 more)

### Community 49 - "SyncEvidenceError"
Cohesion: 0.12
Nodes (17): Raised when synchronization evidence is malformed or insufficient., SyncEvidenceError, _pulses(), ndarray, An unsafe alignment must be refused, never guessed.  `core/sync.py` decides whet, Shifting past the end leaves nothing to pair., Video frame 0 maps to reference index N, the documented behaviour., Malformed timestamp arrays must be rejected before any fitting. (+9 more)

### Community 50 - "SessionState"
Cohesion: 0.10
Nodes (25): MarkerEntry, Any, Path, Session state and JSON serialization for .avv files., Deserialise from a parsed JSON dict (accepts v1 through v6)., Write session JSON and large exact mappings atomically.          Small mappings, Persisted state for one loaded video., Persisted state for one loaded sensor CSV. (+17 more)

### Community 51 - "SyncWizard"
Cohesion: 0.09
Nodes (19): Affine target-time fit with auditable quality metrics., Return the equivalent master-to-target mapping., A deterministic synchronization proposal with bounded display evidence., Whether this proposal is unambiguous and within its fit tolerance., SyncFit, SyncProposal, A cached signal channel from which TTL transitions are extracted., SignalEvidenceSpec (+11 more)

### Community 52 - "PyAVReader"
Cohesion: 0.08
Nodes (18): ndarray, Path, VideoStream, PyAVReader, Demux one pass to collect presentation timestamps and keyframes.          Demux, Presentation timestamps in source seconds, display order., Number of frames the container actually carries timestamps for., The decoded video stream, for callers building format metadata. (+10 more)

### Community 53 - "Path"
Cohesion: 0.08
Nodes (8): Any, Path, QImage, Open a session file or a folder of recordings.          Routes through the same, Show a per-pane context menu on video right-click (D-022)., Forward to ReadoutPanel with accumulated units for known channels., Show the VideoPropertiesPanel for a video (triggered by badge click)., Show sensor properties for a data source.

### Community 54 - "export_worker.py"
Cohesion: 0.11
Nodes (26): QPixmap, compute_region_stats(), export_data_slice_csv(), export_data_slice_parquet(), Any, ndarray, Path, QImage (+18 more)

### Community 55 - "test_plugin_discovery.py"
Cohesion: 0.11
Nodes (28): ModuleType, Import one loose plugin module without adding its directory to ``sys.path``., Path, Plugin API v1 discovery coverage., A drop-in plugin directory exposes a v1 source to the registry., They are hardcoded *and* declared as entry points; that must not duplicate., `can_open` is offered directories, so a lab can adopt its own folder layout., Claiming the folder must stop the scan recursing into its files.      Otherwise (+20 more)

### Community 56 - "import_controller.py"
Cohesion: 0.09
Nodes (28): enqueue_import(), on_import_error(), on_import_finished(), on_import_thread_finished(), Any, Path, Time-series import and pose routing.  One import worker owns the modal progress, Queue a source import so only one worker owns the import UI at a time. (+20 more)

### Community 57 - "TrackingLoader"
Cohesion: 0.10
Nodes (24): Loads DeepLabCut and LightningPose multi-index CSV files., TrackingLoader, Path, Tests for frame-indexed source contract and DLC fps resolution (D-019)., _frame_indexed_sources accumulates provisional entries when no video is loaded., TimeSeriesSource.is_frame_indexed() should default to False., _rebind_frame_indexed_sources should clear the provisional list., After rebind, re-enqueued import uses the video fps, not the provisional fps. (+16 more)

### Community 58 - "._set_sweep_for_time"
Cohesion: 0.08
Nodes (13): QResizeEvent, Coalesce resize storms before selecting a new pyramid resolution., Apply the once-per-load work after the last queued row exists., Finish any queued row building immediately.          For callers that need every, Remove all channels associated with a specific cache_dir (source)., Remove the row(s) identified by *channel*., Advance the fixed sweep from the master-clock time.          Called on every 60, Format the shared page label with the same mode as transport/readout. (+5 more)

### Community 59 - "format_time"
Cohesion: 0.12
Nodes (7): format_time(), Format *t_seconds* according to *mode*.      t_epoch is the Unix epoch of master, Tests for ui.time_format — format_time() all three modes., TestFormatTimeEdgeCases, TestFormatTimeLocalTOD, TestFormatTimeRelative, TestFormatTimeUTC

### Community 60 - "write_recording"
Cohesion: 0.14
Nodes (27): default_spec(), Path, Build a miniature Open Ephys binary recording for tests.  Small enough to write, One continuous stream to write into the fixture., A TTL line to write as rising/falling edge pairs., Everything one ``recordingN`` directory should contain., Return a two-stream recording with a TTL line, as most tests want it., Write *spec* under *root* and return the ``recording1`` directory. (+19 more)

### Community 61 - "test_pyav_reader.py"
Cohesion: 0.10
Nodes (28): long_gop_video(), MonkeyPatch, Path, TempPathFactory, Unit tests for the PyAV exact-frame reader.  Frame *identity* is proven in ``tes, The cache is a window on where the user just was, bounded by frames., Two float probes in one interval must be one entry, never two., ``t * fps`` arithmetic is wrong on VFR footage; the table is not. (+20 more)

### Community 62 - "test_workload_responsiveness.py"
Cohesion: 0.12
Nodes (28): _assert_no_stall_tail(), dense_source(), loaded_window(), _measure(), _measure_each(), _percentile(), Path, QApplication (+20 more)

### Community 63 - "test_ci_platform_config.py"
Cohesion: 0.07
Nodes (27): Regression checks for the shared cross-platform CI and release contract., An unpinned ffmpeg is both a CI flake and an unreproducible installer.      Choc, Ubuntu 24.04 must provide AppImageTool's libfuse.so.2 runtime ABI., A version tag must not release a side branch or detached commit., Pushing a branch must never publish, and neither must a non-version tag.      wo, No job may build or publish without the tag having been verified., PyPI and the GitHub release must not publish two different versions.      Nothin, A PEP 440 pre-release tag must be marked as one on the release page. (+19 more)

### Community 64 - "test_scrubbing.py"
Cohesion: 0.07
Nodes (27): player_with_mocks(), Tests for live scrubbing coalescing behaviour in Player., Return a Player wired to mock collaborators (no Qt event loop needed)., _on_tick dispatches the pending scrub target once seeker settles., _on_tick does NOT flush while seeker is still busy., A stalled decoder may drop frames but cannot stop plots or 3D., Exact seek on release clears any pending coalesced target., readout_panel.set_cursor is called on every seek, including non-exact. (+19 more)

### Community 65 - "DropScanWorker"
Cohesion: 0.10
Nodes (20): Return True if this source stores frame numbers instead of wall-clock time., DropScanWorker, Path, QObject, Lay out *path* with the session plugin that claims it, if any.          Returns, Scan dropped paths for importable sources off the UI thread., Collect paths and their best-guess loaders recursively, avoiding session files., apply_session_layout() (+12 more)

### Community 66 - "Player"
Cohesion: 0.12
Nodes (12): Return whether accepted per-frame evidence owns this mapping., Player, QObject, Stop UI ticks before the owning window tears down its panes., Start playback for programmatic callers such as the demo launcher., Use the first active exact mapping as the reference frame clock.          This i, Step to the neighbouring decoded frame across all video panes.          The step, Set or clear the A/B loop region on the master clock. (+4 more)

### Community 67 - ".can_open"
Cohesion: 0.11
Nodes (23): Path, Find the dataset root neo should be pointed at, or ``None``.          Open Ephys, Return whether *path* is a dataset rather than a session containing one., Return 1.0 for whitelisted ephys formats; 0.0 for everything else.          Dire, Path, Tests for the NeoLoader ephys data plugin., NeoLoader must never claim .csv files., NeoLoader must return 0.0 for plain text files. (+15 more)

### Community 68 - "session_controller.py"
Cohesion: 0.12
Nodes (25): autosave(), autosave_before_close(), on_session_load_error(), open_recent(), open_session(), Path, Session persistence, window geometry, autosave, and the recent-files menu.  Ever, Load all sources from a SessionState object. (+17 more)

### Community 69 - "PlotInteractionController"
Cohesion: 0.11
Nodes (15): PlotInteractionController, Any, QAction, Refresh overlays whose X coordinates depend on the current page., Handle a right-click only when it lands inside a visible channel row., Own page-local overlay state while delegating semantic actions to PlotPane., Register shared QActions for the plot context menu., Place measurement pin A and publish a complete A/B interval. (+7 more)

### Community 70 - "_parse_args"
Cohesion: 0.11
Nodes (25): _parse_args(), Namespace, Parse the supported AvialSync command-line arguments., The installed CLI exposes a real demo subcommand., test_demo_command_is_accepted(), Path, Tests for the installed ``avialsync open`` command., The documented `avialsync open <session>` invocation is supported. (+17 more)

### Community 71 - "test_core_coverage_edges.py"
Cohesion: 0.11
Nodes (25): channel(), _provenance(), Path, Edge paths in ``core/`` that no other test reached (P6.1, TESTING §1).  TESTING, Recovery is best-effort; failing to restore must not raise on a read path., Unequal arrays would silently mis-map frames on reload., A large mapping lives in a sidecar; a corrupt one must not load silently., `_helper.py` beside a plugin is support code, not a plugin. (+17 more)

### Community 72 - "sync_worker.py"
Cohesion: 0.10
Nodes (18): EventEvidenceSpec, EvidenceSpec, ndarray, QObject, Background TTL/event evidence extraction and alignment fitting., Native timestamp evidence, such as camera-frame trigger timestamps., Build an evidence-based proposal without blocking the UI thread., Extract raw evidence and emit one deterministic fit proposal. (+10 more)

### Community 73 - "main_window.py"
Cohesion: 0.09
Nodes (18): format_diagnostics(), probe_disk_speed(), probe_hwdec(), _pyav_version(), Diagnostics module for AvialSync.  Reports hardware decode capability and disk r, Return the installed PyAV version, for a copyable bug report., Format diagnostics dict as a copyable text block., Report which hardware decoders FFmpeg was built against.      Informational only (+10 more)

### Community 74 - "test_frame_identity.py"
Cohesion: 0.14
Nodes (23): FixtureRequest, Convert a decoded frame to a contiguous ``(H, W, 3)`` uint8 RGB array.      Cost, to_rgb_array(), cfr_video(), _probe_times(), ndarray, Path, TempPathFactory (+15 more)

### Community 75 - "prepare_release.py"
Cohesion: 0.16
Nodes (23): Pattern, dirty_paths(), ensure_preconditions(), main(), prepare_release(), Path, Prepare, validate, commit, tag, and push an AvialSync PyPI release.  Run from an, Update version authorities and optionally create and publish the release tag. (+15 more)

### Community 76 - "test_session_worker.py"
Cohesion: 0.17
Nodes (22): AnnotationExportWorker, Export annotation markers to CSV off the UI thread., Path, Session persistence and annotation export run off the UI thread.  Architecture r, The worker deep-copies at construction, so later edits cannot leak in., A one-million-pair mapping must not stall the Qt event loop.      The heartbeat, Handing the last write to a thread would race widget destruction., Drive one worker on a real QThread and wait for it to finish. (+14 more)

### Community 77 - "PlotHeader"
Cohesion: 0.10
Nodes (14): PlotHeader, QWidget, Compact shared controls for the time-series plot stack., Expose one live-style, page, Y-fit, row-height, and reset control strip., Show a persisted live style without emitting a duplicate state transition., QEvent, QWidget, Keep pyqtgraph's canvas aligned with an application palette change. (+6 more)

### Community 78 - "test_tracking_colors.py"
Cohesion: 0.09
Nodes (19): PointColorRegistry, Hand out one stable colour per body-part name, decided at load time., Assign a colour to every name not seen before, in sorted order.          Idempot, Return *name*'s colour, assigning one now if it was never registered.          P, Forget every assignment. For tests that need a known starting point., _fresh_registry(), The 2D overlay and the 3D view must agree on every body part's colour., Isolate each test from the module-level registry both views share. (+11 more)

### Community 79 - "test_theme_tooltips.py"
Cohesion: 0.08
Nodes (23): Theme tests for appearance-only changes on all supported appearances., Tooltips remain readable through palette roles, not a global stylesheet., Small/Medium/Large apply to existing controls, while System restores the base si, Collecting a cycle mid-snapshot frees widgets Qt has already handed over., Pausing collection around the snapshot must not outlive it., Rooting the snapshot in the window trees may not narrow what it covers., A custom OS accent must flow into links and interactive controls., A widget with no parent is a top-level window in Qt, so it is still covered. (+15 more)

### Community 80 - "ChannelKey"
Cohesion: 0.12
Nodes (15): ChannelKey, disambiguate(), Path, Master-clock presentation of a cached pyramid channel.  A :class:`~avialsync.cor, Stable identity of one channel: its source plus its name.      A channel name al, Return the display name, qualified by source only when it must be., Return display labels, qualifying only names owned by more than one source., The ``(source_id, channel_id)`` identity of this channel. (+7 more)

### Community 81 - "test_ui_sensor_mapping.py"
Cohesion: 0.13
Nodes (21): cache_dir(), Path, QApplication, Sensor offset/drift editing in the sidebar re-aligns plots without reimporting., Session restore holds the mapping until the async import finishes., set_mapping is display-only; it must not re-emit into the handler., Re-aligning must be a redraw, not a reimport — readers keep their identity., The cursor readout must report the sample now under the master cursor. (+13 more)

### Community 82 - "test_cli_demo.py"
Cohesion: 0.11
Nodes (21): AvialSync root module., Path, Tests for the installed ``avialsync demo`` command., The previous two-channel cache cannot silently downgrade the restored demo., The release smoke gate waits for this count, so it must be reachable.      It wa, First-run preparation is visible rather than appearing as a frozen window., The first run remains event-driven while FFmpeg creates every input., The demo applies known mappings and queues sensor/ephys/tracking sources. (+13 more)

### Community 83 - "test_aol_chunk_boundaries.py"
Cohesion: 0.17
Nodes (22): _collect(), ndarray, Path, AOL loaders honour the frozen ingest contract across batch boundaries (V-15, V-0, A 15-channel file must not read 45 columns to answer for one., Projection is an optimisation; it must not change a single sample., Shrink the batch size so a boundary is reachable in a small fixture., Frame 3 follows frame 9 across the boundary; that must not pass silently. (+14 more)

### Community 84 - "test_aol_pose_routing.py"
Cohesion: 0.15
Nodes (22): aol_session(), _finish_import(), Path, AOL pose routing: 2D overlays per camera, 3D to the 3D view, neither plotted.  2, _eks.csv' has an empty leading token; it must not match by empty substring., Complete one import through the routing path, without the worker/dialog.      Mi, 2D pose reaches only its own camera's overlay, and creates no plot rows., Write a DeepLabCut/LightningPose multi-index CSV. (+14 more)

### Community 85 - "make_fixtures.py"
Cohesion: 0.14
Nodes (21): Path, Regression guard: make_fixtures._clean_generated() must never delete permanent f, Running _clean_generated twice must not error (no dirs to remove second time)., session_v1.avv, session_v2.avv, session_v3.avv must be committed in tests/fixtur, _clean_generated() deletes generated subdirs but leaves .avv files intact., test_clean_generated_is_idempotent(), test_clean_generated_preserves_session_files(), test_permanent_fixtures_exist_in_repo() (+13 more)

### Community 86 - "test_subprocess_no_window.py"
Cohesion: 0.13
Nodes (20): Call, no_window_kwargs(), NoWindowKwargs, Process-level runtime helpers.  This module used to locate a media runtime — lib, Subprocess keyword arguments that suppress a console window.      A ``TypedDict`, Return subprocess kwargs that keep a child process from opening a console., _is_platform_guarded(), Path (+12 more)

### Community 87 - "demo.py"
Cohesion: 0.16
Nodes (21): CancelledCallback, RuntimeError, demo_data_dir(), _demo_frame_times(), ensure_demo_data(), _generate_video(), _has_header(), Path (+13 more)

### Community 88 - "extract_ttl_edges"
Cohesion: 0.10
Nodes (18): Edge, extract_ttl_edges(), One raw synchronization event in a source time domain., Extract raw TTL transitions from chronological signal chunks.      Args:, SyncEvent, Raw edges are evidence; unusable input must not become empty evidence., Anonymous evidence cannot be attributed in saved provenance., A contact bounce is one transition, not several. (+10 more)

### Community 89 - "Tracking3DCanvas"
Cohesion: 0.11
Nodes (11): QWheelEvent, QWidget, Custom-painted current-pose view with mouse orbit and wheel zoom., Number of complete XYZ points available to the view., Names of complete XYZ coordinate triplets., Index of the world axis currently rendered upward., Whether larger values on :attr:`up_axis` render downward., Set explicit skeleton edges between named points.          Each edge is a ``(nam (+3 more)

### Community 90 - ".paintEvent"
Cohesion: 0.13
Nodes (13): ndarray, QPainter, QPaintEvent, _qcolor(), Copy of the currently sampled XYZ positions, including NaN placeholders., Rotate world coordinates so the anatomical vertical is view +Z., Project world points to screen; the anatomical vertical maps to screen up., Project points already expressed in view space (see :meth:`_to_view`). (+5 more)

### Community 91 - "test_never_freeze.py"
Cohesion: 0.13
Nodes (19): QApplication, The UI must stay responsive, visible, and closeable under any workload.  This is, The regression: closeEvent called event.ignore() and trapped the user., Abandoning jobs must not skip the session write., A worker that ignores cancellation, like a blocked syscall., A wedged job must not hold shutdown open., The grace period is a total budget, not per job., test_a_quiet_job_is_reported_as_not_responding() (+11 more)

### Community 92 - "test_ui_layout_resize.py"
Cohesion: 0.13
Nodes (21): Path, QApplication, Window and pane resizing behaviour.  Three defects motivated these tests:  1. ``, A rigid minimum makes the window feel unresizable on a small screen., Dragging a handle must actually move it, not snap back.      Two things made ear, The regression: plots used to be handed zero pixels on launch., saveState stores the collapsible flag; restoring must not undo the policy., A layout saved before this policy could carry a zero pane; repair it.      The z (+13 more)

### Community 93 - "MasterClock"
Cohesion: 0.12
Nodes (11): MasterClock, Single master clock for AvialSync.      Time is driven externally via advance(mo, Register a callback that is fired on seek or playback advance., Set the absolute limits of the master timeline., Set playback rate, clamped between 0.01 and 10.0., Seek to a specific master time., Advance time based on monotonic deltas., test_inverted_bounds() (+3 more)

### Community 94 - ".eventFilter"
Cohesion: 0.11
Nodes (16): _editor_rejects_text(), _is_mid_edit(), QDragEnterEvent, QDropEvent, QEvent, QObject, QWidget, Return whether this key belongs to the playhead rather than the focus widget. (+8 more)

### Community 95 - "TimeDisplayMode"
Cohesion: 0.11
Nodes (20): QSlider, _fmt_relative(), Enum, Time display mode enum and single formatting authority (D-020).  All time-displa, Format signed elapsed time without wrapping negative values by a day., TimeDisplayMode, _ABPin, _AnnotationLane (+12 more)

### Community 96 - "Tracking3DPane"
Cohesion: 0.20
Nodes (19): Timeline-synchronized 3D tracking pane., Set explicit skeleton connectivity for the 3D view., Tracking3DPane, _anatomical_readers(), Path, Tests for the timeline-synchronized 3D tracking pane., The 3D view must orient anatomy head-up, not use a fixed Z-up axis.      The ref, An explicit choice pins the orientation against later auto-detection. (+11 more)

### Community 97 - "cfr_times"
Cohesion: 0.12
Nodes (20): MonkeyPatch, Path, CFR timestamps must not receive the VFR integrity warning., Variable presentation intervals win over a container's nominal CFR declaration., A second open mmaps the validated frame index instead of rebuilding it.      Bui, B-frame packet order must not decide VFR detection or frame stepping.      Again, Two tables over one file would be two authorities on which frame is which., VFR detection is based on timestamps, not a misleading average FPS. (+12 more)

### Community 98 - "test_ui_dialogs.py"
Cohesion: 0.20
Nodes (20): csv_file(), Path, QApplication, Coverage for the four import/inspection dialogs (P6.1).  `import_wizard`, `relin, Browsing is the only way a path gets resolved, so drive that., Skipping a file must open the session without it, not invent a path., Configs are per-file; one file's settings must not leak onto another., A column literally called "timestamp" must not need manual selection. (+12 more)

### Community 99 - "annotations.py"
Cohesion: 0.14
Nodes (17): PlotItem, Annotation markers: point and range, with list panel and CSV export., Stateful interaction controller for plot measurements, markers, and menus., ContextChoice, Any, InfiniteLine, QAction, Overlay drawing and context-menu helpers for pyramid-backed plot rows. (+9 more)

### Community 100 - ".load"
Cohesion: 0.15
Nodes (18): Read a .avv session file and validate any exact-map sidecars., Path, Tests for SessionState serialisation and schema migrations., A v3 session must survive a save/load cycle with video_frames intact., Version 99 must raise ValueError., An empty session should save and load without error., A v1 .avv file must load correctly after the v2-v5 schema changes., Loading a v1 session then saving it should produce a valid v5 file. (+10 more)

### Community 101 - "test_channel_identity.py"
Cohesion: 0.12
Nodes (19): Path, QApplication, Two sources may share a channel name without controlling each other.  P3.5 P1 id, An unqualified name is ambiguous; that must be reported, not guessed., The two sources hold opposite-signed data; neither may shadow the other., Two independent caches that both contain a channel called force_z., test_a_bare_name_matches_every_owner_and_says_so(), test_both_sources_get_their_own_row() (+11 more)

### Community 102 - "test_ui_follow.py"
Cohesion: 0.11
Nodes (5): Path, Tests for fixed-window oscilloscope plotting., A narrow spike remains visible instead of being averaged into a midpoint., sweep_pane(), test_decimated_plot_preserves_minimum_and_maximum_envelope()

### Community 103 - "write_video"
Cohesion: 0.14
Nodes (18): encode_frame_index(), ndarray, Frame strip encoder and decoder for robust video sync testing.  We encode a 32-b, Encode a 32-bit integer into the top-left pixels of the given frame (in-place)., Test that we can perfectly round-trip integers through the encoder/decoder., Generate a tiny video, extract frames with ffmpeg, decode, assert indices., test_framestrip_in_memory(), test_framestrip_via_ffmpeg() (+10 more)

### Community 104 - "transcode.py"
Cohesion: 0.15
Nodes (18): CancelCheck, InputContainer, _duration_seconds(), encode_proxy(), encode_video(), _even(), Fraction, ndarray (+10 more)

### Community 105 - "test_packaging_smoke.py"
Cohesion: 0.19
Nodes (18): CaptureFixture, _load_smoke_module(), ModuleType, MonkeyPatch, Path, Regression tests for built-bundle startup verification., Freezing a bundle is release-tag work, and it must be gated on startup., CI proves correctness on every push; only a tag builds and ships.      Bundling (+10 more)

### Community 106 - "test_ui_shortcut_reach.py"
Cohesion: 0.15
Nodes (18): KeyboardModifier, _fires(), _focusable(), Key, QWidget, Every transport shortcut must reach the playhead from anywhere in the window.  T, No widget in the window may swallow a playhead key.      Generated over every fo, A numeric field discards letters, so it must not eat the shuttle keys.      Rest (+10 more)

### Community 107 - "test_diagnostics.py"
Cohesion: 0.11
Nodes (16): Startup diagnostics lifecycle tests., A failed capability query must stay observable rather than raise., A bug report has to say what decoded the video, not what is installed., Concurrent app instances must not contend for one fixed probe filename., Repeated windows share one diagnostics probe instead of spawning threads., Informational only — software decode already meets every budget (D-075).      Py, test_diagnostics_report_names_the_decoder_actually_in_use(), test_disk_probe_uses_unique_file_and_cleans_it() (+8 more)

### Community 108 - "TimelineEvidence"
Cohesion: 0.18
Nodes (6): QWidget, Titled, collapsible Data Streams shell for named TimelineOverview lanes., The currently displayed status message, without its label prefix., Show active work beside Reset Zoom and clear non-active messages shortly after., Detach Data Streams so the main workspace splitter can own its height., TimelineEvidence

### Community 109 - "._on_evidence_changed"
Cohesion: 0.12
Nodes (12): _normalise_events(), ndarray, Register one source coverage span, keyed for later replacement., Display accepted sync matches with inspectable provenance text., Display imported data gaps as red ticks., Display point/range annotations in their stored colors., Refresh labels and ensure populated lanes have usable vertical space., Show one video or data coverage span in the overview strip. (+4 more)

### Community 110 - "Path"
Cohesion: 0.12
Nodes (10): Any, Path, Return 0..1 confidence that *path* is a session this can lay out.          Calle, Return the session's contents and the settings that span them.          ``regist, Return a confidence in ``[0.0, 1.0]`` without expensive I/O., Read metadata required for :meth:`channels` and :meth:`read_chunks`.          ``, Return 0..1 confidence that this loader can open the file., Probe source metadata; this method may perform blocking I/O. (+2 more)

### Community 111 - "DemoLaunch"
Cohesion: 0.13
Nodes (12): DemoLaunch, Display a worker status event., Coordinate visible demo preparation with a worker thread., Show progress UI and start generation., Request cancellation without touching the worker from the UI thread., Surface the failed command's diagnostic text to the user., main(), load_saved_font_size() (+4 more)

### Community 112 - "test_demo_data.py"
Cohesion: 0.15
Nodes (15): Path, Path, Regression tests for generated, user-facing demo inputs., The demo tracking file must match the loader's three-row DLC contract., The compatibility script cannot drift from ``avialsync demo`` again., test_generated_pose_csv_is_importable_dlc_data(), test_tools_launcher_delegates_to_installed_application(), _is_dlc_pose_csv() (+7 more)

### Community 113 - "_FakePane"
Cohesion: 0.14
Nodes (14): _FakePane, Path, QWidget, Removing a video persists the session before the media client is torn down.  Tea, Removal must not invent a session file for someone who never saved one., A real widget the grid's layout accepts, minus libmpv.      A plain object canno, The signal is useless if it arrives after the teardown it guards., A snapshot taken here must describe the session without this video. (+6 more)

### Community 114 - "test_sync_golden.py"
Cohesion: 0.15
Nodes (17): app_with_main_window(), _capture_frame(), _fixture_frame_time(), ndarray, QApplication, Golden sync testing for video playback., Test multi-camera golden sync with offsets., Return a timestamp inside the known decoded interval for a fixture frame.      F (+9 more)

### Community 115 - "AvialSync Plot UX Refinement Plan"
Cohesion: 0.12
Nodes (16): 10. Focus and keyboard contract, 11. Performance invariants, 12. Persistence and migration, 13. Implementation slices, 14. Required test evidence, 15. Definition of done, 1. Objective, 2. Compatibility ledger — nothing in this list may be lost (+8 more)

### Community 116 - "UiHeartbeat"
Cohesion: 0.12
Nodes (9): QObject, Detect and report stalls of the UI thread itself.  Background work being off-thr, Measure UI-thread responsiveness and report stalls., The largest stall seen so far, for diagnostics., UiHeartbeat, Blocking the loop must be surfaced, not merely felt as lag., test_heartbeat_reports_a_blocked_ui_thread(), test_heartbeat_reset_clears_history() (+1 more)

### Community 117 - "TESTING.md"
Cohesion: 0.12
Nodes (15): 1. Test layers, 2. Fixtures — `tools/make_fixtures.py` (ground truth for everything), 3. Golden sync tests (`tests/test_sync_golden.py`), 3a. TTL/event synchronization golden tests (D-026), 4. Performance benchmarks (`tests/benchmarks/`), 5. GUI test conventions, 5a. Plot UX refinement gates (P4.6 / D-044), 6. Manual smoke checklist (human, end of each phase, on YOUR real field data) (+7 more)

### Community 118 - "test_core_timeline.py"
Cohesion: 0.12
Nodes (16): ndarray, Drift of 2ppm over 1h maps within float64 precision of closed form value., An accepted fit replaces the mapping instead of preserving a stale live anchor., test_advance_while_paused(), test_affine_edit_explicitly_replaces_exact_mapping(), test_drift_closed_form(), test_exact_mapping_reports_local_rate_scale(), test_exact_mapping_snaps_to_nearest_master_frame_trigger() (+8 more)

### Community 119 - "ARCHITECTURE.md"
Cohesion: 0.12
Nodes (14): 1. Repository layout (complete — the authoritative map of what lives where), 2. Runtime dataflow, 2a. Synchronization dataflow (D-026), 2b. Timeline Evidence overview (D-027), 3. Threading model, 4. Plugin contract (frozen at Phase 5 as API v1), 5. Session file (.avv, JSON, schema_version field), 5b. Cache invalidation key (updates D-004) (+6 more)

### Community 120 - "Plugin guide"
Cohesion: 0.12
Nodes (13): Formats, Lab formats, Sensor and tracking data, Video, Claiming a whole recording folder, Naming your format, Optional: single-pass bulk ingest, Plugin guide (+5 more)

### Community 121 - "ToyBinarySource"
Cohesion: 0.13
Nodes (10): Any, ndarray, Path, A minimal external AvialSync Plugin API v1 implementation., Read ``.toybin`` records encoded as little-endian ``(time, value)`` pairs., Recognise the example file extension without opening the input., Store the path after validating whole-record alignment., Expose the single dimensionless signal channel. (+2 more)

### Community 122 - "theme.py"
Cohesion: 0.22
Nodes (15): QPalette, _accent(), _apply(), _is_dark_palette(), _palette_with_surfaces(), QColor, Native-aware dark, light, and system appearance for AvialSync.  System appearanc, Read the platform's selected/accent colour with a safe fallback. (+7 more)

### Community 123 - "ProxyWorker"
Cohesion: 0.17
Nodes (12): needs_proxy(), proxy_path_for(), ProxyWorker, Path, QObject, Proxy generation — re-encode videos to all-keyframe scrub-friendly proxies., Return the sidecar proxy path for a given video., Check if a proxy already exists and is newer than the source. (+4 more)

### Community 124 - "QApplication"
Cohesion: 0.20
Nodes (16): apply_font_size(), _apply_font_to_existing_widgets(), _capture_widget_base_fonts(), _collection_paused(), _live_widgets(), QApplication, QFont, Record live widget fonts before Qt propagates a new application font. (+8 more)

### Community 125 - "tracking_3d_pane.py"
Cohesion: 0.17
Nodes (15): _build_sources(), _coordinate_name(), detect_up_axis(), _mean_axis_position(), _nearest_index(), _PointChannels, Interactive 3D view for cached tracking-coordinate channels., Group complete XYZ triplets by source cache and pre-warm their mmap arrays. (+7 more)

### Community 126 - "DecodeWorker"
Cohesion: 0.14
Nodes (9): DecodeWorker, QObject, Decode the newest requested time, if one is still outstanding., Close the reader on its own thread, where it was opened., Open a video file on this pane's decode thread., Stop the decode thread and close its reader.          Ownership is explicit, as, Stop decoding before closing the widget.          Returns whatever ``QWidget.clo, Owns one :class:`PyAVReader` on a decode thread.      Requests coalesce: only th (+1 more)

### Community 127 - "test_ui_plot_sliced_refresh.py"
Cohesion: 0.13
Nodes (15): channel_cache(), pane(), Path, A span change requeries every row without holding the UI thread (D-063).  The be, Built once: 128 pyramids are slow enough to matter per test., The callback must hand work back to the event loop, not finish it all., Deferring must not mean dropping., A drag emits several spans; rows must settle on the newest, not a mix. (+7 more)

### Community 128 - "TestShowDelta"
Cohesion: 0.12
Nodes (4): panel(), Tests for ReadoutPanel.show_delta and set_camera_states., TestSetCameraStates, TestShowDelta

### Community 129 - "generate_session_screenshot.py"
Cohesion: 0.19
Nodes (15): capture(), _load_session(), main(), Image, Path, QImage, quantize_to_shared_palette(), Capture a short looping animation of a real session folder opened through its pl (+7 more)

### Community 130 - "create_channel_plot"
Cohesion: 0.13
Nodes (11): GraphicsLayoutWidget, Build queued rows in time slices, letting the event loop run between them., create_channel_plot(), Path, Create one row without deciding shared X-axis ownership.      The row always rea, Any, Curve whose already-decimated data may be revealed by a moving sweep edge., Move the paint clip without rebuilding or re-querying curve data. (+3 more)

### Community 131 - "QLabel"
Cohesion: 0.28
Nodes (8): QLabel, _CameraRow, QWidget, Show this camera's frame number and media time.          Deliberately not called, Preserve a fixed-width family while inheriting the application font size., Update per-camera frame display.  states = [(label, time_pos, fps), ...], Shows frame number and media timestamp for one camera., _set_monospace()

### Community 132 - "job_manager.py"
Cohesion: 0.17
Nodes (11): BackgroundWorker, _drop_finished_threads(), JobState, Enum, Protocol, QThread, One owner for every background job, so the UI can never be trapped.  Three prope, Release retained jobs whose threads have stopped.      Never call this from a th (+3 more)

### Community 133 - "test_bench_plot_pane.py"
Cohesion: 0.23
Nodes (14): _channel_cache(), _populated_pane(), Path, Performance guards for the populated plot pane (BLUEPRINT.md budgets).  P4.6's e, A drag resizes continuously; no single callback may pass the ceiling.      128 c, One slice of row construction must not freeze the window.      Rows are built in, Build a field-shaped multi-channel pyramid cache.      Sample depth is kept mode, Return a pane with *count* rows fully built, not queued. (+6 more)

### Community 134 - "test_transport_resize.py"
Cohesion: 0.18
Nodes (14): _expected_pin_x(), Regression tests: transport A/B pins must realign after window resize., Pin remains correctly positioned across consecutive resizes., Return the correct x for a pin at *frac* given the slider's current geometry., A/B in-pin must sit at the correct groove fraction after a resize., A/B out-pin realigns after resize (non-midpoint fraction)., Both A/B pins realign independently after a single resize., No pins are shown after resize if none were set. (+6 more)

### Community 135 - "Contributor Covenant Code of Conduct"
Cohesion: 0.14
Nodes (13): 1. Correction, 2. Warning, 3. Temporary Ban, 4. Permanent Ban, Attribution, Contributor Covenant Code of Conduct, Enforcement, Enforcement Guidelines (+5 more)

### Community 136 - "2026-07 · D-020 · Inspection layer — what is surfaced where"
Cohesion: 0.14
Nodes (14): 2026-07 · D-020 · Inspection layer — what is surfaced where, Copy as text, Delta measurement: distinct measure points on PlotPane, Demo data extensions, Gap markers on plot, Import Report access, ImportWorker.finished signal change, Integrity badge (+6 more)

### Community 137 - "Data handling"
Cohesion: 0.14
Nodes (12): Data handling, Gaps and missing values, Identity and export correctness, Required ground-truth workloads, Sessions and provenance, Source files and caches, Time and precision, Audit status (2026-07-29) (+4 more)

### Community 138 - "test_engine_layering.py"
Cohesion: 0.18
Nodes (12): Module, stmt, _is_type_checking_guard(), The engine layer must not depend on the UI layer (V-13, ARCHITECTURE §1).  `engi, Whether an `if` statement is the `if TYPE_CHECKING:` guard., Return ``(module_scope_linenos, deferred_linenos)`` for `avialsync.ui` imports., Guard the guard: if the scan matched nothing the test above is vacuous., `player` read `transport._bounds`; Transport now publishes `bounds`. (+4 more)

### Community 139 - "AnnotationPanel"
Cohesion: 0.18
Nodes (8): QTableWidgetItem, AnnotationPanel, Path, QGroupBox, Write one row per (marker, video) — format for DLC/LightningPose retraining., Widget that lists annotations and provides add/delete/export controls., Rebuild the table from the store., Remove a marker by index.

### Community 140 - "JobManager"
Cohesion: 0.16
Nodes (7): JobManager, QObject, Owns every background worker/thread pair and reports their state., Every job currently owned, newest last., A one-line summary for the transport status area., Refresh the watchdog clock for whichever job reported., Drop finished threads without relying on sender() identity (D-051).

### Community 141 - "ReadoutPanel"
Cohesion: 0.18
Nodes (7): QGroupBox, Live channel value readout at the current playhead position.      Call `update_s, Interpolate and display each channel's value at time *t*., Display A/B-region statistics computed by a background worker., Shows min/max/mean/rms for one channel in a region., ReadoutPanel, _StatsRow

### Community 142 - "test_conda_recipe.py"
Cohesion: 0.24
Nodes (13): _project_metadata(), The conda-forge recipe must describe the package this repository builds., A recipe pinned to a stale version publishes the wrong source archive., A missing run dependency is an import error on a user's first launch., The conda package is now the same shape as the wheel (D-075).      Decoding, pro, conda must not offer the package on a Python the project excludes., The console script conda installs must be the one the package defines., _recipe_text() (+5 more)

### Community 143 - "_BulkLoader"
Cohesion: 0.20
Nodes (8): _BulkLoader, Path, Tests for the asynchronous time-series import pipeline., One-pass test loader whose legacy per-channel API must never be used., Bounds come from parsed data, so Windows can atomically rename the cache., test_import_cache_key_includes_accepted_loader_configuration(), test_import_worker_commits_cache_without_reopening_mmap(), test_import_worker_uses_one_bulk_parse_then_reuses_valid_cache()

### Community 144 - "ImportReportDialog"
Cohesion: 0.18
Nodes (9): ImportReportDialog, QDialog, QWidget, Scrollable plain-text view of an ImportReport with a Copy button., Show the full ImportReport dialog for a data source., A v1 session carries no ImportReport; the dialog must still open., test_import_report_copy_puts_the_same_text_on_the_clipboard(), test_import_report_handles_a_source_with_no_report() (+1 more)

### Community 145 - ".__init__"
Cohesion: 0.19
Nodes (11): _guess_format(), _guess_time_column(), Path, QWidget, Timestamp import wizard with preview, format autodetect, and timezone handling., Return the index of the most likely timestamp column., Heuristic: guess the timestamp format from sample values., Guess the CSV separator from a few lines. (+3 more)

### Community 146 - "ImportWizard"
Cohesion: 0.17
Nodes (6): ImportWizard, Any, QDialog, Dialog for configuring CSV/time-series import parameters.      Previews the file, Select the matching format in the combo, or fall back to auto., Return the import configuration dict for the pipeline.

### Community 147 - "RelinkDialog"
Cohesion: 0.17
Nodes (9): QDialog, Missing-file relink dialog shown when session files cannot be found., Return {original_path: new_path} for files the user relocated., Lets the user relocate missing files referenced by a session.      Shows a table, RelinkDialog, Callers must not be able to mutate the dialog's state through the result., test_relink_cancelled_browse_resolves_nothing(), test_relink_mapping_is_a_copy() (+1 more)

### Community 148 - "TestMeasureMarkers"
Cohesion: 0.15
Nodes (3): plot_pane(), Tests for PlotPane measure markers and measure_changed signal., TestMeasureMarkers

### Community 149 - "generate_icons.py"
Cohesion: 0.21
Nodes (12): generate(), main(), parse_args(), Image, Namespace, Path, Generate AvialSync's platform icon assets from its canonical raster source., Return a high-quality square icon without stretching or cropping artwork. (+4 more)

### Community 150 - "AvialSync — Model Handout"
Cohesion: 0.17
Nodes (11): Architecture Rules (violations = rejected PR), AvialSync — Model Handout, File, Marking, Module Map, Naming (binding), Playback, Run Commands (+3 more)

### Community 151 - "MIGRATION_PYAV.md — libmpv → PyAV, and a pip-only install"
Cohesion: 0.17
Nodes (11): 1. Goal, in one sentence, 2. Why — the measured case, 3. The invariant that outranks everything, 4. Steps — update the status column as you go, 5. Licensing — settled, 6. Rollback, 7. Environment notes for whoever picks this up, MIGRATION_PYAV.md — libmpv → PyAV, and a pip-only install (+3 more)

### Community 152 - "QSettings"
Cohesion: 0.18
Nodes (9): QSettings, restore_geometry(), save_geometry(), current_font_preference(), current_preference(), is_dark(), Return the persisted preference, normalized for legacy settings., Return the persisted font-size preference. (+1 more)

### Community 153 - "build_gap_mask"
Cohesion: 0.17
Nodes (10): build_gap_mask(), Return a boolean mask where True indicates a gap larger than 10x median dt., Verify subsampled gap_mask (stride 10k) detects correctly on clustered gaps (D-0, test_build_gap_mask(), test_pathological_gap_mask(), test_pyramid_gap_mask(), Repeated timestamps give a zero median interval, not a gap threshold.          A, One sample yields no adjacent pair at all. (+2 more)

### Community 154 - "DemoData"
Cohesion: 0.21
Nodes (9): DemoData, DemoWindow, load_demo(), Any, Protocol, The source-loading surface the demo needs from the main window., Load the complete synchronized demo through normal asynchronous paths., Paths comprising the installed inspection demo. (+1 more)

### Community 155 - "SessionSaveWorker"
Cohesion: 0.21
Nodes (7): Path, QObject, Background workers for session persistence.  Architecture rule 3: the UI thread, Serialize and write .avv + sidecars off the UI thread., Read and parse .avv + sidecars off the UI thread.      Only parsing moves here., SessionLoadWorker, SessionSaveWorker

### Community 156 - "Job"
Cohesion: 0.18
Nodes (6): Job, One unit of background work, owned for its whole lifetime., Whether the worker offers a cooperative cancel., Jobs that have gone quiet for longer than the watchdog allows., Ask every cancellable job to stop; never blocks., Stop everything and return the labels that had to be abandoned.          Always

### Community 157 - ".reset_view"
Cohesion: 0.17
Nodes (6): QMouseEvent, Restore the default orbit and fit the current pose., Begin orbiting on a primary-button drag., Orbit around the stable scene bounds., Finish an orbit gesture., Fit the current pose on double click.

### Community 158 - "test_bench_cursor_path"
Cohesion: 0.21
Nodes (11): large_dataset(), Path, Pyramid and cursor-path benchmarks with local engineering budget gates.  Budget-, A committed shared-window change stays below the 30 ms UI budget., Generate 180M samples once per session to save time and memory., Pyramid build for 180M samples must complete within the ★ budget., Full per-tick cursor path: plot set_cursor + transport set_time + readout     se, test_bench_cursor_path() (+3 more)

### Community 159 - "TestPluginDiscovery"
Cohesion: 0.21
Nodes (7): LogCaptureFixture, Path, A leading underscore marks a helper, not a plugin to import., A third-party plugin must never take the application down with it., Users are told to create ~/.avialsync/plugins; most never do., Silent failure made a broken plugin vanish with no way to tell why., TestPluginDiscovery

### Community 160 - "test_headless_core.py"
Cohesion: 0.20
Nodes (10): _production_trees(), Headless core guard test., Architecture rule 2 applies per module, not only to the package __init__.      I, Catch the violation even when a lazy import hides it at runtime., Unexpected failures must be reported, not converted into blank UI state., Guard the UI-thread and cross-platform subprocess architecture rules., test_every_core_module_imports_without_pyside6(), test_no_core_module_imports_pyside6_statically() (+2 more)

### Community 162 - "test_job_thread_lifetime.py"
Cohesion: 0.31
Nodes (10): CompletedProcess, _assert_no_abort(), A running QThread must outlive whatever started it.  Qt aborts the process outri, A job that ends normally must not accumulate in the module registry., The crash: a manager discarded without shutdown, while a job still runs., The documented path still works: shutdown abandons, drain reclaims., _run(), test_a_finished_job_leaves_nothing_retained() (+2 more)

### Community 163 - "PROMPTS.md — kickoff prompts per phase"
Cohesion: 0.18
Nodes (10): Debugging prompt template (any phase), Phase 0 prompts, Phase 1 prompts, Phase 2 prompts, Phase 3 prompts, Phase 4 prompts (one per feature, same pattern), Phase 5 prompts, Phase 6 prompts (+2 more)

### Community 164 - "DemoProgressDialog"
Cohesion: 0.20
Nodes (8): DemoGenerationWorker, DemoProgressDialog, QDialog, QObject, QWidget, Show demo generation progress and an inspectable activity log., Generate or reuse demo inputs outside the UI thread., Generate inputs and report the resulting paths.

### Community 165 - ".load_channels"
Cohesion: 0.20
Nodes (6): Path, Load multiple data sources from cache and build plot rows.          Every row of, Re-align one time-series source against the master clock.          The rows keep, Return the ``(offset, drift_ppm)`` currently applied to a source., Return one source's master-time coverage across all of its channels., Backwards compatibility for Phase 2 single-channel load.

### Community 166 - "_ArrayReader"
Cohesion: 0.22
Nodes (7): _ArrayReader, ndarray, Path, Performance guard for the 3D tracking cursor hot path., Minimal mmap-reader equivalent for isolating per-tick sampling cost., Sampling 128 XYZ points must leave room in the existing cursor budget., test_bench_tracking_3d_cursor()

### Community 167 - "test_core_cache.py"
Cohesion: 0.27
Nodes (10): Path, Neither tier may fail silently, and no mixed sidecar may survive.      ``_commit, A cache written by an older loader_version is stale post-change (D-023)., A held directory handle must not fail the commit.      On Windows a sync client,, test_atomic_commit(), test_cache_commit_falls_back_to_an_in_place_swap_when_the_directory_rename_fails(), test_cache_commit_raises_when_both_the_rename_and_the_in_place_swap_fail(), test_cache_manager_keys() (+2 more)

### Community 168 - "2026-07 · D-022 · Interaction standard — visible surface, depth in menus, shortcuts as accelerators"
Cohesion: 0.20
Nodes (10): 1. Single authority — one QAction (or one transport signal) per action, 2026-07 · D-022 · Interaction standard — visible surface, depth in menus, shortcuts as accelerators, 2. StandardKey over hardcoded strings wherever a platform standard exists, 3. macOS menuRoles required, 4. J/K/L shuttle semantics, 5. A/B button active state, 6. Shortcuts dialog rendering, 7. Open Video → Ctrl+Shift+V, Open Data → Ctrl+Shift+D (+2 more)

### Community 169 - ".fit_current_pose"
Cohesion: 0.20
Nodes (5): Fit the camera to the valid points at the current master time., Use complete XYZ channel triplets from the active cached readers., Reflect the canvas's current orientation without re-triggering it., Pin an explicit vertical axis chosen by the user., Pin which source axis renders upward (see :meth:`Tracking3DCanvas.set_up_axis`).

### Community 170 - "test_prepare_release.py"
Cohesion: 0.29
Nodes (9): Path, Unit coverage for the local release-preparation helper., The helper accepts normal final and prerelease version forms., Tags and PyPI metadata must use a single canonical version spelling., Version authority updates cannot silently replace unrelated quoted text., _release_tool(), test_replace_declared_version_updates_only_the_expected_declaration(), test_validate_version_accepts_canonical_public_versions() (+1 more)

### Community 171 - "Phase Status"
Cohesion: 0.22
Nodes (9): Cross-platform pressure audit (D-040), Done — Inspection Layer (A–K, D-020), Done (Phase 4), Done (Phase 4 UX / loader fixes), Fixed (this PR — Phase 4 stabilization), Implemented — TTL/event synchronization baseline (D-026), mypy is clean — keep it that way (V-07), Pending (+1 more)

### Community 172 - ".exact_time_mapping"
Cohesion: 0.22
Nodes (6): ndarray, Yield one-dimensional ``float64`` time/value chunks for *ch*.          Chunks, i, Per-frame timestamps if the container has them., Return per-frame ``(master_time, source_time)`` evidence, or ``None``., The hook is additive: a frozen v1 video plugin must be unaffected by it., test_video_source_default_declares_no_exact_mapping()

### Community 173 - ".test_both_paths_failing_reports_both_causes"
Cohesion: 0.22
Nodes (6): LogCaptureFixture, MonkeyPatch, Windows sync clients hold directory handles; the commit must survive.          R, A cache that cannot be committed must say why, not fail silently., The worst commit case must still leave a valid cache.      The old sidecar has b, test_a_failed_backup_restore_still_falls_back_to_the_swap()

### Community 174 - "generate_screenshots"
Cohesion: 0.25
Nodes (6): generate_screenshots(), main(), Path, Capture the synchronization walkthrough used in the README.  Run with ``conda ru, generate_screenshots(), on_finished()

### Community 175 - "no_startup_diagnostics"
Cohesion: 0.25
Nodes (7): Config, no_startup_diagnostics(), MonkeyPatch, pytest_configure(), Pytest configuration., Re-arm faulthandler without its all-threads walk on Windows.      pytest enables, Keep the startup diagnostics off the suite's background threads.      ``MainWind

### Community 176 - "Performance Budgets (engineering-certified where ★)"
Cohesion: 0.25
Nodes (8): 29. A built-in loader's dependencies can fail, and that must not be fatal, 30. The Windows `0xC0000005` was inside faulthandler — trigger removed with libmpv, 31. Connect a job's result signals in `configure`, never after `_run_job` returns, 8f. The pyramid query must fill the point budget, not merely fit under it, 8g. Shutdown steps are isolated and ordered; never let one raise skip the rest, 8h. Text editors steal the playhead keys unless they are explicitly reserved, 8i. Never build all plot rows in one call, Performance Budgets (engineering-certified where ★)

### Community 177 - "smoke_bundle"
Cohesion: 0.36
Nodes (7): bundle_executable(), main(), Path, Launch a built AvialSync bundle headlessly and require a clean shutdown., Return the platform executable in a PyInstaller one-directory bundle., Require the bundled Qt application to construct and close successfully.      ``q, smoke_bundle()

### Community 178 - "AvialSync"
Cohesion: 0.25
Nodes (7): AvialSync, Contributing, Documentation, First session, Install, Licence, What it gives you

### Community 179 - "fit_exact_index_mapping"
Cohesion: 0.36
Nodes (7): fit_exact_index_mapping(), Create a deterministic exact index mapping, overriding affine limits.      Frame, Ground-truth tests for exact index synchronization., test_exact_index_mapping_bounds_display_evidence_but_keeps_full_mapping(), test_exact_index_mapping_preserves_raw_pairs_and_nonlinear_timestamps(), test_exact_index_offset_records_unmatched_reference_evidence(), test_exact_index_rejects_dense_samples_mistaken_for_frame_triggers()

### Community 180 - "._apply_default_splitter_sizes"
Cohesion: 0.25
Nodes (4): QSplitter, Forbid collapsing a pane to nothing.          Must be re-applied after ``restore, Re-seed any splitter a previously-saved state left with a zero pane.          A, Seed the first-run pane layout, as sizes now and as shares thereafter.

### Community 181 - "apply_theme"
Cohesion: 0.25
Nodes (6): QAction, Apply the selected system-relative application font scale., apply_theme(), _install_system_appearance_listener(), Follow platform palette changes while the System preference is active., Apply and persist System, Dark, or Light appearance.      System follows Qt's pl

### Community 182 - ".set_readers"
Cohesion: 0.29
Nodes (5): Choose which world axis renders upward, and its direction.          Setting this, Select complete XYZ triplets and retain only their mmap-backed arrays., Build a right-handed basis whose third row is the chosen 'up' direction.      Ro, Update from the same master-clock value used by video and 2D plots., _view_matrix()

### Community 183 - "_QuickWorker"
Cohesion: 0.25
Nodes (7): QObject, _QuickWorker, A job that starts reporting again must stop being flagged., A QObject moved to a QThread with no Python reference never starts., test_a_registered_worker_actually_runs(), test_finished_jobs_are_dropped_from_the_registry(), test_progress_clears_a_not_responding_state()

### Community 184 - "test_ui_plot_row_geometry.py"
Cohesion: 0.39
Nodes (7): _pane_with_channels(), Path, Plot rows must occupy the pane, not collapse to their minimum width.  Rows are b, Every row's plot area must span the pane, whatever the size or row count., A second load must not leave the newest row collapsed beside settled ones., test_a_row_added_after_the_first_load_also_fills_the_pane(), test_rows_fill_the_pane_width()

### Community 185 - "Architecture"
Cohesion: 0.29
Nodes (6): Architecture, Loading and viewing a source, Main parts, Master timeline, Session and extension boundaries, Synchronization design

### Community 186 - "Signal Wiring Map"
Cohesion: 0.29
Nodes (7): Import pipeline (updated, D-020), PlotPane / Player → downstream, Sidebar → MainWindow → subsystems, Signal Wiring Map, Source properties + integrity (D-020), Time display mode (D-020), Transport → Player → subsystems

### Community 187 - "Licensing"
Cohesion: 0.33
Nodes (5): Bundled components, Contributing, Licensing, Plugins are your own work, What you can do

### Community 188 - "Tutorial: align recordings"
Cohesion: 0.33
Nodes (5): Check the result, Choose a reference, Start simple, Tutorial: align recordings, Use TTL or event evidence

### Community 189 - "User Guide"
Cohesion: 0.33
Nodes (5): 3D tracking controls, Appearance and font size, Main areas of the window, Useful controls, User Guide

### Community 190 - "release"
Cohesion: 0.33
Nodes (5): Event, drain_abandoned(), Wait for retained threads to finish. For tests and orderly interpreter exit., Unblock and drain every wedged worker before the test process moves on.      Aba, release()

### Community 191 - "build_bundle"
Cohesion: 0.40
Nodes (5): build_bundle(), main(), Path, Build a one-directory AvialSync bundle for the current platform., Run PyInstaller with only staged, local media libraries included.

### Community 192 - "default_display_name"
Cohesion: 0.33
Nodes (5): default_display_name(), Return the human-readable name for this format., Derive a readable format name from a class name.      ``AOLEksLoader`` becomes ", The fallback names any plugin that does not override, so it must read well., test_derived_names_break_acronyms_correctly()

### Community 193 - "test_a_type_names_the_data_never_the_rig"
Cohesion: 0.33
Nodes (3): Kinds of data an acquisition recording carries besides the ephys.          One r, One reader serves many kinds, so the type must not be the reader's name.      Ev, test_a_type_names_the_data_never_the_rig()

### Community 194 - "test_packaging_spec.py"
Cohesion: 0.33
Nodes (5): Regression checks for the PyInstaller specification., The bundle carries no separately-staged media runtime (D-075).      PyInstaller, SPECPATH is the packaging directory, not the spec-file path., test_spec_resolves_the_project_root_from_packaging_directory(), test_spec_stages_no_media_of_its_own()

### Community 195 - "2026-07 · D-032 · Headless CI uses null video, decoded-frame evidence, and explicit mpv ownership — AMENDED by D-075"
Cohesion: 0.40
Nodes (5): 2026-07 · D-032 · Headless CI uses null video, decoded-frame evidence, and explicit mpv ownership — AMENDED by D-075, Consequences, Context, Decision, macOS render-client teardown amendment

### Community 196 - "2026-07 · D-037 · Releases require a tag reachable from main"
Cohesion: 0.40
Nodes (5): 2026-07 · D-037 · Releases require a tag reachable from main, Consequences, Context, Decision, Ubuntu AppImageTool amendment

### Community 197 - "2026-07 · D-043 · Presentation timestamps own video timing and exact interaction"
Cohesion: 0.40
Nodes (5): 2026-07 · D-043 · Presentation timestamps own video timing and exact interaction, Alternatives rejected, Consequences, Context, Decision

### Community 198 - "2026-07 · D-044 · Plot presentation separates review, sweep, and scope"
Cohesion: 0.40
Nodes (5): 2026-07 · D-044 · Plot presentation separates review, sweep, and scope, Alternatives rejected, Consequences, Context, Decision

### Community 199 - "2026-07 · D-045 · The AOL encoder axis is seconds-since-midnight, unwrapped"
Cohesion: 0.40
Nodes (5): 2026-07 · D-045 · The AOL encoder axis is seconds-since-midnight, unwrapped, Alternatives rejected, Consequences, Context, Decision

### Community 200 - "2026-07 · D-046 · Pose data drives the overlay and 3D view, never plot rows"
Cohesion: 0.40
Nodes (5): 2026-07 · D-046 · Pose data drives the overlay and 3D view, never plot rows, Alternatives rejected, Consequences, Context, Decision

### Community 201 - "pull_request_template.md"
Cohesion: 0.40
Nodes (4): Anything reviewers should look at closely, Checklist, How it was verified, What and why

### Community 202 - "Q: the window adjust metns are slow for the tim, put a limit region eg: n (s)dropdown so that user can define in seconds or minutes or millisecond and hours as units so that we can select the scale and then the slider pick the units if corse adjustment is needed. currently the plotting is very wonky, and dot dyanmic with the scale adjustments when i change windows. adfter a bit of playing things things freeze. fix these issues too things needs to be extreamly fast as possible"
Cohesion: 0.40
Nodes (4): Answer, Outcome, Q: the window adjust metns are slow for the tim, put a limit region eg: n (s)dropdown so that user can define in seconds or minutes or millisecond and hours as units so that we can select the scale and then the slider pick the units if corse adjustment is needed. currently the plotting is very wonky, and dot dyanmic with the scale adjustments when i change windows. adfter a bit of playing things things freeze. fix these issues too things needs to be extreamly fast as possible, Source Nodes

### Community 203 - "Q: the window adjust metns are slow for the tim, put a limit region eg: n (s)dropdown so that user can define in seconds or minutes or millisecond and hours as units so that we can select the scale and then the slider pick the units if corse adjustment is needed. currently the plotting is very wonky, and dot dyanmic with the scale adjustments when i change windows. adfter a bit of playing things things freeze. fix these issues too things needs to be extreamly fast as possible"
Cohesion: 0.40
Nodes (4): Answer, Outcome, Q: the window adjust metns are slow for the tim, put a limit region eg: n (s)dropdown so that user can define in seconds or minutes or millisecond and hours as units so that we can select the scale and then the slider pick the units if corse adjustment is needed. currently the plotting is very wonky, and dot dyanmic with the scale adjustments when i change windows. adfter a bit of playing things things freeze. fix these issues too things needs to be extreamly fast as possible, Source Nodes

### Community 204 - "Q: commit current changes; fix closed or unchecked plots reappearing on resize and streams (video, plots, 3d) freezing or becoming unsmooth after a while"
Cohesion: 0.40
Nodes (4): Answer, Outcome, Q: commit current changes; fix closed or unchecked plots reappearing on resize and streams (video, plots, 3d) freezing or becoming unsmooth after a while, Source Nodes

### Community 205 - "Q: have you checked the focus of keybaord issues ? the focus mut be for the play pause seen kind a things i think right now it stays with the timewindow input area, once i enter a value the focus never goes away form it. but if user already entered the value thats enough to take off the focus from that to play area"
Cohesion: 0.40
Nodes (4): Answer, Outcome, Q: have you checked the focus of keybaord issues ? the focus mut be for the play pause seen kind a things i think right now it stays with the timewindow input area, once i enter a value the focus never goes away form it. but if user already entered the value thats enough to take off the focus from that to play area, Source Nodes

### Community 206 - "Q: Where can AvialView be made freeze-free and faster while preserving accurate data streaming?"
Cohesion: 0.40
Nodes (4): Answer, Outcome, Q: Where can AvialView be made freeze-free and faster while preserving accurate data streaming?, Source Nodes

### Community 207 - "Q: Implement the performance-audit hardening and commit it"
Cohesion: 0.40
Nodes (4): Answer, Outcome, Q: Implement the performance-audit hardening and commit it, Source Nodes

### Community 208 - "Q: Make planning-file changes for the approved plot UX refinement without code changes, preserving all current functionality."
Cohesion: 0.40
Nodes (4): Answer, Outcome, Q: Make planning-file changes for the approved plot UX refinement without code changes, preserving all current functionality., Source Nodes

### Community 209 - "sign_notarize.sh"
Cohesion: 0.80
Nodes (4): notarize_dmg(), require_env(), sign_notarize.sh script, sign_app()

### Community 210 - ".closeEvent"
Cohesion: 0.40
Nodes (3): QCloseEvent, Always close.          This used to ``event.ignore()`` while any background job, Run one shutdown step; log and continue if it fails.          Closing is the one

### Community 211 - "set_font_family"
Cohesion: 0.40
Nodes (4): Import Report dialog — shows ImportReport stats with a copy-as-text button., QWidget, Use *family* without opting a widget out of application font scaling., set_font_family()

### Community 214 - "_DeltaRow"
Cohesion: 0.50
Nodes (3): _DeltaRow, Shows Δvalue for one channel., Show Δt and Δvalue per channel between measure points A and B.

### Community 215 - "2026-07 · D-033 · Packaging inputs are explicit and CI artifact builds are a separate gate"
Cohesion: 0.50
Nodes (4): 2026-07 · D-033 · Packaging inputs are explicit and CI artifact builds are a separate gate, Consequences, Context, Decision

### Community 216 - "2026-07 · D-034 · Themes are palette/font appearance, never interaction redesign"
Cohesion: 0.50
Nodes (4): 2026-07 · D-034 · Themes are palette/font appearance, never interaction redesign, Consequences, Context, Decision

### Community 217 - "2026-07 · D-036 · PR and tag quality use one cross-platform test contract"
Cohesion: 0.50
Nodes (4): 2026-07 · D-036 · PR and tag quality use one cross-platform test contract, Consequences, Context, Decision

### Community 218 - "2026-07 · D-038 · Windows video panes use libmpv's Qt OpenGL render API — SUPERSEDED by D-075"
Cohesion: 0.50
Nodes (4): 2026-07 · D-038 · Windows video panes use libmpv's Qt OpenGL render API — SUPERSEDED by D-075, Consequences, Context, Decision

### Community 219 - "2026-07 · D-039 · Release bundles own the complete media runtime — AMENDED by D-075"
Cohesion: 0.50
Nodes (4): 2026-07 · D-039 · Release bundles own the complete media runtime — AMENDED by D-075, Consequences, Context, Decision

### Community 220 - "2026-07 · D-040 · Sidecar writes use bounded concurrency and failures remain observable"
Cohesion: 0.50
Nodes (4): 2026-07 · D-040 · Sidecar writes use bounded concurrency and failures remain observable, Consequences, Context, Decision

### Community 221 - "2026-07 · D-042 · Plots use one fixed, shared oscilloscope sweep"
Cohesion: 0.50
Nodes (4): 2026-07 · D-042 · Plots use one fixed, shared oscilloscope sweep, Consequences, Context, Decision

### Community 222 - ".eventFilter"
Cohesion: 0.50
Nodes (3): QEvent, QObject, Reserve Space for playback while retaining ordinary Tab accessibility.

### Community 225 - "test_packaging_metadata.py"
Cohesion: 0.50
Nodes (3): Tests for published-package compatibility metadata., Published metadata supports exactly the tested Python range., test_package_caps_python_at_3_12()

### Community 226 - "test_worker_thread_teardown.py"
Cohesion: 0.50
Nodes (3): Regression checks for how background workers are destroyed (D-062)., A worker moved onto a QThread must not be ``deleteLater``-ed from it.      Both, test_no_worker_is_destroyed_inside_its_own_thread()

### Community 227 - "2026-07 · D-023 · Benchmarks CI-gated; budget-assertion pattern; CI multiplier"
Cohesion: 0.67
Nodes (3): 2026-07 · D-023 · Benchmarks CI-gated; budget-assertion pattern; CI multiplier, Context, Decisions

### Community 228 - "2026-07 · D-029 · Separate GitHub workload correctness from local speed certification"
Cohesion: 0.67
Nodes (3): 2026-07 · D-029 · Separate GitHub workload correctness from local speed certification, Context, Decision

### Community 229 - "2026-07 · D-030 · Test-level watchdog for cross-platform Qt verification"
Cohesion: 0.67
Nodes (3): 2026-07 · D-030 · Test-level watchdog for cross-platform Qt verification, Context, Decision

### Community 230 - "2026-07 · D-031 · Libmpv commands stay on the Qt-owning thread — SUPERSEDED by D-075"
Cohesion: 0.67
Nodes (3): 2026-07 · D-031 · Libmpv commands stay on the Qt-owning thread — SUPERSEDED by D-075, Context, Decision

### Community 232 - "_demo_frame"
Cohesion: 0.67
Nodes (3): _demo_frame(), ndarray, Draw one recognisable test frame.      A moving bar over a static gradient, plus

## Knowledge Gaps
- **413 isolated node(s):** `avialsync-plugin-example`, `make_appimage.sh script`, `make_dmg.sh script`, `avialsync`, `What and why` (+408 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **18 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Work-memory lessons

**Preferred sources** — corroborated by past sessions; start here.
- `PlotPane` (6× useful, score=5.991221348) _(code changed — re-verify)_
- `SweepWindowControl` (4× useful, score=3.99383005) _(code changed — re-verify)_
- `MainWindow` (3× useful, score=2.99751553) _(code changed — re-verify)_
- `PyramidReader` (3× useful, score=2.994276161) _(code changed — re-verify)_
- `Transport` (2× useful, score=1.998534709) _(code changed — re-verify)_
- `Player` (2× useful, score=1.997391299) _(code changed — re-verify)_

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MainWindow` connect `MainWindow` to `LoaderRegistry`, `generate_session_screenshot.py`, `SensorInfoWidget`, `Transport`, `PlotPane`, `CacheManager`, `AnnotationPanel`, `JobManager`, `ReadoutPanel`, `VideoGrid`, `test_pane_proportions.py`, `ImportReportDialog`, `VideoStandardLoader`, `SourceInspection`, `QSettings`, `test_interaction_standard.py`, `DemoData`, `export_controller.py`, `test_close_and_focus.py`, `DemoProgressDialog`, `test_ui_main.py`, `AnnotationStore`, `pyramid.py`, `ReaderReference`, `test_worker_lifetime.py`, `generate_screenshots`, `no_startup_diagnostics`, `SessionState`, `SyncWizard`, `._apply_default_splitter_sizes`, `Path`, `apply_theme`, `_QuickWorker`, `import_controller.py`, `TrackingLoader`, `test_workload_responsiveness.py`, `DropScanWorker`, `Player`, `session_controller.py`, `_parse_args`, `sync_worker.py`, `main_window.py`, `test_session_worker.py`, `ChannelKey`, `test_ui_sensor_mapping.py`, `.closeEvent`, `._generate_proxy`, `._on_sensor_mapping_changed`, `test_aol_pose_routing.py`, `demo.py`, `test_never_freeze.py`, `test_ui_layout_resize.py`, `MasterClock`, `.eventFilter`, `TimeDisplayMode`, `Tracking3DPane`, `test_channel_identity.py`, `.resizeEvent`, `test_ui_shortcut_reach.py`, `DemoLaunch`, `_FakePane`, `test_sync_golden.py`, `UiHeartbeat`, `ProxyWorker`?**
  _High betweenness centrality (0.192) - this node is a cross-community bridge._
- **Why does `PlotPane` connect `PlotPane` to `MainWindow`, `create_channel_plot`, `SensorInfoWidget`, `test_bench_plot_pane.py`, `TestMeasureMarkers`, `test_bench_cursor_path`, `plot_pane.py`, `SweepWindowControl`, `test_close_and_focus.py`, `.load_channels`, `TimeMap`, `AnnotationStore`, `timeline.py`, `test_ui_plot_row_geometry.py`, `._set_sweep_for_time`, `test_scrubbing.py`, `Player`, `PlotInteractionController`, `main_window.py`, `PlotHeader`, `test_theme_tooltips.py`, `ChannelKey`, `TimeDisplayMode`, `annotations.py`, `test_ui_follow.py`, `test_ui_plot_sliced_refresh.py`?**
  _High betweenness centrality (0.076) - this node is a cross-community bridge._
- **Why does `TimeMap` connect `TimeMap` to `LoaderRegistry`, `MainWindow`, `create_channel_plot`, `PlotPane`, `VideoMetadata`, `CacheManager`, `test_playback_smoothness.py`, `PaintCanvas`, `VideoPane`, `MappedChannelReader`, `PyramidBuilder`, `export_controller.py`, `plot_pane.py`, `.load_channels`, `timeline.py`, `ReaderReference`, `sync.py`, `SyncWizard`, `export_worker.py`, `import_controller.py`, `Player`, `test_core_coverage_edges.py`, `test_session_worker.py`, `ChannelKey`, `test_ui_sensor_mapping.py`, `extract_ttl_edges`, `Tracking3DCanvas`, `Tracking3DPane`, `test_core_timeline.py`, `tracking_3d_pane.py`, `DecodeWorker`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Are the 56 inferred relationships involving `MainWindow` (e.g. with `DemoData` and `DemoGenerationWorker`) actually correct?**
  _`MainWindow` has 56 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `PlotPane` (e.g. with `Player` and `_JobWorker`) actually correct?**
  _`PlotPane` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 40 inferred relationships involving `TimeMap` (e.g. with `ChannelKey` and `MappedChannelReader`) actually correct?**
  _`TimeMap` has 40 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `PyramidReader` (e.g. with `ChannelKey` and `MappedChannelReader`) actually correct?**
  _`PyramidReader` has 27 INFERRED edges - model-reasoned connections that need verification._