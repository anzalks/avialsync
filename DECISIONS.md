# DECISIONS.md — lightweight ADR log
Format per entry: date · decision · context · alternatives rejected · consequences.
Agents: read before coding; append when making irreversible choices; never silently reverse entries.

## 2026-07 · D-051 · MainWindow may not be split into Qt-slot mixins

**Context:** `ui/main_window.py` is ~2 500 lines, over the ~500-line rule
(V-09 / BLUEPRINT P2-maintainability). The obvious cheap fix is to move method
groups into mixin classes that `MainWindow` inherits, keeping every method name
and `self` intact so no caller or test changes.

**Decision:** do not do this. It was implemented, measured, and reverted.

Moving `@Slot`-decorated methods onto a plain mixin class changes how PySide
resolves the connection. Two failures were reproduced, not theorised:

1. `QObject.sender()` returns `None` inside an inherited slot, so every
   `_on_*_thread_finished` handler stopped removing its thread from the job
   registry. Any queue gated on `len(registry)` stalled — a five-camera load
   started three probes and hung.
2. Worse, `worker.opened` reached `_on_video_opened` through a **direct**
   connection instead of a queued one, so `video_grid.add_pane` — which builds
   widgets — ran on the worker thread. `tests/test_ui_main.py::
   test_drop_real_video_completes_async_open` asserts that thread identity and
   caught it. Passing `Qt.ConnectionType.QueuedConnection` explicitly did not
   fix it.

A 2 500-line module is a review hazard. Creating widgets off the UI thread is a
crash. The line-count rule does not outrank architecture rule 3.

**Alternatives rejected:** mixins (this entry); `functools.partial`-bound
connections (same direct-connection problem); relaxing the size rule for this
file (it hides real UI-thread work, which is why the rule exists).

**Consequences:** the split must be done as **composition** — each controller a
real `QObject` that owns its own slots and holds a reference to the window, with
signals connected between two genuine QObjects so thread affinity is preserved.
That is a larger change than a mechanical extraction and needs its own task.
Until then `main_window.py` stays oversized and V-09 stays open. Any future
attempt must keep `test_drop_real_video_completes_async_open` green — it is the
tripwire for off-thread widget creation.

## 2026-07 · D-045 · Bounded reads, source TimeMaps, and scoped channel identity

**Context:** the P3.5 audit left four correctness/scale gaps: `PyramidReader._load_level` leaked to
five subsystems that could each materialise a whole recording; imports accumulated complete channels
with `np.concatenate`; time-series sources had no `TimeMap`, so a sensor on its own clock could not
be aligned; and channel names were treated as globally unique.

**Decision:**
1. `PyramidReader` exposes a bounded read API — `coverage`, `sample_count`, `sample_at`, `value_at`,
   `raw_slice`, `iter_raw_chunks`, `mapped_columns`. `_load_level` is private and an AST guard test
   fails the build if any module outside `core/pyramid.py` calls it.
2. `core/pyramid.ChannelStage` stages parser chunks to disk; `PyramidBuilder.save_levels(
   include_base=False)` lets a streamed import write each raw sample exactly once. `NeoLoader` reads
   blocks lazily and slices per batch.
3. `core/channel_reader.MappedChannelReader` presents a cached channel on the master clock through a
   `TimeMap`. Only bounded results are converted; `mapped_columns` stays in source time on purpose,
   because converting a whole time column would copy the recording. Session schema v6 persists
   sensor `offset`/`drift_ppm`. Re-aligning a source is a redraw, never a re-import.
4. Identity is `ChannelKey(source_id, channel_id)` across plots, readouts, units, visibility, region
   statistics, and export. A bare channel name remains accepted but is logged as ambiguous when more
   than one source owns it.

**Alternatives rejected:** keeping `_load_level` public with a documentation-only warning; an
in-memory chunk list with a size cap (still unbounded per channel); rewriting cached samples to
apply an offset; qualifying every channel label with its filename unconditionally; wide-form export
that assumes all sources share a time axis.

**Consequences:** `core/` gained `channel_reader.py` and must stay headless — `core/session.py` no
longer imports PySide6 and the guard test now imports every core module individually. Cache layout
is unchanged, so existing sidecars stay valid. Pre-v6 sessions load with the identity mapping.

## 2026-07 · D-046 · Session IO and annotation export never run on the UI thread

**Context:** architecture rule 3 was violated by session save, load, autosave, and annotation
export. A session carrying an accepted million-pair frame mapping is not a "fast enough" write, and
on a network drive none of these are.

**Decision:** `engine/session_worker.py` owns `SessionSaveWorker`, `SessionLoadWorker`, and
`AnnotationExportWorker`. Each takes an immutable snapshot at construction, so the UI thread may
keep mutating its own state. Parsing moves to the worker; *applying* a loaded session — creating
panes, starting imports — stays on the UI thread where Qt object ownership belongs. The single
exception is the final autosave in `closeEvent`, which is synchronous by design and documented:
the window is being torn down, so handing that write to a QThread would race widget destruction.

**Alternatives rejected:** a modal progress dialog around a blocking write; `QApplication.
processEvents()` pumping (banned by the production guard); making the close-time autosave
asynchronous and joining the thread in the destructor.

**Consequences:** a Qt heartbeat test gates this — it fails if the event loop stalls more than
500 ms during a one-million-pair session write.

## 2026-07 · D-047 · Presentation is rate-limited; authoritative time is not

**Context:** the 60 Hz tick formatted every readout label and resampled the full pose set even when
those panels were collapsed, and timeline evidence paint scanned every event on every frame.

**Decision:** the master clock, plot cursor, and seek bar still see all 60 ticks per second.
Text-formatting and pose-sampling consumers refresh at 20 Hz and are skipped entirely while hidden.
Discrete events — seek, frame step, pause — pass `force=True` so a stale readout can never be shown
as if it were current. `_update_timeline_views` takes the caller's already-sampled
`time.monotonic()` value and never samples the clock itself, so it cannot perturb drift accounting.
Timeline event lanes keep a sorted time index; paint and hover binary-search it, so their cost
scales with pixels rather than event count.

**Alternatives rejected:** throttling the master clock itself; repainting everything and relying on
Qt's update coalescing; dropping the readout panel from the tick and refreshing it on a separate
timer (it would then disagree with the playhead after a seek).

**Consequences:** 20 Hz is a presentation constant, not a timing guarantee; any test asserting a
readout value must force an update or drive the clock past the interval.

## 2026-07 · D-048 · Video probes run bounded-parallel; native panes stay serialized

**Context:** metadata probing and native pane construction were both serialized, so a four-camera
session paid four probe latencies in a row for work that is independent per file.

**Decision:** up to three ffprobe metadata/timestamp probes run concurrently. Native render pane
construction remains strictly one at a time and in the order the user requested the files, so the
grid layout never depends on which file probed fastest, and D-040's requirement that libmpv accept
commands on one pane before the next is built is preserved. A failed probe is dropped from the
ordering so files queued behind it still open.

**Alternatives rejected:** unbounded probe fan-out (a 32-camera session would thrash one disk);
parallel pane construction; building panes in probe-completion order.

**Consequences:** the probe bound is a constant, not a per-machine calculation; raising it needs a
measurement on spinning-disk and network-mounted media, not just an SSD.

## 2026-07 · D-049 · No splitter pane may be collapsed to nothing

**Context:** the plot area launched with zero height because stretch factors alone let Qt allocate
nothing to a pane whose sibling's size hint already filled the splitter; every splitter also
permitted dragging a child to zero, leaving no handle affordance to recover it.

**Decision:** all four workspace splitters seed explicit proportional sizes before any saved state
loads and set `childrenCollapsible(False)`. Because `QSplitter.saveState` stores that flag, the
policy is re-asserted after `restoreState`, and a restored layout carrying a zero-size visible pane
is repaired to the defaults. The 3D tracking pane is shown only once a source provides complete XYZ
triplets, so it never holds media width or raises the window minimum for sessions without tracking.

**Alternatives rejected:** relying on stretch factors alone; giving each pane a large hard
`setMinimumHeight` (it makes the window unshrinkable); a "reset layout" menu item as the only
recovery path.

**Consequences:** hiding a pane is a deliberate control — the Data Streams collapse button, the
sidebar tab, channel visibility — never an accidental drag. Layout regressions are covered by
`tests/test_ui_layout_resize.py`.

## 2026-07 · D-027 · Timeline Evidence must be named and conditional

**Context:** coverage, sync/TTL events, gaps, and annotations share the master timeline, but an
unlabeled colour-only strip makes scientific evidence ambiguous.

**Decision:** `ui/transport.py` owns the named **Data Streams** presentation with conditional lanes,
inspectable event details, click-to-seek, native splitter handles, a fixed source-label gutter, and
persisted view-only collapse preference. It reads existing UI state; `core/` remains headless and makes
no visual decisions.

**Alternatives rejected:** a permanently visible unlabeled colour strip; a second independent
timeline; presenting sync evidence only in the wizard/sidebar.

**Consequences:** implementation must bucket dense evidence for paint, preserve the ≤2 ms cursor
path, never infer/alter mappings, and have pytest-qt coverage for discoverability and accessibility.

## 2026-07 · D-001 · Master time = float64 seconds, UTC epoch
Context: need one representation across video, 50 kHz data, UI. Alternatives: int ns (rerun-style),
per-source relative time. float64 gives ~µs precision at epoch scale — sufficient (50 kHz = 20 µs
sample spacing); simpler math everywhere. Consequence: never use float32 for time anywhere.

## 2026-07 · D-002 · Video playback = libmpv only
Alternatives rejected: QtMultimedia (inaccurate seeks), OpenCV (no proper playback pipeline),
GStreamer (dependency pain on Windows/macOS). Consequence: bundle LGPL mpv in installers.

## 2026-07 · D-003 · License Apache-2.0; no GPL deps
Enables commercialization and permissive reuse. PyQt (GPL) banned; PySide6 (LGPL) allowed.

## 2026-07 · D-004 · Sidecar cache format
Parsed time series → `<file>.avialcache/` dir: `meta.json`, `t.npy`-style raw mmap arrays per channel,
`pyr_16.bin`/`pyr_256.bin`/`pyr_4096.bin` min/max pairs. Invalidation key: (path, size, mtime, loader
version). Alternatives: HDF5 (heavy dep), Parquet-only (no mmap random access win for pyramids).

## 2026-07 · D-005 · Chunked ingest is the only ingest path
TimeSeriesSource.read_chunks() iterator; cache builder pulls incrementally. Enables 50 GB files
and streaming later without API break. Full-array loading banned even for small files.

## 2026-07 · D-006 · VideoSource conversion hook is first-class
needs_conversion()/prepare() in the ABC. Image sequences, .cine, split files are plugins, not hacks.

## 2026-07 · D-007 · Frame stepping uses actual frame timestamps
Never 1/fps arithmetic. VFR and dropped-frame footage are normal field conditions.

## 2026-07 · D-008 · Cache key gets content-hash tail
(path, size, mtime, loader_version, xxhash first+last 64 KB). Supersedes D-004 key. Stale-cache
silence is a trust-destroying bug class in a measurement tool.

## 2026-07 · D-009 · Gaps and NaN are rendered honestly
gap_mask at 10× median dt; lines break at gaps; NaN skipped via nanmin/nanmax; sentinel→NaN only
by explicit user config. We never invent data the logger didn't record.

## 2026-07 · D-010 · No-data state is uniform and explicit
Outside a source's bounds: dimmed placeholder (video), empty axis (plot), "—" (readout). Never
freeze the last frame. Timeline = union of source bounds with coverage shading.

## 2026-07 · D-011 · macOS mpv path built first
Render-API embedding on macOS is the project's highest integration risk; Phase 2 starts there.

## 2026-07 · D-012 · Distribution channels & zero-step guarantee
Release = ONE tag → CI builds ALL channels: (a) OS installers (Inno .exe, .dmg, AppImage) with
LGPL libmpv + ffmpeg BUNDLED — end user does nothing but install & run; (b) PyPI wheel+sdist —
pip users get everything Python-side automatically; libmpv/ffmpeg gap handled by startup probe
(D-013) and Windows auto-fetch (D-014). conda-forge recipe as supplementary channel.
Never ship a release where installers and PyPI are out of version sync.

## 2026-07 · D-028 · Release wheel smoke test gates installers and PyPI

**Context:** a tag release needs one deterministic package-level proof before spending time on
three platform installer builds or publishing to PyPI, while retaining cross-platform correctness
as the first gate.

**Decision:** the tag workflow runs the full cross-platform quality matrix, documentation build,
and distribution build first. It then installs the built wheel into a clean environment and proves
the package imports. Only that successful smoke test unlocks the three installer jobs. OIDC PyPI
upload starts only after every installer passes, and the GitHub Release is created last.

**Alternatives rejected:** TestPyPI as an extra public index and delayed-CI smoke test; a manual
approval gate; publishing to PyPI before every installer has passed.

**Consequences:** a failed installer prevents PyPI publishing and GitHub Release creation. A tag
is therefore complete only when all three installer artifacts and the matching PyPI distribution
have passed their gates.

## 2026-07 · D-029 · AppImage build tool is pinned in the release workflow

**Context:** release access must require no mutable repository variables, matching the hands-off
tag workflow model, but an unverified moving download would violate the release supply-chain gate.

**Decision:** `release.yml` records the fixed AppImageTool release URL and SHA-256 next to the
download-and-verify step. No repository variable or secret is required for AppImage packaging.

**Alternatives rejected:** a mutable `continuous` tool download without checksum verification;
administrator-maintained URL/checksum variables.

**Consequences:** updating AppImageTool is a reviewable source change that updates both values in
one commit. A tag release remains fully hands-off after PyPI Trusted Publishing is configured.

## 2026-07 · D-013 · Lazy mpv import + startup probe (never crash on missing libmpv)
`import mpv` is FORBIDDEN at module top level anywhere. video_pane imports lazily after
diagnostics probes for libmpv. Missing lib → app still opens, shows an OS-detected dialog with
the exact install one-liner (apt/dnf/pacman/brew) or the Windows auto-fetch offer. A ctypes
traceback at launch is a release-blocking bug.

## 2026-07 · D-014 · Windows pip auto-fetch of libmpv
First run without libmpv on Windows: offer one-click download of the pinned LGPL libmpv build
(URL + SHA256 hardcoded per release) into the app data dir; loaded from there. Makes pip on
Windows effectively zero-step. Optional `avialview[media]` binary companion wheel is post-1.0.

## 2026-07 · D-015 · LGPL-configured libmpv ONLY in bundles
libmpv is dual GPL/LGPL; bundling a GPL-configured build would poison D-003. Packaging must use
LGPL builds (-Dgpl=false; e.g. shinchiro LGPL Windows builds) and CI release asserts the build
flavor before bundling. Same for ffmpeg (LGPL configuration, no --enable-gpl).

## 2026-07 · D-016 · Code signing: stubbed at v1.0, hooks ready
v1.0 ships unsigned (SmartScreen "Run anyway" / macOS right-click-Open documented in README +
docs). Release workflow contains signing/notarization steps behind secrets-present conditionals
so enabling later = adding secrets, zero code change. Buy Apple $99/yr + Windows signing at
first commercial interest or when Mac-user friction reports appear.

## 2026-07 · D-017 · python-mpv naming
Dependency is `python-mpv` on PyPI; imported module is `mpv`. The unrelated PyPI package named
`mpv` must never be installed. Pin in pyproject: python-mpv>=1.0.7.

## 2026-07 · D-018 · Product name = AvialView (final)
Brand/display: `AvialView`. Package/module/CLI/entry-point group/paths: `avialview`
(lowercase, single word). Session ext `.avv`; cache sidecar `<file>.avialcache/`; installers
`AvialView-Setup.exe` / `AvialView.dmg` / `AvialView.AppImage`; env vars `AVIALVIEW_*`;
third-party plugins `avialview-plugin-<name>`. Casing table is binding (AGENTS.md §Naming).
Agents must not introduce spelling variants or rename anything. ACTION FOR OWNER: register
`avialview` on PyPI (stub 0.0.1) and the GitHub org/repo before Phase 0 work begins.

## 2026-07 · D-019 · Frame-indexed sources — is_frame_indexed() pre-freeze API addition
`TimeSeriesSource` (core/source.py) gains a non-abstract `is_frame_indexed() → bool` method
defaulting to False.  Loaders whose on-disk format stores raw frame counters (not wall-clock
seconds) override it to return True.  `TrackingLoader` (DLC/LP) is the first such loader.

Resolution order for fps when importing a frame-indexed source:
1. Exactly one video loaded → fps pre-filled from that video; user confirms in one click.
2. Multiple videos loaded → dropdown of video filenames; user picks the matching camera.
3. No videos loaded → manual entry of nominal fps; source recorded as provisional in
   `MainWindow._frame_indexed_sources`.  When the first video is subsequently added,
   `_rebind_frame_indexed_sources(fps)` removes the provisional channels, re-imports with the
   video fps, and clears the provisional list.

fps is NOT added to the cache key (D-008) — re-import always overwrites the sidecar atomically,
which is correct because ImportWorker never short-circuits on a cache hit.

## 2026-07 · D-020 · Inspection layer — what is surfaced where

This entry governs the design of the source-properties, load-provenance, sync-provenance,
precision-readout, delta-measurement, time-display-mode, import-report, and integrity-badge
features (Features A–K in the Phase 4 UX kickoff).

### Single-source-of-truth rule
Every displayed value is read from the object that OWNS it at the time it is needed — never
cached into widget state, never re-probed from disk, never parsed back from a formatted string.
Owners:
  - Video metadata (container, codec, resolution, fps, frame count, GOP, bit-depth): VideoStandardLoader
  - Live video state (measured fps, decode mode): live mpv instance via mpv properties
  - TimeMap (offset, drift, effective source time): VideoPane.time_map
  - Channel metadata (unit, dtype, rate_hz): ChannelInfo returned by loader.channels()
  - Import stats (rows, gaps, NaN, sentinel counts): ImportReport emitted by ImportWorker
  - Integrity flags: IntegrityFlags computed by ImportWorker / VideoStandardLoader at open time
  - Cache state: CacheManager.is_cache_valid() — never duplicated into widget fields

### New headless core module: core/inspection.py
Three frozen dataclasses — no PySide6 imports, test-enforced.
  - ImportReport: rows_parsed, rows_dropped_duplicate, rows_dropped_nonmonotonic,
    gap_count, nan_count, sentinel_count, gap_locations (list[float]), import_timestamp (float)
  - IntegrityFlags: is_vfr (bool), fps_mismatch (bool), has_gaps (bool), drift_nonzero (bool),
    fps_provisional (bool); vfr_threshold_pct = 2.0 % deviation from nominal fps
  - SourceInspection: path (str), loader_id (str), import_config (dict), import_report
    (ImportReport | None), integrity_flags (IntegrityFlags), fps_binding (str — "provisional",
    "bound:<video_path>", or "" for non-frame-indexed sources)

### Session schema bump: v1 → v2
SensorEntry gains: loader_id (str), import_config (dict), import_report (ImportReport as dict).
VideoEntry gains: integrity_flags (IntegrityFlags as dict).
Backward compatibility: v1 sessions loaded with empty reports and zero-flags (never fail).
Version field checked on load; "version": 2 written on save.

### ImportWorker.finished signal change
Old: finished(path: str, cache_dir: str, channels: list[str], bounds: tuple[float, float])
New: finished(path: str, cache_dir: str, channels: list[str], bounds: tuple[float, float],
              inspection: SourceInspection)
ImportWorker computes ImportReport and IntegrityFlags while building the pyramid (gap_mask already
built; NaN/sentinel counts gathered during read_chunks; import_timestamp = time.time() at finish).
All callers (MainWindow._on_import_finished) updated. The fifth parameter is ignored gracefully if
not present (backward compat via **kwargs or signal versioning).

### VideoStandardLoader additions
New probed fields stored as typed attributes after open():
  _container (str), _width (int), _height (int), _pix_fmt (str), _frame_count (int | None),
  _gop_size (int | None), _profile (str).
All probed from the same ffprobe JSON response already fetched — no extra subprocess call.
_gop_size: read from streams[*].codec_tag or inferred from min(pts_dts_diff) in frame_times
  if available; None if indeterminate.
Measured fps: NOT stored in VideoStandardLoader (it's a live runtime property of the mpv
  decoder). Read from VideoPane.mpv.estimated_vf_fps when populating the properties panel.
Decode mode: Read from VideoPane.mpv.hwdec-current when populating the properties panel.

### UI panel strategy: extend, not parallel
VideoInfoWidget in sidebar.py gains a collapsible "Properties" section showing all video fields.
SensorInfoWidget gains a collapsible "Properties" section + "Report…" button.
These are toggle-collapsed by default to keep the sidebar compact.
Module sidebar.py will exceed 500 lines after these additions — it is split into:
  - sidebar.py: SidebarPane (navigation/controls/open buttons) + thin VideoInfoWidget/SensorInfoWidget
    headers (filename, remove button, offset control, visibility checkbox)
  - source_properties.py: VideoPropertiesPanel + SensorPropertiesPanel (the collapsible detail section
    including import provenance, cache status, integrity flags, copy button)
No parallel hierarchy — source_properties panels are children of the existing sidebar widgets.

### Time display modes
TimeDisplayMode enum: RELATIVE (default) | UTC | LOCAL_TOD.
ui/time_format.py: format_time(t_seconds: float, mode: TimeDisplayMode, t_epoch: float) → str
  where t_epoch is the recording start epoch (0.0 if unknown → RELATIVE always from 0).
Stored as a singleton in MainWindow, persisted in QSettings("AvialView","AvialView","time_mode").
MainWindow emits time_mode_changed(mode) signal. Transport, VideoPane OSD, ReadoutPanel, and
all properties panels subscribe. format_time() is the ONLY place time is formatted — no inline
HH:MM:SS formatting scattered through widgets.

### Delta measurement: distinct measure points on PlotPane
A/B pins in Transport remain loop-only. Measurement is a distinct two-click mode on PlotPane:
  - PlotPane gains set_measure_a(t) / set_measure_b(t) / clear_measure() public methods.
  - A right-click context menu item "Set measure point A/B" places markers on the plot.
  - When both are set, PlotPane emits measure_changed(t_a, t_b).
  - ReadoutPanel responds to measure_changed, appending a "Δ" section showing:
    Δt, per-channel Δvalue (value_at(t_b) − value_at(t_a)), and per-camera frames-between
    (computed as round((t_b − t_a) * fps) per pane, accessed via player.video_grid.panes).
Rationale: "loop from A to B" and "measure delta A to B" are different user intents. Entangling
them would require mode-switching UX that is harder to discover and test. Separate mechanism is
cleaner and lets both be active simultaneously.

### Import Report access
SensorInfoWidget's "Report…" button opens ImportReportDialog (new file ui/import_report.py):
  a scrollable plain-text view of the ImportReport fields, plus a "Copy as text" button.
ImportReport is stored in SourceInspection which flows into MainWindow._inspections dict
(keyed by path), persisted to session, reloaded on session open.

### Integrity badge
WarningBadge: a small QLabel("⚠", tooltip=<list of anomalies>) on the right side of each
VideoInfoWidget and SensorInfoWidget header. Visible only when IntegrityFlags has any True field.
Clicking opens the relevant Properties section scrolled to the integrity summary.
No new widget class required — populated in the respective header layouts.

### Copy as text
Every collapsible properties section and ImportReportDialog has a QPushButton("Copy as text").
Handler calls QApplication.clipboard().setText(widget.as_plain_text()) where as_plain_text() is
a method returning aligned columns suitable for pasting into a lab notebook or ticket.
No mixin class required — each panel implements the method directly (DRY for 3 call sites
is premature abstraction; AGENTS rule: three similar lines is better than a premature abstraction).

### Gap markers on plot
Gaps (where gap_mask is True) are surfaced as vertical InfiniteLines at gap positions, overlaid
on the existing per-channel coverage_region in PlotPane. No separate timeline strip is built.
Positions loaded from the pyramid gap arrays after import finishes — no re-scan.

### Demo data extensions
generate_demo_data.py extended (NOT make_fixtures.py — fixtures are for CI).
New outputs:
  - examples/data/camera_vfr.mp4: ffmpeg lavfi testsrc with deliberately dropped frames (via
    ffmpeg -vf "select=not(mod(n\,7))" to drop every 7th frame → measured fps ≠ nominal)
  - examples/data/sensors_gaps.csv: 10 kHz signal, 3 gaps at 2s/5s/8s, 500 NaN values,
    200 sentinel (-9999) values
  - examples/data/pose.csv: minimal 2-bodypart DLC file, 300 frames @ nominal 30 fps
  - examples/data/camera_2.mp4: second clean camera with +1.234 s offset in launch_demo.py
  - Non-zero drift (0.5 ppm) set on camera_3 in launch_demo.py
  - Demo load order: camera_1 first (triggers pose.csv D-019 rebind), then camera_2/camera_3

## 2026-07 · D-025 · Plugin API v1 is ingest-only for time series and preparation-aware for video

`TimeSeriesSource` is frozen around capability detection, metadata discovery, and chunked ingest:
`read()` and `time_bounds()` are removed because cache readers own all post-import querying and
source bounds are derived from their persisted data. `config_widget()` is removed: core remains
headless and plugin configuration is JSON-serialisable host-provided data rather than a Qt object.

`VideoSource` retains `needs_conversion()` and `prepare()` (D-006), gains abstract
`time_bounds()`, and is opened through the registry in a worker thread before mpv receives its
prepared media path. Discovery supports Python entry points plus `~/.avialview/plugins/` drop-ins.
The removed methods must not be reintroduced without a versioned API decision.

## 2026-07 · D-022 · Interaction standard — visible surface, depth in menus, shortcuts as accelerators

### 1. Single authority — one QAction (or one transport signal) per action

Every user-reachable action (button, menu item, context-menu item, keyboard shortcut) MUST
share exactly one implementation path. Parallel handlers are forbidden.

Concretely:
- If an action is in the menu bar, its `QAction` carries the keyboard shortcut (`setShortcut`
  or `setShortcuts`). The matching `QShortcut` in `_setup_shortcuts()` is REMOVED.
- Transport buttons emit a signal; that signal is connected to the engine; keyboard shortcuts
  that duplicate those buttons must emit the SAME signal, not call the engine directly.
- Context-menu items must trigger the SAME `QAction` objects used by the menu bar and toolbars
  (verified by object identity in tests). Never create a second action for the same effect.

Rationale: parallel handlers caused the Ctrl+E / Ctrl+0 double-trigger bug and makes the
shortcuts dialog impossible to keep in sync with reality.

### 2. StandardKey over hardcoded strings wherever a platform standard exists

Use `QKeySequence.StandardKey` for:
- Save session → `StandardKey.Save` (Ctrl+S on Win/Linux, Cmd+S on macOS)
- Open session → `StandardKey.Open` (Ctrl+O / Cmd+O)
- Quit → `StandardKey.Quit` (Ctrl+Q / Cmd+Q)
- HelpContents → `StandardKey.HelpContents` (F1); `?` stays as an alias QShortcut
- FullScreen → `StandardKey.FullScreen` (F11 on Win/Linux; Ctrl+Cmd+F on macOS)

Hardcoded string shortcuts are only acceptable when no StandardKey covers the action
(e.g., `Ctrl+T` for theme cycle, `Ctrl+E` for snapshot, field keys J/K/L).

### 3. macOS menuRoles required

- Quit action: `setMenuRole(QAction.MenuRole.QuitRole)` AND `StandardKey.Quit`
- About action: `setMenuRole(QAction.MenuRole.AboutRole)` — even if just a stub
- Preferences: DEFERRED — no settings dialog exists yet; add when it does

Without `QuitRole`, the macOS app menu has no Quit item, which breaks notarization review
and violates HIG. This was a known omission confirmed at audit (D-022 pre-condition).

### 4. J/K/L shuttle semantics

- **L** — step up through the playback-rate set (0.01×, 0.05×, 0.1×, 0.25×, 0.5×, 1×,
  2×, 4×, 8×, 10×). Each press advances one step; wraps at max. Emits `transport.rate_changed`.
- **K** — pause (equivalent to clicking the pause button; emits `transport.play_toggled(False)`).
- **J** — jump back 1 second (emits `transport.jump_requested(-1.0)`). True reverse-play is not
  implemented; J is a time-jump, not reverse. This is documented in the shortcuts dialog.
- Rationale: J=back/K=stop/L=forward-speed is the industry-standard (Avid, Premiere, DaVinci).
  True reverse requires re-seeking every frame at playback rate which mpv supports but creates
  seek-settle complexity not yet designed. Defer to a future PR.

### 5. A/B button active state

Transport A-in and A-out buttons are `setCheckable(True)`. When a point is set, the button
is shown as checked. When cleared (`_on_ab_clear`), both buttons are unchecked.
Visual differentiation: checked state uses a distinct background to signal "loop is armed."

### 6. Shortcuts dialog rendering

`ShortcutsDialog` must NOT maintain a static string table. Instead:
- `MainWindow._show_shortcuts()` collects all registered `QAction` objects that have shortcuts.
- Passes them to `ShortcutsDialog(actions, parent)`.
- The dialog renders `QKeySequence.toString(QKeySequence.SequenceFormat.NativeText)` for each.
- Grouped by category tag: Playback / Marking / View / File.
- Consequence: it is impossible for the dialog to drift from the actual bindings.

### 7. Open Video → Ctrl+Shift+V, Open Data → Ctrl+Shift+D

The previous bindings Ctrl+V ("Open Video") and Ctrl+D ("Open Data") collide with
system Paste and platform bookmark/dock keys respectively. They are rebound here.

Decision: pre-1.0, zero external users, cheapest moment to change. The new bindings
are less ergonomic but non-colliding.

**TRAP: never bind Ctrl+V or Ctrl+D to any application action.** These are reserved
by the OS/desktop across all three platforms. If a future action needs a shortcut,
use Ctrl+Shift+<letter> or pick a non-colliding combination.
The previous collision was a known bug confirmed at audit; this entry resolves it.

### 8. Accepted numeric/time edits return focus to playback

Space and the playback keys remain protected while a line edit, spin box, or combo is actively
being edited. Once Enter accepts a valid transport time or plot-window limit—or a plot-window unit
is selected—focus moves to the containing non-editor playback surface. The next Space therefore
uses the window-scoped Play/Pause `QAction` instead of remaining trapped in the editor.

### Consequences (what every future agent must not reverse)

- Never create a `QShortcut` for an action that already has a menu `QAction` with
  the same shortcut. The `QAction` is the single authority; the shortcut is set on it.
- Never call `player.set_playing()` or `player.step_frame()` from a keyboard shortcut
  handler. Always emit the corresponding transport signal so the transport bar stays
  in sync.
- Never bind Ctrl+V or Ctrl+D.
- Never leave keyboard focus in an accepted time/window editor; preserve Space while editing and
  return focus to a non-editor playback surface after acceptance.
- Never add a Preferences action without also setting `MenuRole.ApplicationSpecificRole`
  or `PreferencesRole` appropriately.
- J shortcuts dialog rendering must remain derived from live `QAction` registry; no
  static table. If new actions are added, they appear automatically.

## 2026-07 · D-023 · Benchmarks CI-gated; budget-assertion pattern; CI multiplier

### Context
Benchmarks in `tests/benchmarks/` were never CI-gated for two reasons: the file was
named `bench_pyramid.py` (not collected by pytest) and `ci.yml` passed
`--ignore=tests/benchmarks`.  A known regression existed: pyramid build measured 3.3 s
vs the 2 s BLUEPRINT budget.

### Decisions

**Collection:** Renamed `bench_pyramid.py` → `test_bench_pyramid.py` so pytest collects
it normally under the existing `test_*.py` pattern.

**CI step:** Added a separate `Run Benchmarks (budget-gated ★)` step in `ci.yml` that
runs `pytest tests/benchmarks --benchmark-only`.  Kept `--ignore=tests/benchmarks` on
the main test step so regular tests remain fast.  Rationale for separate step (not
inline): budget failures surface as a named, identifiable CI step rather than a
mid-suite failure that is hard to bisect.

**Budget assertion pattern (superseded by D-029):** This initially used one CI multiplier.
Experience showed that a shared hosted runner cannot certify the user-facing timing target at all.
D-029 replaces the multiplier with uncalibrated local timing checks and a GitHub workload-correctness
check. No per-test multiplier is permitted.

**Pyramid build optimization (to meet ≤2s budget):**
Profiling showed two hotspots at 180 M samples (total ~3.3 s):
  1. `np.median(np.diff(t))` — 1000 ms.  Fix: estimate median from every 10 000-th diff
     element (statistically equivalent for uniform/near-uniform sensor data; gap_threshold
     is still correctly set; only changes O(n) → O(n/10000)).
  2. Level-16 vmin/vmax np.save (float64, ~360 MB) — 550 ms.  Fix: cast to float32
     before save (sensor precision is ≤16-bit → float32 is lossless in practice; halves
     IO).  t arrays remain float64 for seek accuracy.

Both changes are backward-compatible: `float()` casts on scalar reads and numpy auto-
promotion on arithmetic work with float32 arrays.  Cache key (D-008) is unaffected —
ImportWorker always rebuilds on open, never short-circuits on pyramid data alone.

**Agents:** Never change the pyramid storage format (dtype, file layout) without bumping
the loader_version in the cache key (D-008) so stale caches are automatically invalidated.

## 2026-07 · D-024 · Pyramid Build Budget Adjustment & Future Format Migration

**Decision:** Increase the Pyramid build budget for 180M samples from 2.0s to 2.5s.

**Rationale:** Profiling demonstrates that the current `.avialcache` sidecar format writes ~3.5 GB of data for a 180M sample track (Level-1 timestamps and values saved as `float64` dominates this volume). Writing 3.5 GB sequentially hits the physical limits of typical PCIe 4.0 NVMe SSDs, bottoming out at an I/O floor of ~2.1 seconds natively before any CPU overhead (decimation math, gap mask computation, etc.) is accounted for. This budget is adjusted *by decision* with profiling evidence attached, not artificially via multiplier.

**Future Optimization (Format Migration deferred post-1.0):**
For uniform-rate sources, the Level-1 `t` array does not need to be written to disk. It is perfectly reconstructible from a `(t0, dt)` tuple, which would save ~1.44 GB of writes per channel and almost certainly bring the build time back comfortably under 2.0s. This optimization requires a cache-format change (bump `loader_version` and refactor format migration) and is explicitly deferred until post-1.0 to prioritize stabilization. The 2.5s budget is therefore considered provisional.

## 2026-07 · D-028 · Hierarchical pyramid construction

**Decision:** Build the 16× display envelope from raw samples, then derive the
256× and 4096× envelopes from the preceding level's min/max values. Compute gap
masks in bounded chunks rather than allocating one full timestamp-difference array.

**Rationale:** Minima and maxima are associative, so hierarchical aggregation is
identical to direct aggregation at each published level, including partial final
blocks. It reduces full-resolution passes from three to one and avoids a large
temporary allocation during gap detection. The 180M-sample build benchmark improved
from 3.11 s to 1.69 s on the development machine while retaining exact envelopes.

## 2026-07 · D-026 · Synchronization is evidence-based, plugin-extensible, and user-accepted

AvialView is a visual-inspection tool, not an acquisition system or a built-in scientific-analysis
suite. It must align independently-clocked cameras, sensors, electrodes, and tracking data using
TTL/event evidence without changing the raw recordings.

Core will represent raw event timestamps, matched evidence, an affine offset/drift proposal,
residuals, confidence, and accepted provenance. It will support common periodic clocks,
camera-frame triggers, and sparse pulse sequences through deterministic chunked extraction and
matching. Lab-specific file formats and event encodings belong in plugins.

The UI must show the evidence and fit quality, detect ambiguity/outliers, permit manual fallback,
and require explicit user acceptance before updating a `TimeMap`. Accepted provenance is persisted
in `.avv` so an alignment is reproducible and auditable. Sync accuracy and throughput are release
criteria: every implementation requires ground-truth fixtures and benchmarks, and may not regress
existing playback, import, or plotting budgets.

## 2026-07 · D-029 · Separate GitHub workload correctness from local speed certification

### Context

The 180 M-sample pyramid build meets its 2.5 s mark on the defined engineering machine, but it
measured 15.6 s on an Ubuntu GitHub-hosted runner. That runner has shared CPU and ephemeral disk,
so using it as the authority for the raw product mark produces false failures. Scientists care
about app responsiveness under a real multi-camera, multi-stream session, not CI build speed.

### Decision

GitHub Actions verifies the representative three-camera, four-stream workload for correctness only.
The local `pytest --benchmark-only` command enforces the raw 2.5 s / 5 ms / 2 ms / 250 ms timing
marks, without any multiplier. The cross-platform matrix never claims shared hosted hardware can
certify user-facing speed. Per-test multipliers remain prohibited.

## 2026-07 · D-030 · Test-level watchdog for cross-platform Qt verification

### Context

Two Windows test jobs remained inside pytest for more than fifteen hours, despite the workflow's
job timeout. A job-level timeout only tells us a runner is wedged; it does not identify the test or
provide the stack needed to fix a Qt, worker, or subprocess deadlock.

### Decision

The development-only `pytest-timeout` dependency (MIT) runs every CI test with a 60-second,
thread-based watchdog. It reports the exact stuck test and its Python stack, then fails the job.
The timeout applies to correctness tests only; local performance benchmarks retain their own timing
marks and are not weakened. Raising a workflow timeout or skipping a timed-out test is forbidden.

**Platform correction:** Qt documents its `offscreen` platform plugin as fully supported only on
X11. Windows CI therefore overrides the global headless setting with the native `qwindows` backend
for its QWidget tests. Linux and macOS continue to use offscreen testing. This is a test-platform
selection fix, not an application behavior change.

## 2026-07 · D-031 · Libmpv commands stay on the Qt-owning thread

### Context

The macOS Python 3.12 CI job could load libmpv but intermittently left the observed `seeking`
property true after an exact seek. The command had been sent from a `QThreadPool` worker while the
embedded video pane and its property observers belonged to the Qt UI thread.

### Decision

`SeekGroup` fans out `mpv.seek` calls from the Qt-owning thread. The call only queues an operation
in libmpv; decode and property observation remain on libmpv's own threads. Settling continues to
require the observed `seeking=False` state and target `time-pos`, never a sleep. This preserves a
responsive UI without cross-thread access to an embedded libmpv client.

## 2026-07 · D-032 · Headless CI uses null video, decoded-frame evidence, and explicit mpv ownership

### Context

The D-030 Windows `qwindows` correction still required a hosted runner to behave like a desktop
compositor and led to failures inside native embedding. Separately, a successful exact-seek command
or a rendered screenshot could represent an old frame, and leaving pane shutdown to QWidget
destruction left libmpv event threads alive during test teardown.

### Decision

This supersedes only D-030's platform correction. GitHub Actions uses global
`QT_QPA_PLATFORM=offscreen` on all OSes. `VideoPane` detects that boundary and selects libmpv
`vo=null`; production native Windows/Linux embedding and the macOS render-API path are unchanged.
Windows CI provisions a pinned libmpv archive, verifies its SHA-256, and runs `import mpv` before
the suite.

Exact-frame golden tests use `screenshot-raw video` and decode the frame-strip fixture. An
unavailable or stale pre-seek raw snapshot is rejected and retried through the Qt event loop at a
bounded interval; they never sleep, skip, or accept a stale displayed frame. They require delivered
`seeking`/`time-pos` target evidence and, if a Windows observer is delayed, repeat the same exact
seek once before failing. Runtime seek coordination continues to use delivered observer values and
target properties; callbacks must not re-enter libmpv.

Shutdown is owned by the widget hierarchy: `MainWindow.closeEvent()` first calls `Player.stop()` to
remove its precise tick timer, then `VideoGrid.shutdown()`, which closes each `VideoPane` and
terminates libmpv before Qt destroys the widgets. Decode and property handling remain libmpv-owned
during playback; explicit ownership makes teardown deterministic.

### Consequences

CI certifies cross-platform timeline/decode correctness and catches lifecycle faults without
claiming a hosted runner certifies native compositing or performance. D-029 remains the authority
for local timing marks.

### macOS render-client teardown amendment

For the native macOS render API, the libmpv OpenGL render context is explicitly freed while its
`QOpenGLWidget` is current, before `mpv.terminate()` destroys the client. The opposite order leaves
the Qt render object holding an invalid mpv client and aborts the process on exit. This is a lifecycle
ordering rule only; it does not alter seek, decode, or rendering behavior while the app is open.

## 2026-07 · D-035 · Exact seeks decode without frame dropping

**Context:** libmpv permits decoder frame dropping during high-resolution seeks by default. Its
reported target time can therefore advance before the raw decoded frame has replaced the prior
frame, producing stale-frame evidence in cross-platform golden tests.

**Decision:** every `VideoPane` configures `hr-seek-framedrop=no`. Paused exact seeks decode through
the requested frame before the raw-frame golden assertion is made. Playback retains its normal
frame-dropping behavior, so synchronization correctness during playback is unaffected.

**Alternatives rejected:** accepting a stale screenshot; a fixed sleep; a test-only mpv setting
that would leave the shipped paused-seek path unverified.

**Consequences:** exact paused seeks can take longer on long-GOP media, by design. This is the
explicit fidelity side of the application's speed-and-timing release criteria.

## 2026-07 · D-033 · Packaging inputs are explicit and CI artifact builds are a separate gate

### Context

PyInstaller sets `SPECPATH` to the directory containing a spec. Treating it as the repository root
breaks source discovery. Converting an unset `AVIALVIEW_MEDIA_ROOT` directly to `Path` also maps it
to the current working directory, allowing unrelated files to enter an artifact.

### Decision

The spec derives the project root from `Path(SPECPATH).parent`. It stages media only when
`AVIALVIEW_MEDIA_ROOT` is non-empty and is a directory; an invalid supplied path is a hard error.
Pull-request CI builds a media-free PyInstaller artifact on every OS. The tag-only release workflow
is responsible for providing and licence-verifying the explicit media inputs.

### Consequences

Build failures identify a path or declared-input defect early without making CI artifacts equivalent
to release installers. Keep the spec force-added despite the repository-wide `*.spec` ignore rule.

## 2026-07 · D-034 · Themes are palette/font appearance, never interaction redesign

### Context

The original theme stylesheet styled slider grooves/handles, splitters, scrollbars, and other
standard controls. Qt application stylesheets replace parts of the native style engine, so selecting
Dark or Light could change the seek bar's geometry and other interaction affordances. For scientific
inspection, a colour preference must not change how the shared timeline or plot navigation behaves.

### Decision

`ui/theme.py` changes only `QPalette` roles and the explicit application-font preference. It retains
the native Qt widget style and applies no application-level QSS. Palette-aware custom views read
their colours from the current palette. A theme change must preserve seek-slider geometry, range,
value, and exact-seek semantics; plot range/follow state; playback; shortcuts; splitter and scrollbar
behavior; and window/view layout. Accessibility font scaling may reflow text, but it cannot change
those behaviors or stored view state.

### Consequences

Tests switch through System, Dark, and Light while asserting seek and plot state remains intact.
Future visual refinements use palette roles or local, non-interaction decoration; they must not
reintroduce global control selectors.

## 2026-07 · D-036 · PR and tag quality use one cross-platform test contract

### Context

The tag workflow is the release authority, but it had gradually diverged from pull-request CI:
fixture generation relied on runner defaults, its test command omitted the per-test Qt watchdog,
and Windows installer staging sourced mpv from a different, unverified package path. Those gaps
can make a green PR fail late on a tag or let a release test a different media boundary.

### Decision

Both quality matrices run Ubuntu, macOS, and Windows on Python 3.11 and 3.12 with global Qt
offscreen mode; explicit ffmpeg/libmpv dependencies; deterministic fixture regeneration; and the
same 60-second `pytest-timeout` command. They use checkout v5 and setup-python v6 on GitHub-hosted
runners. Windows quality and installer staging use the same checksum-verified libmpv archive and
an import probe; ffmpeg remains sourced from Chocolatey.

The platform installation commands remain local to each OS rather than being hidden behind a
generic action, because their package layout and DLL discovery semantics differ. A Python
regression test asserts the shared contract in both workflow files.

### Consequences

A change to the quality gate that affects PR and release behavior must update both workflows and
the parity assertion in the same review. A tag failure is now evidence of an OS-specific packaging
or release-only operation, not a silently weaker test invocation.

## 2026-07 · D-037 · Releases require a tag reachable from main

### Context

Git tags are repository-wide references, not branch-owned objects. A `v*` tag can otherwise point
to an unreviewed side-branch or detached commit while still matching the release trigger.

### Decision

The tag workflow first fetches `origin/main` and proves the tagged commit is its ancestor with
`git merge-base --is-ancestor`. Release quality and documentation jobs depend on this gate, so no
distribution, installer, PyPI upload, or GitHub Release can run from a non-main tag.

### Consequences

Create release tags only after the intended release commit is pushed to `main`. The local
`prepare_release.py` helper enforces the same branch requirement before it creates a tag.

### Ubuntu AppImageTool amendment

The pinned AppImageTool release uses the FUSE 2 ABI. GitHub's Ubuntu 24.04 image provides that
ABI through `libfuse2t64`, which must be installed in the Linux installer job before executing the
tool. Do not install the obsolete `fuse` package; it is not needed for this headless build.

The AppDir must also stage the reviewed `avialview.png` icon declared by `avialview.desktop`.
`assets/icons/avialview-source.png` is the canonical artwork; `tools/generate_icons.py` produces
the Linux PNG, Windows ICO, macOS ICNS, and runtime PNG from it. AppImageTool treats a missing
declared icon as an artifact-integrity error, so the packaging test asserts both the declaration
and staged source asset. The AppDir also provides the required `.DirIcon` symlink and validates
its desktop file with `desktop-file-validate` before AppImageTool runs.

## 2026-07 · D-038 · Windows video panes use libmpv's Qt OpenGL render API

### Context

On affected Windows compositor/driver combinations, libmpv's native `wid` child window decodes
media and reports advancing timestamps but presents a uniform gray surface inside Qt. The tracking
overlay must be visually transparent so it never covers an otherwise working video surface.

### Decision

Interactive Windows and macOS panes use the libmpv OpenGL render API through `QOpenGLWidget`.
Headless Windows continues to use `vo=null`. The Win32 `wid` value remains safely cast to an
unsigned 32-bit HWND for any future native embedding fallback, but it is not the default renderer.
`PaintCanvas` uses transparent/no-system-background attributes and does not autofill its background.

### Consequences

Windows video rendering shares the explicit render-context lifecycle already required on macOS.
Any renderer change must verify visible decoded frames in an interactive window, not only mpv
timestamps or `screenshot-raw` evidence. The gray-surface failure and overlay opacity are covered
by the pane configuration and timing tests.

## 2026-07 · D-039 · Release bundles own the complete media runtime

### Context

An end user must not configure Conda, `PATH`, FFmpeg, or libmpv after installing AvialView. Source
checkouts still use locally supplied native tools, but a release bundle must include both playback
and metadata-probing executables plus the dynamic libraries they require.

### Decision

Release staging rejects a media directory that lacks `ffmpeg`, `ffprobe`, or libmpv. On Windows and
macOS it copies the dynamic libraries from the dedicated media-package roots; Windows keeps the
libmpv dependency DLLs together with `libmpv-2.dll`. At startup, `avialview.runtime` gives bundled
media precedence and configures it before the lazy `mpv` import. Video inspection resolves an
explicit `ffprobe` executable rather than relying on the process working directory.

### Consequences

`AvialView-Setup.exe` is the supported plug-and-play route. A source checkout documents its two
unavoidable native prerequisites separately. Any future packaging change must retain the staging
validation and a clean-environment installer smoke test.

## 2026-07 · D-040 · Sidecar writes use bounded concurrency and failures remain observable

### Context

The 180-million-sample pyramid retained exact values and the settled sidecar format, but a Windows
audit measured a repeatable 3.25-second build against the 2.5-second engineering mark. Profiling
showed that independent NumPy sidecar writes dominated the path. The same audit found broad
exception handlers that could turn diagnostic, autosave, seek, or shutdown failures into blank UI
state without evidence.
The Windows demo also started four metadata workers and then constructed four libmpv/OpenGL panes
in one burst. It could freeze before any pane appeared. Its initial exact seeks raced libmpv file
loading, and a fast tiny file could emit readiness before the queue handler was connected, leaving
the remaining videos permanently queued.


### Decision

`PyramidBuilder` reduces every published level deterministically, then persists independent arrays
through one bounded three-worker pool. Every future is joined and its exception propagated before
the builder returns. The file layout, dtypes, gap semantics, and cache loader version do not change.
All-NaN envelope blocks remain valid but no longer emit `RuntimeWarning`.
Video metadata probes and native pane initialization are serialized. A pane retains seeks until
libmpv emits `file-loaded`; queue advancement is connected before playback begins and occurs only
after that readiness signal. Failed probes advance when their worker exits. Decode and rendering
remain libmpv-threaded after initialization.


Production-code architecture tests reject `QApplication.processEvents()`, `shell=True`, and
`except Exception: pass`. Expected transient failures may be handled at adapter/UI boundaries, but
they must be narrowed, logged, returned in diagnostics, or surfaced through an actionable signal.
Disk diagnostics use unique temporary files and always clean them up.

### Consequences

The five-round Windows build mean measured 2.07 seconds with the unchanged 2.5-second assertion.
The worker count remains a small constant; do not scale it with channel count or CPU count. The
native Windows release-demo probe completed with four ready video panes, 12 data channels,
empty video/data queues, and 175 event-loop ticks during its bounded 20-second run.

CI bundles must start and exit cleanly. Staged-media release bundles receive a fresh isolated demo
directory and must generate and load four videos and all 12 channels within 120 seconds.

Native window compositing still requires installer smoke tests on physical Windows, macOS, and Linux;
hosted offscreen CI certifies decode/timeline/lifecycle correctness, not desktop-driver behavior.

## 2026-07 - D-041 - 3D tracking is a cache-backed current-pose view

The 3D view consumes complete `name_x` / `name_y` / `name_z` channel triplets from the same
`PyramidReader` objects used by plots and readouts. It is not a new source type, does not alter the
frozen plugin API, and receives time only from `Player`'s `MasterClock` update path.

`VideoGrid` and `Tracking3DPane` share a native horizontal `QSplitter`, producing a draggable
vertical handle whose local geometry is stored in QSettings. The view samples one nearest cached
pose, groups shared timestamps per source, and custom-paints only that pose; it never loads or draws
a full trajectory on a clock tick. The 128-point cursor benchmark retains the 2 ms budget.

No skeleton edges are inferred from point names because doing so would invent scientific semantics.
Explicit topology can be added later through versioned plugin/configuration metadata. PyOpenGL and
GPU-specific scene libraries were rejected here: the bounded QPainter projection is portable,
adds no dependency, follows the active palette, and is substantially below the cursor budget.

## 2026-07 · D-041 · TimeMap exact piecewise interpolation

**Context:** The application previously strictly enforced a single affine (`offset` + `drift_ppm`) mapping for all sources. While mathematically sound for slightly-drifting clocks, this cannot correctly map dropped frames (gaps) from a Variable Frame Rate (VFR) container back to a continuous hardware trigger sequence (e.g. CSV frame timestamps). An affine mapping causes progressive visual drift during playback and seeking when frames are dropped.

**Decision:** `TimeMap` accepts an optional `_exact_master` and `_exact_source` interpolation array pair. When present, `to_source` and `to_master` evaluate the exact timestamp mapping via `numpy.interp`, entirely overriding the affine fallback.

**Alternatives rejected:** Passing a custom TimeMap subclass (violates static type expectations and UI decoupling); rewriting the media container's timestamps on disk using ffmpeg (modifies user data, slow); generating a temporary mpv `--tcfile` (causes OSD and internal app state to misalign with true frame timestamps).

**Consequences:** `SyncWizard` provides an "Exact Index (1:1 Frame Mapping)" mode. If chosen, `SyncWorker` maps the reference index to the video index (with a user-supplied offset) 1-to-1. Video playback natively pauses on missing frames exactly when the CSV indicates a gap, preserving 0 drift across the entire timeline regardless of container defects. Session schema v5 persists both complete timestamp arrays; loading a session restores the exact mapping rather than degrading it to the affine summary.

## 2026-07 · D-042 · Plots use one fixed, shared oscilloscope sweep

### Context

Continuously translating every plot range makes the X-axis labels move during playback and the
discrete window selector cannot express the inspection interval a user actually needs. Giving each
row its own navigation control would also allow channels to show different time spans and undermine
visual comparison.

### Decision

Every time-series row shares one fixed `0…window` X range. The master-clock time deterministically
selects a sweep anchored at the master timeline start: the trace is revealed from left to right,
then the next bounded pyramid slice starts at the left edge. A numeric window limit and
`ms` / `s` / `min` / `h` unit selector define the scale for one linearly mapped, fine-grained
slider below the complete plot stack. Plot rows do not pan or zoom independently. Their small close
buttons route through the existing sidebar checkbox and do not create a second visibility state.

Ordinary clock ticks update only the playhead and a paint clip over pre-decimated curve data.
Pyramid queries occur when a sweep boundary is crossed, when the shared duration changes, or when
sources change. Absolute master timestamps remain authoritative for annotations, gaps, coverage,
and measurement points; they are converted to sweep-relative display positions only at render time.
Slider drags expose the pending value immediately but cap pyramid refreshes to the display cadence;
release always commits the newest value. Resize storms similarly issue one deferred refresh at a
quantized final viewport width, and hidden rows are skipped.

### Consequences

All plots retain one X-link, one duration, and one navigation control. The explicit limit makes
millisecond inspection and hour-scale coarse adjustment predictable without a second scrollbar.
Session `plot_x0`/`plot_x1` compatibility fields persist `0` and the shared duration without a
schema bump. The cursor benchmark uses populated plot rows and retains the 2 ms release budget;
a four-channel committed-window refresh must remain below the 30 ms UI-worker threshold.

## 2026-07 · D-043 · Presentation timestamps own video timing and exact interaction

### Context

Containers can declare a constant nominal rate while their presentation timestamps are variable.
Repeatedly extracting every packet timestamp also makes long-video reloads unnecessarily slow.
After a user accepts a 1:1 frame-trigger mapping, arbitrary exact scrub times and fixed-delay
frame-step callbacks can leave the master cursor between the evidence timestamps.

### Decision

`VideoMetadata` is an additive, defaulted `VideoSource` v1 extension. Standard video classifies
CFR/VFR and computes measured/range rates from presentation timestamps; the container's rate remains
visible only as nominal evidence. The timestamp array is stored in the normal content-hash-validated
sidecar and mmap-read on later opens. The OSD and properties panel consume this format-neutral
metadata and show timing classification, both nominal and measured evidence, codec, and byte size.

For an accepted exact mapping, the first active exact-mapped pane is the reference frame clock.
Exact scrub release, pause, and stepping snap the master clock to its nearest/adjacent accepted
trigger timestamp, then all panes receive their own `TimeMap` target. Playback uses the local
piecewise mapping slope and half-frame drift tolerance. libmpv commands remain on the Qt-owning
thread and exact settling still requires delivered seek-state and target-time evidence.

Active playback never blocks `MasterClock` on a pane's `seeking` observer. An unsettled pane drops
frames and rejoins independently; healthy panes and non-video views continue. libmpv render and OSD
callbacks use a latest-value pending slot rather than enqueueing one Qt invocation per callback.
Unchecked video panes remain loaded but paused and absent from seek/drift fanout, and their stored
visibility survives every grid or fullscreen relayout.

### Alternatives rejected

Trusting `r_frame_rate`; showing only one average VFR number; decoding frame metadata on every open;
`time × fps` frame indices; a 50 ms frame-step timer; issuing one exact seek per playback frame.

### Consequences

Existing third-party video plugins remain source-compatible because `video_metadata()` has a
default implementation. Timestamp-aware plugins can override it. Cached timestamp format changes
must bump its loader version. The four-video application-side exact-mapping dispatch benchmark must
remain below 2 ms, as must a four-video 120-frame callback burst after coalescing; real decode still
owns the existing 250 ms three-camera exact-seek budget.

## 2026-07 · D-044 · Plot presentation separates review, sweep, and scope

### Context

D-042 correctly established one fixed shared plot duration, stable X coordinates, bounded pyramid
queries, and close-to-checkbox visibility. Its clear-and-restart reveal is useful oscilloscope
behaviour but is not sufficient for two different field tasks: inspecting a complete recorded page
while paused and monitoring playback with an ECG-like overwrite sweep. Repeated X axes, automatic
Y movement, equal-weight min/max lines, arbitrary rainbow traces, competing overlays, and two
similar-looking sliders also obscure scientific comparison without adding information.

### Decision

D-042 remains authoritative for shared time state and performance: all plots keep one X link, one
duration, one global horizontal navigator, absolute-time overlays, pyramid-only data, boundary
queries, and the existing visibility route. Its clear/restart display remains available as
**Scope** style.

Presentation gains three explicit states defined by `PLOT_UX_PLAN.md`: paused/scrubbed **Review**
shows the complete fixed page; live **Sweep** retains the previous page until a bounded eraser gap
overwrites it; live **Scope** retains the current clear/restart behaviour. Sweep is the default
fresh live-style preference, while Scope remains selectable. Strip/Roll, which translates X labels,
is not part of this refinement.

Data Streams is extended into the only full-session horizontal navigator by adding a draggable
visible-window rectangle without removing its coverage, Sync/TTL, gap, annotation, detail,
collapse, splitter-resize, or click-to-seek responsibilities. Its width follows the shared duration
and is not a second duration state. Time-span entry retains a number,
`ms` / `s` / `min` / `h` selector, and continuous slider; unit changes convert rather than
reinterpret duration, and the slider mapping is logarithmic or piecewise-monotonic. Individual
rows may have Y Fit/Auto/Manual state and one shared vertical channel-list scrollbar, but never
independent X navigation.

The visual hierarchy uses one bottom master-time axis, fixed channel gutters with unit/range and
close-to-hide, a single min/max envelope, semantic palette roles, quieter grids, and pooled/shared
overlays where possible. Controls may move to plot, video, annotation, or transport groups, but
existing QActions/signals, shortcuts, and capabilities remain the single authorities and cannot be
deleted. Widgets retain normal Tab focus; shortcut arbitration, not blanket `NoFocus`, protects
Space during text editing.

### Alternatives rejected

Replacing D-042 with an always-scrolling strip chart; giving each row its own scrollbar or time
range; removing the current Scope behaviour; midpoint-only decimation; continuous hidden
auto-ranging; a global QSS restyle; deleting controls because their layout changes; implementing
the refinement as one uncharacterized rewrite.

### Consequences

The work proceeds in the tested slices in `PLOT_UX_PLAN.md` §13. Existing `.avv` files remain
loadable and new presentation fields are optional with explicit defaults. Ordinary clock ticks
still cannot query the pyramid or scan all evidence, retained sweep buffers are bounded to the
current/previous page, and the populated ≤2 ms cursor, ≤16 ms plot, and 30 ms UI-callback ceilings
remain release gates. `HANDOUT.md` must distinguish planned from implemented slices.

---

## 2026-07 · D-045 · The AOL encoder axis is seconds-since-midnight, unwrapped

### Context

AOL sessions place video, 3D EKS tracking, and the encoder log on one master timeline. The manifest
reads each camera's absolute UTC start epoch, and `drop_worker._collect_aol_candidates` subtracts the
session's anchor-date epoch from it. `AOLEncoderLoader._parse_wall_clock` independently produces
seconds since midnight from the log's `HH:MM:SS:mmm` column.

An audit claimed the encoder was therefore misaligned because it ignores `config["anchor_date"]`.
Measuring the reference session (`2026-05-08/experiment_1/09-35-24`) disproved this: video covers
master `[34526.312 … 34586.502]`, EKS `[34526.312 … 34586.499]`, encoder `[34526.082 … 34586.964]`.
All three already share one axis, and the encoder correctly brackets the cameras by ~0.2–0.5 s.

### Decision

Seconds-since-midnight (UTC) is the AOL master axis. `AOLEncoderLoader` must NOT add the anchor
epoch; `config["anchor_date"]` is accepted for provenance and deliberately unused. Across midnight
the encoder axis is *unwrapped* (86400, 86401, …) rather than wrapped to 0, because video and EKS
master time is epoch-derived and keeps increasing.

### Alternatives rejected

Adding the anchor epoch inside the encoder loader (shifts it ~20.6 days out of alignment on the
reference session); moving video/EKS to absolute epoch instead (a larger change that alters every
existing AOL `.avv`); wrapping the encoder at midnight (desynchronises by a full day).

### Consequences

`test_encoder_axis_is_seconds_since_midnight` pins the axis and names this entry, so the withdrawn
"fix" cannot be reattempted silently. Any future move to absolute epoch must change the manifest,
the loader, and the session schema together.

---

## 2026-07 · D-046 · Pose data drives the overlay and 3D view, never plot rows

### Context

An AOL session emits 27 3D EKS channels plus, per camera, an EKS-fused 2D prediction and one file
per contributing model (~81 2D channels per camera on the reference session, 12 files across three
cameras). Previously only the 3D file was discovered, everything imported became plot rows, and the
overlay was fed from `plot_pane.sources_changed` — so every pane received every camera's points, and
3D millimetre coordinates were painted as if they were pixels.

Channel names are not unique across these files: every camera and every model emits `head_bar_x`.

### Decision

Import candidates carry a `role`: `"overlay2d"`, `"pose3d"`, or absent for ordinary recorded
signals. `MainWindow._on_import_finished` routes by role — pose sources register with the overlay or
the 3D view and are **not** plotted; only signals like the encoder get plot rows. 2D tracks are
routed to the pane for their own video path, never broadcast. Overlay readers are built from each
source's own sidecar cache, so duplicate channel names across cameras and models cannot collide
without waiting for the global `(source_id, channel_id)` identity work.

2D overlays carry no `start_epoch`: they are painted against mpv's media clock, which starts at 0.
3D pose keeps `start_epoch` because the 3D view works in master time.

The 3D view's vertical axis is detected from head/foot landmark names and flipped so head renders
above toes; data with no recognisable landmarks keeps a neutral Z-up default rather than guessing,
and an explicit user choice pins the orientation against later loads.

### Alternatives rejected

Plotting pose channels and hiding them afterwards (still builds ~250 plot rows); inferring the
overlay target by matching channel names at paint time (relies on the very uniqueness that does not
hold); a fixed Z-up 3D projection (renders the reference session edge-on); inferring skeleton
topology from names (already rejected by D-041).

### Consequences

`tests/test_aol_pose_routing.py` covers per-camera targeting, the plot-row exclusion, ensemble vs
model colouring, and the empty-camera-token fallback. The overlay legend names each source, so
colour is never the sole distinction. The frozen v1 plugin contract is unchanged: `role` is host
supplied import configuration, not a new loader API.


## 2026-07 · D-052 · Encoder log aligns to relative zero on manual import

**Context:** D-045 and the original architecture dictated that the encoder log remain
in seconds-since-midnight, keeping it on the same axis as EKS tracking and the
AOL video streams (which are shifted via manifest offset by `drop_worker`). However,
when imported manually outside of an AOL session, videos and CSVs natively start at
0.0, leaving a ~9 hour gap between them and the encoder.

**Decision:** The encoder loader now checks if it's being invoked manually -- the
absence of `auto_resolved` in the configuration, which `drop_worker` sets to `True`
on every candidate it builds for an AOL session. `anchor_date` is not a valid signal
for this: a normal auto-detected session with a resolved anchor date carries
`anchor_date` too, so keying off its presence would misclassify real sessions as
manual imports. When manual, the loader subtracts its first timestamp to become
"time only" (relative, starting at 0.0), perfectly aligning it with manual video
and tracking streams. AOL session loads remain unaffected and preserve the strict
seconds-since-midnight axis needed for multi-camera correlation.

## 2026-07 · D-053 · Drift is judged against the frame interval, and per-frame UI work is capped

**Context:** playback juddered on Windows and on fast machines with 4+ cameras, described as a
"seek and show" behaviour. Two independent costs scaled with `panes × decoded fps` on the UI
thread.

First, the drift corrector. libmpv's `time-pos` is the timestamp of the frame *on screen*, so it
only advances when a frame is presented. Sampled by the 60 Hz tick against a continuous master
clock, a decoder keeping perfect time still reads back as 0–1 whole frame intervals behind. The
corrector compared `|time_pos - source_t|` against a *half*-frame tolerance — a deadband narrower
than the observable's own quantum, which no healthy pane can satisfy. Driving the real
`Player._on_tick` with a decoder pinned exactly to master measured **48 `mpv.speed` writes per
second per pane**. Each write takes libmpv's core lock away from the decoder threads.

Second, presentation. `_observe_time` fires once per presented frame per pane and relaid out the
OSD label and composited the tracking overlay every time — 720 UI-thread repaints/sec at six
cameras and 120 fps. `PaintCanvas._video_scale` additionally read `mpv.dwidth`/`dheight` from
inside `paintEvent`, taking libmpv's core lock on the UI thread during a paint (measured 26–34 µs
typical, 165 µs p99, per pane per frame).

**Decision:**

1. Drift is measured as `residual = (time_pos - source_t) + interval/2`, centring the expectation
   inside the frame-display window, with a deadband of one full interval
   (`_SOFT_CORRECTION_FRAMES`). `VideoTimingMixin.frame_interval_at_master()` replaces
   `sync_tolerance_at_master()` so the units are unambiguous at the call site.
2. The residual is smoothed per pane (`_DRIFT_SMOOTHING`) because the raw value is frame-quantised,
   and the commanded speed is quantised (`_CORRECTION_STEP`) and written only on a change of step.
3. The 5-tick hysteresis now guards the soft speed nudge as well as the hard re-seek.
4. A corrective seek drops that pane's `_drift_estimates` entry: the estimate describes where the
   pane *was*, and keeping it holds the pane above threshold and re-seeks it in a loop.
5. OSD text and overlay repaints are rate-limited to `_OSD_MAX_HZ` (20 Hz, matching
   `player._PRESENTATION_HZ`), leading-edge with a trailing single-shot timer. `PaintCanvas`
   skips the repaint entirely when it has no readers or tracks.
6. `paintEvent` never reads an mpv property. A `video-out-params` observer mirrors the displayed
   size into `VideoPane.video_size`.
7. Every pane sets `audio="no"`. The application exposes no audio feature anywhere, yet each pane
   was opening an audio output and letting mpv's default `video-sync=audio` slave video timing to
   it. Measured to roughly halve the cost of the property calls above.

**Alternatives rejected:** removing the corrector entirely (real drift on a struggling decoder
would go uncorrected); tightening the gate on `mpv.speed` writes without fixing the deadband
(treats the symptom, and the underlying oscillation still commands a modulated rate); moving OSD
updates onto the existing `Player` presentation tick (a paused seek or frame step must paint
immediately, which a fixed tick cannot guarantee); flipping `hr-seek-framedrop` back to mpv's
default — that is D-035's settled fidelity trade and it affects paused exact seeks, not playback.

**Consequences:** a healthy pane now provokes zero speed writes and zero re-seeks; a decoder
running 3 % slow is still corrected and held within ~2 frames, at ~1.6 writes/sec instead of ~56; a
pane starting 2 s behind is re-seeked exactly once. The OSD clock and tracking markers update at
20 Hz rather than at the decode rate — deliberate, and the same rate the readout panel has always
used. Regression coverage is in `tests/test_playback_smoothness.py`; the golden sync tests are
untouched and passing.

## 2026-07 · D-054 · Plots repaint at 30 Hz and stay visually plain

**Context:** video stayed choppy after D-053 with 4+ cameras. Profiling the plot pane separated
two costs that had been conflated. Advancing the sweep *state* on a 60 Hz tick is cheap — 0.23 ms
at 16 rows. Repainting the scene is not: 7.8 ms at 16 rows, 14.9 ms at 32. That repaint runs on the
same UI thread that must call `paintGL()` for every video pane, and it was being triggered on every
single tick. Measured share of the UI thread consumed by the plot alone:

| rows | before | after |
|---|---|---|
| 4  | 17 % | 10 % |
| 8  | 25 % | 14 % |
| 16 | 39 % | 23 % |
| 32 | 74 % | 45 % |

At 32 rows the plot was taking three quarters of the UI thread, leaving the video panes nothing to
present with. That is the choppiness.

**Decision:**

1. `PlotPane.set_cursor()` still runs on every 60 Hz tick and time still advances at the full tick
   rate, but the per-channel graphics-item updates are throttled to `_CURSOR_REPAINT_HZ` (30 Hz).
   A page boundary changes *what* is drawn and is never deferred. `set_cursor(immediate=True)`
   bypasses the throttle; `Player` passes it for the discrete events (seek, pause, frame step)
   that already bypass the readout rate limit.
2. The due-check carries half a tick of slack (`_CURSOR_REPAINT_SLACK_S`). Ticks land on a 16.7 ms
   grid; without slack a repaint due to the microsecond is deferred a whole further tick and the
   real rate beats down to ~22 Hz.
3. **Plots stay plain. Decorative shading is not added back.** The per-page `retained_fill`
   (an alpha-blended `FillBetweenItem` tinting the data about to be overwritten) is removed; the
   previous page keeps its min/max outlines as thin pens. No gradients, shadows, glows, or
   decorative alpha layers may be introduced in plot rows. Anything drawn on a plot row must carry
   information, because everything drawn there is repainted while video is trying to present.
4. Per-tick allocation is not acceptable in the sweep path: the eraser `QBrush` is cached against
   the palette instead of rebuilt per row per tick, and the page label is only re-set when its
   text actually changes.

**Alternatives rejected:** throttling `set_cursor` itself (would break the D-043 guarantee that
authoritative time advances at 60 Hz, and the hot-path test that asserts it); moving plots to a
second thread (Qt graphics are main-thread only); dropping the sweep's retained page entirely
(it is the affordance that makes Sweep mode readable).

**Consequences — measured, and one of them is negative:** removing the alpha fill did **not** make
individual repaints cheaper; replacing it with a second outline pen made them ~20 % dearer
(12.4 ms → 14.9 ms at 32 rows). The entire win came from repainting half as often. The fill is
still gone because §3 is a standing policy, not a performance claim. If plot cost needs cutting
further, the next lever is the row count and the retained page's second outline, not more shading
removal. The envelope fill between `curve` and `envelope_upper` is **data** — the min/max range of
decimated samples, the only thing showing true signal excursion at 50 kHz — and is deliberately
retained. Covered by `tests/test_playback_smoothness.py`.

## 2026-07 · D-055 · The sweep write-head band is removed; the cursor is a plain line

**Context:** each plot row drew a yellow `cursor_line` at the sweep phase *and* a `sweep_eraser`
`LinearRegionItem` — a dark band from `phase` to `phase + max(window*0.006, 0.002)` — immediately
beside it, to imitate an oscilloscope write head separating new data from the page being
overwritten. On screen this reads as two cursors: a line with a blinking dark companion trailing
it, and the band's width scales with the window so it is wider on longer pages.

**Decision:** the band is removed. The boundary between new and retained data is the cursor line
itself. The plot cursor is a plain vertical line with no companion marks, no animation, no
easing, and no fade. Per D-054 §3 this is a standing policy, not a one-off cleanup.

**Alternatives rejected:** narrowing or dimming the band (it would still be a second moving mark);
making it a preference (a toggle for a decoration that costs a `LinearRegionItem` repaint per row
per frame is not worth the setting, the code path, or the test).

**Consequences:** one fewer graphics item per row, and one fewer `setRegion` + `setBrush` pair per
visible row per repaint. Measured effect on repaint cost is small (14.9 ms → 14.5 ms at 32 rows,
~3 %) — the change is primarily a correctness-of-appearance fix, and it is reported as such rather
than dressed up as a performance win. `test_live_sweep_retains_only_the_previous_page_until_overwritten`
now asserts the cursor position where it used to assert the band's region.

## 2026-07 · D-056 · Fonts are read from the platform, never asserted

**Context:** re-confirmed while auditing UI cost. Test runs emit
`Populating font family aliases took ~100 ms … missing font family "Sans Serif"`, which looks like
a startup cost the application is paying.

**Decision:** it is not, and no font handling changes. `theme._system_font()` captures
`QApplication.font()` — the platform font, `.AppleSystemUIFont` on macOS — and monospace readouts
use `QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)`. AvialView ships no font files,
registers nothing with `QFontDatabase.addApplicationFont`, and names no family literal anywhere.
`set_font_family()` only re-applies an already-resolved platform family so a widget keeps its role
through application font scaling.

**Evidence:** with the real `cocoa` platform the app font is `.AppleSystemUIFont` and **no** font
message is emitted. The warning appears only under `QT_QPA_PLATFORM=offscreen`, whose plugin has
no platform font theme and falls back to the `"Sans Serif"` alias. It is an artifact of the
headless test environment and must not be "fixed" by hardcoding a family — doing so would
override the user's system font choice, which is exactly what this design avoids.

## 2026-07 · D-057 · One trace per row, drawn as an interleaved min/max polyline; Scope is the only live presentation

**Context:** two follow-ups from D-054/D-055 review of a live screenshot.

First, a row still showed a shaded band around the bright line. That band was an
`envelope_fill` `FillBetweenItem` spanning `curve` (the per-column **minimum**) and an invisible
`envelope_upper` (the per-column **maximum**). So the bright line users read as "the signal" was
actually the minimum, and the peak of a spike lived only in the shading on top of it — visible in
the reviewed screenshot as a trace peaking at ~26.5 with the band reaching ~29.

Second, the header offered two live presentations, `Sweep` and `Scope`, differing only in whether
the previous page stayed drawn underneath the new one. Only Scope is wanted.

**Decision:**

1. A row draws **one** curve. `refresh_channel_plot` interleaves each decimated column's min and
   max into a single polyline — `(x, min)`, `(x, max)` per column — which strokes one vertical
   span per pixel column and connects them, the way an oscilloscope or audio waveform is drawn.
   `envelope_upper` and `envelope_fill` are deleted. Three items become one, nothing is
   alpha-blended, and **no peak is lost**: the range that used to require the fill to see is now
   in the stroke itself. Gap columns carry NaN at both ends so `connect="finite"` breaks the line
   rather than drawing across.
2. `PlotPresentation.SWEEP` is removed along with `retained_curve`, `retained_upper`, and
   `retain_channel_plot`. `SCOPE` is the only selectable live presentation; `REVIEW` remains the
   automatic paused/scrubbing state and is not user-selectable. The saved
   `plot/live_presentation` default becomes `scope`; an existing `"sweep"` setting falls back
   through the existing `ValueError` guard.
3. A visible row is now exactly two items: the trace and the yellow cursor line.

**Alternatives rejected:** keeping the fill (it hides the fact that the bright line is a minimum,
and it is the shading that was objected to); dropping the upper boundary and drawing the minimum
alone (fastest, but it silently shortens every peak — a spike of 100 would have drawn as 0 in
`test_decimated_plot_preserves_minimum_and_maximum_envelope`); drawing the column midpoint (a
single honest-looking line that still discards both extremes).

**Consequences — measured.** UI-thread share taken by the plot, 60 Hz-repaint original → now:
4 rows 17 % → 8 %, 16 rows 39 % → 21 %, 32 rows 74 % → 42 %. `load_channels()` for 64 channels
dropped from 713 ms to 550 ms (23 %) because a row builds fewer graphics items. Per-*repaint* cost
is not lower than the original (12.4 ms → 13.9 ms at 32 rows): the interleaved curve has twice the
vertices of the old single boundary line, and that roughly offsets deleting the fill. As with
D-054, the wall-clock win comes from repainting half as often, not from removing shading — recorded
so nobody re-adds a fill expecting it to be free. `test_decimated_plot_preserves_minimum_and_maximum_envelope`
now asserts the spike survives by reading the one curve, which is a stronger guarantee than before.

## 2026-07 · D-058 · The pyramid query fills the point budget instead of undershooting it by up to 16x

**Context:** traces looked jagged and blocky rather than following the sampling rate. It was neither
the data nor the min/max rendering of D-057. `PyramidReader.query` chose the *first* stored level
whose point count fit the budget. Levels step by 16 (`LEVELS = [1, 16, 256, 4096]`), so the result
routinely fell far below the budget — the plot was handed a fraction of the columns it had pixels
for, and long straight segments between sparse min/max extremes is what "jagged" looks like:

| samples in window | columns drawn (before) | px per column @1400 px | columns (after) |
|---|---|---|---|
| 1 500 | 93 | 15.1 | 750 |
| 50 000 | 195 | 7.2 | 1 041 |
| 1 000 000 | 244 | 5.7 | 1 302 |

The same search also had a fall-through that returned the coarsest level *unconditionally*, so a
180 M-sample recording returned **43 945 points** — far past the budget and straight into
pyqtgraph, against ARCHITECTURE rule 4.

**Decision:** take the coarsest stored level that still holds *at least* `max_points` (which bounds
the read to under `16 * max_points`), then aggregate that down to the budget with the existing
`_aggregate_pyramid_level` / `_aggregate_gap_mask` helpers. A window whose raw samples already fit
is returned untouched — exact samples, `vmin == vmax`, no envelope at all. The budget is now a hard
ceiling in both directions.

**Alternatives rejected:** adding more stored levels, e.g. a 4x step (multiplies sidecar size and
build time for the same result); lowering `point_budget_for_width` to make the undershoot less
visible (draws less of the signal, which is the complaint); rendering the column midpoint (smooth,
but discards both extremes and hides spikes — see D-057).

**Consequences — a real trade-off, recorded rather than buried.** `test_bench_four_channel_window_refresh`
improved 6.6x (6 195 us → 928 us) because a refresh no longer pushes tens of thousands of points
into pyqtgraph. `test_bench_pyramid_query` **regressed 10x** (8.9 us → 89 us) because the query now
does the aggregation the plot layer used to force downstream; it sits at 1.8 % of its declared 5 ms
budget, so the gate passes with wide headroom, and the composite operation is what got faster.

Repaint cost rose with resolution, because drawing more of the signal costs more: at 16 rows,
7.1 ms → 12.3 ms per repaint (21 % → 37 % of the UI thread at 30 Hz). A measured sweep of
columns-per-pixel at 16 rows: 1.0 → 13.7 ms, 0.5 → 9.9 ms, 0.25 → 7.2 ms. **One column per pixel is
kept.** Below that the trace is visibly under-resolved, which is the defect this entry fixes; buying
back UI-thread time by drawing less of the signal is not a trade this project makes. Sessions with
very many plot rows should hide rows rather than have every row drawn wrong.

## 2026-08 · D-059 · Shutdown is fault-isolated and ordered; the playhead keys are reserved

**Context:** two reported defects, plus a third found while reproducing them.

*The window sometimes would not close.* `closeEvent` ran its teardown steps in bare sequence. A
raise in any step skipped every later one — including `video_grid.shutdown()`. Each pane owns a
libmpv event thread that outlives its widget, so a stranded pane keeps the process alive after the
window hides. The trigger is state-dependent, which is why it was intermittent:
`_release_mpv_render_context` called `widget.makeCurrent()` *outside* its `try`, and that raises on
a `QOpenGLWidget` whose surface was never created or is already gone.

*Playhead keys stopped working after some operations.* Qt offers every key to the focused widget as
a `ShortcutOverride` before running a window shortcut. Probing all 37 focusable widgets in the
window showed exactly two classes accept that offer: `QLineEdit` and `QAbstractSpinBox`, and they
take Space, Left, Right, Home and End. Both are one click away — the transport's time field and the
sweep-length spin box — so a single click silently disabled playback control.

*The final autosave wrote a session with no videos.* `_build_session_state()` reads
`video_grid.panes`, and `closeEvent` called `video_grid.shutdown()` — which clears them — first.
Measured directly: two open videos, zero written. Every close with a session open discarded the
user's video list.

**Decision:**

1. Every `closeEvent` step runs through `_close_step`, which logs and continues. Closing is the one
   path with no later chance to recover, so no single failure may abandon the rest.
2. State is captured before anything is torn down: geometry and the final autosave run first, and
   libmpv teardown runs last.
3. `VideoGrid.shutdown()` isolates each pane, so one pane's failure cannot strand the next pane's
   event thread. `_release_mpv_render_context` guards `makeCurrent` and `doneCurrent` too.
4. Space, Left, Right, Home, End, comma and period are reserved for the playhead across the window
   via an application-level `ShortcutOverride` filter. Two exceptions: a text editor the user is
   part-way through typing into keeps its caret keys (`QLineEdit.isModified()`), so correcting a
   half-entered timecode still works; and the filter never applies outside this window, so a
   dialog's editors keep everything.
5. **Space is never returned to an editor.** No timecode and no number contains one.
6. The filter is removed in `closeEvent`. A filter installed on the `QApplication` outlives the
   widget that installed it, and a destroyed window left in that chain aborts the process on the
   next key event.

**Alternatives rejected:** restoring focus to a neutral widget after each operation (only fixes the
paths someone remembers to wire, and the defect is that focus is *somewhere unexpected*);
`Qt.ShortcutContext.ApplicationShortcut` (does not change which widget wins a ShortcutOverride, and
would leak the shortcuts into dialogs); giving the editors `NoFocus` (they must be typeable).

**Consequences:** `test_entered_time_editor_returns_focus_to_playback_surface` asserted
`received == []` for Space pressed inside an editor — it encoded the defect as the contract. Its
real subject, that accepting a value returns focus to a playback surface, is unchanged and still
asserted; only the Space expectation was corrected. Covered by `tests/test_close_and_focus.py`.

## 2026-08 · D-060 · Plot rows are built in time slices, so a load never takes the UI thread

**Context:** reported as "drag and drop is not working" plus "many UI blockages". Drag and drop was
measured to be fine: with the correct enter-then-drop sequence, every one of ten candidate targets
routes exactly once. The real fault is that `PlotPane.load_channels()` built every row in one call
at ~8-12 ms of Qt widget construction each — 128 ms for 16 channels, 550 ms for 64, worse on
Windows with real data. During that the window processes no events at all, so drops, playback keys
and the close button all appear dead. "Drag and drop is broken" was a symptom of the freeze.

**Decision:** rows are queued and built in `_ROW_BUILD_SLICE_S` (12 ms) slices, with
`QTimer.singleShot(0, ...)` returning control to the event loop between them. Qt graphics objects
must be created on the UI thread, so the work cannot move to a worker; slicing is the available
mechanism. Supporting parts:

* Each slice loads pyramid data for only the rows it just built. Leaving all 64 to the end made
  completion a 62 ms hitch; it is now 5 ms.
* A new row gets its X range **before** it is linked. An X link only propagates on a *change* of
  the master's range, so a row linked later kept its construction default. Setting the range after
  linking is worse: it feeds back through the link and rescales the master.
* `_finish_loading` activates the graphics layout before configuring the shared range. pyqtgraph
  maps a link through the two views' *pixel* geometry, and a row created in the same call has not
  been laid out, so the final row of every load got a wildly wrong range.
* `_configure_shared_x_range` is **not** called per slice — it is O(rows), which made the load
  quadratic and measurably slower (1261 ms) as it became more responsive.
* `cancel_pending_rows()` runs in `closeEvent`. A close must never wait for construction it no
  longer needs, and a queued slice must not fire into a pane being destroyed.
* `channels_loaded` lets `MainWindow` re-apply exact reader-derived bounds once every row exists;
  until then the import worker's bounds stand in. `rows_pending` reports progress so a partial plot
  is not mistaken for the whole thing.
* `wait_for_pending_rows()` exists for callers that genuinely need every row now — tests and
  session restore. Interactive loads must not use it.

**Measured, 64 channels.** First pass: event-loop turns serviced went from 0 to 35, worst single
UI block ~550 ms → ~89 ms. Three further changes took it the rest of the way:

* the slice stops before the *next* row would overrun, not after one already has — checking
  afterwards let a slice run to roughly twice its budget;
* each row's pyramid data loads inside the timed region, so the budget covers it;
* completion runs in its own event-loop turn rather than on the tail of the last slice, which had
  been making one block out of two.

`_ROW_BUILD_SLICE_S` was then chosen by measurement rather than reasoning: 12 ms gave a 31-38 ms
worst block, 5 ms was no better (39 ms), and 8 ms won on every axis. Final: **worst single UI block
18-37 ms** (from ~550 ms), event-loop turns 55-64, total load 614-946 ms against 550 ms originally.
A slice always builds at least one row, so a single expensive row sets the floor — the worst case
cannot go below one row's cost by shrinking the slice further.

**The load is slower on purpose** — yielding costs wall-clock, and a responsive window during a
one-second load beats a frozen one during half a second. Verified interactively: Space and Home
reach the playhead mid-load, and closing mid-load is accepted in 3 ms with the queue abandoned.

Both deferrals use `QTimer.singleShot(0, self, slot)` — the context-object overload. Without it Qt
fires the callback into a destroyed `PlotPane` and raises `Internal C++ object already deleted`,
which surfaced as two benchmark failures.

**Alternatives rejected:** a worker thread (Qt graphics objects are main-thread only);
`QApplication.processEvents()` between rows (forbidden by AGENTS, and it re-enters arbitrary
handlers mid-construction); building rows lazily as they scroll into view (the rows must exist for
bounds, readout and annotation wiring).

## 2026-08 · D-061 · Panes keep their share of the window; controls keep their size

**Context:** resizing the window did not rescale the workspace. `QSplitter` distributes only the
*delta* of a resize, by stretch factor, and a pane already sitting on its minimum absorbs none of
it — its sibling takes the entire change. Measured on the built window:

| window | video : plots | video : 3D |
|---|---|---|
| 1280x800 | 34 : 66 | 59 : 41 |
| 1000x600 | 47 : 53 | 47 : 53 |
| 2000x1200 | 29 : 71 | 61 : 39 |

The drift is one-way: growing the window back did not restore the ratio, so a session accumulated
skew every time the window changed size. Two floors caused the pinning — the empty video area's
drop-target placeholder (`lbl_empty`, a hard 200 px minimum height) and the 3D pane's header row
(406 px minimum width).

Separately, `_apply_default_splitter_sizes` never took effect. Its pixel counts were discarded by
the first real resize, so what a fresh profile actually got was decided by whichever pane had the
largest minimum — for the vertical split, the placeholder above.

**Decision:**

1. `ui/pane_proportions.py` reallocates each managed splitter's whole span by remembered fractions
   on every window resize, clamping to minimums and re-sharing what is left. Managed: the
   workspace/Data Streams, video/plots, and video/3D splitters.
2. **Panes scale; controls do not.** No button width, icon, font size, or label text changes with
   the window. This was the user's explicit constraint and it is not to be relaxed into a "UI scale
   factor" later: text that resizes with the window is a different product decision, and a
   measurement tool whose readouts change size is worse, not better.
3. The inspector column (`_h_splitter`) is deliberately **not** managed. A source list that widens
   with the monitor only takes width the media panes want.
4. The remembered ratio is always one the layout actually produced. A drag records the user's
   choice; restoring a session records what was restored; a visible pane measuring zero is refused,
   because that is a layout that has not happened yet and recording it pins that pane forever.
5. First-run defaults are ratios, not sizes: the same numbers seed `setSizes` and the proportion
   store, and only the store survives the first resize.
6. The placeholder's 200 px minimum becomes a preference, not a floor. An empty video area is still
   readable as a drop target (`VideoGrid` minimum height 72) without dictating how the window's
   height is shared.

**Consequences:** proportions now hold exactly from 2000x1200 down to the window's minimum, and a
shrink-then-grow returns to the original arrangement. Reallocation is coalesced at 16 ms, so a
drag-resize costs one relayout per frame rather than one per pixel of mouse travel.

Remaining floors are chrome, left untouched under decision 2: the window cannot be narrower than
**966 px**, set by the Data Streams header row (764 px) plus the inspector (198 px), with the
transport's timeline row close behind at 680 px. Below ~1280 px the 3D pane also stops scaling, held
at its own header's 406 px. Narrowing further requires shortening or wrapping those rows.

**Alternatives rejected:** scaling control metrics and fonts with the window (rejected by the user:
buttons, icons, and text must not change); applying proportions only when the resize settles (the
layout visibly snaps on release); trusting `QSplitter` stretch factors alone (they distribute the
delta, which is the bug).

## 2026-08 · D-062 · Background workers are destroyed on the UI thread, never inside their own

**Context:** the staged-bundle release gate (`packaging/smoke_test.py --demo`) hung permanently
instead of failing. `sample` on the stuck process showed a two-thread cycle:

| thread | holds | waits for |
|---|---|---|
| worker `QThread` | a Qt signal/slot mutex (inside `~QObject`) | the GIL, via PySide's `disconnectNotify` |
| UI thread | the GIL | a Qt signal/slot mutex, closing a `QProgressDialog` |

`QObject::~QObject` severs the object's connections while holding one of Qt's **131 pooled**
signal/slot mutexes — pooled by object address, so two unrelated objects share a mutex whenever
their addresses collide. PySide overrides `disconnectNotify` on every wrapper, so severing a
connection calls `PyGILState_Ensure`. Destroy a worker on its own thread and that sequence runs
there; a UI thread inside any PySide virtual dispatch holds the GIL and can be waiting on the
colliding mutex. Neither side can yield.

The workers were reaching that state through `worker.finished.connect(worker.deleteLater)` and
`thread.finished.connect(worker.deleteLater)`. Both signals are emitted **in the worker thread**,
and the worker was moved there, so both connections are *direct*: `deleteLater()` posted a
`DeferredDelete` to the worker's own event loop, which then ran the destructor there.

Because the trigger is an address collision, the hang was intermittent — about one demo launch in
six from source, and roughly half of frozen-bundle runs.

**Decision:**

1. No worker moved onto a `QThread` is `deleteLater`-ed from a signal that thread emits. Every
   owner already had a UI-thread slot (`_on_*_thread_finished`, `JobManager._on_thread_finished`,
   `SyncWizard._on_thread_finished`) that drops the registry reference; that release — on the UI
   thread, where the GIL is already held — is now the only one, which is what those slots'
   docstrings already claimed.
2. `MainWindow._import_worker` is declared in `__init__` and cleared in
   `_on_import_thread_finished`, so the import worker follows the same rule.
3. `tests/test_worker_thread_teardown.py` fails on any reintroduction of the pattern.

`deleteLater` on the `QThread` objects themselves is unaffected: a `QThread` lives in the thread
that created it, so those connections are queued onto the UI thread already.

**Evidence:** 1/6 source runs hung before; 0/40 after. Full suite 705 passed.

**Alternatives rejected:** deleting the worker from the UI thread with `deleteLater` (it always
posts to the object's *own* thread, which by then is dead — the event is never processed);
`moveToThread` back to the UI thread on completion (an object cannot be pushed from another
thread); joining every worker in `closeEvent` (D-059 established that closing must never block on
a background job).
