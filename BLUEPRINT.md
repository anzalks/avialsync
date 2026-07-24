# KinoChronix — Project Blueprint (v1)

> Name: **KinoChronix** (final). Casing rules are binding — see AGENTS.md §Naming.
> Open-source, GUI-first tool to scrub time-synced multi-camera video + dense time series.
> License: Apache-2.0 (commercial-friendly). Stack: Python 3.11+, PySide6, libmpv, pyqtgraph, numpy, polars.

---

## Non-negotiable design principles (every phase, every agent, every PR)

1. **One master clock.** All UI state derives from a single absolute time `t_master` (float seconds, UTC epoch). Sources map to it via `t_source = t_master + offset + drift_rate * (t_master - t_ref)`.
2. **Never block the UI thread.** Decoding, file IO, cache building → workers/mpv. UI thread only issues commands and paints.
3. **Never draw more points than pixels.** All plotting goes through the decimation pyramid.
4. **Modular loaders.** Every data source (video or time series) enters through a plugin interface. CSV and standard video are just the built-in plugins.
5. **No GPL dependencies.** PySide6 (LGPL), mpv/ffmpeg LGPL builds, pyqtgraph (MIT), numpy/polars (BSD/MIT) only. New deps require a license check in the PR.
6. **Sync correctness > frame completeness** during playback; exact frames when paused/stepping.
7. **Binary sidecar cache.** Text formats are parsed once → cached as mmap-able binary (`.kcache/` sidecar dir: raw arrays + pyramid levels + metadata JSON).

## Performance budgets (CI-enforced where marked ★)

| Metric | Budget |
|---|---|
| Scrub response (3 cams, exact seek, release-of-slider) | ≤ 250 ms |
| Plot pan/zoom frame time ★ | ≤ 16 ms |
| Cursor update per tick ★ | ≤ 2 ms |
| Cached session open (3 cams + 4×50 kHz ch) | ≤ 3 s |
| First CSV import 1 GB (with progress) | ≤ 60 s |
| Pyramid build 180 M samples ★ | ≤ 2 s |
| Idle RAM, session loaded | ≤ 2.5 GB |

Benchmarks live in `tests/benchmarks/`, run via `pytest --benchmark-only`, regressions > 20 % fail CI.

---

## Phase 0 — Foundation (Week 0–1)

**Goal:** empty app window ships to all 3 OSes via CI before any feature exists.

Deliverables:
- Repo layout (see ARCHITECTURE.md), `pyproject.toml` (hatchling), `pip install -e .[dev]` works.
- Tooling: ruff (lint+format), mypy (strict on `core/`), pre-commit, pytest + pytest-qt + pytest-benchmark.
- CI matrix (ubuntu/windows/macos): lint → type → test → build PyInstaller artifact.
- `kinochronix` entry point opens an empty PySide6 main window.
- **Synthetic data generator** `tools/make_fixtures.py`: ffmpeg test videos with burned-in frame counter + known start timestamps (8-bit and 12-bit variants, short & long GOP), numpy 50 kHz multi-channel signals with a known event (step at exact t) → this is the ground truth for all sync tests forever.

Exit criteria: green CI on 3 OSes; artifacts download and open; fixtures generate deterministically **including the edge-case variants (TESTING.md §7): VFR, dropped-frame, no-metadata video, image sequence, timestamp-pathology CSVs, NaN/gap/sentinel signals, split recording**.

## Phase 1 — Core engine, headless (Week 1–2)

**Goal:** the timeline model, fully unit-tested, no GUI dependency.

Deliverables:
- `core/timeline.py`: MasterClock (play/pause/rate/seek, monotonic-driven), TimeMap (offset + drift), Session model (sources, offsets, layout) with JSON round-trip.
- `core/source.py`: abstract `TimeSeriesSource` and `VideoSource` interfaces (the plugin contract, frozen here — see ARCHITECTURE.md §4), **including chunked ingest (D-005), the video conversion hook (D-006), frame_times() for VFR (D-007), and the no-data contract (D-010)**.
- `core/pyramid.py`: min/max decimation pyramid (levels 1×,16×,256×,4096×), vectorized numpy, mmap read/write — **NaN-aware (nanmin/nanmax) and gap-aware (gap_mask, D-009) from day one**.
- `core/cache.py`: sidecar cache manager with content-hash-hardened key (D-008), atomic writes.
- Built-in loaders: `loaders/csv_loader.py` (polars, timestamp column/format/unit config), `loaders/video_ffprobe.py` (metadata + start-time extraction).

Exit criteria: 100 % branch coverage on timeline math; pyramid benchmark ★ passes; property-based tests (hypothesis) on TimeMap round-trips.

## Phase 2 — Playback MVP (Week 2–4)

**Goal:** one video + one CSV, shared slider, play/pause, cursor. The "it works!" demo.

Deliverables:
- mpv embedded in a Qt widget (`ui/video_pane.py`) — **build the macOS render-API path FIRST (D-011), then wid on Win/Linux**; settle detection via property observation, no sleeps.
- `ui/plot_pane.py`: pyqtgraph plot fed by pyramid, vertical playhead cursor (single InfiniteLine, cursor-only updates).
- Transport bar: play/pause (space), slider, time readout, speed 0.1–8×.
- Playback loop: QTimer @ 60 Hz advances MasterClock; mpv follows via rate-matched play + drift correction (re-seek if |video_t − target| > 40 ms **for N consecutive ticks — hysteresis, see AGENTS traps**); slider drag = keyframe seeks, release = exact seek; frame stepping via actual frame timestamps (D-007).
- Open file dialogs + drag-and-drop for one video, one CSV (minimal import dialog: pick timestamp column, format, unit).

Exit criteria: **golden sync test** — for fixture video (burned frame counter) at 20 random `t`, OCR/pixel-decode the paused frame counter and assert |frame_time − t| ≤ 1 frame; manual scrub feels smooth on dev machines.

## Phase 3 — Multi-source + performance (Week 4–7)

**Goal:** the real spec: 3–4 cameras, multi-channel 50 kHz, still smooth.

Deliverables:
- Dynamic video grid (row 1, N columns, camera label overlay, double-click fullscreen).
- Channel rows (row 2+): one plot row per time series source, shared X axis link, show/hide channels, per-channel color/legend.
- Left Sidebar / Inspector Pane (~20% width, collapsible):
  - File open/management buttons (video/sensor) + remove/hide toggles.
  - Per-file metadata readouts (codec, resolution, sample rate, channels).
  - Per-source offset spinboxes (live preview) + optional drift rate; persisted in session.
- Global Session Summary (Master timeline absolute times, duration).
- Async parallel seeking across mpv instances (QThreadPool or asyncio bridge); frame-drop tolerance during play.
- Import pipeline: background parse → binary sidecar → pyramid, with progress + cancel.
- Proxy generator: one-click ffmpeg re-encode to short-GOP scrub proxies; session tracks original↔proxy pairs.
- Startup diagnostics: disk read speed probe, hw-decode capability report, slow-drive warning.

Exit criteria: benchmark session (3× 1080p fixtures + 4× 50 kHz × 1 h synthetic) meets all budgets on CI perf runner + one real mid-spec machine; golden sync test now runs across 3 cameras simultaneously.

## Phase 4 — UX completeness (Week 7–10)

**Goal:** everything a daily user expects.

Deliverables:
- Session save/load (.kcx JSON) incl. layout, zoom, visibility; recent files; autosave.
- Keyboard map (arrows = frame step, shift+arrows = 1 s, home/end, [ ] = A/B loop, m = marker…), discoverable via a shortcuts dialog.
- Frame step fwd/back (exact seek ±1/fps of the reference camera), jump-to-time input.
- Annotations: point + range markers with label/comment, list panel, CSV export.
- Cursor readout panel: value of every visible channel at `t_master`.
- Region select → export data slice (CSV/Parquet) and optionally trimmed video clips (ffmpeg copy).
- A/B loop, snapshot export (frame + plot PNG), basic region stats (min/max/mean/rms).
- Timestamp import wizard (preview table, format autodetect suggestions, **explicit timezone choice for naive input, anchor date for time-of-day-only, sentinel→NaN mapping option, euro-dialect/BOM handling**, s/ms/µs/ns).
- Missing-file relink dialog on session load; label disambiguation for duplicate filenames.
- No-footage/no-data placeholder states (D-010); timeline coverage shading; channel tree +
  grouping for many-channel sources (ARCHITECTURE §5c).
- Error handling pass: unreadable file, missing column, codec unsupported → actionable dialogs; "copy diagnostics" button.
- Dark/light theme; window state persistence.

Exit criteria: scripted UX walkthrough (pytest-qt integration test) covering open→align→annotate→export with zero unhandled exceptions; keyboard-only operation possible for the core loop.

## Phase 5 — Plugin API + packaging (Week 10–13)

**Goal:** third parties can add proprietary formats; normal users can install in one click.

Deliverables:
- Public plugin API v1: Drop-in directory system (`~/.kinochronix/plugins/` and bundled `examples/plugins/`); document + freeze the `TimeSeriesSource`/`VideoSource` ABCs; PluginManager uses `sys._MEIPASS` for compiled bundles.
- Loader capability negotiation (can_open(path) → score) and per-plugin config UI hook.
- Packaging per ARCHITECTURE §6 / D-012..D-017: PyPI wheel + sdist; PyInstaller **one-dir**
  bundles with LGPL-verified mpv/ffmpeg (build-flavor assertion in CI); Inno Setup installer;
  arm64 .dmg; AppImage; **Windows pip auto-fetch of libmpv (pinned URL + SHA256)**;
  signing/notarization steps stubbed behind secrets-present conditionals; conda-forge recipe.
- `release.yml`: single tag builds installers AND publishes PyPI atomically (all-or-nothing —
  a failed channel fails the release; no version skew between channels).
- `kinochronix open <folder>` CLI; sample dataset auto-download command.
- Docs site (mkdocs-material): quickstart ≤ 5 min, plugin author guide, format notes (short-GOP advice), troubleshooting.

Exit criteria: a stranger can `pip install kinochronix` **on a machine WITHOUT mpv installed**
(guided dialog / auto-fetch gets them running) or download an installer, and open the sample
dataset in < 5 minutes with zero manual dependency steps; users can drop a `.py` plugin into their folder and it appears in the import dialog; installers verified to contain LGPL-flavor binaries.

## Phase 6 — Release & community (Week 13–16)

**Goal:** v1.0 tag, community-ready.

Deliverables:
- Test coverage ≥ 80 % overall, 100 % on `core/`; CI release workflow on tag (build all artifacts, draft GitHub release, publish to PyPI).
- CONTRIBUTING.md, code of conduct, issue/PR templates, good-first-issues.
- Demo video/GIFs in README; announcement posts (HN/Reddit r/opensource + your field's forums).
- Optional stretch: MCAP read-only importer plugin (pulls in the robotics crowd).

Exit criteria: v1.0.0 released on all channels; at least the sample-dataset happy path verified by someone who is not you.

---

## Working method with AI agents (all phases)

- One phase = one milestone = a series of small PR-sized tasks. Agents work from `PROMPTS.md` kickoff prompts + `AGENTS.md` standing rules.
- Every task PR must include/extend tests; `core/` changes require benchmarks unaffected or improved.
- Human review checkpoints: end of each phase, run the manual smoke checklist in `TESTING.md` §6 on your own real field data (agents never see it; it stays your private regression reality-check).
- Keep `DECISIONS.md` (lightweight ADR log): every irreversible choice (formats, API shapes) gets 5 lines — context, decision, alternatives. Agents must read it and must not silently reverse decisions.

## Timeline summary

| Phase | Calendar (part-time) | Calendar (focused) |
|---|---|---|
| 0 Foundation | 1 wk | 3 days |
| 1 Core engine | 1–2 wk | 4 days |
| 2 Playback MVP | 2 wk | 1 wk |
| 3 Multi-source/perf | 3 wk | 1.5 wk |
| 4 UX completeness | 3 wk | 2 wk |
| 5 Plugins + packaging | 3 wk | 2 wk |
| 6 Release | 2–3 wk | 1.5 wk |
| **Total to v1.0** | **~4 months** | **~2 months** |
