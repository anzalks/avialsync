# PROMPTS.md — kickoff prompts per phase

Model-agnostic: written for frontier coding agents (Claude Sonnet/Opus-class, GPT-5-class,
Gemini 3-class). Paste the Universal Preamble + the phase prompt into a fresh session.
Break each phase into the numbered tasks; run ONE task per agent session for clean context.

---

## Universal preamble (prepend to every session)

```
You are working on AvialView. Before doing anything:
1. Read AGENTS.md fully — these are binding rules.
2. Read the current phase in BLUEPRINT.md and DECISIONS.md.
3. State a short plan (files, tests, risks) and wait for nothing — proceed unless the plan
   conflicts with AGENTS.md, in which case stop and report the conflict.
Hard rules recap: core/ never imports PySide6; UI thread never blocks; all plotting via the
pyramid; libmpv only for video; no GPL deps; tests ship with code; never weaken failing tests.
For CI, playback, or packaging work, distinguish hosted-runner correctness from local performance
certification and release validation. Preserve exact-frame evidence; do not hide a platform or
lifecycle failure with sleeps, skips, a native CI display override, or a weaker assertion.
Work in small increments and run `pytest -x -q` + `ruff check .` after each increment.
```

## Phase 0 prompts

- **P0.1 Scaffold**: "Create the repository skeleton exactly as in ARCHITECTURE.md §1:
  pyproject.toml (hatchling, PySide6/pyqtgraph/python-mpv/numpy/polars deps, dev extras with
  pytest/pytest-qt/pytest-benchmark/hypothesis/ruff/mypy), ruff+mypy config, pre-commit,
  empty-but-importable modules with docstrings, `avialview` entry point opening an empty
  QMainWindow titled 'AvialView'. Add the headless-core guard test from TESTING.md §5.
  Everything must pass `pytest -x`, `ruff check .`, `mypy src/avialview/core`."
- **P0.2 CI**: "Implement .github/workflows/ci.yml per TESTING.md §7 (3-OS matrix, ffmpeg install
  per OS, global offscreen Qt env, artifact build via PyInstaller on all OSes). Windows provisions
  a pinned SHA-verified libmpv DLL and proves `import mpv`; headless VideoPane uses `vo=null`, never
  a forced native `wid`. Keep jobs < 15 min; CI proves correctness, not performance certification."
- **P0.3 Fixtures**: "Implement tools/make_fixtures.py per TESTING.md §2 AND the edge-case
  fixture list at the end of TESTING.md §7 (VFR, dropped-frame, no-metadata, image sequence,
  timestamp pathologies, NaN/gap/sentinel, split recording, euro CSV). The binary frame-strip
  must be decodable by a pure-numpy function you also write (tests/util_framestrip.py with its
  own unit test). Deterministic via seed. Document ffmpeg commands used."

## Phase 1 prompts

- **P1.1 Timeline core**: "Implement core/timeline.py (MasterClock, TimeMap with offset+drift,
  PlaybackState) and core/errors.py per ARCHITECTURE.md §2. Monotonic-driven ticks (AGENTS.md
  known-traps). 100 % branch coverage; hypothesis property tests: TimeMap round-trip
  (to_source∘to_master = id), rate changes preserve continuity, seek clamps to bounds."
- **P1.2 Pyramid + cache**: "Implement core/pyramid.py (levels 1/16/256/4096, vectorized min/max,
  mmap write/read) and core/cache.py per D-004. Add benchmarks bench_pyramid.py with the ≤2 s /
  ≤5 ms budgets. Query API: given (t0,t1,max_points) choose the level and return (t,vmin,vmax)."
- **P1.3 Source ABCs + registry**: "Implement core/source.py ABCs exactly per ARCHITECTURE.md §4
  and core/registry.py using importlib.metadata entry points group 'avialview.loaders'.
  Unit-test discovery with a dummy in-repo plugin."
- **P1.4 Built-in loaders**: "Implement loaders/csv_loader.py (polars, explicit timestamp schema,
  units s/ms/µs/ns, ISO8601, tz, chunked ingest per D-005, sort-or-raise on non-monotonic,
  sentinel→NaN config, euro-dialect/BOM) and loaders/video_standard.py (ffprobe metadata,
  start_time guess-only, frame_times() extraction, needs_conversion=False). Test against every
  Time & Data row of the TESTING.md §7 matrix using the Phase-0 fixtures."
- **P1.5 Edge-case sweep**: "Work through the TESTING.md §7 matrix rows owned by core/ and
  loaders/ (all Time, all Data content, cache rows). One test per row minimum; fix code to spec.
  Report a checklist of rows covered in the PR description."

## Phase 2 prompts

- **P2.1 Video pane**: "Implement ui/video_pane.py embedding libmpv via python-mpv into a Qt
  widget (Qt OpenGL render API on Windows/macOS; native `wid` on Linux; isolate per-OS logic here;
  hwdec=auto-safe; keep-open=yes; exact-seek helper method; frame-step helpers). Manual run
  instructions in the module docstring."
- **P2.2 Plot pane**: "Implement ui/plot_pane.py: pyqtgraph PlotWidget fed exclusively by
  pyramid queries for the visible range; playhead InfiniteLine updated independently of curve
  redraws; 'follow playhead' toggle. Bench cursor update ≤ 2 ms offscreen."
- **P2.3 Engine + transport**: "Implement engine/player.py and ui/transport.py per
  ARCHITECTURE.md §2 dataflow: 60 Hz tick, rate-matched mpv follow with 40 ms drift re-seek,
  slider drag = keyframe seeks / release = exact seek, play/pause/space, speed 0.1–8×.
  Wire main_window.py minimal: one video + one CSV via open dialogs and drag-drop."
- **P2.4 Golden sync v1**: "Implement tests/test_sync_golden.py items 1–4 from TESTING.md §3
  for the single-camera case using the frame-strip decoder. This test is sacred: coordinate with
  mpv property observation, then prove the exact decoded `screenshot-raw video` frame. Retry only
  transient raw-capture unavailability; never sleep, skip, or accept a stale rendered screenshot."

## Phase 3 prompts

- **P3.1 Multi-camera grid**: "Implement ui/video_grid.py: N panes, dynamic columns, camera
  label overlay (disambiguate duplicate filenames with parent dir), no-footage placeholder state
  per D-010, double-click fullscreen-single toggle. Extend engine/player.py to fan out to N
  mpv instances; implement engine/seeker.py parallel seeks (gather-then-update). Extend golden
  sync to the 3-camera fixture set with per-source offsets."
- **P3.2 Import pipeline**: "Move CSV parsing to a cancellable QThread worker with progress
  signals; UI progress bar; crash-safe cache writes (write temp, atomic rename). Test cancel and
  kill-mid-import recovery."
- **P3.3 Offsets + drift UI**: "Implement ui/offsets_panel.py: per-source offset spinbox
  (10 ms and 1-frame steps) + optional drift ppm, live-preview via TimeMap update; persisted in
  session. Golden offset test (TESTING.md §3.5)."
- **P3.4 Proxies + conversion + diagnostics**: "Implement engine/proxy.py (ffmpeg short-GOP
  proxy via QProcess arg-lists, progress, session tracks original↔proxy) and wire the
  VideoSource needs_conversion()/prepare() flow (D-006) incl. the image-sequence fixture
  end-to-end and ui/diagnostics.py (disk read probe,
  hwdec probe, slow-drive warning, copy-diagnostics, libmpv probe + guided-install dialog +
  lazy mpv import per D-013; Windows auto-fetch offer per D-014)."
- **P3.5 Perf hardening**: "Run all benchmarks against the big fixtures; profile and fix until
  BLUEPRINT budgets pass. Report before/after numbers in the PR description."

## Phase 4 prompts (one per feature, same pattern)

P4.x: sessions+autosave · keyboard map+shortcuts dialog · frame-step/jump-to-time ·
annotations+export · readout panel · region export (data slice + ffmpeg -c copy clips) ·
A/B loop+snapshots+region stats · import wizard (preview, autodetect suggestions) ·
error-handling pass (typed errors → actionable dialogs, tested) · theming+state persistence.
Template: "Implement <feature> per BLUEPRINT Phase 4. Add pytest-qt coverage for the happy path
and one failure path. Update docs/user-guide stub. Keyboard-first where sensible."

- **P4.6 Plot review/sweep UX — run one slice per session**: "Read `PLOT_UX_PLAN.md`, D-042,
  D-044, `HANDOUT.md`, and TESTING §5a before editing. Implement exactly one numbered slice from
  `PLOT_UX_PLAN.md` §13. Start with characterization tests and state which compatibility-ledger
  entries that slice touches. Preserve Scope mode, the single master clock/X link/duration/global
  navigator, every existing QAction/signal/shortcut/evidence lane, absolute overlay times,
  pyramid-only rendering, and session compatibility. Do not replace the plot/transport stack in one
  rewrite. Ordinary ticks may not query the pyramid or scan all events. Add the §14 pytest-qt,
  query-count, focus, migration, theme, and performance evidence relevant to the slice; run golden
  sync for any playback/seek change. Update HANDOUT only for behaviour actually shipped."

## Phase 5 prompts

- **P5.1 API freeze**: "Review core/source.py against every built-in loader; finalize as Plugin
  API v1; write docs/plugin-guide.md with a full walkthrough; create the external
  avialview-plugin-example repo content under examples/ reading a toy binary format;
  test it installs via pip and appears in the import dialog."
- **P5.2 Packaging**: "Implement ARCHITECTURE §6 exactly: one-dir PyInstaller specs per OS
  bundling LGPL-verified mpv/ffmpeg (CI asserts build flavor, D-015); Inno Setup; arm64 dmg;
  AppImage; release.yml building installers AND PyPI atomically from one tag, with signing/
  notarization steps stubbed behind secrets-present conditionals (D-016); Windows libmpv
  auto-fetch with pinned SHA256 (D-014); conda-forge recipe skeleton. Packaging smoke test:
  each bundle launches headless, opens sample session, exits 0; plus a pip-install test in a
  clean container WITHOUT libmpv asserting the guided dialog appears (D-013). `SPECPATH` is the
  spec directory, so derive the project root from it. Stage media only from a non-empty, validated
  `AVIALVIEW_MEDIA_ROOT`; an unset value must include no media. Keep PR CI artifact builds separate
  from release media/licence verification."
- **P5.3 Docs site**: "Read the Docs/Sphinx site: 5-minute quickstart with the sample dataset,
  format advice (short GOP!), troubleshooting (slow drive, no hwdec, timestamp formats),
  plugin guide. CI validates warnings as errors; Read the Docs deploys from its project integration."
- **P5.4 Evidence-based synchronization**: "Implement D-026 and BLUEPRINT P5.4. First add
  ground-truth fixtures and failing tests for periodic TTL clocks, camera-frame triggers, sparse
  pulses, drift, missing pulses, ambiguity, and outliers. Keep `core/` headless. Extract events
  chunkwise in a worker; preserve raw timestamps; use deterministic matching and robust affine
  offset/drift fitting. Build a Sync Wizard that previews paired evidence, residuals, and confidence,
  requires explicit user acceptance, persists provenance in `.avv`, and offers manual fallback.
  Do not add acquisition drivers or built-in scientific analysis; expose lab-specific event formats
  through plugins. Add benchmarks before release: speed and declared timing accuracy are equal gates."

## Phase 6 prompts

- **P6.1 Coverage & polish**: "Raise coverage to targets (TESTING §1); fix all mypy strict on
  core; triage TODOs into issues. Implement the D-027 Timeline Evidence contract from
  ARCHITECTURE §2b with pytest-qt coverage, preserving the ≤2 ms cursor path."
- **P6.2 Community**: "CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue/PR templates, 10 good-first-
  issues drafted from the backlog, README with GIF placeholders and feature matrix vs
  PlotJuggler/Rerun/Foxglove (factual, respectful)."
- **P6.3 Release**: "Dry-run the release workflow on a rc tag; verify artifacts on all OSes;
  cut v1.0.0."

## Debugging prompt template (any phase)

```
Bug: <symptom>. Repro: <steps/fixture>. Expected vs actual: <...>.
First write a failing test that reproduces it, then fix, then show the test passing.
Do not touch golden sync assertions. If the fix changes behavior, update docs and DECISIONS.md.
For CI failures, also identify the boundary that failed (dependency/runtime, headless compositor,
decode evidence, lifecycle, or packaging); do not paper over it with retries outside the known
transient raw-capture case.
```
