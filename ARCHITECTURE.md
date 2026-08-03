# ARCHITECTURE.md

## 1. Repository layout (complete — the authoritative map of what lives where)

```
avialsync/                          # repo root = GitHub repo `avialsync`
├── pyproject.toml                    # hatchling; dep `python-mpv`; extras: [dev], [docs];
│                                     #   entry point `avialsync`; entry-point group `avialsync.loaders`
├── README.md                         # user-facing: what/GIFs/install (installers first, pip second)
├── LICENSE                           # Apache-2.0 (D-003)
├── .gitignore                        # incl. tests/fixtures/ (generated), dist/, *.avialcache/
├── .pre-commit-config.yaml           # ruff check+format, basic hygiene hooks
│
│   # ---- agent & planning docs (repo root, read by all models) ----
├── AGENTS.md                         # canonical rules; CLAUDE.md / GEMINI.md are pointers to it
├── CLAUDE.md
├── GEMINI.md
├── BLUEPRINT.md                      # phases & exit criteria
├── ARCHITECTURE.md                   # this file
├── DECISIONS.md                      # ADR log D-001..
├── HANDOUT.md                        # model handout: module map, API, traps, run commands, bug log
├── PROMPTS.md                        # per-task kickoff prompts
├── TESTING.md                        # test strategy + edge-case matrix
│
├── src/avialsync/                  # the installable package (src layout — import avialsync)
│   ├── __init__.py                   # __version__ single source (read by pyproject)
│   ├── __main__.py                   # CLI: `avialsync` / `avialsync open <path>`
│   ├── core/                         # HEADLESS — must never import PySide6 (test-enforced)
│   │   ├── timeline.py               # MasterClock, TimeMap(offset, drift), PlaybackState
│   │   ├── session.py                # Session model + .avv JSON (versioned schema v6)
│   │   ├── source.py                 # ABCs + VideoMetadata (plugin contract, §4)
│   │   ├── pyramid.py                # NaN/gap-aware min-max pyramid build + query (D-009)
│   │   ├── cache.py                  # .avialcache/ sidecar manager, content-hash key (D-008), atomic writes
│   │   ├── registry.py               # plugin scan: `~/.avialsync/plugins/` + bundled examples/ and sys._MEIPASS
│   │   ├── inspection.py             # ImportReport, IntegrityFlags, SourceInspection — headless, frozen dataclasses (D-020)
│   │   ├── sync.py                   # SyncEvent, match evidence, affine fit/provenance dataclasses (D-026)
│   │   ├── channel_reader.py         # MappedChannelReader (master-clock view) + ChannelKey identity (D-045)
│   │   └── errors.py                 # typed exceptions (NonMonotonicTimeError, ...)
│   ├── loaders/                      # built-in plugins (use ONLY the public core API)
│   │   ├── csv_loader.py             # polars; chunked ingest (D-005); tz/anchor/sentinel config
│   │   ├── video_standard.py         # ffprobe metadata + mmap-cached presentation timestamps
│   │   ├── tracking_loader.py        # DeepLabCut CSV; multi-scorer, bodypart/coord flat-headers
│   │   ├── neo_loader.py             # Neo electrophysiology; OpenEphys/NCS/NIX; BFS root detect
│   │   ├── aol_session_loader.py     # AOL folder detection + manifest (videos, 2D/3D pose, encoder, timing)
│   │   ├── aol_eks_loader.py         # AOL 3D EKS triangulation CSV; frame-indexed x/y/z triplets
│   │   └── aol_encoder_loader.py     # AOL encoder log; seconds-since-midnight, midnight-unwrapped (D-045)
│   ├── engine/                       # playback machinery (imports core + mpv, no widgets)
│   │   ├── player.py                 # clock→mpv fanout, hysteresis drift correction
│   │   ├── seeker.py                 # parallel exact/keyframe seeks, settle detection
│   │   ├── importer.py               # QThread worker: parse → cache → pyramid; progress + cancel signals
│   │   ├── export.py                 # snapshot, data slice (CSV/Parquet), video clip trim
│   │   ├── proxy.py                  # ffmpeg short-GOP proxies + prepare() conversion flow (D-006)
│   │   ├── sync_worker.py            # chunked event extraction and deterministic fitting (D-026)
│   │   ├── drop_worker.py            # off-thread drop classification; AOL session fan-out + pose roles (D-046)
│   │   ├── session_worker.py         # off-thread .avv save/load
│   │   ├── export_worker.py          # off-thread region stats, data slice, clip, snapshot jobs
│   │   └── video_worker.py           # off-thread video probe before native pane creation
│   ├── runtime.py                    # bundled/env media-tool discovery; no_window_kwargs (V-14)
│   ├── ui/                           # PySide6 widgets only; no business logic
│   │   ├── main_window.py            # widget construction, menu/shortcut table, controller wiring; behaviour lives in controllers/
│   │   ├── controllers/              # MainWindow behaviour as plain functions taking the window (D-066)
│   │   │   ├── drop_controller.py    # drag/drop intake, drop scan, capability-resolved candidate routing
│   │   │   ├── session_controller.py # .avv save/load/restore, QSettings geometry, autosave, recent files
│   │   │   ├── export_controller.py  # snapshot, data slice, video clip, annotations, A/B region stats
│   │   │   ├── video_controller.py   # bounded concurrent ffprobe probes; serialized pane build (D-040)
│   │   │   └── import_controller.py  # time-series import queue + pose routing to overlay/3D (D-046)
│   │   ├── video_pane.py             # mpv embedding — ALL per-OS logic isolated here; lazy import (D-013)
│   │   ├── video_timing.py           # timestamp rates, OSD text, frame lookup/step behavior
│   │   ├── video_overlay.py          # transparent overlay; multi-source 2D pose tracks + legend (D-046)
│   │   ├── video_grid.py             # dynamic N columns, labels, no-footage state (D-010), fullscreen
│   │   ├── plot_pane.py              # pyramid-fed pyqtgraph rows, playhead, channel tree/groups (§5c); measure markers
│   │   ├── plot_row.py               # one channel row's plot/curve/close-control construction
│   │   ├── plot_sweep.py             # shared continuous window control + deterministic sweep state
│   │   ├── plot_header.py            # presentation, page, Y-fit, row-height, reset controls
│   │   ├── plot_interactions.py      # plot context actions, measurement, annotation, gap state
│   │   ├── plot_overlays.py          # bounded page-local overlay drawing + context menu helpers
|   |   |-- tracking_3d_pane.py       # cache-backed current-pose projection; orbit/zoom (D-041); head-up axis (D-046)
│   │   ├── pane_proportions.py       # panes keep their share of the window on resize; minimum-aware allocator
│   │   ├── transport.py              # two-row timeline + named evidence lanes, controls, status, A/B loop
│   │   ├── import_wizard.py          # timestamp col/format/tz/unit/sentinel preview dialog
│   │   ├── sync_wizard.py            # evidence selection, residual preview, explicit acceptance (D-026)
│   │   ├── offsets_panel.py          # per-source offset + drift ppm, live preview (D-020)
│   │   ├── recent_files.py           # recent-session list in QSettings — kept out of core/ (rule 2)
│   │   ├── annotations.py            # point/range markers panel + CSV export
│   │   ├── readout_panel.py          # nearest-sample values at t_master + units + sample index + Δ section
│   │   ├── source_properties.py      # VideoPropertiesPanel + SensorPropertiesPanel — collapsible detail (D-020)
│   │   ├── import_report.py          # ImportReportDialog — scrollable import stats + "Copy as text" (D-020)
│   │   ├── time_format.py            # TimeDisplayMode enum + format_time(t, mode, t_epoch) helper (D-020)
│   │   ├── relink_dialog.py          # missing session files → browse/search (§5)
│   │   ├── shortcuts_dialog.py       # keyboard shortcuts reference dialog (? key)
│   │   ├── diagnostics.py            # startup probes: libmpv/hwdec/disk; guided per-OS install text (D-013)
│   │   └── theme.py                  # native-aware system/dark/light appearance
│   └── resources/                    # icons, .qss themes, sample-session manifest (packaged data)
│
├── tools/
│   ├── make_fixtures.py              # ground-truth generator: frame-strip videos, 50 kHz signals,
│   │                                 #   ALL edge-case variants (TESTING §7); deterministic, CI-run
│   ├── generate_demo_data.py         # generate examples/data/ sample videos+CSV; writes tools/launch_demo.py
│   └── launch_demo.py                # (generated) launch the app pre-loaded with demo data
│
├── tests/                            # mirrors src/ layout
│   ├── conftest.py                   # offscreen Qt, fixture paths, qtbot helpers
│   ├── util_framestrip.py            # numpy decoder for burned frame indices (+ its own test)
│   ├── test_core_*.py                # timeline / pyramid / cache / session / registry units
│   ├── test_loaders_*.py             # CSV pathologies, video metadata, chunked ingest
│   ├── test_headless_core.py        # guard: core imports without PySide6
│   ├── test_sync_golden.py           # THE sacred end-to-end time-correctness suite
│   ├── test_ui_*.py                  # pytest-qt widget/flow/error-path tests
│   ├── benchmarks/                   # bench_pyramid / cursor / plot / seek / import (budget gates)
│   └── fixtures/                     # GENERATED by make_fixtures.py — gitignored, never committed
│
├── packaging/                        # everything release.yml/ci.yml call — nothing else lives here
│   ├── avialsync.spec              # PyInstaller one-DIR spec (all OSes)
│   ├── fetch_media_libs.py           # downloads pinned LGPL libmpv/ffmpeg, --verify-lgpl (D-015)
│   ├── smoke_test.py                 # bounded bundle startup; staged releases load a fresh full demo
│   ├── probe_dialog_test.py          # pip-without-libmpv guided-dialog assertion (D-013)
│   ├── windows/
│   │   ├── avialsync.iss           # Inno Setup → AvialSync-Setup.exe
│   │   └── sign.ps1                  # stubbed signing (D-016)
│   ├── macos/
│   │   ├── make_dmg.sh               # arm64 AvialSync.dmg
│   │   └── sign_notarize.sh          # stubbed notarization (D-016)
│   └── linux/
│       └── make_appimage.sh          # AvialSync.AppImage
│
├── examples/
│   ├── data/                         # user-provided sample footage and sensor/tracking data for manual testing
│   └── plugins/                      # bundled plugins loaded via sys._MEIPASS on compiled builds;
│                                     #   template for custom drop-in plugin authors (Phase 5)
│
├── docs/                             # mkdocs-material site → GitHub Pages (Phase 5)
│   ├── mkdocs.yml
│   ├── index.md  quickstart.md  formats.md  troubleshooting.md  plugin-guide.md
│   └── user-guide/                   # per-feature pages grown during Phase 4
│
└── .github/
    ├── workflows/
    │   ├── ci.yml                    # PR gate: lint→type→test→docs→artifact build (3 OS)
    │   ├── release.yml               # tag → installers + PyPI, all-or-nothing (D-012)
    ├── ISSUE_TEMPLATE/  PULL_REQUEST_TEMPLATE.md   # Phase 6
    └── CONTRIBUTING.md  CODE_OF_CONDUCT.md         # Phase 6
```

Placement rules (binding): user-visible deliverable code only under `src/avialsync/`;
anything CI executes but users never install under `packaging/` or `tools/`; generated
artifacts (`tests/fixtures/`, `dist/`, `*.avialcache/`) never committed; agent/planning docs stay
flat at repo root so every model finds them without searching. Dependency direction:
`ui → engine → core` and `loaders → core`; never the reverse, and `core` imports nothing above it.

## 2. Runtime dataflow

```
            ┌────────────── MasterClock (core) ─────────────┐
   QTimer→tick (monotonic delta)                            │ subscribe(t)
            │                                               ▼
            ▼                                   ┌─────────────────────┐
  PlaybackEngine (engine/player.py)             │ UI observers        │
   for each VideoSource:                        │  transport readout  │
     target = TimeMap(t)                        │  plot playhead line │
     local exact-map rate + frame-aware PLL     │  readout panel      │
   scrub: keyframe seeks while dragging,        └─────────────────────┘
          snap to accepted trigger + exact seek on release
```

Time series never keep an independent playback clock. Plots render pyramid-decimated data for one
shared fixed-duration page selected from `t_master`. Ordinary master-clock ticks move only the
playhead and cheap presentation clip/gap; they do not query the pyramid or rebuild curve data.
Paused/scrubbed **Review** shows the complete selected page. Live **Sweep** retains the previous
page only until a narrow eraser gap overwrites it; compatibility **Scope** clears/restarts at the
left edge as in D-042. At a deterministic page boundary, plots load the next bounded slice.
Retained display data is limited to the current and immediately previous page, and the full cursor
path remains within the ≤ 2 ms budget (D-044, `PLOT_UX_PLAN.md`).
The 3D tracking view follows the same rule: it recognizes complete `name_x`, `name_y`, `name_z`
channel triplets already imported through a `TimeSeriesSource`, samples only the nearest mmap-backed
cache row at `t_master`, and paints only the current pose. Coordinates sharing one source reuse one
timestamp lookup. It never sends a full trajectory to a widget, never creates an independent timer,
and never infers skeleton connectivity from names. The video grid and 3D view share a native
side-by-side splitter whose geometry is a local QSettings preference (D-041).

### 2b. Timeline Evidence overview (D-027)

The full-width lanes above the master seek row form a **Data Streams** view, not an unlabeled
decoration. It gives visual-inspection users a concise account of what exists on the shared master
timeline without replacing the plot, sidebar, or synchronization wizard.

```
Data Streams               [Hide] [Flag Frame]                                  [Status: …]
source labels │ ━ video / data spans (one named row per visible source group)
Sync / TTL     │ accepted paired-event ticks only
Data gaps      │ imported discontinuities only
Annotations    │ point and range markers only
Navigator      │ full-session overview · visible-window rectangle · playhead
══════════════ native splitter handle ══════════════
playhead controls · time ───── master seek bar ───── end · A/B · Speed [selector]
```

**Presentation contract:**

- The title is exactly **Data Streams**. Hide and **Flag Frame** sit beside it, followed by compact
  status text. Snapshot/Fullscreen remain existing video/main actions and Reset Zoom remains the
  existing plot QAction; presentation may proxy old buttons during migration but may not duplicate
  command logic. Busy status remains visible;
  ordinary completion/status messages clear after a short delay. Each visible lane has a text label and an accessible name;
  colour is supporting information, never the only meaning. Do not print a long inline list of all
  source names in the header.
- Lanes are conditional: do not show Sync / TTL until accepted synchronization evidence exists, or
  Gaps / Annotations until those objects exist. Coverage remains visible whenever sources are loaded.
- A fixed source-label gutter keeps every source name clear of the timeline. Coverage is clipped to
  the timeline area to its right: a source spanning negative master time begins at that common edge,
  while a later source remains blank until its actual start. An event
  hover/focus card reports type, source(s), master timestamp, and, for accepted sync evidence, the
  match/provenance identity. Clicking any location seeks the master clock; it never changes a mapping.
- Video panes must use the same mapped source bounds as their coverage rows: an out-of-range pane is
  paused and shows **No Footage**, never its last decoded frame.
- The full-session navigator adds one draggable visible-window rectangle. Its position follows the
  current shared plot page and its width follows the one shared plot duration. Dragging seeks through
  the existing approximate/coalesced path with one exact release while preserving playhead phase
  within the page. Rectangle width is display-only and has no separate duration state. This is the
  only horizontal plot navigation surface; rows never gain individual scrollbars or X ranges.
- Native vertical splitter handles, matching the video/plot boundary, distinguish plots from Data
  Streams and Data Streams from the seek/transport section. Those handles resize the overview; a
  collapse button preserves a minimal title row. Expanded/collapsed state is a QSettings view preference,
  not scientific session data.
- The view consumes existing UI-side inspection/synchronization/annotation state. `core/` stays
  headless and owns no colours, widget geometry, or tooltip strings.
- Rendering is bounded: coverage is precomputed spans, and dense event sequences are bucketed to
  display pixels before paint. Master-clock ticks may move only the playhead; they must not scan all
  events. The cursor-path budget remains ≤2 ms.

This view is explanatory evidence, not analysis: it must faithfully surface accepted provenance and
raw import facts, and it must never infer synchronization or hide rejected/ambiguous evidence.

### 2a. Synchronization dataflow (D-026)

```
Plugin/raw signal → chunked TTL edge extraction or native event timestamps
       → deterministic matcher and affine TimeMap proposal
       → residual/confidence preview in Sync Wizard
       → explicit user acceptance → persisted provenance in .avv
```

The raw recordings are never resampled, rewritten, or altered. The accepted result only changes the
source-to-master `TimeMap`. Event extraction and fitting run off the UI thread; preview data is
bounded and decimated where needed. Exact index acceptance makes the first active exact mapping the
reference frame clock: exact scrub release, pause, and stepping snap to its accepted trigger times,
while every pane receives its own mapped presentation timestamp. During playback, each pane applies
the local piecewise mapping slope and a half-frame drift tolerance. The workflow supports a common
periodic clock, camera frame triggers, or sparse experimental pulses, while lab-specific event
encodings remain plugins.

## 3. Threading model

- UI thread: Qt event loop only.
- mpv: own internal threads per instance (3–4 instances).
- Import worker: QThread per import job (parse → cache → pyramid), progress via signals, cancellable.
- Seeker: UI-thread fanout of non-blocking libmpv seek commands; libmpv performs decode and
  property observation on its own threads. Render and OSD callbacks retain only the latest pending
  UI update, so a slow paint cannot create an unbounded Qt event backlog.
- Proxy generation: QProcess (ffmpeg), non-blocking, progress parsed from stderr.

### Appearance boundary

`ui/theme.py` owns appearance preferences only: Qt palette roles, the operating-system accent, and
the selected application font scale. Theme changes must preserve the platform widget style and all
interaction state: seek-slider geometry/value/semantics, splitter and scrollbar behavior, plot
range/follow state, playback, shortcuts, and view layout. Application-level QSS is prohibited for
theme controls because it replaces native style metrics; custom-painted views read colours from the
active palette and never infer or reset state from a palette change.

### Playback ownership and proof of exact frames

`VideoPane` is the ownership boundary for its libmpv client. Exact seek commands are issued from
the Qt-owning thread and queue work in libmpv; decoder and observer work remain asynchronous. An
observer consumes the value it was given rather than re-entering libmpv from its callback thread.
At window close, ownership unwinds explicitly: `MainWindow.closeEvent()` calls
`Player.stop()` before `VideoGrid.shutdown()`. This removes the precise master-tick timer, then
closes every pane and lets `mpv.terminate()` join its event thread before Qt tears down widgets.
On Windows and macOS the pane first frees its libmpv render context while the `QOpenGLWidget` is
current; only then may it terminate libmpv. That ordering prevents the render widget from
dereferencing a destroyed client during process exit.

Runtime coordination uses observed `seeking=False` and target `time-pos`, without sleeps. That is
not sufficient evidence for a scientific golden test: the test captures `screenshot-raw video`,
decodes the fixture frame strip, and compares it with the requested exact frame. A transient raw
screenshot-unavailable result may be retried while the exact seek is settling; a stale displayed
image may never be accepted as proof.

During active playback, an unsettled or stalled decoder never stops `MasterClock`. That pane drops
frames and rejoins through the existing drift correction while plots, transport, readout, 3D, and
healthy videos continue from the authoritative clock. Unchecked panes remain loaded but are paused
and excluded from seek/drift fanout; grid and fullscreen layout changes cannot override the stored
user visibility state.

Standard-video probing happens off the UI thread. Presentation timestamps are authoritative for
CFR/VFR classification even when container metadata declares CFR, and are stored once in the
content-hash-validated `<video>.avialcache/` sidecar. Later opens mmap that timestamp index. The
video overlay reports nominal CFR, timestamp-derived VFR/measurement rates, codec, and file size;
annotations and stepping derive frame indices from the same timestamp array, never `time × fps`
when timestamp evidence exists.

### CI video boundary

Production uses native `wid` embedding on Linux and the libmpv Qt OpenGL render API on Windows and
macOS. Hosted CI is deliberately displayless on all three platforms: global Qt `offscreen` selects
libmpv `vo=null` in `VideoPane`. This exercises timeline, seek, decode, and exact-frame correctness
without claiming to validate a desktop compositor. CI must not force `qwindows` or a `wid` merely to
make a Windows runner behave like a desktop.

## 4. Plugin contract (frozen at Phase 5 as API v1)

```python
class TimeSeriesSource(ABC):
    @classmethod
    def can_open(cls, path: Path) -> float: ...  # 0..1 confidence
    def open(self, path: Path, config: dict) -> None: ...
    def channels(self) -> list[ChannelInfo]: ...  # name, unit, dtype, rate|irregular
    # CHUNKED INGEST (mandatory): cache/pyramid builder pulls incrementally so 50 GB files
    # and streaming sources work without loading everything into RAM.
    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield (t, v) chunks in time order. Loader must SORT non-monotonic input or raise
        NonMonotonicTimeError (never yield unsorted silently). Duplicate timestamps: keep-last.
        NaN/inf pass through; sentinel codes (e.g. -9999) mapped to NaN only via explicit
        loader config, never guessed."""

    # BULK INGEST (OPTIONAL, NOT PART OF v1): a loader whose format is parsed in one pass —
    # a CSV, a tracking table — may additionally offer read_all_chunks. The importer detects
    # it by name (`getattr(loader, "read_all_chunks", None)`) and, when present, uses it
    # INSTEAD of calling read_chunks once per channel, so an 80-channel file is parsed once
    # rather than 80 times. It is not on this ABC and never will be: a plugin that omits it
    # is fully supported and takes the per-channel path. See D-067.
    def read_all_chunks(self) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
        """Yield {channel_name: (t, v)} per chunk, every channel aligned on the same rows.
        Same ordering, duplicate, NaN, and sentinel rules as read_chunks. Yielding channels
        the loader did not declare, or omitting declared ones, is a loader bug."""

    # Timestamp handling contract: loader must resolve timezone (naive input → user chooses
    # in import wizard, default UTC with a visible warning), handle DST-ambiguous local
    # times by refusing ambiguity silently (ask), and support time-of-day-only formats via
    # an anchor date config. Clock-resync jumps backwards → NonMonotonicTimeError with the
    # row number, plus an offered auto-fix (split into segments).


class VideoSource(ABC):
    @classmethod
    def can_open(cls, path: Path) -> float: ...
    def open(self, path: Path, config: dict) -> None: ...

    # CONVERSION HOOK: for sources mpv can't play directly (TIFF/PNG image sequences,
    # Phantom .cine, Photron, GenICam dumps, split multi-part files). First-class, not a hack.
    def needs_conversion(self) -> bool: ...
    def prepare(self, progress_cb: Callable[[float], None]) -> Path:
        """Produce an mpv-playable file (ffmpeg proxy etc.), cancellable, cached in sidecar."""

    def media_path(self) -> Path: ...  # what mpv actually plays (proxy-aware)
    def start_time(self) -> float | None:
        ...  # metadata guess ONLY; may be None
        # (very common) → defaults to offset 0,
        # user aligns manually; offset always wins

    def time_bounds(self) -> tuple[float, float]:
        ...
        # (metadata start, metadata start + duration), or (0, duration)
        # when the source has no UTC timestamp

    def frame_times(self) -> "np.ndarray | None":
        """Per-frame timestamps if the container has them. REQUIRED for correct stepping on
        VFR footage and dropped-frame recordings; if None, constant-fps stepping is used and
        the UI shows a 'nominal fps' badge. Frame stepping must always use mpv's actual
        frame timestamps, never t += 1/fps arithmetic."""

    def fps(self) -> float:
        ...  # nominal; mixed fps across cameras is
        # normal (25/29.97/30) — never assumed equal

    def video_metadata(
        self,
    ) -> VideoMetadata: ...  # optional compatible extension; timestamp-derived timing evidence

    def label(self) -> str:
        ...  # UI ensures uniqueness (adds parent dir
        # when filenames collide)
```

**No-footage / no-data state (uniform rule):** every pane must render a defined state when
`t_master` maps outside a source's bounds — video pane shows a dimmed "no footage at this time"
placeholder (never last frame frozen, which misleads); plots show axis with no curve; readout
shows "—". Timeline bounds = union of all sources; a 4 h video + 10 min data is legal and the
overview strip shades each source's coverage span.

Discovery: Python entry points and dynamic directory scanning (`~/.avialsync/plugins/`); highest `can_open` score wins,
ties → user picks. Built-ins register directly into the PluginManager.

### Synchronization plugin extension (D-026; not frozen API v1)

The shipped workflow extracts rising TTL edges from cached time-series channels and compares them
with video frame-event timestamps. The frozen loader API remains focused on opening video and
chunked time-series ingest. A later, separate plugin extension will let a loader expose native raw
`SyncEvent` evidence (digital events, TTL edges, or camera-frame triggers). It will be headless,
timestamp-only, and independent of any lab acquisition system. The core will perform no scientific
analysis; plugins may offer lab-specific analysis separately. A source proposal includes its paired
event evidence and fit quality so the user can inspect and explicitly accept it.

Video acceptance is capability-based rather than suffix-based: files playable by the installed
ffmpeg/mpv stack use the standard video path, while non-playable laboratory formats use a plugin's
conversion hook. Format-specific parsing is deliberately a plugin responsibility.

## 5. Session file (.avv, JSON, schema_version field)

Stores: source list (path, loader id, loader config, offset, drift, proxy path), layout
(grid order, visible channels, colors), view state (shared plot-window duration, theme), annotations, and—after an
alignment is accepted—synchronization provenance (evidence summary, matching settings, residuals,
confidence, and the accepted affine or exact piecewise mapping). Schema v5 stores the complete
exact mapping arrays so reopening a session cannot silently fall back to offset/drift.
Paths stored relative to session file when possible, absolute fallback.

Timeline Evidence splitter geometry/collapse is deliberately excluded from `.avv`: they are local
QSettings view preferences, so opening a collaborator's session does not unexpectedly alter their
workspace.

**Missing-file relink:** on load, any unresolved path opens a relink dialog (browse / search a
chosen folder by filename+size); session loads with unresolved sources placeholdered, never fails
wholesale. **Path hygiene:** all paths handed to ffmpeg/mpv/QProcess as argument lists (never
shell strings); unicode + spaces on Windows are first-class test cases.

## 5b. Cache invalidation key (updates D-004)

Key = (path, size, mtime, loader_version, **xxhash of first+last 64 KB**). The content-hash tail
catches Excel rewrites, cross-drive copies with preserved mtime, and coarse-mtime network shares.
A stale cache silently showing old data is a trust-destroying bug class — when in doubt, rebuild.
Multi-part recordings (one logical stream split across N files) are a loader concern: the loader
presents them as ONE source; the cache key covers all parts.

## 5c. Channel scaling (32+ channels)

Per-source plot rows stop scaling past ~8 channels. Rule: a source row plots up to N overlaid
channels with a legend; beyond that, channels are organized in a tree panel with
check-to-show and optional user-defined groups (each group = one row). Overlay vs stacked is a
per-row toggle. Sub-frame readout convention: readout shows the sample nearest to t_master
(50 kHz ⇒ ~1,667 samples per video frame; "frame value" is undefined — we always use nearest
sample to the exact master time, documented in the UI tooltip).

## 6. Packaging & shipping (D-012..D-017)

One release tag → `.github/workflows/release.yml` builds and publishes ALL of:

| Channel | Artifact | libmpv/ffmpeg | User steps |
|---|---|---|---|
| Windows installer | Inno Setup `AvialSync-Setup.exe` (one-DIR PyInstaller inside; never one-file — AV false positives) | bundled (LGPL, verified D-015) | install → run |
| macOS | `AvialSync.dmg` (arm64 v1; Intel via pip) | bundled | drag → run (right-click-Open until signed, D-016) |
| Linux | `AvialSync.AppImage` | bundled | download → run |
| PyPI | wheel + sdist | NOT included; probe+guide (D-013) | `pip install avialsync` → install libmpv + ffmpeg once (README) → run |
| conda-forge | recipe (Phase 5) | pulled as conda deps | `conda install avialsync` → run |

Startup sequence (all channels): diagnostics probe (libmpv present? hwdec? disk speed?) →
missing libmpv → guided dialog (distro-specific one-liner / brew line / Windows mpv-dev archive
plus `AVIALSYNC_MEDIA_ROOT`) → lazy `import mpv` only after probe passes. The app window
ALWAYS opens; capability problems degrade to dialogs, never tracebacks. Those prerequisites are
documented for pip users in README "Native prerequisites for a pip install" and `docs/quickstart.md`;
`ui/diagnostics.libmpv_install_guidance` holds the per-platform text the dialog shows.

GitHub Actions is the only release authority: the tag workflow builds every installer and the PyPI
wheel/sdist before either is published. The Linux AppImage tool URL and SHA256 are repository
configuration values, verified before use. PyPI uses GitHub OIDC trusted publishing; no developer
workstation token or upload is permitted. Signing/notarization steps exist in release.yml behind
`if: secrets present` (D-016).

The pull-request CI quality gate runs lint/type checks, documentation with warnings as errors,
fixture-backed cross-platform correctness tests, and a PyInstaller build on each OS. A successful
artifact build proves the spec can locate project code and package its declared inputs; it does not
prove an installer release or native-window rendering. `SPECPATH` is the `packaging/` directory, so
the spec derives the project root from it. Optional media is included only when
`AVIALSYNC_MEDIA_ROOT` is non-empty and names a directory; release workflows separately provide and
verify licensed media.
