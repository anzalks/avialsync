# ARCHITECTURE.md

## 1. Repository layout (complete — the authoritative map of what lives where)

```
kinochronix/                          # repo root = GitHub repo `kinochronix`
├── pyproject.toml                    # hatchling; dep `python-mpv`; extras: [dev], [docs];
│                                     #   entry point `kinochronix`; entry-point group `kinochronix.loaders`
├── README.md                         # user-facing: what/GIFs/install (installers first, pip second)
├── LICENSE                           # Apache-2.0 (D-003)
├── .gitignore                        # incl. tests/fixtures/ (generated), dist/, *.kcache/
├── .pre-commit-config.yaml           # ruff check+format, basic hygiene hooks
│
│   # ---- agent & planning docs (repo root, read by all models) ----
├── AGENTS.md                         # canonical rules; CLAUDE.md / GEMINI.md are pointers to it
├── CLAUDE.md
├── GEMINI.md
├── BLUEPRINT.md                      # phases & exit criteria
├── ARCHITECTURE.md                   # this file
├── DECISIONS.md                      # ADR log D-001..
├── PROMPTS.md                        # per-task kickoff prompts
├── TESTING.md                        # test strategy + edge-case matrix
│
├── src/kinochronix/                  # the installable package (src layout — import kinochronix)
│   ├── __init__.py                   # __version__ single source (read by pyproject)
│   ├── __main__.py                   # CLI: `kinochronix` / `kinochronix open <path>`
│   ├── core/                         # HEADLESS — must never import PySide6 (test-enforced)
│   │   ├── timeline.py               # MasterClock, TimeMap(offset, drift), PlaybackState
│   │   ├── session.py                # Session model + .kcx JSON (versioned schema)
│   │   ├── source.py                 # ABCs: TimeSeriesSource, VideoSource (plugin contract, §4)
│   │   ├── pyramid.py                # NaN/gap-aware min-max pyramid build + query (D-009)
│   │   ├── cache.py                  # .kcache/ sidecar manager, content-hash key (D-008), atomic writes
│   │   ├── registry.py               # plugin discovery via entry points `kinochronix.loaders`
│   │   └── errors.py                 # typed exceptions (NonMonotonicTimeError, ...)
│   ├── loaders/                      # built-in plugins (use ONLY the public core API)
│   │   ├── csv_loader.py             # polars; chunked ingest (D-005); tz/anchor/sentinel config
│   │   └── video_standard.py         # ffprobe metadata, frame_times(), needs_conversion=False
│   ├── engine/                       # playback machinery (imports core + mpv, no widgets)
│   │   ├── player.py                 # clock→mpv fanout, hysteresis drift correction
│   │   ├── seeker.py                 # parallel exact/keyframe seeks, settle detection
│   │   └── proxy.py                  # ffmpeg short-GOP proxies + prepare() conversion flow (D-006)
│   ├── ui/                           # PySide6 widgets only; no business logic
│   │   ├── main_window.py            # 2-row layout: video grid / channel plot rows
│   │   ├── video_pane.py             # mpv embedding — ALL per-OS logic isolated here; lazy import (D-013)
│   │   ├── video_grid.py             # dynamic N columns, labels, no-footage state (D-010), fullscreen
│   │   ├── plot_pane.py              # pyramid-fed pyqtgraph rows, playhead, channel tree/groups (§5c)
│   │   ├── transport.py              # slider, play/pause, speed, A/B loop, time readout
│   │   ├── import_wizard.py          # timestamp col/format/tz/unit/sentinel preview dialog
│   │   ├── offsets_panel.py          # per-source offset + drift ppm, live preview
│   │   ├── annotations.py            # point/range markers panel + CSV export
│   │   ├── readout_panel.py          # nearest-sample values at t_master
│   │   ├── relink_dialog.py          # missing session files → browse/search (§5)
│   │   ├── diagnostics.py            # startup probes: libmpv/hwdec/disk; guided-install; auto-fetch (D-013/14)
│   │   └── theme.py                  # dark/light qss
│   └── resources/                    # icons, .qss themes, sample-session manifest (packaged data)
│
├── tools/
│   └── make_fixtures.py              # ground-truth generator: frame-strip videos, 50 kHz signals,
│                                     #   ALL edge-case variants (TESTING §7); deterministic, CI-run
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
│   ├── kinochronix.spec              # PyInstaller one-DIR spec (all OSes)
│   ├── fetch_media_libs.py           # downloads pinned LGPL libmpv/ffmpeg, --verify-lgpl (D-015)
│   ├── smoke_test.py                 # launch built bundle headless, open sample session, exit 0
│   ├── probe_dialog_test.py          # pip-without-libmpv guided-dialog assertion (D-013)
│   ├── windows/
│   │   ├── kinochronix.iss           # Inno Setup → KinoChronix-Setup.exe
│   │   └── sign.ps1                  # stubbed signing (D-016)
│   ├── macos/
│   │   ├── make_dmg.sh               # arm64 KinoChronix.dmg
│   │   └── sign_notarize.sh          # stubbed notarization (D-016)
│   └── linux/
│       └── make_appimage.sh          # KinoChronix.AppImage
│
├── examples/
│   └── kinochronix-plugin-example/   # complete external loader plugin (toy binary format);
│                                     #   template for kinochronix-plugin-<name> authors (Phase 5)
│
├── docs/                             # mkdocs-material site → GitHub Pages (Phase 5)
│   ├── mkdocs.yml
│   ├── index.md  quickstart.md  formats.md  troubleshooting.md  plugin-guide.md
│   └── user-guide/                   # per-feature pages grown during Phase 4
│
└── .github/
    ├── workflows/
    │   ├── ci.yml                    # PR gate: lint→type→test→fast benchmarks→artifact build (3 OS)
    │   ├── release.yml               # tag → installers + PyPI, all-or-nothing (D-012)
    │   └── nightly.yml               # big-fixture benchmarks + packaging smoke (Phase 5)
    ├── ISSUE_TEMPLATE/  PULL_REQUEST_TEMPLATE.md   # Phase 6
    └── CONTRIBUTING.md  CODE_OF_CONDUCT.md         # Phase 6
```

Placement rules (binding): user-visible deliverable code only under `src/kinochronix/`;
anything CI executes but users never install under `packaging/` or `tools/`; generated
artifacts (`tests/fixtures/`, `dist/`, `*.kcache/`) never committed; agent/planning docs stay
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
     play-rate match; if |Δ|>40ms → seek        │  readout panel      │
   scrub: keyframe seeks while dragging,        └─────────────────────┘
          parallel exact seek on release (seeker.py)
```

Time series never "play": plots render pyramid slices for the visible window; only the playhead
line moves per tick (≤ 2 ms budget).

## 3. Threading model

- UI thread: Qt event loop only.
- mpv: own internal threads per instance (3–4 instances).
- Import worker: QThread per import job (parse → cache → pyramid), progress via signals, cancellable.
- Seeker: thread-pool fanout of seek commands; completion gathered, then one UI update.
- Proxy generation: QProcess (ffmpeg), non-blocking, progress parsed from stderr.

## 4. Plugin contract (frozen at Phase 5 as API v1)

```python
class TimeSeriesSource(ABC):
    @classmethod
    def can_open(cls, path: Path) -> float: ...        # 0..1 confidence
    def open(self, path: Path, config: dict) -> None: ...
    def channels(self) -> list[ChannelInfo]: ...       # name, unit, dtype, rate|irregular
    def time_bounds(self) -> tuple[float, float]: ...  # absolute UTC seconds

    # CHUNKED INGEST (mandatory): cache/pyramid builder pulls incrementally so 50 GB files
    # and streaming sources work without loading everything into RAM.
    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield (t, v) chunks in time order. Loader must SORT non-monotonic input or raise
        NonMonotonicTimeError (never yield unsorted silently). Duplicate timestamps: keep-last.
        NaN/inf pass through; sentinel codes (e.g. -9999) mapped to NaN only via explicit
        loader config, never guessed."""

    def read(self, ch: str, t0: float, t1: float, max_points: int) -> ChannelSlice:
        """Serve from pyramid/cache. ChannelSlice = (t, vmin, vmax, gap_mask):
        gap_mask marks intervals larger than gap_threshold (default 10× median dt) —
        renderers MUST break lines at gaps, never interpolate across them.
        Empty/no-data windows return length-0 arrays, never raise."""

    def config_widget(self) -> "QWidget | None": ...   # optional import-config UI hook
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

    def media_path(self) -> Path: ...                  # what mpv actually plays (proxy-aware)
    def start_time(self) -> float | None: ...          # metadata guess ONLY; may be None
                                                       # (very common) → defaults to offset 0,
                                                       # user aligns manually; offset always wins
    def frame_times(self) -> "np.ndarray | None":
        """Per-frame timestamps if the container has them. REQUIRED for correct stepping on
        VFR footage and dropped-frame recordings; if None, constant-fps stepping is used and
        the UI shows a 'nominal fps' badge. Frame stepping must always use mpv's actual
        frame timestamps, never t += 1/fps arithmetic."""
    def fps(self) -> float: ...                        # nominal; mixed fps across cameras is
                                                       # normal (25/29.97/30) — never assumed equal
    def label(self) -> str: ...                        # UI ensures uniqueness (adds parent dir
                                                       # when filenames collide)
```

**No-footage / no-data state (uniform rule):** every pane must render a defined state when
`t_master` maps outside a source's bounds — video pane shows a dimmed "no footage at this time"
placeholder (never last frame frozen, which misleads); plots show axis with no curve; readout
shows "—". Timeline bounds = union of all sources; a 4 h video + 10 min data is legal and the
overview strip shades each source's coverage span.

Discovery: Python entry points group `kinochronix.loaders`; highest `can_open` score wins,
ties → user picks. Built-ins register the same way (no special path).

## 5. Session file (.kcx, JSON, schema_version field)

Stores: source list (path, loader id, loader config, offset, drift, proxy path), layout
(grid order, visible channels, colors), view state (zoom ranges, theme), annotations.
Paths stored relative to session file when possible, absolute fallback.

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
| Windows installer | Inno Setup `KinoChronix-Setup.exe` (one-DIR PyInstaller inside; never one-file — AV false positives) | bundled (LGPL, verified D-015) | install → run |
| macOS | `KinoChronix.dmg` (arm64 v1; Intel via pip) | bundled | drag → run (right-click-Open until signed, D-016) |
| Linux | `KinoChronix.AppImage` | bundled | download → run |
| PyPI | wheel + sdist | NOT included; probe+guide (D-013), Windows auto-fetch (D-014) | `pip install kinochronix` → run |
| conda-forge | recipe (Phase 5) | pulled as conda deps | `conda install kinochronix` → run |

Startup sequence (all channels): diagnostics probe (libmpv present? hwdec? disk speed?) →
missing libmpv → guided dialog (distro-specific one-liner / brew line / Windows auto-fetch
button with pinned SHA256 download) → lazy `import mpv` only after probe passes. The app window
ALWAYS opens; capability problems degrade to dialogs, never tracebacks.

Signing/notarization steps exist in release.yml behind `if: secrets present` (D-016).
