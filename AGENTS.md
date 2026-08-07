# AGENTS.md — AvialSync agent instructions (canonical)

This file is the single source of truth for ALL coding agents (Claude Code, Codex, Gemini/Antigravity,
Cursor, Copilot, etc.). `CLAUDE.md` and `GEMINI.md` are thin pointers to this file — never duplicate
content there. If tool-specific config is unavoidable, it still must say "rules live in AGENTS.md".

## What this project is

GUI desktop app for visual synchronization and inspection of multi-camera video (h264/h265, incl.
12-bit greyscale) together with dense time series (up to 50 kHz, 16-bit, CSV or plugin formats) on
one master timeline. Acquisition and built-in scientific analysis are out of scope: labs extend file
formats, TTL/event semantics, and optional analysis through plugins. Open-source
(AGPL-3.0-or-later, D-069). Copyright is held in one place so the work can be licensed
coherently, which is why every contribution needs the CLA. Targets: Windows / macOS / Linux, mid-spec machines (8-core, 16 GB, SSD). Read
`BLUEPRINT.md` for phases, `ARCHITECTURE.md` for structure,
`DECISIONS.md` for settled choices. Do not re-litigate settled decisions; propose changes as a
DECISIONS.md entry in the PR description instead of silently diverging.

## Naming & casing — BINDING (never invent variants)

| Context | Exact form |
|---|---|
| Brand / UI / window title / docs prose / installer filenames | `AvialSync` |
| PyPI package, import module, CLI command, repo dir, entry-point group, paths | `avialsync` (all lowercase, one word, no hyphen/underscore) |
| Python identifiers derived from it | `avialsync` (e.g. `from avialsync.core import ...`) |
| Env vars / constants | `AVIALSYNC_*` |
| Session file extension | `.avv` |
| Sidecar cache dir | `<file>.avialcache/` |
| Installer artifacts | `AvialSync-Setup.exe`, `AvialSync.dmg`, `AvialSync.AppImage` |
| Plugin packages (3rd party convention) | `avialsync-plugin-<name>` on PyPI |
| Plugin `display_name()` / `display_aliases()` | the **kind of data**, never the rig — `Video`, `IMU / Motion Data`, `TTL Events`. A camera is a camera whichever system recorded it |
| Which rig an item came from | the session's `SessionItem.label`, not the type — the type column answers "what is this", not "who wrote it" |

Use `AvialSync` only for the displayed product name and `avialsync` for technical identifiers.
Do not invent alternative spellings. A rename is never "improved" by an agent (D-018).

## Tech stack — FIXED

- Python 3.11–3.12 · PySide6 (never PyQt5/PyQt6 — license) · PyAV (`av` on PyPI, import `av`) for
  ALL video decoding and probing (never QtMultimedia, never OpenCV, never libmpv — D-075)
  · pyqtgraph for plots · numpy + polars for data · hatchling build
  · pytest / pytest-qt / pytest-benchmark / hypothesis.
- **`pip install avialsync` must need no OS-level install step on any platform.** A change that
  reintroduces one is rejected. The single documented exception is Qt's own floor: PySide6 needs
  system GL/xcb libraries on Linux, which no packaging choice removes. Decoding is done (steps 1-5
  and the libmpv sweep); the FFmpeg *command line* is still external for proxy generation, clip
  export, and the demo — MIGRATION_PYAV.md step 7. Read that file before touching video code.
- Dependency policy: the project is AGPL-3.0-or-later (D-069), so GPL dependencies are
  licence-*compatible* but foreclose the commercial dual-licence — prefer LGPL, and escalate any
  GPL-configured binary to a DECISIONS.md entry rather than deciding it in a packaging commit
  (D-015 as amended). Adding any dependency requires: license named in PR description,
  justification, and it must be pip-installable on all 3 OSes.

## Architecture rules (violations = rejected PR)

1. Single master clock in `core/timeline.py`. UI and sources NEVER keep independent time state;
   they subscribe to MasterClock. Time is float seconds, UTC epoch, with per-source
   `offset + drift_rate` mapping in TimeMap.
2. `core/` is headless: importing anything from `core/` must not import PySide6. Enforced by a test.
3. UI thread never blocks: no file IO, parsing, or decoding on it. Use worker threads — PyAV
   releases the GIL during decode, so decode threads genuinely run in parallel. Any function that
   can take > 30 ms gets a worker + progress signal.
4. Plotting only via the decimation pyramid (`core/pyramid.py`). Never pass raw full-resolution
   arrays to pyqtgraph for datasets > 100 k samples.
5. All data sources go through the plugin ABCs in `core/source.py` (`TimeSeriesSource`,
   `VideoSource`). Built-in CSV/video support are plugins too. Do not special-case formats in UI code.
6. Playback: sync correctness beats frame completeness (drop frames, never drift). Paused/stepping:
   exact seeks only. **The frame shown for master time `t` is the one whose presentation interval
   contains `t` — the last frame with `pts <= t`, per `core/video_timing.py::frame_index_at`.** A
   reader returning the first frame with `pts >= t` is wrong at every scrub position between two
   frames (measured 179/179; 33 ms of misattribution at 30 fps). Frame caches are keyed by integer
   frame index, never by float time. One authority selects *and* names the frame — never two
   (D-075).
7. Text data is parsed once → binary sidecar cache (`core/cache.py`), mmap-read afterwards.
8. Synchronization is evidence-based. TTL/event alignment preserves raw source timestamps and records
   matched evidence, fitted offset/drift, residuals, and confidence. Never silently invent a match or
   apply a proposed TimeMap without explicit user acceptance.
9. Speed and timing accuracy are co-equal release criteria. Sync extraction is chunked; fitting is
   deterministic and benchmarked; any timing feature needs a ground-truth fixture before it ships.

## Coding standards

- ruff for lint+format (config in pyproject; run `ruff check --fix . && ruff format .` before finishing).
- mypy --strict on `core/`; standard on `ui/` and `loaders/`.
- Type hints everywhere; dataclasses/pydantic-free core (plain dataclasses OK).
- Qt: signals/slots over polling; no `QApplication.processEvents()` hacks; objects have parents or
  documented ownership.
- Themes are appearance-only: palette roles, platform accent, and the selected application font may
  change; widget style, control metrics, shortcut/input behavior, seek semantics, plot navigation,
  playback state, and layout/view state may not. Do not use application-level QSS to restyle controls.
- Docstrings: module + public API, Google style. Comments explain WHY, not what.
- No new module > ~500 lines; split. No function > ~60 lines without justification.
- Naming: `snake_case`, Qt widget classes end in their role (`VideoPane`, `TransportBar`).
- Errors: raise typed exceptions from `core/errors.py`; UI layer converts to user dialogs with
  actionable text. Never `except Exception: pass`.
- **Never silence a type/lint error to ship code known to be broken.** A `# type: ignore`
  is only valid for genuine mypy limitations (e.g. `**dict[str, object]` unpacking, missing
  third-party stubs). A TODO comment acknowledging a crash is forbidden — fix it or stop and
  report. Suppressing a checker warning that hides a real defect is the same as shipping the
  defect with extra steps.

## Definition of Done (every task)

- [ ] Code + tests in the same change. New logic in `core/` → unit tests; UI behavior → pytest-qt test
      where feasible; performance-relevant code → benchmark present and within budgets
      (BLUEPRINT.md table).
- [ ] `pytest -x`, `ruff check .`, `mypy` all pass locally on the files touched.
- [ ] Golden sync tests (`tests/test_sync_golden.py`) untouched-and-passing for any change in
      `core/timeline.py`, playback loop, or seek logic.
- [ ] CI, playback, or packaging changes preserve the full quality gate: cross-platform correctness,
      exact-frame fixtures where applicable, documentation warnings-as-errors, and all PyInstaller
      artifact builds. A build artifact is not a release or a speed certification.
- [ ] No performance budget regressed (> 20 % on touched benchmarks).
- [ ] Docs updated if public API or user-visible behavior changed.
- [ ] Conventional commit message: `feat(scope): …` / `fix:` / `perf:` / `test:` / `docs:` / `chore:`.

## How to run things

ALL commands must be prefixed with `conda run -n avialsync` when working inside the
`avialsync` conda environment. Never run project commands (pytest, ruff, mypy, pip,
avialsync) without this prefix — the system Python may differ from the env Python.

```bash
conda run -n avialsync pip install -e .[dev]          # setup
conda run -n avialsync python tools/make_fixtures.py  # generate test videos + signals (needs ffmpeg in PATH)
QT_QPA_PLATFORM=offscreen conda run -n avialsync pytest -x -q   # tests
conda run -n avialsync pytest --benchmark-only                   # perf budgets
conda run -n avialsync avialsync                                # run the app
conda run -n avialsync avialsync open tests/fixtures/sample_session/

# Type checking — run BOTH; strict mode applies only to core/
conda run -n avialsync mypy src/avialsync/core    # strict (enforced)
conda run -n avialsync mypy src/avialsync          # standard (ui/engine/loaders; pre-existing errors suppressed per pyproject.toml)

# Lint + format
conda run -n avialsync ruff check --fix . && conda run -n avialsync ruff format .
```

## Task protocol for agents

1. Read HANDOUT.md (module map, current phase status, known bugs, run commands) and the
   relevant BLUEPRINT.md phase + the kickoff prompt in PROMPTS.md before coding.
   **Rule:** any PR that changes a module's public API, adds a trap, or fixes a listed bug
   must update HANDOUT.md in the same commit.
2. Plan first: for any task touching > 2 files, write a short plan (files to change, test strategy,
   risks) in your response before edits. If the plan conflicts with this file → stop and say so.
3. Small steps: implement in reviewable increments; run the test suite after each increment, not
   only at the end.
4. Never delete or weaken a failing test to make it pass. If a test seems wrong, explain why and
   propose the fix explicitly.
5. Fixtures, not real data: all tests use `tools/make_fixtures.py` outputs. Never assume the user's
   private field data is available; never hardcode paths outside the repo/tmp.
6. Cross-platform paranoia: pathlib everywhere; no shell=True; guard OS-specific code
   (`sys.platform`) and provide fallbacks. Video rendering no longer differs per OS (D-075 removed
   the mpv `wid`/render-context split) — if you find yourself adding a `sys.platform` branch to
   `ui/video_pane.py`, that is a signal to stop and reconsider.
7. When uncertain between two designs, choose the one that keeps `core/` simpler and put the
   complexity in the adapter/UI layer.
8. Update `DECISIONS.md` when you make a choice future agents must not reverse.
9. Consistency over preference: match existing naming/patterns in the module you touch, even if
   you'd choose differently. Multiple models rotate through this codebase; style entropy is a
   real failure mode. Do not "improve" working patterns without a DECISIONS.md entry.
10. Library APIs (PyAV, pyqtgraph, polars) may differ from your training data — verify against
    the installed version's docs/signatures when behavior surprises you; don't force remembered APIs.
11. Test and scratch script locations: NEVER create temporary test scripts, scratch files, or ad-hoc tests in the repository root or inside `src/`. All formal tests must be placed in `tests/` and appropriately named (e.g., `test_*.py`). If you need temporary scratch files, use the designated artifact scratch folder or `/tmp/`, and clean them up afterward.

## Known traps (learned the hard way — do not rediscover)

- `.gitignore` ignores `*.spec` files by default. If you create or modify `packaging/avialsync.spec`, you must force-add it or it will be silently excluded from commits and break CI.
- The GitHub Actions Windows runner does not have `ffmpeg` pre-installed (unlike Ubuntu/macOS). Any script that invokes `ffmpeg` (like `make_fixtures.py`) will fail with `FileNotFoundError` unless `choco install ffmpeg` is in the CI workflow. Chocolatey is used because it is preinstalled on that image; WinGet is a Windows *client* feature and is not available on the Server image. This is a build-time concern only — released installers bundle their own media runtime.
- Every `apt-get install` in a workflow passes `--no-install-recommends`. `ffmpeg`'s recommends pull
  `yt-dlp`, pipewire, and a 27 MB pocketsphinx speech model; on a slow archive mirror that download
  ran twelve minutes and took the whole 15-minute job with it, which reads like a hung test suite
  rather than an infrastructure stall. The codecs the fixtures need are *depends*, not recommends.
- Runner images are pinned (`ubuntu-24.04`, `macos-15`, `windows-2022`), not `*-latest`. A floating label already broke the release once, when an image bump renamed `fuse` to `libfuse2t64`. `tests/test_ci_platform_config.py` fails if a floating label reappears.
- `choco install ffmpeg` on the Windows job used to be unpinned, unlike the runner images beside it. Chocolatey moved 8.1.2 → 9.0.0 between two runs an hour apart and ffmpeg 9 removed `-vsync`, so both Windows jobs went red with no commit in between — re-running the last green run at the same SHA reproduced it. Before debugging a Windows-only CI failure, diff the `ffmpeg vX.Y.Z [Approved]` line in the choco step against the last green run. Use `-fps_mode`, never `-vsync`, in anything that shells out to ffmpeg.
- Windows CI once fetched a pinned libmpv DLL archive, verified its SHA-256, and probed
  `import mpv`. All of it is gone: PyAV's wheel carries its own FFmpeg, so there is no library to
  fetch or verify. `tests/test_ci_platform_config.py` fails if any of it comes back. The workflows
  still install `ffmpeg` because it encodes the test fixtures.
- PyAV fixture writing: you must set **both** `stream.time_base` and
  `stream.codec_context.time_base`. Setting only the former makes `mux()` reject every packet with
  a bare `ArgumentError: Invalid argument ... returned 22`, which reads like a corrupt file rather
  than a missing attribute.
- A PyAV reader's forward-decode-vs-reseek crossover must be measured in **frames against GOP
  size**, never in seconds. A fixed 2-second window at 230 fps walks ~460 frames forward where a
  re-seek costs ~125; that alone took the 3-cam jump case from 106 ms to 293 ms, over budget.
- B-frame content demuxes in *decode* order. A pts table built by iterating packets must be sorted
  into display order, or every frame lookup is quietly scrambled.
- CI does **not** run benchmarks: both workflows pass `--ignore=tests/benchmarks`. Seeing
  `pytest-benchmark` in a CI log means `pip install -e ".[dev]"` installed it, not that it ran.
  Speed is certified locally with `pytest --benchmark-only` (BLUEPRINT.md "Performance budgets").
- A zero-delay `QTimer.singleShot` that walks widgets can outlive them, and `QApplication.allWidgets()`
  then returns freed pointers: the process dies with SIGSEGV, not an exception, so there is no
  traceback pointing at the real cause. Either do the work synchronously or pass a context object
  (`QTimer.singleShot(0, owner, callback)`) so Qt drops the callback with its owner. `shiboken6.isValid`
  guards a widget you already hold; it cannot save you while the list is being built (D-062, D-064).
- A channel name becomes a cache filename. Windows rejects `< > : " / \ | ? *`, which are all legal
  on POSIX, so a test that builds a channel from an exotic name passes on macOS and fails on Windows.
- Do not assert pixel outcomes from Qt layout. Font metrics differ per platform, so minimum sizes
  differ: the same window measures 966 px wide on macOS and 1114 px on Windows. Assert the policy
  (nothing collapsed, a drag stuck) and give a test the room it needs itself rather than changing a
  shared fixture — widening one broke an unrelated minimum-size test that had been passing.
- Test ordering can hide a broken assertion. `test_window_minimum_width_fits_a_laptop_display` passed
  for months only because earlier tests left the shared `QApplication` measuring smaller; alone it
  failed everywhere. When a test fails only in CI, run it **alone** locally before assuming platform.
- `mypy` results depend on the installed NumPy, not just on the code: NumPy 2.4.6 and 2.5.1 type
  `np.concatenate` differently, so `mypy src/avialsync/core` passed locally and failed in CI on
  identical source. To reproduce CI exactly, build a venv pinned to the versions its log reports.
- Windows ships no IANA time zone database, so `zoneinfo` finds nothing there. `tzdata` is declared
  as a Windows-only dependency; without it every timezone-aware CSV import fails on Windows only.
- A conda env is not a virtualenv: it still reads the **per-user** site-packages
  (`%APPDATA%\Python\Python312\site-packages` on Windows) and reads it *before* its own. A package
  an earlier `pip install --user` left there silently wins over the env, and pip never revisits it.
  A user hit this with a `quantities` predating NumPy 2 — `import neo` raised
  `AttributeError: 'numpy.ndarray' has no attribute 'ptp'` in an env whose own copy was fine.
  Version floors in pyproject cannot fix a shadowing install; `PYTHONNOUSERSITE=1` can. When a
  traceback's paths span two prefixes, read the paths before believing the version numbers.
- Never import a built-in loader unguarded at startup. `LoaderRegistry._load_builtins` imports each
  one separately and records failures in `plugin_errors`, because a loader's third-party dependency
  stack belongs to the user's machine, and the registry is built inside `MainWindow.__init__` —
  one bad dependency used to be a traceback before any window existed rather than one lost format.
- Hosted CI is headless on every OS: keep `QT_QPA_PLATFORM=offscreen` global and make
  `VideoPane` select `vo=null` there. Never force `qwindows` or native `wid` embedding merely to
  make a Windows job pass; interactive Windows and macOS use the Qt OpenGL render API, while Linux
  retains native `wid` embedding.

- pyqtgraph `setDownsampling` is not enough at 180 M points — always go through our pyramid.
- QTimer drift: drive MasterClock from `time.monotonic()` deltas, never by accumulating timer intervals.
- polars `read_csv` infers types per-chunk; always pass explicit schema for the timestamp column.
- ffprobe start times lie for some machine-vision containers; treat metadata start time as a default,
  never as truth — the user offset always wins.
- 12-bit video: never assume hw decode; probe once at startup (`ui/diagnostics.py`) and surface it.
- PyInstaller evaluates `SPECPATH` as the spec directory, not the project root. Resolve the root
  from it, and stage media only from a non-empty, validated `AVIALSYNC_MEDIA_ROOT`; an unset value
  must never accidentally package the current working directory.
- Theme changes must not restyle sliders, splitters, scrollbars, plot interaction, or layout. A
  global QSS changes Qt's style engine and can alter those controls; use `QPalette` only for theme
  colours and verify seek/plot state survives a theme switch.
- Playback drift correction needs hysteresis: re-seek only after N consecutive off-target ticks,
  or late Qt timers cause re-seek/stutter cascades under UI load.
- Frame stepping: always the decoded presentation timestamps; never `t += 1/fps` (breaks on VFR and
  dropped-frame footage).
- Video shutdown ownership is explicit: `MainWindow.closeEvent()` → `VideoGrid.shutdown()` →
  `VideoPane.close()` → stop the pane's decode thread. Do not rely on garbage collection or Qt
  child destruction to join it.
- A pane's decode thread must never be handed work from the UI thread that blocks: requests
  coalesce onto the newest wanted time, so a decoder slower than the 60 Hz tick skips rather than
  building a backlog nobody will see.
- `QImage` does not copy the array it wraps. A pane holds the decoded buffer for as long as the
  image built from it lives; dropping it faults during a repaint instead of raising.
- Pyramid must be NaN-aware (nanmin/nanmax) and gap-aware (gap_mask); never draw across gaps.
- Cache key includes a content-hash tail (ARCHITECTURE §5b); (path,size,mtime) alone is a lie.
- Timezone-naive timestamps: force an explicit user choice in the wizard; silent-UTC caused real
  1–2 h "corruption" reports in comparable tools.
- ffmpeg/QProcess: argument lists only, never shell strings (unicode/space paths on Windows).
