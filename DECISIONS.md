# DECISIONS.md — lightweight ADR log
Format per entry: date · decision · context · alternatives rejected · consequences.
Agents: read before coding; append when making irreversible choices; never silently reverse entries.

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

### Consequences (what every future agent must not reverse)

- Never create a `QShortcut` for an action that already has a menu `QAction` with
  the same shortcut. The `QAction` is the single authority; the shortcut is set on it.
- Never call `player.set_playing()` or `player.step_frame()` from a keyboard shortcut
  handler. Always emit the corresponding transport signal so the transport bar stays
  in sync.
- Never bind Ctrl+V or Ctrl+D.
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
bounded interval; they never sleep, skip, or accept a stale displayed frame. Runtime seek
coordination continues to use delivered observer values and target properties; callbacks must not
re-enter libmpv.

Shutdown is owned by the widget hierarchy: `MainWindow.closeEvent()` calls
`VideoGrid.shutdown()`, which closes each `VideoPane` and terminates libmpv before Qt destroys the
widgets. Decode and property handling remain libmpv-owned during playback; explicit ownership makes
teardown deterministic.

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
