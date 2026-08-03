# AvialSync — Project Blueprint (v1)

> Name: **AvialSync** (final). Casing rules are binding — see AGENTS.md §Naming.
> Open-source, GUI-first tool to scrub time-synced multi-camera video + dense time series.
> License: AGPL-3.0-or-later (D-069). Stack: Python 3.11–3.12, PySide6, libmpv, pyqtgraph, numpy, polars.

---

## Non-negotiable design principles (every phase, every agent, every PR)

1. **One master clock.** All UI state derives from a single absolute time `t_master` (float seconds, UTC epoch). Sources map to it via `t_source = t_master + offset + drift_rate * (t_master - t_ref)`.
2. **Never block the UI thread.** Decoding, file IO, cache building → workers/mpv. UI thread only issues commands and paints.
3. **Never draw more points than pixels.** All plotting goes through the decimation pyramid.
4. **Modular loaders.** Every data source (video or time series) enters through a plugin interface. CSV and standard video are just the built-in plugins.
5. **No GPL dependencies.** PySide6 (LGPL), mpv/ffmpeg LGPL builds, pyqtgraph (MIT), numpy/polars (BSD/MIT) only. New deps require a license check in the PR.
6. **Sync correctness > frame completeness** during playback; exact frames when paused/stepping.
7. **Binary sidecar cache.** Text formats are parsed once → cached as mmap-able binary (`.avialcache/` sidecar dir: raw arrays + pyramid levels + metadata JSON).
8. **Evidence-based alignment.** TTL/event alignment preserves raw timestamps and presents the
   matched evidence, offset/drift fit, residuals, and confidence before the user accepts it.
   Ambiguous evidence is surfaced, never silently guessed.
9. **Speed and timing accuracy are co-equal.** Synchronization extraction is chunked, matching is
   deterministic, and every new timing path requires a ground-truth fixture and benchmark.

## Performance budgets (engineering-certified where marked ★)

| Metric | Budget |
|---|---|
| Scrub response (3 cams, exact seek, release-of-slider) | ≤ 250 ms |
| Plot pan/zoom frame time ★ | ≤ 16 ms |
| Full populated cursor update per tick ★ | ≤ 2 ms |
| 3D pose sample (128 XYZ points) ★ | ≤ 2 ms |
| Cached session open (3 cams + 4×50 kHz ch) | ≤ 3 s |
| First CSV import 1 GB (with progress) | ≤ 60 s |
| Pyramid build 180 M samples ★ | ≤ 2.5 s (revised, D-024) |
| Idle RAM, session loaded | ≤ 2.5 GB |
| Any UI-thread callback | target ≤ 8 ms, hard ceiling 30 ms |

Benchmarks live in `tests/benchmarks/`, run locally via `pytest --benchmark-only`, where the raw
★ marks are enforced without a multiplier. GitHub Actions verifies the representative scientific
session's correctness across platforms but does not use shared hosted machines to certify speed.

### Full performance and accurate-streaming audit (2026-07-29; implementation closed 2026-07-30)

The architecture is sound at its main boundaries: the monotonic master clock does not wait for a
decoder, libmpv owns decoding, video callbacks and scrub requests are coalesced, hidden video panes
are removed from synchronization work, data/video/sync/proxy preparation has worker entry points,
and plots query bounded mmap-backed pyramid slices. Those protections must be retained.

Every audited **implementation** gap below is now closed. What remains is **measurement**: the
representative populated workload has not been recorded, so the timing budgets in the table above
are not yet certified. A fast median alone is insufficient — record p50/p95/p99 and the maximum UI
heartbeat delay, and fail on timing/data mismatches even when throughput passes.

| Priority | Audited gap | Status (2026-07-30) |
|---|---|---|
| P0 accuracy | Plot envelopes, gap propagation, CSV timestamp schema, and per-source `TimeMap`. | **Done.** Envelopes render pyramid extrema; raw gap evidence is OR-reduced into every level; CSV enforces an explicit timestamp dtype with cross-batch chronology checks. Every time-series source now maps through a `TimeMap` (D-045); session schema v6 persists sensor offset/drift. |
| P0 streaming | Import concatenated complete channels; Neo materialised a full block. | **Done.** `ChannelStage` stages parser chunks to disk and materialises once, so peak memory is one chunk per channel. Neo reads blocks lazily and slices per batch. Gap locations are bounded; `gap_count` stays exact. |
| P0 UI freeze | Session save/load/autosave and annotation export ran on the UI thread. | **Done.** All four moved to workers (D-046), with a Qt heartbeat test over a one-million-pair write. The close-time autosave is synchronous by design. |
| P0 scale | Exact fits and large session mappings. | **Done.** Bounded evidence retained; large mappings use checksum-validated compressed sidecars; session IO is off-thread. |
| P1 identity | Channel IDs treated as globally unique. | **Done.** `ChannelKey(source_id, channel_id)` throughout (D-045). CSV export labels each block by source; Parquet is long-form and assumes no shared axis. |
| P1 hot path | 60 Hz tick formatted all labels and sampled hidden consumers; evidence paint scanned all events. | **Done.** Presentation rate-limited to 20 Hz and skipped when hidden; event lanes indexed by time (D-047). |
| P1 loading | Probing serialized with native pane creation. | **Done.** Bounded-parallel probes, serialized in-order pane construction (D-048); D-040 preserved. |
| P1 cache durability | — | **Done.** Recoverable swap with fault-injection coverage. |
| P2 maintainability | `ui/main_window.py` is ~2 400 lines. | **Open.** Splitting into bounded job controllers is unstarted. |
| **Measurement** | Populated-workload certification. | **Open.** 4/32/128-channel latency, peak RSS, 1 GB/180 M-sample import, second-open latency, and decoder-settle-plus-rendered-frame numbers are not yet recorded on a mid-spec machine. |

The existing microbenchmarks remain useful but do not close these items. In particular, the cursor
benchmark constructs an empty `ReadoutPanel`, does not process the queued paint events, the video
callback benchmark uses a fake signal, and the exact-seek benchmark measures command fan-out rather
than decoder settle/paint latency. P3.5 is complete only when the representative workload exercises
populated widgets, real event-loop paints, cold and warm storage, decoder settle plus decoded-frame
proof, cancellation, and peak memory. A fast median alone is insufficient: record p50/p95/p99 and
maximum UI heartbeat delay, and fail on timing/data mismatches even when throughput passes.

---

## Phase 0 — Foundation (Week 0–1)

**Goal:** empty app window ships to all 3 OSes via CI before any feature exists.

Deliverables:
- Repo layout (see ARCHITECTURE.md), `pyproject.toml` (hatchling), `pip install -e .[dev]` works.
- Tooling: ruff (lint+format), mypy (strict on `core/`), pre-commit, pytest + pytest-qt + pytest-benchmark.
- CI matrix (ubuntu/windows/macos): lint → type → warnings-as-errors docs → fixture-backed test →
  build PyInstaller artifact. Hosted tests use one global offscreen Qt boundary; Windows also
  provisions a pinned, SHA-verified libmpv DLL and proves `import mpv` before tests.
- `avialsync` entry point opens an empty PySide6 main window.
- **Synthetic data generator** `tools/make_fixtures.py`: ffmpeg test videos with burned-in frame counter + known start timestamps (8-bit and 12-bit variants, short & long GOP), numpy 50 kHz multi-channel signals with a known event (step at exact t) → this is the ground truth for all sync tests forever.

Exit criteria: green CI on 3 OSes; every artifact build completes; fixtures generate deterministically **including the edge-case variants (TESTING.md §7): VFR, dropped-frame, no-metadata video, image sequence, timestamp-pathology CSVs, NaN/gap/sentinel signals, split recording**. A CI artifact build is a packaging gate, not proof of a release installer or hosted-runner performance.

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
- mpv embedded in a Qt widget (`ui/video_pane.py`) — **build the Windows/macOS Qt OpenGL render-API paths FIRST (D-011, D-038), then native `wid` on Linux**; settle coordination via property observation, no sleeps. Exact-frame tests prove the decoded `screenshot-raw video` frame-strip result and retry only transient raw-capture unavailability.
- `ui/plot_pane.py`: pyqtgraph plot fed by pyramid, fixed oscilloscope-style sweep window,
  vertical playhead cursor, bounded paint-clip-only updates between sweep boundaries, and
  coalesced resize/window refreshes.
- Transport bar: play/pause (space), slider, time readout, speed 0.1–8×.
- Playback loop: precise QTimer @ 60 Hz advances MasterClock without waiting for a decoder; mpv
  follows via rate-matched play + drift correction (re-seek if |video_t − target| > 40 ms **for N
  consecutive ticks — hysteresis, see AGENTS traps**); slider drag = keyframe seeks, release =
  exact seek; frame stepping via actual frame timestamps (D-007). Cross-thread render/OSD callbacks
  are latest-value coalesced.
- Standard-video presentation timestamps are probed off-thread, content-hash cached, and override
  misleading container CFR declarations. The pane readout shows CFR/VFR timing evidence, codec, and
  file size without querying media on a clock tick.
- Open file dialogs + drag-and-drop for one video, one CSV (minimal import dialog: pick timestamp column, format, unit).

Exit criteria: **golden sync test** — for fixture video (burned frame counter) at 20 random `t`, decode the paused raw video frame and assert |frame_time − t| ≤ 1 frame; manual scrub feels smooth on dev machines. The test never treats a seek return, a timer delay, or a stale rendered image as frame evidence.

## Phase 3 — Multi-source + performance (Week 4–7)

**Goal:** the real spec: 3–4 cameras, multi-channel 50 kHz, still smooth.

Deliverables:
- Dynamic video grid (row 1, N columns, camera label overlay, double-click fullscreen).
- Video visibility is persistent across grid/fullscreen/resize changes; unchecked panes stay loaded
  but are paused and excluded from playback synchronization work.
- Channel rows (row 2+): one plot row per time series source, shared fixed-duration X window,
  one numeric `ms` / `s` / `min` / `h` limit with a linear continuous slider, show/hide channels,
  per-channel close-to-hide control, and color/legend.
- Left Sidebar / Inspector Pane (~20% width, collapsible):
  - File open/management buttons (video/sensor) + remove/hide toggles.
  - Per-file metadata readouts (codec, resolution, sample rate, channels).
  - Per-source offset spinboxes (live preview) + optional drift rate; persisted in session.
- Global Session Summary (Master timeline absolute times, duration).
- Non-blocking seek fan-out from the Qt thread that owns each embedded pane; libmpv decoders perform
  the work concurrently. Never move pane commands to `QThreadPool`/asyncio; frame-drop tolerance
  applies during play.
- Accepted exact frame-trigger mappings snap exact scrubs/pauses/steps to evidence timestamps and
  apply their local piecewise rate during multi-video playback.
- Import pipeline: background parse → binary sidecar → pyramid, with progress + cancel.
- Proxy generator: one-click ffmpeg re-encode to short-GOP scrub proxies; session tracks original↔proxy pairs.
- Startup diagnostics: disk read speed probe, hw-decode capability report, slow-drive warning.

Exit criteria: representative session (3× 1080p fixtures + 4× 50 kHz streams) works correctly in
GitHub Actions; the 3× 1080p + 4× 50 kHz × 1 h benchmark session meets all timing marks locally on
a real mid-spec machine; golden sync test now runs across 3 cameras simultaneously.

## Phase 4 — UX completeness (Week 7–10)

**Goal:** everything a daily user expects.

Deliverables:
- Session save/load (.avv JSON) incl. layout, zoom, visibility; recent files; autosave.
- Keyboard map (arrows = frame step, shift+arrows = 1 s, home/end, [ ] = A/B loop, m = marker…), discoverable via a shortcuts dialog.
- Frame step fwd/back using the reference camera's adjacent real presentation timestamp (never
  `±1/fps`), jump-to-time input.
- Annotations: point + range markers with label/comment, list panel, CSV export.
- Cursor readout panel: value of every visible channel at `t_master`.
- Region select → export data slice (CSV/Parquet) and optionally trimmed video clips (ffmpeg copy).
- A/B loop, snapshot export (frame + plot PNG), basic region stats (min/max/mean/rms).
- Timestamp import wizard (preview table, format autodetect suggestions, **explicit timezone choice for naive input, anchor date for time-of-day-only, sentinel→NaN mapping option, euro-dialect/BOM handling**, s/ms/µs/ns).
- Missing-file relink dialog on session load; label disambiguation for duplicate filenames.
- No-footage/no-data placeholder states (D-010); timeline coverage shading; channel tree +
  grouping for many-channel sources (ARCHITECTURE §5c).
- Error handling pass: unreadable file, missing column, codec unsupported → actionable dialogs; "copy diagnostics" button.
- Dark/light theme limited to palette/accent/font appearance; it must preserve native control style,
  seek and plot interaction state, playback state, shortcuts, and window/view state. Window state persistence.
- Timeline Evidence overview (D-027): named, conditional Coverage / Sync-TTL / Gaps / Annotations
  lanes under the **Data Streams** header; event hover/focus details; click-to-seek; standard section
  splitter handles matching the video/plot boundary plus a collapse control. A fixed label gutter
  clips coverage to the master-time area so labels are never overpainted. Colour supplements labels/icons, never substitutes for them. Persist only local splitter geometry/collapse preferences and keep playhead updates within the existing cursor budget.

Exit criteria: scripted UX walkthrough (pytest-qt integration test) covering open→align→annotate→export with zero unhandled exceptions; keyboard-only operation possible for the core loop. Timeline Evidence is understandable without a manual or colour interpretation: its populated lanes, event details, collapse/resize controls, and empty-lane suppression are covered.

### P4.6 — Plot review and sweep UX refinement (core implementation complete; certification pending)

**Goal:** make dense scientific plots behave like a stable recording browser while retaining the
existing oscilloscope presentation and every current transport, evidence, visibility, readout,
annotation, export, timing, and performance capability.

The normative behaviour, compatibility ledger, implementation slices, and acceptance tests live in
`PLOT_UX_PLAN.md` and D-044. In summary:

- paused/scrubbed data uses a complete fixed-page **Review** presentation;
- live playback offers **Sweep** (overwrite with an eraser gap) and compatibility **Scope**
  (clear/restart) styles;
- all rows retain one X link, one duration, and one global Data Streams navigator;
- the numeric `ms` / `s` / `min` / `h` control remains continuous, but unit changes convert the
  value and the slider uses a useful logarithmic/piecewise mapping;
- one bottom master-time axis, aligned channel gutters, stable explicit Y-scale modes, one
  min/max envelope, semantic colours, and a quieter overlay/grid hierarchy replace repeated,
  equally weighted plot furniture;
- control relocation proxies existing QActions/signals rather than deleting functionality;
- normal Tab focus is restored without weakening window-scoped playback shortcuts.

Current implementation covers the presentation, time-span, navigator, Y-scale, layout, focus, and
compatibility slices. Exit criteria remain: all `PLOT_UX_PLAN.md` §14 evidence passes; golden
synchronization remains unchanged; the populated ≤2 ms cursor and ≤16 ms plot budgets pass; a
128-channel field-shaped fixture can be played, resized, scrubbed, and rescaled without a >30 ms UI
callback or an unbounded graphics/query queue.

## Phase 5 — Plugin API + packaging (Week 10–13)

**Goal:** third parties can add proprietary formats; normal users can install in one click.

Deliverables:
- Public plugin API v1: Drop-in directory system (`~/.avialsync/plugins/` and bundled `examples/plugins/`); document + freeze the `TimeSeriesSource`/`VideoSource` ABCs; PluginManager uses `sys._MEIPASS` for compiled bundles.
- Loader capability negotiation (can_open(path) → score). Plugin configuration is a
  JSON-serialisable dictionary supplied by the host; plugins do not return Qt widgets (D-025).
- Packaging per ARCHITECTURE §6 / D-012..D-017/D-039: PyPI wheel + sdist; PyInstaller **one-dir**
  bundles with LGPL-verified complete mpv/ffmpeg runtimes (including `ffprobe` and dependency DLLs,
  validated in CI); Inno Setup installer; arm64 .dmg; AppImage; source-checkout native-prerequisite
  guidance rather than Windows pip auto-fetch of libmpv;
  signing/notarization steps stubbed behind secrets-present conditionals; conda-forge recipe.
- PyInstaller hardening: derive the source root from `SPECPATH`; stage media only from an explicit,
  validated `AVIALSYNC_MEDIA_ROOT`; fail on an invalid supplied directory and never stage the current
  working directory when the variable is absent. CI builds each OS artifact, while the tag workflow
  alone supplies and licence-verifies release media.
- `release.yml`: single tag builds installers AND publishes PyPI atomically (all-or-nothing —
  a failed channel fails the release; no version skew between channels).
- `avialsync open <folder>` CLI; sample dataset auto-download command.
- Docs site (Read the Docs/Sphinx): quickstart ≤ 5 min, plugin author guide, format notes (short-GOP advice), troubleshooting.

Exit criteria: a stranger can `pip install avialsync` **on a machine WITHOUT mpv installed**
(the app opens; the guided dialog and the documented per-OS prerequisites get them running) or
download an installer, and open the sample dataset in < 5 minutes — zero manual dependency steps
from an installer, one documented native install from pip; users can drop a `.py` plugin into their folder and it appears in the import dialog; installers verified to contain LGPL-flavor binaries.

### P5.4 — Evidence-based synchronization (TTL/events)

**Goal:** let a scientist align independently-clocked cameras, sensors, electrodes, and tracking
data through a simple visual workflow, while retaining enough evidence to trust and reproduce the
result. AvialSync remains a visual-inspection tool: acquisition and scientific analysis stay out of
the core and may be supplied by plugins.

Deliverables:
- A headless synchronization model for raw event evidence, proposed mappings, residuals, confidence,
  and accepted provenance; no PySide6 in `core/`.
- Chunked extraction of rising/falling TTL edges and ingestion of native digital events or camera-frame
  triggers supplied by plugins. Raw timestamps are preserved.
- Deterministic matching for common periodic pulses, camera-frame TTLs, and sparse event sequences;
  robust affine offset/drift fitting, outlier rejection, ambiguity detection, and manual fallback.
- A synchronization wizard: select source evidence, preview paired events and residuals, accept or
  reject the proposal, then persist the accepted mapping and evidence summary in `.avv`.
- Plugin extension points for lab-specific file formats and event semantics; core provides no lab
  acquisition drivers and no scientific-analysis algorithms.
- Synthetic fixtures and golden tests for common-clock drift, camera-frame triggers, sparse pulses,
  missing pulses, ambiguous matches, and outlier contamination; extraction/matching benchmarks are
  established before the feature is released.

Exit criteria: an accepted alignment is reproducible from the session alone, never changes raw data,
and stays within its declared timing error on every ground-truth fixture without regressing the
existing playback, import, or plotting budgets.

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
