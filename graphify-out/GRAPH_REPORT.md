# Graph Report - .  (2026-07-26)

## Corpus Check
- 138 files · ~68,984 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1632 nodes · 2839 edges · 112 communities (92 shown, 20 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 272 edges (avg confidence: 0.62)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- Community 43
- Community 44
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 55
- Community 56
- Community 57
- Community 58
- Community 59
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70
- Community 71
- Community 72
- Community 73
- Community 74
- Community 75
- Community 76
- Community 77
- Community 78
- Community 79
- Community 80
- Community 81
- Community 82
- Community 83
- Community 84
- Community 85
- Community 86
- Community 87
- Community 88
- Community 89
- Community 90
- Community 91
- Community 92
- Community 93
- Community 94
- Community 95
- Community 96
- Community 97
- Community 98
- Community 99
- Community 100
- Community 101
- Community 102
- Community 103
- Community 104

## God Nodes (most connected - your core abstractions)
1. `MainWindow` - 135 edges
2. `Transport` - 56 edges
3. `SourceInspection` - 42 edges
4. `PlotPane` - 39 edges
5. `TimeMap` - 33 edges
6. `VideoPane` - 33 edges
7. `CSVLoader` - 31 edges
8. `VideoGrid` - 31 edges
9. `PyramidReader` - 29 edges
10. `VideoSource` - 29 edges

## Surprising Connections (you probably didn't know these)
- `plot_pane()` --calls--> `PlotPane`  [INFERRED]
  tests/test_ui_plot_measure.py → src/avialview/ui/plot_pane.py
- `panel()` --calls--> `ReadoutPanel`  [INFERRED]
  tests/test_ui_readout_delta.py → src/avialview/ui/readout_panel.py
- `ToyBinarySource` --uses--> `ChannelInfo`  [INFERRED]
  examples/plugins/avialview-plugin-example/src/avialview_plugin_example/__init__.py → src/avialview/core/source.py
- `ToyBinarySource` --uses--> `TimeSeriesSource`  [INFERRED]
  examples/plugins/avialview-plugin-example/src/avialview_plugin_example/__init__.py → src/avialview/core/source.py
- `load_data()` --calls--> `CacheManager`  [INFERRED]
  tools/launch_demo.py → src/avialview/core/cache.py

## Import Cycles
- None detected.

## Communities (112 total, 20 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (31): Return the equivalent master-to-target mapping., MasterClock, PlaybackState, Master timeline and synchronization logic., Maps master timeline to a specific source timeline.      t_source = t_master + o, Update mapping parameters dynamically, anchoring so that mapped time         at, Replace this source mapping with an accepted, absolute calibration.          Unl, Single master clock for AvialView.      Time is driven externally via advance(mo (+23 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (46): Path, Regression guard: make_fixtures._clean_generated() must never delete permanent f, Running _clean_generated twice must not error (no dirs to remove second time)., session_v1.avv, session_v2.avv, session_v3.avv must be committed in tests/fixtur, _clean_generated() deletes generated subdirs but leaves .avv files intact., test_clean_generated_is_idempotent(), test_clean_generated_preserves_session_files(), test_permanent_fixtures_exist_in_repo() (+38 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (19): QResizeEvent, QSlider, Transport bar: play/pause, frame step, scrub slider,     A/B loop, rate control,, Set the A/B loop in-point at the current slider position (public, D-022.1)., Set the A/B loop out-point at the current slider position (public, D-022.1)., Show compact, non-blocking status text beside Reset Zoom., Show one video or data coverage span in the overview strip., Show accepted synchronization events in the overview strip. (+11 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (42): QAction, QDialog, QWidget, Keyboard shortcuts reference dialog — derived from live QAction registry (D-022., Modal dialog listing all keyboard shortcuts.      Derives content entirely from, ShortcutsDialog, _all_shortcuts(), main_window() (+34 more)

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (23): QTreeWidgetItem, _make_empty_inspection(), QFrame, QWidget, Left Sidebar / Inspector Pane., Update badge and properties panel from a SourceInspection., Displays metadata and controls for a single loaded video., Displays metadata and per-channel controls for one loaded sensor CSV. (+15 more)

### Community 5 - "Community 5"
Cohesion: 0.06
Nodes (13): QCloseEvent, QMainWindow, MainWindow, Toggle fullscreen for the first (or only) pane (D-022)., Clamp and seek relative to the current playhead (D-022)., Project media bounds through its TimeMap before drawing master-time coverage., Create UI state only after asynchronous source opening succeeds., Show a source-open error without leaving a partially-created pane. (+5 more)

### Community 6 - "Community 6"
Cohesion: 0.10
Nodes (38): Edge, AvialView exception hierarchy., Raised when synchronization evidence is malformed or insufficient., Raised when event evidence supports multiple equally valid alignments., SyncAmbiguityError, SyncEvidenceError, _candidate_indices(), _default_tolerance() (+30 more)

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (30): Exception, CacheManager, Path, Cache management for sidecar files., Manages .avialcache sidecar directories with atomic writes and hardened keys., Hash the first and last 64KB of the file., Generate cache invalidation key per D-008., Return the path to the sidecar cache directory. (+22 more)

### Community 8 - "Community 8"
Cohesion: 0.10
Nodes (15): Enum, _fmt_relative(), format_time(), Time display mode enum and single formatting authority (D-020).  All time-displa, Format *t_seconds* according to *mode*.      t_epoch is the Unix epoch of master, Format signed elapsed time without wrapping negative values by a day., TimeDisplayMode, JumpSlider (+7 more)

### Community 9 - "Community 9"
Cohesion: 0.08
Nodes (21): ABC, Plugin registry and discovery., Source plugin abstract base classes., Return an optional UTC-epoch metadata guess; user offset always wins., Return source coverage in master-time seconds.          Sources with a metadata, Nominal frames per second., Camera label for the UI., Frozen v1 plugin contract for chunked time-series ingestion.      Instances are (+13 more)

### Community 10 - "Community 10"
Cohesion: 0.08
Nodes (24): Path, PyramidBuilder, PyramidReader, Builds and serializes a multi-level pyramid to disk., Reads pyramid queries dynamically from mmapped arrays., Return (t, vmin, vmax, gap_mask) for the given time range,         choosing appr, Return the exact value at the given time `t_target` using the highest resolution, ChannelPlot (+16 more)

### Community 11 - "Community 11"
Cohesion: 0.09
Nodes (29): MonkeyPatch, QDragEnterEvent, QDropEvent, main_window(), Path, QApplication, Main Window regression tests., Demo/programmatic imports may finish without an interactive progress dialog. (+21 more)

### Community 12 - "Community 12"
Cohesion: 0.09
Nodes (25): add_recent(), clear_recent(), get_recent(), MarkerEntry, Any, Path, Session state and JSON serialization for .avv files., Persisted state for one loaded video. (+17 more)

### Community 13 - "Community 13"
Cohesion: 0.11
Nodes (13): QMouseEvent, QPaintEvent, Return the currently populated lanes, in their rendered order., Refresh labels and ensure populated lanes have usable vertical space., Return the clipped timeline span, excluding the source-label gutter., Return concise inspectable evidence nearest the pointer, if any., Paint named, conditional timeline-evidence lanes without owning time state., Set the shared master-time range rendered by this overview. (+5 more)

### Community 14 - "Community 14"
Cohesion: 0.09
Nodes (16): Any, ndarray, Path, Loads standard videos utilizing ffprobe metadata., Return whether decoded frame timestamps have variable intervals., VideoStandardLoader, B-frame packet order must not decide VFR detection or frame stepping., VFR detection is based on timestamps, not a misleading average FPS. (+8 more)

### Community 15 - "Community 15"
Cohesion: 0.10
Nodes (21): QPixmap, export_data_slice_csv(), export_data_slice_parquet(), Path, QWidget, Export utilities: snapshot PNG, data slice CSV/Parquet, video clip., Grab a widget's current visual content as a QPixmap., Trim a video clip using ffmpeg stream copy (no re-encode). (+13 more)

### Community 16 - "Community 16"
Cohesion: 0.12
Nodes (19): Series, NonMonotonicTimeError, Raised when time series timestamps go backwards., CSVLoader, Any, ndarray, Path, CSV Time Series Loader. (+11 more)

### Community 17 - "Community 17"
Cohesion: 0.10
Nodes (13): ChannelInfo, Metadata for a single data channel., Return stable metadata for every importable channel., NeoLoader, ndarray, Loads electrophysiology data using the neo library., Any, ndarray (+5 more)

### Community 18 - "Community 18"
Cohesion: 0.12
Nodes (22): Any, Path, Find the true ephys root by scanning up to depth 3 for signatures., Return 1.0 for whitelisted ephys formats; 0.0 for everything else.          Dire, Path, Tests for the NeoLoader ephys data plugin., NeoLoader must never claim .csv files., NeoLoader must return 0.0 for plain text files. (+14 more)

### Community 19 - "Community 19"
Cohesion: 0.13
Nodes (9): _PropertiesBase, Any, QGroupBox, QWidget, Collapsible properties panel for one video source., Read live mpv properties; call when the panel is expanded., Shared skeleton: collapsible section with a Copy button., VideoPropertiesPanel (+1 more)

### Community 20 - "Community 20"
Cohesion: 0.10
Nodes (17): _guess_format(), _guess_time_column(), ImportWizard, Any, Path, QDialog, QWidget, Timestamp import wizard with preview, format autodetect, and timezone handling. (+9 more)

### Community 21 - "Community 21"
Cohesion: 0.09
Nodes (9): Video rendering pane.      Uses macOS Render API via QOpenGLWidget on Darwin,, Mark the on-video readout so its instantaneous rate is contextualized., Supply the stream's nominal rate for stable CFR readout., Set the source-time interval that contains decodable media., Return whether this pane has media at the supplied master time., Seek to a specific time. Exact seek or keyframe., Step one frame forward or backward., Terminate mpv before closing the widget. (+1 more)

### Community 22 - "Community 22"
Cohesion: 0.11
Nodes (18): EventEvidenceSpec, EvidenceSpec, ndarray, QObject, Background TTL/event evidence extraction and alignment fitting., Native timestamp evidence, such as camera-frame trigger timestamps., Build an evidence-based proposal without blocking the UI thread., Extract raw evidence and emit one deterministic fit proposal. (+10 more)

### Community 23 - "Community 23"
Cohesion: 0.09
Nodes (11): Any, Path, QObject, Select, open, and optionally prepare one video source off the UI thread., Request cancellation between source operations., Adapt the plugin's normalized progress callback to the UI signal., VideoOpenWorker, _PreparedVideo (+3 more)

### Community 24 - "Community 24"
Cohesion: 0.10
Nodes (16): QWidget, Terminate all libmpv panes before their Qt parent is destroyed., Update the time offset for a specific video., Apply a user-accepted absolute synchronization mapping to one video., Show or hide a video pane without unloading it., Manages N VideoPanes in either a horizontal strip or an NxN grid.      Uses a si, Return a copy of the loaded video paths, parallel to self.panes., Pass tracking data readers to all video panes for overlay rendering. (+8 more)

### Community 25 - "Community 25"
Cohesion: 0.13
Nodes (18): _aggregate_pyramid_level(), build_gap_mask(), build_pyramid_level(), ndarray, Pyramid module for decimation and plotting., Build a decimation level for arrays t and v.      Returns (t_decimated, v_min, v, Return a boolean mask where True indicates a gap larger than 10x median dt., Aggregate one pyramid level from the preceding level's min/max envelopes. (+10 more)

### Community 26 - "Community 26"
Cohesion: 0.14
Nodes (9): Read a .avv session file., Path, Open a registry-selected video source without blocking the UI thread., Start a registry-selected time-series import for one path., Return (fps, ok) for a frame-indexed source, using loaded video fps when possibl, Start a background ImportWorker for the given path/loader/config., Load all sources from a SessionState object., Export annotation markers to CSV — one row per (marker, video). (+1 more)

### Community 27 - "Community 27"
Cohesion: 0.12
Nodes (13): A deterministic, inspectable synchronization proposal., Whether this proposal is unambiguous and within its fit tolerance., SyncProposal, A cached signal channel from which TTL transitions are extracted., SignalEvidenceSpec, Open evidence-based TTL/frame-event alignment for loaded sources., QDialog, Non-blocking wizard for inspecting and accepting synchronization evidence. (+5 more)

### Community 28 - "Community 28"
Cohesion: 0.14
Nodes (9): Headless dataclasses for import statistics and source integrity (D-020).  No PyS, All collected inspection data for one loaded source.      Not frozen because imp, SourceInspection, Asynchronous data source importer pipeline., Import Report dialog — shows ImportReport stats with a copy-as-text button., Collapsible source-properties panels for VideoInfoWidget and SensorInfoWidget (D, Unit tests for core.inspection dataclasses (ImportReport, IntegrityFlags, Source, SourceInspection is not frozen — its dict field must be mutable. (+1 more)

### Community 29 - "Community 29"
Cohesion: 0.09
Nodes (21): player_with_mocks(), Tests for live scrubbing coalescing behaviour in Player., Return a Player wired to mock collaborators (no Qt event loop needed)., _on_tick dispatches the pending scrub target once seeker settles., _on_tick does NOT flush while seeker is still busy., Exact seek on release clears any pending coalesced target., readout_panel.set_cursor is called on every seek, including non-exact., Out-of-range panes show No Footage and are never asked to seek a stale frame. (+13 more)

### Community 30 - "Community 30"
Cohesion: 0.19
Nodes (18): Path, Regression tests for generated, user-facing demo inputs., The demo tracking file must match the loader's three-row DLC contract., test_generated_pose_csv_is_importable_dlc_data(), _ffmpeg(), _is_dlc_pose_csv(), _is_valid_vfr_video(), main() (+10 more)

### Community 31 - "Community 31"
Cohesion: 0.10
Nodes (19): Tests for the two-row timeline and status transport layout., Seek-row controls follow the compact visual-inspection workflow., Evidence is understandable in text and does not reserve empty lanes., Hover details make sync evidence inspectable rather than colour-only., Negative and later streams share one timeline origin outside the label gutter., Status updates do not block controls and reset has one explicit signal., The seek bar must not jump or resize when Play becomes Pause., Flag lives in the Data Streams header and retains the annotation action. (+11 more)

### Community 32 - "Community 32"
Cohesion: 0.16
Nodes (8): Player, QObject, Step forward or backward by one frame across all video panes.          Uses mpv', Read first pane's time_pos and seek master clock to match., Set or clear the A/B loop region on the master clock., Synchronize pane availability with master-time coverage before display or seek., Coordinates playback between UI and MasterClock., Start playback for programmatic callers such as the demo launcher.

### Community 33 - "Community 33"
Cohesion: 0.14
Nodes (4): DummyTimeSeriesLoader, DummyVideoLoader, Path, test_loader_discovery()

### Community 34 - "Community 34"
Cohesion: 0.13
Nodes (18): Path, Tests for frame-indexed source contract and DLC fps resolution (D-019)., _frame_indexed_sources accumulates provisional entries when no video is loaded., TimeSeriesSource.is_frame_indexed() should default to False., _rebind_frame_indexed_sources should clear the provisional list., After rebind, re-enqueued import uses the video fps, not the provisional fps., TrackingLoader.is_frame_indexed() must return True., Write a minimal two-bodypart DLC CSV to *path*. (+10 more)

### Community 35 - "Community 35"
Cohesion: 0.12
Nodes (12): Marker, Annotation markers: point and range, with list panel and CSV export., Per-video frame snapshot stored with an annotation marker., A single annotation marker on the timeline.      If ``t_end`` is None this is a, Add a point marker at time *t*., Add a range marker from *t_start* to *t_end*., VideoFrame, Add a point marker at the clicked time on the plot (D-022). (+4 more)

### Community 36 - "Community 36"
Cohesion: 0.12
Nodes (10): ImportReportDialog, QDialog, QWidget, Scrollable plain-text view of an ImportReport with a Copy button., Any, Show a per-pane context menu on video right-click (D-022)., Forward to ReadoutPanel with accumulated units for known channels., Show the VideoPropertiesPanel for a video (triggered by badge click). (+2 more)

### Community 37 - "Community 37"
Cohesion: 0.18
Nodes (10): ModuleType, LoaderRegistry, Path, Discovers and loads source plugins., Return supported loose-plugin directories, in discovery order., Find all loaders in the avialview.loaders entry point group., Load source classes exported by loose ``*.py`` plugin modules., Import one loose plugin module without adding its directory to ``sys.path``. (+2 more)

### Community 38 - "Community 38"
Cohesion: 0.18
Nodes (8): _ABPin, QFrame, QWidget, Titled, collapsible Data Streams shell for named TimelineOverview lanes., Show active work beside Reset Zoom and clear non-active messages shortly after., Thin vertical marker overlaid on the slider for A/B loop points., Detach Data Streams so the main workspace splitter can own its height., TimelineEvidence

### Community 39 - "Community 39"
Cohesion: 0.14
Nodes (16): Path, Tests for SessionState serialisation and schema migrations., A v3 session must survive a save/load cycle with video_frames intact., Inspection fields and accepted synchronization provenance survive a round trip., An empty session should save and load without error., A v1 .avv file must load correctly after the v2-v4 schema changes., Loading a v1 session then saving it should produce a valid v4 file., A v2 .avv file must load without error; video_frames defaults to []. (+8 more)

### Community 40 - "Community 40"
Cohesion: 0.13
Nodes (10): Any, ndarray, Path, A minimal external AvialView Plugin API v1 implementation., Read ``.toybin`` records encoded as little-endian ``(time, value)`` pairs., Recognise the example file extension without opening the input., Store the path after validating whole-record alignment., Expose the single dimensionless signal channel. (+2 more)

### Community 41 - "Community 41"
Cohesion: 0.14
Nodes (9): PlotPane, QWidget, Update playhead position independently of curve redraws on all channels., Toggle playhead following mode., Zoom the X-axis in by ~30 % (+ key, D-022)., Zoom the X-axis out by ~40 % (- key, D-022)., Overlay thin red vertical lines at gap positions for one channel., Data plotting pane for multiple time-series channels.      Uses pyqtgraph Graphi (+1 more)

### Community 42 - "Community 42"
Cohesion: 0.18
Nodes (14): _expected_pin_x(), Regression tests: transport A/B pins must realign after window resize., Pin remains correctly positioned across consecutive resizes., Return the correct x for a pin at *frac* given the slider's current geometry., A/B in-pin must sit at the correct groove fraction after a resize., A/B out-pin realigns after resize (non-midpoint fraction)., Both A/B pins realign independently after a single resize., No pins are shown after resize if none were set. (+6 more)

### Community 43 - "Community 43"
Cohesion: 0.16
Nodes (14): QColor, QPalette, _palette_with_surfaces(), _qss(), Return only styling Qt cannot consistently derive from a palette., Build an explicit appearance while retaining the platform accent colour., Tooltips stay readable even when a native platform tooltip is unreliable., A custom OS accent must flow into links and interactive controls. (+6 more)

### Community 44 - "Community 44"
Cohesion: 0.18
Nodes (8): QTableWidgetItem, AnnotationPanel, Path, QGroupBox, Write one row per (marker, video) — format for DLC/LightningPose retraining., Widget that lists annotations and provides add/delete/export controls., Rebuild the table from the store., Remove a marker by index.

### Community 45 - "Community 45"
Cohesion: 0.23
Nodes (5): ImportReport, Any, Statistics collected by ImportWorker during one source import., from_dict must tolerate a dict with only some keys (e.g. older data)., TestImportReport

### Community 46 - "Community 46"
Cohesion: 0.15
Nodes (8): Any, Path, Return what mpv actually plays (proxy-aware)., Return a confidence in ``[0.0, 1.0]`` without expensive I/O., Read metadata required for :meth:`channels` and :meth:`read_chunks`.          ``, Return 0..1 confidence that this loader can open the file., Probe source metadata; this method may perform blocking I/O., Produce an mpv-playable cached proxy and report progress in ``[0, 1]``.

### Community 47 - "Community 47"
Cohesion: 0.19
Nodes (13): _accent(), _apply(), current_font_preference(), _is_dark_palette(), Native-aware dark, light, and system appearance for AvialView.  System appearanc, Apply *pref* without duplicating preference persistence logic., Return the persisted font-size preference., Return whether a palette has a dark window surface. (+5 more)

### Community 48 - "Community 48"
Cohesion: 0.15
Nodes (7): Remove all widgets from the grid and re-add them in the         current arrangem, Update camera labels, disambiguating duplicate filenames., Toggle fullscreen for the pane identified by *path*.          If *path* is None,, Toggle fullscreen for the clicked pane., Switch between horizontal-strip and NxN grid layout., Add a pane identified by original *path*, playing *media_path* if supplied., Remove a video pane by path.

### Community 49 - "Community 49"
Cohesion: 0.21
Nodes (9): needs_proxy(), proxy_path_for(), ProxyWorker, Path, QObject, Proxy generation — re-encode videos to short-GOP scrub-friendly proxies., Return the sidecar proxy path for a given video., Check if a proxy already exists and is newer than the source. (+1 more)

### Community 50 - "Community 50"
Cohesion: 0.15
Nodes (10): Startup diagnostics lifecycle tests., Repeated windows share one diagnostics probe instead of spawning threads., test_startup_diagnostics_starts_one_background_probe(), Theme tests for readable tooltips on all supported appearances., The demo must use the same saved appearance as the production app., The visible toggle must retain the captured native accent in every mode., Small/Medium/Large are relative preferences, while System is exact restoration., test_demo_launcher_uses_the_application_theme() (+2 more)

### Community 51 - "Community 51"
Cohesion: 0.18
Nodes (7): _ChannelReadout, QGroupBox, Live channel value readout at the current playhead position.      Call `update_s, Replace displayed channels with a new list of readers., Interpolate and display each channel's value at time *t*., Single row: channel name | value (unit) | sample index., ReadoutPanel

### Community 52 - "Community 52"
Cohesion: 0.18
Nodes (11): displayed_frame_rate(), instantaneous_frame_rate(), ndarray, Return the displayed frame's rate from its timestamp interval.      VFR does not, Supply decoded frame timestamps for instantaneous VFR readout., Use a stable nominal rate for CFR and timestamp evidence for VFR., Timestamp-derived video readout tests., VFR readout must not collapse variable intervals into one average FPS. (+3 more)

### Community 53 - "Community 53"
Cohesion: 0.15
Nodes (3): plot_pane(), Tests for PlotPane measure markers and measure_changed signal., TestMeasureMarkers

### Community 54 - "Community 54"
Cohesion: 0.23
Nodes (9): AnnotationStore, QObject, QWidget, In-memory store for timeline markers.      Emits ``changed`` whenever markers ar, Path, test_add_point_no_frames_defaults_to_empty(), test_export_csv_columns(), test_export_csv_marker_with_no_frames() (+1 more)

### Community 55 - "Community 55"
Cohesion: 0.31
Nodes (3): IntegrityFlags, Anomaly flags for one loaded source.      Video flags (is_vfr, fps_mismatch) are, TestIntegrityFlags

### Community 56 - "Community 56"
Cohesion: 0.20
Nodes (8): ImportWorker, Any, Path, QObject, Background worker for parsing and building pyramids from time-series sources., load_data(), main(), Demo launcher — loads all example fixtures to exercise inspection-layer features

### Community 57 - "Community 57"
Cohesion: 0.27
Nodes (10): main(), apply_theme(), _install_system_appearance_listener(), load_saved_font_size(), load_saved_theme(), QApplication, Follow platform palette changes while the System preference is active., Apply and persist System, Dark, or Light appearance.      System follows Qt's pl (+2 more)

### Community 58 - "Community 58"
Cohesion: 0.22
Nodes (9): _configure_macos_env(), probe_disk_speed(), probe_hwdec(), probe_libmpv(), Diagnostics module for AvialView.  Probes for libmpv, hardware decode capability, Configure dyld paths on macOS for Homebrew libmpv., Probe for libmpv. Show a dialog if missing and return False., Probe hardware decode capabilities via mpv.      Returns a dict with 'available' (+1 more)

### Community 59 - "Community 59"
Cohesion: 0.29
Nodes (4): Collapsible properties panel for one data source., SensorPropertiesPanel, Tests for ui.source_properties — as_plain_text() roundtrips., TestSensorPropertiesPanel

### Community 60 - "Community 60"
Cohesion: 0.22
Nodes (7): QFont, QAction, Apply the selected system-relative application font scale., apply_font_size(), Apply and persist a system-relative application font-size preference., Return the platform application font captured before user scaling., _system_font()

### Community 61 - "Community 61"
Cohesion: 0.28
Nodes (6): compute_region_stats(), Compute min/max/mean/rms for each channel in [t0, t1]., Cursor readout panel — per-channel values, camera frame numbers, Δ measurement., Compute and display stats for the A/B loop region., Shows min/max/mean/rms for one channel in a region., _StatsRow

### Community 62 - "Community 62"
Cohesion: 0.25
Nodes (5): Queue a seek on one pane without blocking the UI thread., Issue parallel seek commands to all active panes., Return True if all panes have finished seeking., Fan out non-blocking libmpv seek commands across video panes.      ``mpv.seek``, SeekGroup

### Community 63 - "Community 63"
Cohesion: 0.25
Nodes (5): QDialog, Missing-file relink dialog shown when session files cannot be found., Return {original_path: new_path} for files the user relocated., Lets the user relocate missing files referenced by a session.      Shows a table, RelinkDialog

### Community 64 - "Community 64"
Cohesion: 0.31
Nodes (4): PaintCanvas, QPaintEvent, QWidget, Transparent overlay for drawing tracking markers.

### Community 65 - "Community 65"
Cohesion: 0.22
Nodes (3): panel(), Tests for ReadoutPanel.show_delta and set_camera_states., TestSetCameraStates

### Community 66 - "Community 66"
Cohesion: 0.36
Nodes (7): discover_media_files(), main(), Path, Stage locally installed LGPL media libraries for a release bundle.  Downloads ar, Find mpv/ffmpeg runtime files in the supplied package-manager directories., Copy discovered runtime media files into a clean bundle-local directory., stage_media_files()

### Community 67 - "Community 67"
Cohesion: 0.68
Nodes (3): QLabel, _mono_style(), QWidget

### Community 68 - "Community 68"
Cohesion: 0.32
Nodes (3): Place measure pin A at time *t* on all channels., Place measure pin B at time *t* on all channels., Remove both measure pins.

### Community 69 - "Community 69"
Cohesion: 0.32
Nodes (6): _Pane, Tests for libmpv seek command dispatch., Minimal VideoPane stand-in for SeekGroup tests., Record a queued libmpv seek command., Seek completion remains owned by libmpv's seeking property observer., test_seek_group_fans_out_commands_without_marking_panes_stuck()

### Community 70 - "Community 70"
Cohesion: 0.38
Nodes (3): Asynchronous seek coordinator., Video grid layout manager., Video rendering pane using libmpv.

### Community 71 - "Community 71"
Cohesion: 0.33
Nodes (4): Path, Load multiple data sources from cache and build plot rows., Backwards compatibility for Phase 2 single-channel load., Query the pyramid for the current view range and update all curves.

### Community 72 - "Community 72"
Cohesion: 0.29
Nodes (3): Remove all channels associated with a specific cache_dir (source)., Remove a single channel by its channel_id, regardless of cache_dir., Draw point and range markers from the annotation store on all channels.

### Community 74 - "Community 74"
Cohesion: 0.40
Nodes (5): build_bundle(), main(), Path, Build a one-directory AvialView bundle for the current platform., Run PyInstaller with only staged, local media libraries included.

### Community 75 - "Community 75"
Cohesion: 0.40
Nodes (4): current_preference(), is_dark(), Return the persisted preference, normalized for legacy settings., Return whether the currently resolved application appearance is dark.

### Community 76 - "Community 76"
Cohesion: 0.47
Nodes (5): _media_stager(), Path, Tests for release media staging without requiring platform media packages., The release bundle receives media runtimes, not arbitrary package-manager files., test_media_staging_copies_only_runtime_media_files()

### Community 77 - "Community 77"
Cohesion: 0.33
Nodes (5): Regression checks for the PyInstaller specification., An unset media path must not accidentally mean the working directory., SPECPATH is the packaging directory, not the spec-file path., test_spec_only_includes_explicitly_staged_media(), test_spec_resolves_the_project_root_from_packaging_directory()

### Community 78 - "Community 78"
Cohesion: 0.40
Nodes (3): ndarray, Per-frame timestamps if the container has them., Yield one-dimensional ``float64`` time/value chunks for *ch*.          Chunks, i

### Community 80 - "Community 80"
Cohesion: 0.50
Nodes (3): _CameraRow, Update per-camera frame display.  states = [(label, time_pos, fps), ...], Shows frame number and media timestamp for one camera.

### Community 81 - "Community 81"
Cohesion: 0.50
Nodes (3): _DeltaRow, Shows Δvalue for one channel., Show Δt and Δvalue per channel between measure points A and B.

### Community 82 - "Community 82"
Cohesion: 0.50
Nodes (3): Accepted synchronization evidence summary persisted in a session., SyncProvenance, Apply an explicitly accepted proposal and retain reproducible provenance.

### Community 83 - "Community 83"
Cohesion: 0.50
Nodes (3): QEvent, QObject, Forward drops over child panes to the main-window source router.

### Community 85 - "Community 85"
Cohesion: 0.50
Nodes (3): Performance gate for deterministic TTL/event alignment previews., A 10,000-event preview must remain interactive and deterministic., test_bench_sync_fit_preview()

### Community 86 - "Community 86"
Cohesion: 0.50
Nodes (3): Regression checks for the Qt platform selection in CI., Displayless Windows CI must select VideoPane's null-video backend., test_windows_ci_uses_headless_video_backend()

### Community 87 - "Community 87"
Cohesion: 0.50
Nodes (3): Tests for published-package compatibility metadata., Published metadata supports exactly the tested Python range., test_package_caps_python_at_3_12()

## Knowledge Gaps
- **5 isolated node(s):** `avialview-plugin-example`, `make_appimage.sh script`, `make_dmg.sh script`, `sign_notarize.sh script`, `avialview`
  These have ≤1 connection - possible missing edges or undocumented components.
- **20 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MainWindow` connect `Community 5` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 11`, `Community 12`, `Community 15`, `Community 16`, `Community 17`, `Community 20`, `Community 22`, `Community 23`, `Community 24`, `Community 26`, `Community 27`, `Community 28`, `Community 32`, `Community 34`, `Community 35`, `Community 36`, `Community 37`, `Community 41`, `Community 44`, `Community 45`, `Community 49`, `Community 51`, `Community 54`, `Community 55`, `Community 56`, `Community 57`, `Community 60`, `Community 63`, `Community 75`, `Community 79`, `Community 82`, `Community 83`?**
  _High betweenness centrality (0.367) - this node is a cross-community bridge._
- **Why does `Transport` connect `Community 2` to `Community 32`, `Community 3`, `Community 5`, `Community 70`, `Community 38`, `Community 8`, `Community 10`, `Community 42`, `Community 79`, `Community 15`, `Community 84`, `Community 29`, `Community 31`?**
  _High betweenness centrality (0.118) - this node is a cross-community bridge._
- **Why does `VideoSource` connect `Community 9` to `Community 33`, `Community 37`, `Community 5`, `Community 78`, `Community 14`, `Community 46`, `Community 15`, `Community 23`, `Community 26`?**
  _High betweenness centrality (0.079) - this node is a cross-community bridge._
- **Are the 42 inferred relationships involving `MainWindow` (e.g. with `CacheManager` and `ImportReport`) actually correct?**
  _`MainWindow` has 42 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `Transport` (e.g. with `Player` and `MainWindow`) actually correct?**
  _`Transport` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `SourceInspection` (e.g. with `ImportWorker` and `ImportReportDialog`) actually correct?**
  _`SourceInspection` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `PlotPane` (e.g. with `Player` and `MainWindow`) actually correct?**
  _`PlotPane` has 8 INFERRED edges - model-reasoned connections that need verification._