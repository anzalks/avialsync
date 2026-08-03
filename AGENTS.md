# AGENTS.md — AvialView agent instructions (canonical)

This file is the single source of truth for ALL coding agents (Claude Code, Codex, Gemini/Antigravity,
Cursor, Copilot, etc.). `CLAUDE.md` and `GEMINI.md` are thin pointers to this file — never duplicate
content there. If tool-specific config is unavoidable, it still must say "rules live in AGENTS.md".

## What this project is

GUI desktop app for visual synchronization and inspection of multi-camera video (h264/h265, incl.
12-bit greyscale) together with dense time series (up to 50 kHz, 16-bit, CSV or plugin formats) on
one master timeline. Acquisition and built-in scientific analysis are out of scope: labs extend file
formats, TTL/event semantics, and optional analysis through plugins. Open-source (Apache-2.0),
commercializable. Targets: Windows / macOS / Linux, mid-spec machines (8-core, 16 GB, SSD). Read
`BLUEPRINT.md` for phases, `ARCHITECTURE.md` for structure,
`DECISIONS.md` for settled choices. Do not re-litigate settled decisions; propose changes as a
DECISIONS.md entry in the PR description instead of silently diverging.

## Naming & casing — BINDING (never invent variants)

| Context | Exact form |
|---|---|
| Brand / UI / window title / docs prose / installer filenames | `AvialView` |
| PyPI package, import module, CLI command, repo dir, entry-point group, paths | `avialview` (all lowercase, one word, no hyphen/underscore) |
| Python identifiers derived from it | `avialview` (e.g. `from avialview.core import ...`) |
| Env vars / constants | `AVIALVIEW_*` |
| Session file extension | `.avv` |
| Sidecar cache dir | `<file>.avialcache/` |
| Installer artifacts | `AvialView-Setup.exe`, `AvialView.dmg`, `AvialView.AppImage` |
| Plugin packages (3rd party convention) | `avialview-plugin-<name>` on PyPI |

Use `AvialView` only for the displayed product name and `avialview` for technical identifiers.
Do not invent alternative spellings. A rename is never "improved" by an agent (D-018).

## Tech stack — FIXED

- Python 3.11–3.12 · PySide6 (never PyQt5/PyQt6 — license) · libmpv via `python-mpv` (PyPI name; import `mpv`) for ALL video
  playback (never QtMultimedia, never OpenCV for playback) · pyqtgraph for plots · numpy + polars
  for data · hatchling build · pytest / pytest-qt / pytest-benchmark / hypothesis.
- Dependency policy: no GPL/AGPL. Adding any dependency requires: license named in PR description,
  justification, and it must be pip-installable on all 3 OSes.

## Architecture rules (violations = rejected PR)

1. Single master clock in `core/timeline.py`. UI and sources NEVER keep independent time state;
   they subscribe to MasterClock. Time is float seconds, UTC epoch, with per-source
   `offset + drift_rate` mapping in TimeMap.
2. `core/` is headless: importing anything from `core/` must not import PySide6. Enforced by a test.
3. UI thread never blocks: no file IO, parsing, or decoding on it. Use worker threads / mpv's own
   threads. Any function that can take > 30 ms gets a worker + progress signal.
4. Plotting only via the decimation pyramid (`core/pyramid.py`). Never pass raw full-resolution
   arrays to pyqtgraph for datasets > 100 k samples.
5. All data sources go through the plugin ABCs in `core/source.py` (`TimeSeriesSource`,
   `VideoSource`). Built-in CSV/video support are plugins too. Do not special-case formats in UI code.
6. Playback: sync correctness beats frame completeness (drop frames, never drift). Paused/stepping:
   exact seeks only (`seek --exact` semantics).
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

ALL commands must be prefixed with `conda run -n avialview` when working inside the
`avialview` conda environment. Never run project commands (pytest, ruff, mypy, pip,
avialview) without this prefix — the system Python may differ from the env Python.

```bash
conda run -n avialview pip install -e .[dev]          # setup
conda run -n avialview python tools/make_fixtures.py  # generate test videos + signals (needs ffmpeg in PATH)
QT_QPA_PLATFORM=offscreen conda run -n avialview pytest -x -q   # tests
conda run -n avialview pytest --benchmark-only                   # perf budgets
conda run -n avialview avialview                                # run the app
conda run -n avialview avialview open tests/fixtures/sample_session/

# Type checking — run BOTH; strict mode applies only to core/
conda run -n avialview mypy src/avialview/core    # strict (enforced)
conda run -n avialview mypy src/avialview          # standard (ui/engine/loaders; pre-existing errors suppressed per pyproject.toml)

# Lint + format
conda run -n avialview ruff check --fix . && conda run -n avialview ruff format .
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
   (`sys.platform`) and provide fallbacks; mpv embedding differs per OS — keep that logic isolated
   in `ui/video_pane.py`.
7. When uncertain between two designs, choose the one that keeps `core/` simpler and put the
   complexity in the adapter/UI layer.
8. Update `DECISIONS.md` when you make a choice future agents must not reverse.
9. Consistency over preference: match existing naming/patterns in the module you touch, even if
   you'd choose differently. Multiple models rotate through this codebase; style entropy is a
   real failure mode. Do not "improve" working patterns without a DECISIONS.md entry.
10. Library APIs (mpv, pyqtgraph, polars) may differ from your training data — verify against
    the installed version's docs/signatures when behavior surprises you; don't force remembered APIs.
11. Test and scratch script locations: NEVER create temporary test scripts, scratch files, or ad-hoc tests in the repository root or inside `src/`. All formal tests must be placed in `tests/` and appropriately named (e.g., `test_*.py`). If you need temporary scratch files, use the designated artifact scratch folder or `/tmp/`, and clean them up afterward.

## Known traps (learned the hard way — do not rediscover)

- `.gitignore` ignores `*.spec` files by default. If you create or modify `packaging/avialview.spec`, you must force-add it or it will be silently excluded from commits and break CI.
- The GitHub Actions Windows runner does not have `ffmpeg` pre-installed (unlike Ubuntu/macOS). Any script that invokes `ffmpeg` (like `make_fixtures.py`) will fail with `FileNotFoundError` unless `choco install ffmpeg` is in the CI workflow. Chocolatey is used because it is preinstalled on that image; WinGet is a Windows *client* feature and is not available on the Server image. This is a build-time concern only — released installers bundle their own media runtime.
- Runner images are pinned (`ubuntu-24.04`, `macos-15`, `windows-2022`), not `*-latest`. A floating label already broke the release once, when an image bump renamed `fuse` to `libfuse2t64`. `tests/test_ci_platform_config.py` fails if a floating label reappears.
- Windows CI also needs an explicit, pinned libmpv DLL archive with SHA-256 verification and an
  `import mpv` probe. Do not assume a runner image provides a compatible DLL.
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
  `np.concatenate` differently, so `mypy src/avialview/core` passed locally and failed in CI on
  identical source. To reproduce CI exactly, build a venv pinned to the versions its log reports.
- Windows ships no IANA time zone database, so `zoneinfo` finds nothing there. `tzdata` is declared
  as a Windows-only dependency; without it every timezone-aware CSV import fails on Windows only.
- Hosted CI is headless on every OS: keep `QT_QPA_PLATFORM=offscreen` global and make
  `VideoPane` select `vo=null` there. Never force `qwindows` or native `wid` embedding merely to
  make a Windows job pass; interactive Windows and macOS use the Qt OpenGL render API, while Linux
  retains native `wid` embedding.

- mpv `wid` embedding must be set before mpv initializes video output on Linux. Windows and macOS
  use the documented render-API path; free their render context while the `QOpenGLWidget` is current.
- pyqtgraph `setDownsampling` is not enough at 180 M points — always go through our pyramid.
- QTimer drift: drive MasterClock from `time.monotonic()` deltas, never by accumulating timer intervals.
- polars `read_csv` infers types per-chunk; always pass explicit schema for the timestamp column.
- ffprobe start times lie for some machine-vision containers; treat metadata start time as a default,
  never as truth — the user offset always wins.
- 12-bit video: never assume hw decode; probe once at startup (`ui/diagnostics.py`) and surface it.
- Windows/macOS mpv embedding: use the Qt OpenGL render API; native `wid` is retained for Linux.
  Build and verify both the Windows and macOS render paths FIRST in Phase 2 (highest-risk integration).
- Seek settle: "seek command returned" ≠ "frame painted". Detect settle via mpv property
  observation (`seeking`=False + `time-pos` at target) for runtime coordination — never sleeps.
  Golden frame tests must additionally decode `screenshot-raw video` and match the fixture frame;
  retry only transient screenshot unavailability, never accept a stale rendered frame. Flaky golden
  tests get ignored, which defeats their purpose; keep them rock solid.
- Libmpv has an event thread that outlives a QWidget destructor. Shutdown ownership is explicit:
  `MainWindow.closeEvent()` → `VideoGrid.shutdown()` → `VideoPane.close()` → `mpv.terminate()`.
  Do not rely on garbage collection or Qt child destruction to join it.
- On Windows/macOS render-API panes, free the libmpv render context while the `QOpenGLWidget` is current
  before terminating mpv. Reversing that order aborts the process during app exit.
- PyInstaller evaluates `SPECPATH` as the spec directory, not the project root. Resolve the root
  from it, and stage media only from a non-empty, validated `AVIALVIEW_MEDIA_ROOT`; an unset value
  must never accidentally package the current working directory.
- Theme changes must not restyle sliders, splitters, scrollbars, plot interaction, or layout. A
  global QSS changes Qt's style engine and can alter those controls; use `QPalette` only for theme
  colours and verify seek/plot state survives a theme switch.
- Playback drift correction needs hysteresis: re-seek only after N consecutive off-target ticks,
  or late Qt timers cause re-seek/stutter cascades under UI load.
- Frame stepping: always mpv's actual frame timestamps; never `t += 1/fps` (breaks on VFR and
  dropped-frame footage).
- Pyramid must be NaN-aware (nanmin/nanmax) and gap-aware (gap_mask); never draw across gaps.
- Cache key includes a content-hash tail (ARCHITECTURE §5b); (path,size,mtime) alone is a lie.
- Timezone-naive timestamps: force an explicit user choice in the wizard; silent-UTC caused real
  1–2 h "corruption" reports in comparable tools.
- ffmpeg/mpv/QProcess: argument lists only, never shell strings (unicode/space paths on Windows).
- Locale bomb: Qt stomps LC_NUMERIC needed by libmpv → call
  `locale.setlocale(locale.LC_NUMERIC, 'C')` AFTER importing Qt, BEFORE first mpv.MPV().
  Symptom without it: float options/seeks silently misparsed in decimal-comma locales.
- Dependency name: `python-mpv` (PyPI) → `import mpv`. The PyPI package literally named `mpv`
  is a different project; never add it (D-017).
- NEVER `import mpv` at module top level (D-013): lazy import behind the diagnostics probe so a
  missing libmpv shows the guided dialog instead of a ctypes crash.
