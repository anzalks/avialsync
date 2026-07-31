# AvialView — Model Handout

Desktop tool for scrubbing time-synchronized multi-camera video with dense time-series data on a single master timeline.  
**Stack:** Python 3.11–3.12, PySide6, libmpv (python-mpv), pyqtgraph, polars, numpy
**License:** Apache-2.0  
**Env:** `conda run -n avialview <cmd>` — every command without exception

---

## Naming (binding)

| Context | Form |
|---|---|
| Brand / UI / window title | `AvialView` |
| Module / CLI / PyPI / import paths | `avialview` (lowercase, one word) |
| Session files | `.avv` |
| Cache sidecar dirs | `<file>.avialcache/` |

Use `AvialView` for displayed text and `avialview` for technical identifiers. Do not invent variants.

---

## Tech Stack

| Layer | Library | Notes |
|---|---|---|
| GUI | `PySide6` | NEVER PyQt5/PyQt6 — license |
| Video | `python-mpv` → `import mpv` | Lazy import only (D-013). Never QtMultimedia or OpenCV for playback |
| Plots | `pyqtgraph` | All data via decimation pyramid — never raw arrays >100k samples |
| Data | `polars` + `numpy` | polars for CSV; numpy for pyramid math |
| Build | `hatchling` | `pip install -e .[dev]` |
| Tests | `pytest` + `pytest-qt` | `QT_QPA_PLATFORM=offscreen` for headless |
| Lint | `ruff` | `ruff check --fix . && ruff format .` before finishing |
| Types | `mypy` | `--strict` on `core/`; standard on `ui/` and `loaders/` |

---

## Phase Status

Phases 0–4 complete; P3.5 hardening implemented (measurements pending — see Pending).
Phase 5.1 has frozen the Plugin API v1: time-series plugins
provide chunked ingest only; video sources open asynchronously through the registry,
retain D-006 conversion hooks, and may be discovered through entry points or drop-ins.
P5.4 has an initial implementation: cached TTL-channel extraction and video frame-event alignment
with explicit user acceptance and session provenance. Native plugin event providers remain unfrozen.

### Done (Phase 4)
- Session save/load `.avv` schema v5, autosave 2 min, recent files, relink dialog
- Transport: unified `QLineEdit` 110px minimum, `HH:MM:SS.fff`, `_time_editing` guard
- Theme: System/Dark/Light radio group in View menu; Ctrl+T cycles; System retains the platform
  style, palette, accent, and font, and follows Qt-reported palette changes while open. Explicit
  Dark/Light use the same platform accent with readable application surfaces. Themes are
  palette/font-only: they must not alter seek-bar geometry or semantics, plot range/follow state,
  splitter/scrollbar behavior, playback, shortcuts, or layout state.
- Font size: View → Font Size offers System, Small, Medium, and Large; each non-System choice is a
  persisted scale relative to the platform application font and applies to already-open controls.
  Fixed-width readouts retain their monospaced family while inheriting that scale.
- Video/channel visibility checkboxes (hide without unloading)
- A/B loop + region stats in ReadoutPanel
- Annotations (point + range markers, M key, CSV export)
- Keyboard shortcuts dialog (`?` key)
- Snapshot / data slice / video clip export
- Import wizard (CSV format/TZ/sentinel/euro-decimal) + proxy worker
- `plot_pane.reset_zoom()` method exists
- Plots share one master-time page and continuous **Time span** control (`ms` / `s` / `min` / `h`),
  with lossless unit conversion, logarithmic slider mapping, coalesced drag updates, and normal
  Tab/Enter focus. Paused and approximate scrubs use complete-page **Review**; live playback offers
  retained-page/eraser **Sweep** (default) and compatible clear/restart **Scope**. The pyramid is
  queried only at page changes, coalesced span changes, or quantized-density resize changes; hidden
  rows are not queried. One bottom master-time axis, per-channel fixed name/unit/range gutters,
  bounded min/max envelope, close-to-sidebar visibility path, stable Fit/Auto/Manual Y modes,
  native vertical scrolling, and retained current+previous sweep pages preserve dense-data clarity.

### Done (Phase 4 UX / loader fixes)
- **Live scrubbing coalescing**: During slider drag `Player.seek(exact=False)` coalesces in-flight keyframe seeks — if a seek is already dispatched, the newest target is held in `_pending_scrub_t` and flushed in `_on_tick` as soon as `SeekGroup.is_settled()`. Plot cursor and readout panel update every drag event. Exact seek fires on release as before.
- **No decoder-global freeze**: `MasterClock` advances on every active playback tick even if one
  libmpv pane remains in `seeking`. That pane drops frames and rejoins independently; it cannot stop
  plots, transport, readout, 3D, or healthy videos. Render and OSD callbacks retain only the newest
  pending UI update instead of building an unbounded event queue.
- **Persistent visibility**: unchecked videos and plot rows stay hidden through resize,
  grid/fullscreen relayout, and sweep refresh. Hidden videos stay loaded but are paused and excluded
  from seek/drift work; hidden plot rows are excluded from pyramid and overlay refreshes.
- **Frame-trigger exact interaction**: after exact-index alignment, release-of-scrub, pause, and
  frame-step snap to the first active accepted trigger clock. Every pane maps that master trigger
  through its own `TimeMap`; playback applies the local piecewise slope and frame-aware drift
  tolerance. Frame stepping uses the cached presentation index immediately—no fixed-delay timer.
- **Fast timestamp index + truthful OSD**: `VideoStandardLoader` probes presentation timestamps
  off-thread once and stores them in the content-hash-validated video sidecar. Reopens mmap the
  index. Timestamp intervals—not a container CFR declaration—decide CFR/VFR. The video pane shows
  nominal CFR, measured/VFR range and current rate, codec, and file size below its time readout.
- **Cross-platform exact seek dispatch**: `SeekGroup` queues libmpv commands from the Qt-owning
  thread. libmpv itself remains asynchronous; this avoids macOS property observers getting stuck
  in a seeking state when commands are issued from a Qt worker thread. Observer callbacks use
  their delivered values rather than querying libmpv recursively, avoiding Windows callback-thread
  crashes. Golden tests require delivered `seeking=False`/`time-pos` evidence at the target, retry
  one delayed exact command if the observer has not delivered it, then decode `screenshot-raw video`
  until it provides the expected raw frame—the only definitive frame-accuracy evidence. An
  unavailable or stale pre-seek raw snapshot is rejected, never accepted; retry uses the Qt event
  loop at a bounded interval. Fixture seeks use a timestamp within the known decoded-frame interval,
  never an ambiguous presentation-time boundary that another libmpv backend may resolve to the
  adjacent frame. Every pane sets libmpv
  `hr-seek-framedrop=no`, so a paused exact seek decodes to its target instead of allowing the
  decoder to discard target-adjacent frames. Raw-frame golden tests run on Linux/macOS headless CI;
  Windows skips them because libmpv cannot safely provide raw captures under Qt's `offscreen` platform.
  Interactive Windows rendering is separately verified through the Qt OpenGL renderer.
- **Headless Windows video CI**: GitHub-hosted Windows runners use the global Qt `offscreen`
  platform, so `VideoPane` selects libmpv's `vo=null` test path. Do not force native `wid` embedding
  in a headless job. Interactive Windows panes use libmpv's Qt OpenGL render API: the native `wid`
  path can decode while presenting only a gray child surface on affected Windows compositor/driver
  combinations.
- **Portable media runtime and demo launch**: `avialview.runtime` configures bundled media or the
  active conda environment before the lazy libmpv import, and `VideoStandardLoader` resolves an
  explicit `ffprobe` path rather than trusting the current directory or activated-shell PATH; on
  Windows it also finds the standard WinGet FFmpeg package path. `tools/launch_demo.py` delegates to
  the installed command so the two paths cannot drift. `avialview demo` generates the full three-CFR
  plus one-VFR camera demo under the platform application-data folder and serially imports its sensor,
  dense ephys/TTL, and tracking tables through the normal asynchronous source paths.
  Generation runs in `DemoGenerationWorker`, with a modal progress/log dialog, FFmpeg diagnostic
  errors, cancellation, and explicit reuse of already-created files. FFmpeg uses `-progress pipe:1`
  with `-loglevel error`; never read progress while leaving verbose stderr unread, or first-run demo
  generation can deadlock after the child process fills its stderr pipe. The dialog update endpoint
  is an explicit Qt `@Slot(int, str)`, and final loading is queued on the UI event loop: never
  connect a worker to a plain widget-mutating Python callback.
  Release staging rejects a bundle without `ffmpeg`, `ffprobe`, and libmpv.
- **Video pane shutdown**: `MainWindow.closeEvent()` calls `Player.stop()` and then
  `VideoGrid.shutdown()` before Qt destroys child widgets. This removes the precise 60 Hz timer and
  closes every `VideoPane`, so python-mpv can join its event thread;
  never rely on QWidget destruction or Python garbage collection to stop libmpv. On Windows/macOS, free the
  libmpv OpenGL render context while its `QOpenGLWidget` is current **before** `mpv.terminate()`;
  reversing that order aborts the process during app exit.
- **Frame-indexed sources (D-019)**: `TimeSeriesSource.is_frame_indexed()` added (default False). `TrackingLoader` overrides to True. Import fps resolution: 1 video → pre-filled confirm; multiple videos → dropdown; no video → manual entry + auto-rebind when first video is added.
- **NeoLoader.can_open tightening**: `SUPPORTED_EXTENSIONS` whitelist added; `can_open` returns 0.0 immediately for any file not in the whitelist. Never claims `.csv` or acts as a fallback for unknown files.

### Done — Inspection Layer (A–K, D-020)
- **Source Properties** (A/B): VideoPropertiesPanel (container, codec, profile/pix_fmt,
  resolution, nominal fps, measured fps, frame count, duration, GOP, decode mode, file size);
  SensorPropertiesPanel (channels + units, declared/measured rate, sample count, duration,
  dtype, file size, cache status, gap/NaN/sentinel counts, timestamp format/tz).
  Collapsible section inside existing VideoInfoWidget / SensorInfoWidget — extend, not parallel.
- **Load Provenance** (B): loader_id + import_config stored in SourceInspection; persisted to
  session schema v2; shown in properties panel.
- **Sync Provenance** (C): metadata start_time and drift_ppm surfaced in VideoPropertiesPanel
  (set_drift() API); offsets_panel.py left as stub — offset editing stays in
  VideoInfoWidget.offset_spin (one place only); no duplicate offset UI.
- **Precision Readouts** (D): ReadoutPanel shows per-channel value + unit + sample index;
  per-camera frame number and media timestamp below video rows.
- **Delta Measurement** (E): PlotPane measure markers (right-click Set Measure A/Set Measure B);
  measure_changed(t_a, t_b) signal; ReadoutPanel shows Δ section with Δt, Δvalue per channel,
  frames-between per camera. A/B loop in Transport remains loop-only.
- **Time Display Modes** (F): TimeDisplayMode enum (RELATIVE/UTC/LOCAL_TOD);
  format_time() in ui/time_format.py; toggle in View menu; persisted in QSettings; all
  time-displaying widgets subscribe to MainWindow.time_mode_changed(mode).
- **Import Report** (G): ImportWorker emits SourceInspection with ImportReport (rows_parsed,
  rows_dropped, gap_count, nan_count, sentinel_count); session schema v2; Report… button →
  ImportReportDialog.
- **Integrity Surfacing** (H): IntegrityFlags (vfr, fps_mismatch, has_gaps, drift_nonzero,
  fps_provisional); WarningBadge on VideoInfoWidget/SensorInfoWidget headers; gap markers
  (InfiniteLine objects) on existing per-channel coverage_region in PlotPane.
- **Units Everywhere** (I): SensorInfoWidget channel list shows `name (unit)`; ReadoutPanel
  _ChannelReadout.set_value(v, unit) appends unit string; VideoInfoWidget shows "fps" / "s" / "MB".
- **Copy as Text** (J): as_plain_text() + "Copy as text" QPushButton on VideoPropertiesPanel,
  SensorPropertiesPanel, ImportReportDialog.
- **Demo Data** (K): extended generate_demo_data.py produces camera_vfr.mp4 (dropped frames),
  sensors_gaps.csv (gaps/NaN/sentinel), pose.csv (DLC), camera_2.mp4 with +1.234 s offset,
  non-zero drift on camera_3; launch_demo.py loads them in D-019 rebind-triggering order.

### Implemented — TTL/event synchronization baseline (D-026)
- Scope: visual alignment of independently-clocked cameras, sensors, electrodes, and tracking
  data. Acquisition and built-in scientific analysis are out of scope; lab-specific semantics are
  plugin-owned.
- Core preserves raw timestamps and models raw events, matched pairs, affine offset/drift,
  residuals, and accepted session provenance. It remains headless.
- `SyncWizard` lets the user choose a cached TTL channel and video frame-event source, preview the
  mapping, then explicitly accept it. Never silently alter a `TimeMap`.
- `SyncWorker` extracts chunks off the UI thread; matching is deterministic. Unit/Qt coverage includes
  chunk boundaries, drift, missing/spurious/ambiguous pulses, session round-trip, and acceptance.
  `test_bench_sync.py` gates a 10,000-event preview at ≤250 ms locally; GitHub Actions checks the
  representative workload for correctness only and uses no timing multiplier.
- Follow-up: native plugin event providers remain separate API work; manual offset/drift fallback is
  available in the Sync Wizard.

### Pending
- **P4.6 plot review/sweep UX refinement — core implementation complete; certification remains
  (D-044):** `PLOT_UX_PLAN.md` remains the canonical contract. Review/Sweep/Scope, the shared
  continuous time-span control, master navigator viewport drag, one bottom axis and channel gutters,
  fit/auto/manual Y control, compact inspector tabs, native focus, and compatibility action proxies
  are implemented and covered by focused offscreen tests. The remaining release certification is the
  full representative 4/32/128-channel performance and three-platform manual field-data checklist;
  do not claim the latency budgets without those measurements.
- P3.5 performance/accurate-streaming hardening (audit 2026-07-29; closed 2026-07-30):
  - **P0 accuracy — done.** Plot envelopes render pyramid min/max; raw gap evidence is OR-reduced
    into every coarser level; CSV enforces an explicit timestamp schema with cross-chunk
    chronology/duplicate validation and the wizard timezone. Every time-series source now has a
    `TimeMap` (D-045): `MappedChannelReader` presents cached channels on the master clock, session
    schema v6 persists sensor `offset`/`drift_ppm`, and the sidebar offers the same offset/drift
    controls video already had. Re-aligning a source is a redraw, never a re-import.
  - **P0 streaming — done.** `ChannelStage` stages parser chunks to disk and materialises once, so
    peak import memory is one chunk per channel instead of the whole recording. `NeoLoader` reads
    blocks lazily and slices per batch. Gap *locations* are capped at 10 000 as display evidence
    while `gap_count` stays exact.
  - **P0 UI freeze — done.** Region statistics, CSV/Parquet export, PNG encoding, ffmpeg clipping,
    and now session save/load/autosave and annotation export all run on workers (D-046). A Qt
    heartbeat test fails if the event loop stalls during a one-million-pair session write. The
    close-time autosave is deliberately synchronous — the window is being destroyed.
  - **P1 identity — done.** `ChannelKey(source_id, channel_id)` keys plots, readouts, units,
    visibility, region statistics, and export (D-045). CSV export labels each block with its source;
    Parquet is long-form and never assumes a shared time axis.
  - **P1 hot path — done.** Authoritative time stays at 60 Hz; readout/pose presentation is
    rate-limited to 20 Hz and skipped when hidden; timeline evidence lanes are indexed by time so
    paint and hover scale with pixels, not event count (D-047).
  - **P1 loading — done.** Video metadata probes run bounded-parallel (3 at a time) while native
    pane construction stays serialized and in request order, preserving D-040 (D-048).
  - **P1 cache durability — done.** Cache commits retain the previous valid sidecar until the
    replacement is installed and recover an interrupted backup on the next validity check.
  - **Still open:** the representative *measurements*. The populated 4/32/128-channel performance
    certification, peak-RSS and second-open-latency numbers for a 1 GB / 180 M-sample import, and
    decoder-settle-plus-rendered-frame latency are not yet recorded. Existing microbenchmarks are
    baselines, not freeze-free certification. Do not claim the BLUEPRINT latency budgets without
    those runs on a real mid-spec machine.
  - **P2 maintainability — still open.** `ui/main_window.py` is ~2 400 lines and still owns loading,
    persistence, synchronization, export, and widget orchestration. Splitting it into bounded job
    controllers is unstarted.
- P5.2 release packaging: CI already builds a media-free one-directory artifact on every OS; the
  tag-only release workflow runs its cross-platform quality matrix, then smoke-tests the built
  wheel in a clean environment before building release-media installers. OIDC PyPI publishing
  starts only after every installer passes, and the GitHub Release is created last. The AppImage
  tool URL and checksum are pinned in the reviewed workflow, not set as repository variables.
  The PR and tag quality matrices share the same 3-OS × 2-Python headless test command, fixture
  determinism check, explicit ffmpeg/libmpv dependencies, and 60-second per-test watchdog. Windows
  quality and Windows bundling both use the same checksum-verified libmpv archive; only the
  platform-native package-manager commands remain intentionally different. A tag workflow first
  proves its commit is reachable from `main`; side-branch or detached tags cannot build or publish.
  The Ubuntu 24.04 AppImage build installs `libfuse2t64` because the pinned AppImageTool requires
  the `libfuse.so.2` ABI; never substitute the obsolete `fuse` package. The AppDir stages the
  reviewed `avialview.png` icon named by its desktop entry; AppImageTool rejects an undeclared or
  missing desktop icon. `assets/avial_view.png` is the canonical source; the generator transparently
  center-pads non-square artwork rather than stretching or cropping it. Regenerate
  Linux PNG, Windows ICO, macOS ICNS, and runtime PNG assets with `tools/generate_icons.py`.
  The AppDir also includes its required `.DirIcon` symlink and runs `desktop-file-validate` before
  AppImageTool, so malformed desktop metadata fails before artifact construction.
- P5.3 Read the Docs deployment: connect the repository to its Read the Docs project; CI already treats
  documentation warnings as errors.
- Native synchronization plugin API (D-026).

### Cross-platform pressure audit (D-040)
- Interactive rendering is intentionally platform-specific at one isolated boundary:
  Windows/macOS use libmpv's Qt OpenGL render API; Linux uses native `wid`; headless tests use
  `vo=null` on all three OSes. Timeline, seek, decoder, shutdown, and packaging contracts are
  exercised by the 3-OS × 2-Python workflow. A Windows-only local run cannot certify native
  compositing on physical macOS/Linux desktops, so release installers still require their native
  smoke tests.
- Burst video opens are serialized through native pane readiness, not merely through ffprobe
  completion. `VideoPane.file_loaded` is connected before playback, early seeks are retained until
  libmpv accepts commands, and the next Windows/macOS OpenGL pane is not constructed before the
  current pane is ready. The native Windows demo probe verifies four ready videos, 12 data channels,
  empty queues, and a responsive event loop.
- Every CI PyInstaller bundle must pass bounded headless startup before upload. Each staged-media
  release bundle additionally generates the demo in a fresh isolated directory and must load four
  ready video panes plus all 12 data channels before the smoke process exits successfully.
- Pyramid sidecar writes use a bounded three-worker pool. The unchanged 180 M-sample engineering
  benchmark dropped from 3.25 s to 2.07 s on the audited Windows machine; write failures propagate
  instead of reporting a successful import, and all-NaN blocks no longer emit misleading warnings.
- Hardware-decode probe errors are retained in diagnostics, every created mpv probe is terminated,
  and disk probes use unique temporary files so concurrent app instances cannot collide.
- Production-code guards reject `QApplication.processEvents()`, `shell=True`, and
  `except Exception: pass`. Expected transient media failures are logged rather than silently
  becoming a blank pane.

### Fixed (this PR — Phase 4 stabilization)
- Left-pane vertical QSplitter: `_left_splitter` in `main_window.py`; state persisted in QSettings `splitter/left`
- Video/3D horizontal QSplitter: `_media_splitter` gives the video grid and `Tracking3DPane` a
  draggable vertical handle; state is persisted in QSettings `splitter/media`. Complete cached
  `name_x` / `name_y` / `name_z` triplets render as the current pose with orbit, wheel zoom, and
  Fit View controls (D-041). No skeleton connectivity is inferred.
- Reset Zoom: wired to View → Reset Plot Zoom (Ctrl+0), timeline-row button, and shortcuts dialog
- Transport UX: the full-width **Data Streams** section is distinct from both plots and the
  seek/transport section with the native splitter handles used for video/plot resizing. Its header owns Hide, Flag Frame, Snapshot,
  Fullscreen Toggle, Reset Zoom, and compact status; busy work remains visible while ordinary messages clear shortly.
  Playhead controls precede master time and the seek bar; end time, A/B controls, and the labelled Speed selector follow it.
  Evidence renders source coverage, annotations, data
  gaps, accepted TTL matches, and playhead; the native handle resizes it against the video/plot workspace,
  never the seek/controls area. A fixed source-label
  gutter prevents coverage from painting beneath labels. It uses the
  system accent for video/TTL evidence.
- VFR: integrity is derived from presentation timestamps; its on-video OSD reports the current
  timestamp-derived rate, range, and nominal declaration, never a misleading single average rate.
- Bug: `video_grid._panes` → `video_grid.panes` (AttributeError on annotate)
- Bug: compact video summaries now receive the codec already probed by the video loader (no false `UNKNOWN`)
- Video availability: panes outside their mapped source bounds pause and show `No Footage`, matching Data Streams coverage
- Bug: negative relative master time is displayed as signed elapsed time (for example `-00:00:01.234`), never a wrapped clock value
- Bug: `Any` not imported from `typing` in `main_window.py`
- Bug: `_start_csv_import` → `_start_data_import` (AttributeError on session restore with sensors)
- Bug: `_update_window_title()` called but never defined — removed phantom call in `_on_channel_remove_requested`
- Bug: source-property copy text preserves the serialized path spelling instead of normalizing a
  foreign-platform path with the runner's `pathlib` implementation.
- Drag/drop routes files and directories through `LoaderRegistry` capability negotiation. Video
  workers are retained until their QThread finishes, so dropped videos now open reliably; Neo,
  tracking, sensor, and third-party source types route to their matching import pipeline.

### Pre-existing mypy errors (suppressed in pyproject.toml — cleanup is separate)
The standard full-package check still relies on module overrides for `ui/transport`, `ui/sidebar`,
`ui/relink_dialog`, `ui/diagnostics`, `ui/plot_pane`, `ui/video_pane`, `ui/readout_panel`,
`ui/video_grid`, `engine/export`, `loaders/neo_loader`, and `loaders/csv_loader`. Removing them
exposes 56 pre-existing Qt-stub, third-party-stub, and annotation errors. Strict `core/` checking
remains unsuppressed. A core-only mypy run reports UI overrides as unused because those modules are
outside that invocation; that message does not mean the full-package overrides are obsolete.

---

## Module Map

| File | Responsibility | Key API |
|---|---|---|
| `core/timeline.py` | Single master clock — HEADLESS, no PySide6 | `MasterClock`, `TimeMap`, `ClockState` |
| `core/pyramid.py` | Decimation pyramid (1×/16×/256×/4096×) | `PyramidReader`, `PyramidBuilder` |
| `core/cache.py` | Sidecar binary cache with content-hash key | `CacheManager` |
| `core/source.py` | Plugin ABCs — frozen API plus compatible video inspection extension | `TimeSeriesSource`, `VideoSource`, `VideoMetadata` |
| `core/session.py` | `.avv` session JSON, schema v5 | `SessionState`, `VideoEntry`, `SensorEntry`, `MarkerEntry`, `SyncProvenance` |
| `core/inspection.py` | Headless dataclasses for import stats + integrity (D-020) | `ImportReport`, `IntegrityFlags`, `SourceInspection` |
| `core/sync.py` | Headless synchronization evidence/model layer (D-026) | `SyncEvent`, `SyncProposal`, match/fit dataclasses |
| `core/channel_reader.py` | Master-clock view of a cached channel + scoped identity (D-045) | `MappedChannelReader`, `ChannelKey`, `disambiguate()` |
| `engine/player.py` | precise 60 Hz tick; decoder-independent MasterClock ↔ mpv ↔ UI | `Player.seek()`, `.set_playing()`, `.step_frame()`, `.stop()` |
| `engine/seeker.py` | Parallel seek across all mpv panes | `SeekGroup` |
| `engine/drop_worker.py` | Off-thread drop classification; AOL session fan-out, pose `role` tagging (D-046) | `DropScanWorker` — signals: `finished(candidates, is_aol)`, `session_found`, `error` |
| `engine/session_worker.py` | Off-thread `.avv` save/load | `SessionSaveWorker`, `SessionLoadWorker` |
| `engine/export_worker.py` | Off-thread region stats / data slice / clip / snapshot | `RegionStatsWorker`, `DataExportWorker`, `ReaderReference` |
| `engine/video_worker.py` | Off-thread video probe before native pane creation | `VideoOpenWorker` |
| `loaders/aol_session_loader.py` | AOL folder detection + manifest (videos, 2D/3D pose, encoder, timing) | `is_aol_session()`, `build_manifest()`, `AOLManifest`, `AOL2DTrack` |
| `loaders/aol_eks_loader.py` | AOL 3D EKS CSV; frame-indexed x/y/z triplets | `AOLEksLoader` (`read_all_chunks` is the bulk API) |
| `loaders/aol_encoder_loader.py` | AOL encoder log; seconds-since-midnight, midnight-unwrapped (D-045) | `AOLEncoderLoader` |
| `engine/importer.py` | Background import worker (QThread); emits SourceInspection | `ImportWorker` — signals: `finished(path, cache_dir, channels, bounds, inspection)`, `progress`, `error` |
| `engine/proxy.py` | ffmpeg proxy generation (cancelable poll loop) | `ProxyWorker` |
| `engine/sync_worker.py` | Chunked event extraction and deterministic alignment fit (D-026) | `SyncWorker`, evidence specs |
| `engine/session_worker.py` | Off-UI-thread session save/load and annotation export (D-046) | `SessionSaveWorker`, `SessionLoadWorker`, `AnnotationExportWorker` |
| `engine/export.py` | Snapshot, data slice, video clip, region stats | `save_snapshot()`, `export_data_slice_csv()`, `trim_video_clip()`, `compute_region_stats()` |
| `ui/main_window.py` | Top-level; wires all signals; session lifecycle; `_inspections` dict | `MainWindow` |
| `ui/video_pane.py` | Single mpv-embedded `QOpenGLWidget` | `VideoPane`, `set_sync_correction()` |
| `ui/video_timing.py` | Timestamp rate/readout/frame-index helpers and pane timing mixin | `VideoTimingMixin`, `format_video_osd()` |
| `ui/video_overlay.py` | Transparent current-frame tracking paint layer | `PaintCanvas` |
| `ui/video_grid.py` | N VideoPanes; persistent visibility; single `QGridLayout`; `_relayout()` | `add_pane()`, `remove_pane()`, `set_pane_visible()`, `visible_panes()`, `set_grid_mode()` |
| `ui/plot_pane.py` | Coordinator for linked pyramid plot rows, presentation, shared X/Y state, and navigator signal | `load_channels()`, `set_window_duration()`, `set_cursor()`, `set_channel_y_mode()` |
| `ui/plot_header.py` | Compact plot presentation, page, Y-fit, row-height, and reset controls | `PlotHeader` |
| `ui/plot_row.py` | One channel row's bounded envelope, retained sweep page, gutter, Y state, coverage, and close control | `ChannelPlot`, `create_channel_plot()`, `fit_channel_y()` |
| `ui/plot_sweep.py` | Review/Sweep/Scope state and shared unit-converting logarithmic time-span control | `PlotPresentation`, `SweepWindowControl`, `SweepCurveItem` |
| `ui/plot_interactions.py` | Plot context actions, measurement, annotation, and gap interaction state | `PlotInteractionController` |
| `ui/plot_overlays.py` | Bounded page-local overlay drawing and plot context menu helpers | `redraw_annotations()`, `redraw_measure_lines()` |
| `ui/tracking_3d_pane.py` | Current-pose XYZ projection from cached triplets; orbit/zoom/fit | `Tracking3DPane.set_readers()`, `set_cursor()` |
| `ui/transport.py` | Seek row with playhead/A-B/rate controls + D-027 named, conditional Data Streams header/status | `set_time()`, `set_bounds()`, `set_source_coverage()`, `set_ttl_events()`, `set_gap_events()`, `set_annotation_markers()`, `set_status()` |
| `ui/sidebar.py` | File management; video/channel visibility; WarningBadge; links to properties panels | `SidebarPane`, `VideoInfoWidget`, `SensorInfoWidget` |
| `ui/source_properties.py` | Collapsible detail for video + sensor sources; copy-as-text (D-020) | `VideoPropertiesPanel`, `SensorPropertiesPanel` |
| `ui/import_report.py` | ImportReportDialog — scrollable import stats + "Copy as text" (D-020) | `ImportReportDialog` |
| `ui/time_format.py` | TimeDisplayMode enum + format_time() — single formatting authority (D-020) | `TimeDisplayMode`, `format_time()` |
| `engine/drop_worker.py` | Off-thread drop scanning and AOL session candidate collection | `DropScanWorker` |
| `loaders/aol_session_loader.py` | AOL session manifest: raw videos, fused per-camera EKS, encoder | `build_manifest()`, `is_aol_session()` |
| `loaders/aol_eks_loader.py` | AOL 2D/3D pose CSV ingest | `AOLEksLoader` |
| `loaders/aol_encoder_loader.py` | AOL encoder log ingest | `AOLEncoderLoader` |
| `ui/video_overlay.py` | Live pose overlay with named markers | `PaintCanvas`, `OverlayTrack` |
| `ui/recent_files.py` | Recent-session list in QSettings — kept out of `core/` (rule 2) | `add_recent()`, `get_recent()`, `clear_recent()` |
| `ui/offsets_panel.py` | Stub — offset editing stays in `VideoInfoWidget.offset_spin`; not filled by D-020 | — |
| `ui/readout_panel.py` | Live per-channel values + units + sample index + Δ section | `update_sources()`, `set_cursor()`, `show_region_stats()`, `show_delta()` |
| `ui/annotations.py` | Annotation store + list panel | `AnnotationStore`, `AnnotationPanel` |
| `ui/theme.py` | QPalette + system/dark/light appearance only | `apply_theme()`, `load_saved_theme()`, `current_preference()`, `THEME_SYSTEM/DARK/LIGHT` |
| `ui/import_wizard.py` | CSV import dialog | `ImportWizard` |
| `ui/diagnostics.py` | Startup probe (hw-decode, disk speed) — async daemon thread | `run_startup_diagnostics()` |
| `loaders/csv_loader.py` | polars CSV ingest; epoch/time-of-day/datetime, euro-decimal, sentinel, BOM | `CSVLoader` |
| `loaders/tracking_loader.py` | DeepLabCut CSV loader; multi-scorer; flat-headers per bodypart/coord | `TrackingLoader` |
| `loaders/neo_loader.py` | Neo electrophysiology (OpenEphys/NCS/NIX); BFS dataset root detection; extension whitelist via `SUPPORTED_EXTENSIONS` | `NeoLoader` |

---

## Architecture Rules (violations = rejected PR)

1. Single master clock in `core/timeline.py`. UI and sources NEVER keep independent time state.
2. `core/` is headless — importing it must not import PySide6. Enforced by test.
3. UI thread never blocks. Any operation >30ms gets a worker thread + progress signal.
4. Plotting only via decimation pyramid. Never pass raw full-resolution arrays >100k samples to pyqtgraph.
5. All data sources go through plugin ABCs in `core/source.py`. No format special-casing in UI code.
6. Sync correctness beats frame completeness. Drop frames, never drift. Paused/stepping: exact seeks only.
7. Text data parsed once → binary sidecar cache, mmap-read afterwards.
8. No GPL/AGPL dependencies. New dep requires license named in PR + pip-installable on all 3 OSes.
9. No module >~500 lines; no function >~60 lines. Errors: typed exceptions from `core/errors.py`. Never `except Exception: pass`.

---

## Signal Wiring Map

All connections established in `MainWindow.__init__` unless noted.

### Sidebar → MainWindow → subsystems

| Signal | Handler / Target |
|---|---|
| `sidebar.open_video_requested` | `_open_video()` |
| `sidebar.open_sensor_requested` | `_open_data()` |
| `sidebar.video_offset_changed(path, offset)` | `_on_video_offset_changed` → `video_grid.set_offset` |
| `sidebar.video_remove_requested(path)` | `_on_video_remove_requested` → `video_grid.remove_pane` + `sidebar.remove_video` |
| `sidebar.video_visibility_changed(path, bool)` | `video_grid.set_pane_visible` (direct) |
| `sidebar.sensor_remove_requested(path)` | `_on_sensor_remove_requested` → `plot_pane.remove_channels` + `sidebar.remove_sensor` |
| `sidebar.channel_remove_requested(path, ch)` | `_on_channel_remove_requested` → `plot_pane.remove_channel(ch)` |
| `sidebar.channel_visibility_changed(path, ch, bool)` | `_on_channel_visibility_changed` → `plot_pane.set_channel_visible(ch, bool)` |
| `sidebar.grid_mode_changed(bool)` | `video_grid.set_grid_mode` (direct) |

### Transport → Player → subsystems

| Signal | Handler |
|---|---|
| `transport.play_toggled(bool)` | `player.set_playing(bool)` |
| `transport.seek_requested(t, exact)` | `player.seek(t, exact)` |
| `transport.rate_changed(float)` | `player.set_rate(float)` |
| `transport.frame_step_requested(int)` | `player.step_frame(int)` |
| `transport.ab_loop_changed(t_in, t_out)` | `player.set_ab_loop` AND `_on_ab_loop_changed` (readout stats) |
| `transport.annotate_requested` | `_on_annotate_requested()` |
| `transport.snapshot_requested` | `_export_snapshot()` |
| `transport.fullscreen_requested` | `_toggle_fullscreen()` — toggles fullscreen of first pane or active pane |
| `transport.jump_requested(float delta)` | `_on_jump_requested(delta)` → `player.seek(t + delta, exact=True)` |
| `transport.reset_zoom_requested` | `plot_pane.reset_zoom()` |
| `video_grid.pane_right_clicked(path, QPoint)` | `_on_pane_right_clicked` → context menu: fullscreen / snapshot / properties / copy frame info |
| `plot_pane.annotate_at_requested(float t)` | `_on_annotate_at_requested(t)` → `annotation_store.add_point(t, ...)` |

### PlotPane / Player → downstream

| Source | Target |
|---|---|
| `plot_pane.sources_changed(readers)` | `readout_panel.update_sources` + `video_grid.set_tracking_readers` |
| `plot_pane.sources_changed(readers)` | `tracking_3d_pane.set_readers` for complete XYZ triplets |
| `plot_pane.measure_changed(t_a, t_b)` | `readout_panel.show_delta(t_a, t_b, panes)` |
| `plot_pane.channel_close_requested(channel)` | `sidebar.set_channel_visible(channel, False)` → existing checkbox visibility signal |
| `player._on_tick()` — direct calls | `plot_pane.set_cursor(t)`, `transport.set_time(t)`, `readout_panel.set_cursor(t)` via `player._readout_panel` attr |
| `Player._update_timeline_views(t)` | `tracking_3d_pane.set_cursor(t)` when the optional pane is present |

### Time display mode (D-020)

| Signal | Handler / Target |
|---|---|
| `MainWindow.time_mode_changed(mode)` | `transport.set_time_mode(mode)`, `readout_panel.set_time_mode(mode)`, all properties panels |
| View menu "Time: Relative / UTC / Local" | `MainWindow._on_time_mode_action(mode)` → persists to QSettings, emits `time_mode_changed` |

### Source properties + integrity (D-020)

| Signal | Handler / Target |
|---|---|
| `VideoInfoWidget.badge_clicked(path)` | `MainWindow._show_video_properties(path)` → shows VideoPropertiesPanel |
| `SensorInfoWidget.badge_clicked(path)` | `MainWindow._show_sensor_properties(path)` → shows SensorPropertiesPanel |
| `SensorInfoWidget.report_requested(path)` | `MainWindow._show_import_report(path)` → ImportReportDialog |
| `VideoPropertiesPanel.copy_requested` | copies `as_plain_text()` to clipboard |
| `SensorPropertiesPanel.copy_requested` | copies `as_plain_text()` to clipboard |

### Import pipeline (updated, D-020)

```
_start_data_import(path)
  → ImportWizard.exec()          # CSV only; returns config dict
  → ImportWorker (QThread)        # now also builds ImportReport + IntegrityFlags
      finished(path, cache_dir, channels, bounds, inspection: SourceInspection)
        → plot_pane.load_channels(cache_dir, channels)
        → _update_bounds(t0, t1)
        → sidebar.add_sensor(path, channels)
        → sidebar.set_sensor_inspection(path, inspection)   # populates badge
        → MainWindow._inspections[path] = inspection        # persisted to session v2
```

---

## Known Traps

### 0a. A `QObject` moved to a `QThread` needs an owning Python reference
`worker.moveToThread(thread)` does **not** transfer ownership. With no Python reference the wrapper
is garbage-collected before `QThread.started` fires and `run()` never executes — silently, with no
error. This killed drag-and-drop and session save/load simultaneously.
**Fix:** start every background job through `MainWindow._run_job()`, which keeps the pair in
`self._jobs` until `thread.finished`. Never hand-roll the `QThread(self)` + `moveToThread` dance.

### 0b. Do NOT add the anchor date to AOL encoder timestamps (D-045)
The AOL master axis is *seconds since midnight UTC*: `drop_worker` subtracts the anchor epoch from
video/EKS start epochs, landing them on the axis `_parse_wall_clock` already produces. Adding
`config["anchor_date"]` inside `AOLEncoderLoader` shifts it ~20.6 days out of alignment. Measured on
the reference session: video `[34526.312…34586.502]`, EKS `[34526.312…34586.499]`, encoder
`[34526.082…34586.964]`. `test_encoder_axis_is_seconds_since_midnight` guards this.

### 0c. AOL pose data must not become plot rows (D-046)
One session emits 27 3D channels and ~81 2D channels *per camera* (12 pose files across 3 cameras on
the reference session). Import candidates carry `role="overlay2d"`/`"pose3d"`; `_on_import_finished`
routes those to the overlay / 3D view instead of `plot_pane.load_channels`. 2D goes to the pane for
its own video path only — every camera and model emits `head_bar_x`, so broadcasting paints SideCam
points over FaceCam. 2D carries no `start_epoch` (overlay uses mpv's media clock); 3D does (master time).

### 0d. `"_eks.csv".split("_")[0]` is `""` — and `"" in name` matches everything
The session-level 3D file names no camera, so substring-matching its leading token bound it to
whichever video came first. Blank tokens are ignored in `_resolve_eks_start_epoch`, which falls back
to the earliest camera start with a log line.

### 1. No bare `QWidget { }` QSS selector — blacks out video panes
`QWidget { background-color: ... }` in QSS applies to `QOpenGLWidget` too, painting over the GL surface.  
**Fix:** Use QPalette for all theme colours. Application-level QSS changes native control metrics and
can change seek/scrollbar/splitter behavior, so `ui/theme.py` sets no theme stylesheet at all.

### 2. `setParent(None)` makes a widget a popup window
Detaches the widget from its parent, promoting it to a standalone window with its own frame.  
**Fix:** To remove from a layout without destroying: `layout.takeAt(index)` + `widget.hide()`. To destroy: `widget.deleteLater()`. See `VideoGrid._relayout()` — uses `takeAt(0)` in a loop, never `setParent`.

### 3. `setLayout()` silently fails if layout already exists
A second `setLayout()` call on a QWidget that has a layout is silently ignored.  
**Fix:** Build the layout once in `__init__`, never reassign. Use a child container widget if a different structure is needed.

### 4. LC_NUMERIC must be 'C' after Qt import, before mpv
Qt stomps LC_NUMERIC on import. libmpv uses it to parse float seeks and options. In decimal-comma locales, `1.5` becomes `1`.  
**Fix:** `locale.setlocale(locale.LC_NUMERIC, 'C')` in the entry point, after Qt imports, before the first `mpv.MPV()`.

### 5. Never import mpv at module top level (D-013)
Top-level `import mpv` causes a ctypes crash before any UI renders when libmpv is missing.  
**Fix:** Lazy import inside a function/method only, after startup diagnostics confirm libmpv is present.

### 6. Video pane needs `WA_StyledBackground = False`
Without it, ancestor QSS may bleed through and paint over the OpenGL surface even when no bare `QWidget` selector exists.  
**Fix:** `VideoPane` and `MpvGLWidget` both call `setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)` in `__init__`. Do not remove these.

### 7. Drive MasterClock from `time.monotonic()` — never accumulate timer intervals
QTimer fires late under UI load. Accumulating the interval leads to drift.  
**Fix:** `delta = now - self._last_tick_monotonic` where `now = time.monotonic()`.

### 8. Drift correction needs hysteresis (5 consecutive ticks)
Seeking on every off-target tick causes stutter cascades.  
**Fix:** Player keys `_drift_counts` by pane identity; re-seeks only after 5 consecutive ticks
above the frame-aware hard threshold, then resets the counter. A seeking pane is skipped while
healthy panes continue, and no decoder may freeze `MasterClock`.

### 9. polars `read_csv` type inference flips per-chunk
Without an explicit schema, the timestamp column type can change between chunks.  
**Current audit finding:** `CSVLoader` does not yet pass that schema. P3.5 must derive an explicit
timestamp dtype from the accepted wizard configuration and test a file whose later batch would
otherwise infer a different type.

### 10. `python-mpv` (PyPI) ≠ `mpv` (PyPI)
The correct dependency is `python-mpv` on PyPI, imported as `import mpv`. The package named `mpv` on PyPI is a different unrelated project (D-017).

### 12. ruff `line-length = 100` — IDE diagnostics at 79 chars are false positives
`pyproject.toml` sets `line-length = 100`. Editor/Pylance red-underline at 79 chars is wrong.
Only `conda run -n avialview ruff check .` is authoritative.

### 13. `_load_level()` is private — use the bounded read API (D-045)

`PyramidReader` exposes `coverage()`, `sample_count()`, `sample_at()`, `value_at()`, `raw_slice()`,
`iter_raw_chunks()`, and `mapped_columns()`. Every consumer reads through those.
`tests/test_pyramid_read_api.py` parses the source tree and **fails the build** if any module
outside `core/pyramid.py` calls `_load_level`.

`mapped_columns()` returns level-1 mmap **views in source time** on purpose — converting a whole
time column to master time would materialise the recording. Tick-rate consumers convert their
scalar query instead: `reader.time_map.to_source(t_master)`.

### 14. Session v1 → v2 migration: SensorEntry / VideoEntry gain new optional fields
`SourceInspection` data is stored as dict in SensorEntry. When loading a v1 session, these fields
are absent — callers must use `.get()` with defaults, never `entry["inspection"]` (KeyError).
`_inspections` dict in MainWindow may be empty for v1-loaded sources — properties panels must
handle None inspection gracefully (show "—" for all stats).

### 15. Never cache time→pixel positions; map from current geometry at paint time
Overlay widgets (e.g. A/B pins) positioned with `setGeometry()` at event time hold stale pixel
coordinates after the parent is resized. The time→pixel mapping must be a pure function of
`(t, bounds, current groove rect)` called on every resize, not once at pin-set time.  
**Fix:** `Transport.resizeEvent` calls `_repin()`, which recomputes each visible pin's position
from the stored time via `_time_to_frac(t)` + `_ABPin.pin_to_slider()` using
`QStyle.subControlRect(SC_SliderGroove)` against the live slider geometry.  
pyqtgraph gap/measure markers (`pg.InfiniteLine`) are safe — pyqtgraph remaps data coordinates
to pixels via the ViewBox transform on every paint call; no cached pixel positions exist.

### 18. System-key collisions — Ctrl+V and Ctrl+D are reserved (D-022)

Ctrl+V is the system Paste shortcut on all three platforms. Ctrl+D is the browser/dock
bookmark shortcut on macOS/Windows. Binding application actions to these keys means:
- On macOS: the system intercepts Ctrl+V before Qt sees it → Open Video never fires.
- On Windows: QShortcut wins but breaks paste in Qt text widgets in the same window.
- On Linux: behavior varies by WM/toolkit — unreliable.

**Fix (D-022.7):** Open Video → `Ctrl+Shift+V`; Open Data → `Ctrl+Shift+D`.
Never bind Ctrl+V or Ctrl+D to any application action. This is a permanent trap.

### 19. VideoPane right-click: eventFilter, NOT CustomContextMenu policy (D-022)

Setting `setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)` on `VideoPane` does **not**
work because libmpv's rendering surface (`MpvGLWidget` / the native `video_container`) intercepts
raw mouse events at the OS level before Qt's event loop sees them. The `ContextMenu` event (type
int 82) is generated by the OS and lands on the mpv widget, which never propagates it up via the
standard Qt mechanism.

**Fix:** `VideoPane.__init__` calls `self._video_widget.installEventFilter(self)`. The `eventFilter`
checks `int(event.type()) == 82` (ContextMenu) and emits `right_clicked(event.globalPos())`, then
returns `True` to consume the event. `VideoGrid.add_pane` connects `pane.right_clicked` to
`self.pane_right_clicked.emit(_p, pos)`. `MainWindow` connects `video_grid.pane_right_clicked` to
`_on_pane_right_clicked`, which builds the QMenu. Never remove the eventFilter or switch to
`CustomContextMenu` — the menu will silently never appear on macOS/Windows with mpv embedded.

### 11. Annotation label edits via `markers` property are silently discarded
`AnnotationStore.markers` returns `list(self._markers)` — a copy. Edits to the copy are lost.  
**Fix:** Access `self._markers` directly when mutating. See `annotations.py:_on_label_edited`.

### 16. `type: ignore` is never a shipping mechanism
Silencing a type checker to work around a known crash is forbidden. Only two legitimate uses:
1. **Genuine mypy limitation** — e.g. `**dict[str, object]` unpacking where the dict structure
   is guaranteed by the caller but mypy can't prove it.
2. **Missing third-party stubs** — e.g. an untyped PyPI package with no `py.typed` marker.

In both cases: document the reason in the comment, not just the suppression. Example:
```python
# type: ignore[arg-type]  # dict[str,object] from our own serializer; shape guaranteed
```
A `# TODO: fix later` comment next to `# type: ignore` is a red flag — stop and fix it now.

**Trap that was caught (D-021):** `_on_annotate_requested` accessed `pane.time_map.path`
which was guarded with `# type: ignore[attr-defined]`. TimeMap has no `.path` attribute.
The crash was real, committed, and silently shipping. Fix: `video_grid.frame_records_at()`
is the single authority for frame computation; MainWindow never reaches into pane internals.

### 20. mypy silently ignores malformed override sections
If you use array syntax `module = ["module_a", "module_b"]` in `pyproject.toml` `[[tool.mypy.overrides]]`, mypy does not support it. It silently treats it as an invalid section. Any "unused section" warning from mypy means the configuration is completely broken and ignored, **not** that the files inside it type-check cleanly! Always use single `module = "..."` per block.

### 21. QSplitter.restoreState also restores `childrenCollapsible` (D-049)

A layout saved before a collapse policy existed will silently re-enable collapsing when restored,
and can carry a zero-size pane that has no handle affordance left to recover it.
**Fix:** `MainWindow._enforce_splitter_policy()` and `_repair_collapsed_panes()` run *after* every
`restoreState`. Stretch factors alone are not enough either — Qt hands a pane zero pixels when its
sibling's size hint already fills the splitter, which is how the plot area shipped fully collapsed.
Always seed explicit `setSizes` as well.

### 22. Presentation refresh is 20 Hz, not 60 Hz (D-047)

`Player._update_timeline_views` refreshes readout labels and pose sampling at 20 Hz and skips them
entirely while hidden; the clock, plot cursor, and seek bar still see all 60 ticks. A test that
asserts a readout value must pass `force=True` or advance past the interval, or it will read a
stale label. The method takes the caller's `time.monotonic()` value and must never sample the clock
itself — doing so perturbs the tick's drift accounting and broke `test_scrubbing` once already.

### 23. Channel names are not unique — key by `ChannelKey` (D-045)

Two loaded files can both contain `force_z`. Plots, readouts, units, visibility, region statistics,
and export are keyed by `ChannelKey(source_id, channel_id)`. The sidebar already emits
`(path, channel)`; pass both through. `PlotPane` still accepts a bare name for compatibility but
logs a warning when more than one source owns it — do not rely on that path in new code.

### 24. Media subprocesses must splat `no_window_kwargs()` (V-14, D-050)

A windowed Windows build has no console, so every `ffprobe`/`ffmpeg` child gets
a brand new one that flashes and steals focus — four times during a four-camera
load. `runtime.no_window_kwargs()` returns `CREATE_NO_WINDOW` on Windows and an
empty mapping elsewhere. Its return type is a `TypedDict`, not `dict[str, int]`,
so mypy can still resolve the `subprocess.run`/`Popen` overloads through the
splat; changing it back to a plain dict reintroduces 4 mypy errors.
`tests/test_subprocess_no_window.py` fails the build on a new unguarded call.

### 25. `VideoPane.__init__` must build its chrome on every path (V-11, D-013)

The libmpv probe used to `return` before `paint_canvas`/`overlay`/`lbl_name`/
`lbl_osd`/`lbl_no_footage` existed, so every later `set_label`,
`set_has_footage`, or `set_tracking_readers` raised AttributeError — a crash
cascade right after the guided-install dialog. `_build_overlay_chrome()` is
called on both the success and the probe-failure path. Keep the success-path
call where it is: the QGridLayout stacks by insertion order, so video must be
added before the canvas and overlay.

### 26. AOL sessions load raw video + one fused EKS track per camera

`build_manifest` prefers root `*.mp4` over `labeled_videos/` because the overlay
is drawn live — a rendered copy would show every marker twice and could not be
toggled. `_collect_2d_tracks` keeps only `*_eks.csv` (one per camera); the
`model_N/` contributing predictions are intermediate pipeline output. Pose data
never reaches a plot row: `overlay2d`/`pose3d` roles route through
`_register_tracking_source`, not `plot_pane.load_channels`.

### 17. Annotation schema (v3) — per-video frame records

**`Marker` (in-memory):**
```python
@dataclasses.dataclass
class VideoFrame:
    path: str
    frame_index: int
    media_timestamp: float


@dataclasses.dataclass
class Marker:
    t_start: float
    t_end: float | None
    label: str
    color: str
    video_frames: list[VideoFrame]  # one entry per loaded video at mark time
```

**`MarkerEntry` (session file, v3):**
```json
{
  "t_start": 1.5, "t_end": null, "label": "stance",
  "video_frames": [
    {"path": "/cam/left.mp4", "frame_index": 45, "media_timestamp": 1.5}
  ]
}
```

**Schema versions:**
- v1: `{t_start, t_end, label}` — no video_frames  
- v2: same marker schema as v1  
- v3: adds `video_frames: []` to each marker (defaults to `[]` when loading v1/v2)

**Single authority:** `VideoGrid.frame_records_at(t_master)` computes per-pane records.
MainWindow calls it and converts to `VideoFrame` objects — no fps/time_map logic anywhere else.

**Export CSV** (`export_csv(path)`) writes one row per (marker × video):
`label, comment, t_master, video_path, frame_index, media_timestamp`
Plain CSV for DLC/LightningPose retraining pipelines.

---


## Run Commands

```bash
# Install
conda run -n avialview pip install -e .[dev]

# Run the app
conda run -n avialview avialview

# Run with sample data
conda run -n avialview avialview open tests/fixtures/sample_session/

# Generate test fixtures (needs ffmpeg in PATH)
conda run -n avialview python tools/make_fixtures.py

# Tests (offscreen)
QT_QPA_PLATFORM=offscreen conda run -n avialview pytest -x -q

# Lint + format
conda run -n avialview ruff check --fix . && conda run -n avialview ruff format .

# Type check
conda run -n avialview mypy src/avialview/core/

# Performance benchmarks
QT_QPA_PLATFORM=offscreen conda run -n avialview pytest --benchmark-only

# Release preflight, version commit, annotated tag, and push (tag workflow publishes)
conda run -n avialview python tools/prepare_release.py 0.1.0b1 --dry-run
conda run -n avialview python tools/prepare_release.py 0.1.0b1
```

---

## Shortcuts Reference (D-022)

### Playback

| Key | Action |
|---|---|
| `Space` | Play / Pause (via `transport.play_toggled`) |
| `←` | Step back 1 frame (via `transport.frame_step_requested(-1)`) |
| `→` | Step forward 1 frame (via `transport.frame_step_requested(+1)`) |
| `,` | Step back 1 frame (alias for `←`) |
| `.` | Step forward 1 frame (alias for `→`) |
| `Shift+←` | Jump back 1 second |
| `Shift+→` | Jump forward 1 second |
| `J` | Jump back 1 second (via `transport.jump_requested(-1.0)`) |
| `K` | Pause (via `transport.play_toggled(False)`) |
| `L` | Step up playback rate (via `transport.rate_changed`) |
| `Home` | Jump to start |
| `End` | Jump to end |

Time and plot-window editors protect Space while text is being entered. Enter accepts a valid value
and returns focus to the containing playback surface, so the next Space immediately plays/pauses.

### Marking

| Key | Action |
|---|---|
| `[` | Set A/B loop in-point |
| `I` | Set A/B loop in-point (alias for `[`) |
| `]` | Set A/B loop out-point |
| `O` | Set A/B loop out-point (alias for `]`) |
| `M` | Add point marker at playhead |

### View

| Key | Action |
|---|---|
| `Ctrl+0` | Reset plot zoom (single QAction authority) |
| `+` | Plot zoom in |
| `-` | Plot zoom out |
| `Ctrl+T` | Cycle theme (System → Dark → Light) |
| `F11` / platform FullScreen | Toggle pane fullscreen (`StandardKey.FullScreen`) |
| `F1` | Shortcuts dialog (`StandardKey.HelpContents`) |
| `?` | Shortcuts dialog (alias) |

### File

| Key | Action |
|---|---|
| `Ctrl+S` / `Cmd+S` | Save session (`StandardKey.Save`) |
| `Ctrl+O` / `Cmd+O` | Open session (`StandardKey.Open`) |
| `Ctrl+Shift+V` | Open Video(s)… |
| `Ctrl+Shift+D` | Open Sensor/Ephys Data… |
| `Ctrl+E` | Export Snapshot (single QAction authority) |
| `Ctrl+Q` / `Cmd+Q` | Quit (`StandardKey.Quit`, `QuitRole`) |


---

## Performance Budgets (engineering-certified where ★)

★ budgets are asserted in `tests/benchmarks/test_bench_pyramid.py` via
`benchmark.stats["mean"] <= budget` without any multiplier. Run them locally on the intended
engineering machine. GitHub Actions verifies the representative multi-camera/multi-stream workload
for correctness only; it is not a speed authority. Never add per-test multipliers (D-023, D-029).

| Metric | Budget |
|---|---|
| Scrub response (3 cams, exact seek) | ≤ 250 ms |
| Plot pan/zoom frame time ★ | ≤ 16 ms |
| Full populated cursor update per tick ★ | ≤ 2 ms |
| 3D pose sample (128 points) ★ | ≤ 2 ms |
| Cached session open (3 cams + 4×50 kHz) | ≤ 3 s |
| First CSV import 1 GB | ≤ 60 s |
| Pyramid build 180 M samples ★ | ≤ 2.5 s (revised, D-024) |
| Idle RAM, session loaded | ≤ 2.5 GB |
| Any UI-thread callback | target ≤ 8 ms, hard ceiling 30 ms |

The pyramid builder creates the 16× level from raw data, then derives 256× and
4096× levels from the preceding min/max envelopes. This preserves exact envelopes
while avoiding repeated full-resolution passes. Its current coarse gap masks are
recomputed from coarse timestamps, however, so P3.5 must OR-reduce raw gap evidence
into parent buckets. The raw gap scan is chunked to avoid a large temporary
timestamp-difference allocation.
