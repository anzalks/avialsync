# PROMPTS.md — kickoff prompts per phase

Model-agnostic: written for frontier coding agents (Claude Sonnet/Opus-class, GPT-5-class,
Gemini 3-class). Paste the Universal Preamble + the phase prompt into a fresh session.
Break each phase into the numbered tasks; run ONE task per agent session for clean context.

> **Historical note (D-075).** The Phase 2–5 prompts below describe building the libmpv playback
> path — the video pane, the drift-corrected follow loop, the startup probe and guided-install
> dialog, the SHA-pinned Windows DLL step. That path is being replaced by PyAV on branch
> `shift_from_libmpv_to_pyav`. These prompts are kept as the record of how the shipped system was
> built; **do not use them to write new video code.** MIGRATION_PYAV.md is the current instruction
> set for anything touching playback, seeking, or media packaging.

---

## Universal preamble (prepend to every session)

```
You are working on AvialSync. Before doing anything:
1. Read AGENTS.md fully — these are binding rules.
2. Read the current phase in BLUEPRINT.md and DECISIONS.md.
3. State a short plan (files, tests, risks) and wait for nothing — proceed unless the plan
   conflicts with AGENTS.md, in which case stop and report the conflict.
Hard rules recap: core/ never imports PySide6; UI thread never blocks; all plotting via the
pyramid; PyAV only for video (D-075 — never libmpv/QtMultimedia/OpenCV); pip must need no OS-level
install; prefer LGPL deps and escalate GPL binaries to DECISIONS.md; tests ship with code; never
weaken failing tests.
For CI, playback, or packaging work, distinguish hosted-runner correctness from local performance
certification and release validation. Preserve exact-frame evidence; do not hide a platform or
lifecycle failure with sleeps, skips, a native CI display override, or a weaker assertion.
Work in small increments and run `pytest -x -q` + `ruff check .` after each increment.
```

## Phase 0 prompts

- **P0.1 Scaffold**: "Create the repository skeleton exactly as in ARCHITECTURE.md §1:
  pyproject.toml (hatchling, PySide6/pyqtgraph/python-mpv/numpy/polars deps, dev extras with
  pytest/pytest-qt/pytest-benchmark/hypothesis/ruff/mypy), ruff+mypy config, pre-commit,
  empty-but-importable modules with docstrings, `avialsync` entry point opening an empty
  QMainWindow titled 'AvialSync'. Add the headless-core guard test from TESTING.md §5.
  Everything must pass `pytest -x`, `ruff check .`, `mypy src/avialsync/core`."
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
  and core/registry.py using importlib.metadata entry points group 'avialsync.loaders'.
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
  lazy mpv import per D-013; the dialog's Windows branch names the mpv-dev archive plus
  `AVIALSYNC_MEDIA_ROOT` — D-014's in-app auto-fetch is superseded, do not build a downloader)."
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
  avialsync-plugin-example repo content under examples/ reading a toy binary format;
  test it installs via pip and appears in the import dialog."
- **P5.2 Packaging**: "Implement ARCHITECTURE §6 exactly: one-dir PyInstaller specs per OS
  bundling LGPL-verified mpv/ffmpeg (CI asserts build flavor, D-015); Inno Setup; arm64 dmg;
  AppImage; release.yml building installers AND PyPI atomically from one tag, with signing/
  notarization steps stubbed behind secrets-present conditionals (D-016); documented per-OS native
  prerequisites for pip users rather than an in-app libmpv downloader (D-014 superseded);
  conda-forge recipe skeleton. Packaging smoke test:
  each bundle launches headless, opens sample session, exits 0; plus a pip-install test in a
  clean container WITHOUT libmpv asserting the guided dialog appears (D-013). `SPECPATH` is the
  spec directory, so derive the project root from it. Stage media only from a non-empty, validated
  `AVIALSYNC_MEDIA_ROOT`; an unset value must include no media. Keep PR CI artifact builds separate
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

## Phase 7 prompts (UX foundations)

Branch: `ux_foundations`. **The plan is `UX_FOUNDATIONS_PLAN.md`** — every prompt below is a thin
pointer into it. The plan carries the file lists, numbered steps, acceptance evidence, and budget
notes; do not restate them here and do not work from the prompt alone.

**Phase 7 preamble — prepend to the universal preamble above, for every Phase 7 session:**

```
You are working on AvialSync Phase 7 (UX foundations), branch ux_foundations.
Read, in this order:
1. AGENTS.md in full — note architecture rules 10–17, which are new and binding.
2. UX_FOUNDATIONS_PLAN.md sections 0–4 (how to use it, objective, the two laws,
   the compatibility ledger, the seven foundations). These apply to every package.
3. Your work package in UX_FOUNDATIONS_PLAN.md section 5, plus any package it
   lists as a dependency. Read nothing else from section 5.
4. UX_FOUNDATIONS_PLAN.md section 11 (traps). Every one of them has already cost
   somebody a day.
Then do exactly that package. One package per session — do not start a second.
Two product laws govern this phase and outrank your instincts about convention:
  Law 1  Never block, always inform. Opening a file is never refused or gated.
         The user is told when the document is dirty and when the data is dirty.
         Never a modal "save your changes?" in front of Open, drop, Open Recent,
         or quit. Quitting always proceeds and writes a recovery snapshot.
  Law 2  Nothing is drawn over video that the user cannot turn off. Every overlay
         is registered and has a checkbox in View -> Overlays.
Where the plan names a class, method, or settings key, use that exact name.
The plan sketches responsibilities, never implementations — write the code
yourself, in the style of the module you are touching.
Check yourself against section 10 (Definition of Done) before reporting, and say
which numbered steps you completed and which remain.
```

- **P7.1 Document + dirty state**: "Do WP-1 in UX_FOUNDATIONS_PLAN.md. Build the headless command
  bus in `core/document.py`, wire dirty state to the window title, and make quitting lossless. The
  three things that will bite you: `core/` cannot import PySide6 so `QUndoStack` goes in `ui/`
  (§4 F1); commands carry inverse operations and never state snapshots, or you breach the idle-RAM
  budget (step 3); and dirty notification must coalesce at 20 Hz or an offset drag storms the title
  repaint past the 8 ms callback target (step 6). `session_controller.autosave()` returning early
  when `_session_path is None` is the single line that leaves unsaved work unprotected today."
- **P7.2 Undo + Edit menu**: "Do WP-2. Depends on WP-1. Wrap core commands in `QUndoCommand` via
  `ui/undo_adapter.py`, add a real Edit menu, and make the destructive actions undoable — the
  sensor `✕`, the video close button, annotation Delete. Do not add confirmation dialogs; undo is
  the better answer and a confirmation violates Law 1's spirit."
- **P7.3 Action registry + palette + shortcuts**: "Do WP-3. No dependencies. Promote the existing
  `_reg()` helper in `main_window.py` into `ui/action_registry.py`, add a `Ctrl+Shift+P` command
  palette, and make shortcuts remappable. Two constraints: `shortcuts_dialog.py` must keep deriving
  from live `QAction`s (D-022.6) — add editing, do not replace the derivation; and the registry
  becomes the single authority for a command's label, so the menu's 'Open Video(s)…' and the
  sidebar's 'Open Videos' resolve to one entry (D-092). If you find yourself restructuring
  `main_window.py`, read D-051 first — composition only, never Qt-slot mixins."
- **P7.4 Overlay registry + View → Overlays**: "Do WP-4. Depends on WP-3. This implements Law 2.
  Build `ui/overlay_registry.py`, generate the View → Overlays submenu from it, and migrate the
  seven existing overlays in the table in that package. Note that `set_point_labels_visible()` and
  `set_legend_visible()` already exist on `PaintCanvas` and no caller anywhere invokes them — wire
  those through the registry rather than writing new toggles beside them. `camera.no_footage` is
  registered but locked visible; hiding it would let a blank pane read as black footage, which
  D-010 exists to prevent. Change no drawing code — this package adds the control surface only."
- **P7.5 Feedback surface**: "Do WP-5. No dependencies, and the highest value per hour in this
  phase: `ui/job_manager.py` already tracks state, cooperative cancel, and stall detection, and
  none of it reaches the user. Add the status-bar activity area, jobs panel, and notification
  strip, then delete the modal `QProgressDialog` for imports and proxy generation (D-091). Change
  JobManager's signals only — never its threading. Cap updates at 20 Hz and never repaint from the
  60 Hz clock tick."
- **P7.6 Error presenter + quality badges**: "Do WP-6. Depends on WP-5. This is the second half of
  Law 1. Map every typed exception in `core/errors.py` to title + plain-language cause + named
  recovery actions, and replace the 40+ bare `QMessageBox` call sites. A source that fails
  partially still loads what it can and reports a finding — never a dialog that stops the session
  appearing. The quality badge needs no new detection work: the loaders already produce
  `SourceInspection` and `ui/sidebar.py` already carries it."
- **P7.7 Settings registry + Preferences**: "Do WP-7. Depends on WP-1. One typed schema in
  `core/settings_schema.py`, `QSettings` still behind it, and a Preferences dialog *generated* from
  the schema rather than hand-built — a hand-built one is how 'Reset to default' gets forgotten.
  Fold in the scattered `QSettings("AvialSync", "AvialSync")` sites. The View-menu radio groups for
  Theme, Font Size, and Time Display stay in the menu but read from the registry."
- **P7.8 Empty state + Help + About**: "Do WP-8. Depends on WP-3. An empty-state view with the drop
  target, the real entry points, and a Try-the-demo button that runs the existing demo generator
  in-process on a worker — it is the best onboarding asset in the project and it is currently
  reachable only from a command line the target user may never open. Help gains documentation,
  tutorial, report-a-problem, and update-check links; About gains version, commit, and library
  versions with copy-to-clipboard, so bug reports stop arriving without a version."
- **P7.9 Display levels for high-bit-depth video**: "Do WP-9. Depends on WP-4 and WP-7. **This is
  the only package that touches a measured hot path — benchmark before you ship, not after
  (AGENTS rule 9).** Read D-093 before starting. The core fact: `to_ndarray(format='rgb24')`
  destroys 12-bit range inside swscale before any UI code runs, so this is a decode stage in
  `engine/display_pipeline.py`, not a filter on the pane. The LUT runs in the decode worker, never
  in `paintEvent`. Keep `PyAVReader._store` caching `av.VideoFrame` pre-conversion and add a
  converted-buffer cache keyed by `(frame_index, levels_generation)`. Measure whether
  `to_ndarray('gray16le')` is as cheap as `rgb24` — that is the genuine unknown; if it is not,
  index the native frame's planes directly. This package must not change which frame is shown, only
  how its pixels map: D-084 and the exact-frame golden tests are untouched by it."
- **P7.10 Alignment evidence + direct manipulation**: "Do WP-10. Depends on WP-1 and WP-3. Promote
  alignment out of the File menu to a top-level Align menu — it is not a file operation, it is the
  reason this product exists. Then show the evidence: BLUEPRINT principle 8 requires presenting the
  matched evidence, and today `sync_wizard.py` reports a fit as one sentence of four numbers. Build
  the residual scatter with its tolerance band, matched vs. rejected events, and a before/after
  preview. Add drag-to-align with live residual feedback and frame-granularity arrow nudge; the
  spin box stays as numeric entry, not the primary interaction. Convert the modal wizard to a dock
  panel. `tests/test_sync_golden.py` stays untouched and passing."
- **P7.11 Sidebar at scale + docking**: "Do WP-11. Depends on WP-1 and WP-7. Filter, sort, group,
  collapse-all, multi-select, and drag reordering in the sidebar; virtualise above ~200 rows so
  widget construction does not compete with the 3 s cached-open budget. Convert the fixed splitters
  to `QDockWidget` with nesting, and add named workspaces. Migrate existing splitter state into
  equivalent dock sizes once rather than discarding a user's layout."
- **P7.12 Accessibility, i18n, colour**: "Do WP-12. Depends on WP-7. **Do this last** — it should
  translate final copy, not copy you are about to rewrite. i18n and the accessibility pass are one
  pass, because both mean touching every user-facing string exactly once. Add `lupdate` to CI so a
  new untranslated string fails the build. On colour: read D-094 first. `theme.py::marker_color` is
  well-reasoned but its even hue spacing is exactly what collapses under deuteranopia — separation
  in hue is not separation in CVD space. Swapping the palette is a legal theme change; the
  redundant encoding beside it is not, and needs its own DECISIONS entry before it ships."

## Debugging prompt template (any phase)

```
Bug: <symptom>. Repro: <steps/fixture>. Expected vs actual: <...>.
First write a failing test that reproduces it, then fix, then show the test passing.
Do not touch golden sync assertions. If the fix changes behavior, update docs and DECISIONS.md.
For CI failures, also identify the boundary that failed (dependency/runtime, headless compositor,
decode evidence, lifecycle, or packaging); do not paper over it with retries outside the known
transient raw-capture case.
```
