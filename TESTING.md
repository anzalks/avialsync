# TESTING.md

## 1. Test layers

| Layer | Tool | Scope | Gate |
|---|---|---|---|
| Unit | pytest + hypothesis | `core/` math, TimeMap, pyramid, cache, session round-trip | 100 % branch on core |
| Golden sync | pytest + fixture videos | end-to-end time correctness (the product's soul) | must always pass |
| GUI | pytest-qt (offscreen) | widgets, shortcuts, dialogs, drag-drop, error paths | key flows covered |
| Performance | pytest-benchmark | budgets from BLUEPRINT table (★ rows) | > 20 % regression fails |
| Packaging smoke | CI artifact test | bundle launches, opens sample session headless | per release |

## 2. Fixtures — `tools/make_fixtures.py` (ground truth for everything)

Deterministic (seeded), regenerated in CI, gitignored. Produces:

- **Videos**: ffmpeg-generated, each frame shows a machine-readable frame index (drawn as a
  binary pixel strip, NOT OCR — read back with a 10-line numpy decoder). Variants:
  30 fps h264 8-bit short-GOP; 30 fps h265 10-bit long-GOP; 12-bit greyscale h265; 3-camera set
  with known, different start offsets (e.g. +0.000 s, +1.234 s, +7.500 s) and one with drift
  (+2 ppm) baked into metadata JSON alongside.
- **Time series**: 50 kHz × 16-bit, 4 channels, 10 min (and a 1 h "big" variant built only for
  benchmarks): sine sweeps + a step event at exactly known t on each channel; written as CSV
  (several timestamp formats: epoch s, epoch ns, ISO8601, relative) + expected-values JSON.
- **Sample session**: small everything, ships with releases as the demo dataset.

## 3. Golden sync tests (`tests/test_sync_golden.py`)

The non-negotiable invariant: *when the app says t, every pane shows t.*

1. Load fixture session (3 videos with known offsets + 1 CSV).
2. For 20 random master times t: exact-seek, wait settle, read the pixels each pane painted,
   decode the binary frame-strip → frame index → frame_time; assert
   |frame_time − TimeMap(t)| ≤ 1/fps for every camera.
3. Assert readout panel value == expected signal value at t (± interpolation tolerance).
4. Frame-step test: 10 steps forward = exactly 10 frame indices advanced, no skips/repeats.
5. Offset test: change offset by +0.5 s in UI → frame indices shift by exactly 15 frames @30fps.
6. Drift test: source with 2 ppm drift stays ≤ 1 frame error across the full fixture duration.

### 3a. TTL/event synchronization golden tests (D-026)

Current automated coverage proves chunk boundaries, offset/drift recovery, missing and spurious
pulses, ambiguity refusal, worker extraction, explicit UI acceptance, and session round-trip. The
following fixture coverage remains the release-level acceptance set:

1. Common periodic TTL clock with known offset and drift: accepted fit recovers both within the
   declared fixture tolerance across the whole recording.
2. Camera-frame TTLs plus a sensor event stream: pairings are correct despite a different nominal
   camera rate.
3. Sparse experimental pulses, missing pulses, and outliers: matching remains deterministic and
   reports the rejected/ambiguous evidence.
4. Ambiguous periodic sequences: automatic acceptance is unavailable; the user must choose a
   constraint or manual alignment.
5. Session round-trip: accepted mapping and provenance recreate the same `TimeMap`; raw event
   timestamps and source recordings are unchanged.

## 4. Performance benchmarks (`tests/benchmarks/`)

- `bench_pyramid.py`: build 180 M samples ≤ 2.5 s; query any window ≤ 5 ms.
- `bench_cursor.py`: playhead update ≤ 2 ms (offscreen).
- `bench_plot.py`: pan/zoom redraw ≤ 16 ms at every pyramid level.
- `bench_import.py`: 1 GB CSV → cache ≤ 60 s (marked slow; nightly, not per-PR).
- `bench_seek.py`: 3-camera parallel exact seek ≤ 250 ms (requires ffmpeg; runs where available).
- `test_bench_sync.py`: deterministic 10,000-event fit preview ≤250 ms locally (with the standard
  CI multiplier); covers the worker's matching hot path without UI or file I/O.
Store baselines with `--benchmark-autosave`; compare with `--benchmark-compare`.
The 2.5 s / 5 ms / 2 ms / 250 ms marks are measured without calibration with the local benchmark
command. GitHub Actions runs the representative three-camera, four-stream workload for correctness,
not speed: shared CI hardware is not a valid stand-in for the machines scientists use.

## 5. GUI test conventions

- `QT_QPA_PLATFORM=offscreen`; use `qtbot.waitSignal` — never `time.sleep`.
- `pytest-timeout` stops any individual test after 60 seconds in CI. A timeout is a bug report with
  a stack trace, never a reason to raise the job timeout or silently skip the test. **Run the suite
  with the CI flags** (`pytest --maxfail=1 -q --timeout=60 --timeout-method=thread
  --ignore=tests/benchmarks`) before pushing: without `--timeout`, a test that stalls simply passes
  slowly on a developer machine and fails only on a runner.
- **The suite writes no real settings or app data.** Thirteen places in `src/` construct
  `QSettings("AvialSync", "AvialSync")`, so an unsandboxed run edits the developer's own installed
  application — a run that exercised the appearance menu once left `theme/preference = light`
  behind and the next genuine launch came up light on a dark desktop (D-106). `conftest.py`
  redirects all settings storage to a temporary ini for the whole process, in `pytest_configure`
  rather than a fixture, because collection imports test modules and an import is early enough to
  construct a `QSettings`. `isolated_recovery_dir` does the same for recovery snapshots. Do not
  rely on per-module `monkeypatch` of `QSettings`: it only ever covers the module somebody
  remembered.
- A test that mutates process-global Qt state — the application palette, font, or a module-level
  helper — restores it. What it leaves behind is inherited by every widget built after it, so the
  cost lands on whichever test runs next.
- Every bug fix adds a regression test reproducing the bug first.
- Error-path tests: corrupt CSV, missing file at session load, unsupported codec → assert the
  actionable dialog text appears and app stays alive.
- Headless-core guard test: `import avialsync.core` in a subprocess with PySide6 uninstalled
  (or import-hook blocked) must succeed.
- Transport layout tests verify the seek-row placement of playhead, A/B, end-time, and labelled Speed
  controls; Flag/Snapshot/Fullscreen/Reset header actions with explanatory tooltips; non-blocking
  transient/busy status; and A/B pins after resize.
  Timeline Evidence tests cover source coverage, accepted TTL events, gaps, annotations, and
  click-to-seek; they require named conditional lanes, accessible names, event hover/focus details,
  empty-lane suppression, splitter handles, label-gutter coverage clipping, collapse/restore, and
  persisted view preference. Tests assert that a master-clock update repaints only the playhead and
  stays inside the ≤2 ms cursor path. Theme tests require readable tooltip colours, platform-accent
  retention in explicit appearances, native-control behavior in System mode, and a Light → System
  palette-toggle path.
  `test_theme_switching.py` covers the surfaces a palette change does *not* reach on its own
  (D-106): the pyqtgraph canvas, axis lines, tick numbers and axis titles repainting for a new
  palette; the playhead, traces and coverage wash being re-penned; the 3D pose view repainting and
  not forcing a white canvas; emphasised text still following the palette; a pane boundary being
  marked along its whole length with the splitter's metrics unchanged; and Dark→System and
  Light→System actually handing the palette back to the platform. Every assertion is a *property* —
  contrast against the surface, a change across a switch, a relationship between two marks — never
  a hex literal, which would need editing whenever the palette moves and would prove nothing about
  legibility. Each regression test was checked against a reintroduced bug.
  Video timing tests verify that VFR OSD rates come from adjacent decoded timestamps rather than an
  average frame rate, while CFR OSD rates remain stable; overview tests also cover header resizing
  for dense evidence. Theme tests cover persisted system-relative font scaling.

### 5a. Plot UX refinement gates (P4.6 / D-044)

Run these as slice-level regression gates; do not wait until the entire visual refinement lands:

| Area | Required automated evidence |
|---|---|
| Compatibility | Characterize every item in `PLOT_UX_PLAN.md` §2 before moving controls. Assert the same QAction/signal result after relocation and that close still changes the sidebar checkbox. |
| Modes | Review paints the complete selected page; Sweep retains the previous pass only until overwrite; Scope preserves D-042 blank/restart; all three map cursor, gaps, measures, annotations, and coverage to identical absolute times. |
| Shared X state | Add/remove/hide, resize, theme change, save/load, slider, typed value, shortcuts, and navigator changes leave every visible row X-linked with one duration and page. No per-row horizontal scrollbar exists. |
| Time span | Unit changes preserve seconds exactly within display precision; the continuous mapping is monotonic at ms/s/min/h scales; drag updates are coalesced and release commits the newest value. |
| Navigator | Data Streams retains named/conditional evidence and detail. Viewport drag preserves playhead phase and emits coalesced approximate seeks plus one exact release; its width follows the shared duration; pixel mapping remains correct after widget resize. |
| Y state | Fit once freezes, Auto is explicit, Manual range/offset persists, ordinary playback does not jump a frozen range, Fit all is global, and clipping is surfaced. |
| Focus/accessibility | Enter leaves valid time/time-span editors; Space then plays; Tab reaches plot controls, channel close, navigator, transport buttons/sliders/combos; all D-022 shortcuts still emit their existing commands. |
| Appearance | Only the bottom row labels X; channel gutters expose name/unit/range; min/max is one envelope; semantic information is not colour-only; theme switches preserve all plot/navigation state and add no application QSS. |
| Hot path | Count pyramid queries and graphics objects through ticks, wrap, resize storms, dense evidence, hide/show, and mode changes. Ticks do not query; retained sweep data is at most current+previous page; items/queues remain bounded. |
| Performance | Populated cursor ≤2 ms, plot interaction/paint ≤16 ms, callbacks <30 ms, and representative 4/32/128-channel runs record p50/p95/p99 plus maximum Qt-heartbeat delay. |

Any playback, seek, cursor-time, page-selection, or overlay-time change also runs
`tests/test_sync_golden.py` untouched. A screenshot comparison may supplement semantic widget/paint
tests but cannot replace time, signal, accessibility, and performance assertions.

## 6. Manual smoke checklist (human, end of each phase, on YOUR real field data)

- [ ] Open real 3-camera folder + real 50 kHz CSVs; import wizard handles your timestamp format.
- [ ] Check System, Dark, and Light in View → Theme: System retains the OS accent/font; tooltips,
  plots, transport, and sidebars remain legible after each switch. Switch *back* to System from
  each explicit appearance and confirm the window returns to the desktop's — that path had a real
  bug (D-106) and a fresh launch into System is not evidence for it. Confirm the plot background,
  tick numbers, axis titles and playhead move with each switch, that bold headings do not stay
  dark on a dark surface, and that every pane boundary is visible along its whole length.
- [ ] Scrub feels ≤ ~200 ms; playback 1× smooth ≥ 60 s; 4× speed doesn't desync.
- [ ] Align offsets against a real physical event visible in both video and data.
- [ ] With Timeline Evidence expanded, identify each populated lane without consulting documentation;
  hover a TTL/gap/annotation event to verify its type, source, and exact master time. Collapse,
  resize, restart, and confirm the view preference restores without changing session data.
- [ ] Frame-step through the event; annotate it; export region; reopen session — everything restored.
- [ ] Kill app mid-import; relaunch; cache not corrupted.
- [ ] Try it on the weakest machine you own; note anything sluggish as an issue.
- [ ] P4.6: pause/scrub shows a complete Review page; Sweep overwrites behind a narrow eraser gap;
  Scope still clears/restarts; switching among them never changes master time or alignment.
- [ ] P4.6: change the same time span through typing, units, slider, zoom keys, and reset; move the
  page through the Data Streams viewport; all rows and the navigator agree, with no per-row
  horizontal scroll.
- [ ] P4.6: verify stable Y ranges, units/clipping, channel close-to-checkbox, keyboard Tab/Space,
  dense annotations/gaps, theme switches, and 128-channel play/resize without a visible freeze.

## 7. Edge-case test matrix (each row = at least one automated test + a fixture variant)

### Time & timestamps
| Case | Expected behavior |
|---|---|
| Timezone-naive CSV | Wizard forces explicit tz choice; default UTC with visible warning |
| Camera UTC vs logger local (1–2 h apart) | Loads fine; offsets panel shows the gap; docs FAQ entry |
| DST-ambiguous local timestamp | Loader asks; never resolves silently |
| Time-of-day-only column | Anchor-date config in wizard; midnight-spanning recording rolls over correctly |
| Non-monotonic rows (buffer flush) | Sorted with notice, or NonMonotonicTimeError with row number |
| Clock resync jump backwards mid-file | Error + offered auto-split into segments |
| Duplicate timestamps | Keep-last, count reported |

### Video
| Case | Expected behavior |
|---|---|
| VFR footage | Frame step uses actual frame timestamps; nominal-fps badge shown |
| Dropped frames (container 30fps, frames missing) | No cumulative drift; golden sync stays ≤1 frame using frame_times() |
| No metadata start time | Source loads at offset 0; alignment workflow prompted; no crash |
| Rotation metadata / anamorphic | Displayed correctly (test asserts orientation) |
| Mixed fps cameras (25/29.97/30) | Per-camera stepping correct; master timeline unaffected |
| Camera starts/ends mid-timeline | Dimmed "no footage" placeholder, never frozen last frame |
| Image sequence folder (img_%06d.tif) | needs_conversion path: proxy generated with progress, then plays |
| Unplayable/corrupt file | Actionable dialog naming the file + codec; app alive |

### Data content
| Case | Expected behavior |
|---|---|
| NaN/inf in channel | Pyramid skips NaN (nanmin/nanmax); plot breaks line; readout shows NaN |
| Sentinel values (-9999) | Only mapped to NaN via explicit wizard option; never guessed |
| Gap (logger stopped 10 min) | gap_mask set at 10× median dt threshold; NO line across gap |
| European CSV (";" + decimal comma), BOM, units row | Wizard preview detects/suggests; parses correctly |
| Multi-part split recording | Loader presents as one source; boundaries seamless in pyramid |
| 32+ channels | Tree panel + grouping; no 32-row explosion |

### Synchronization evidence (planned, D-026)
| Case | Expected behavior |
|---|---|
| Common periodic TTL clock | Deterministic pairing and affine offset/drift fit within fixture tolerance |
| Camera frame trigger + sensor TTL | Correct frame/event alignment despite differing sample and frame rates |
| Sparse pulses with a missing edge | Missing evidence recorded; valid remaining pairs fit without silent interpolation |
| Repeated/ambiguous pulse pattern | No automatic acceptance; wizard explains ambiguity and offers manual constraint |
| Outlier or spurious edge | Robust fit rejects it and records residual/outlier evidence |
| Plugin native event stream | Raw timestamps are preserved; no acquisition driver or format special case in UI |

### Sessions & environment
| Case | Expected behavior |
|---|---|
| Session file paths moved | Relink dialog; partial load with placeholders |
| Duplicate filenames from different dirs | Grid labels disambiguated with parent dir |
| Unicode/space paths → ffmpeg | Arg-list invocation; test on Windows runner |
| Stale cache after Excel edit / cross-drive copy | Content-hash tail invalidates; rebuild triggered |
| Kill app mid-import | Atomic cache writes; relaunch clean |
| 4 h video + 10 min data | Timeline = union; coverage spans shaded in overview |

Fixture additions to `make_fixtures.py`: VFR video, dropped-frame video (delete every 97th frame,
re-mux), no-metadata video, image-sequence folder, CSVs for every timestamp pathology above,
NaN/gap/sentinel signal variants, a 2-part split recording, and a euro-dialect CSV. Each fixture
ships with an expected-values JSON.

## 8. CI matrix (see .github/workflows/ci.yml)

**No benchmark ever runs on CI.** This section used to say "fast benchmarks ★" ran per PR; they did
not, and they must not. `--ignore=tests/benchmarks` has been on the test command in both workflows,
and `tests/test_ci_platform_config.py` now pins it from both ends — the flag's presence, and that no
`test_bench_*.py` exists outside `tests/benchmarks` where it would be collected and timed anyway. A
timing number from a shared runner sharing a core with three other jobs is noise, and the benchmark
suite is the slowest thing in the tree. Budgets are measured locally against BLUEPRINT.md's table
with `pytest --benchmark-only`, as §4 describes. CI answers "is it correct"; your own machine
answers "is it fast".

**Per push, on every branch — four test jobs, not six.** Three OS × two Python versions is six
combinations; Python 3.11 on macOS and Windows is excluded, so every operating system and both
interpreters are still covered while a push costs four jobs. A pure-Python version difference does
not depend on the OS, and an OS difference is caught on 3.12 where macOS and Windows still run.
`test_ci_platform_config.py` fails if a later edit breaks that union rather than merely the count.
Each job runs ruff, mypy (both passes, in the separate lint job), and the unit + GUI suite
offscreen. The fixture determinism check runs once, on Linux, matching what release.yml already
did. ffmpeg is installed via apt/brew/choco — it encodes the fixtures; nothing decodes with it
(D-075). The three job groups start together rather than queueing behind lint.

Release tag: the **full** six-job matrix with `fail-fast: false`, plus wheel, sdist, PyInstaller
bundles, attach to release, publish PyPI. Thoroughness beats latency on the run that ships.

## 9. Conformance gates (source-scanning tests)

Rules that are cheap to state and easy to erode are enforced by tests that read `src/` rather than
by review. Each exists because the rule had already been broken and nothing had said so — the
`QMessageBox` ban had been a written Phase 7 exit criterion for the whole phase while drifting to
nineteen call sites (D-107).

| Test | Rule |
|---|---|
| `test_feedback_surface.py::test_no_modal_progress_dialog_remains` | `QProgressDialog` is banned from `src/` (D-091). |
| `test_feedback_surface.py::test_no_message_box_outside_the_feedback_package` | `QMessageBox` only inside `ui/feedback/` (D-107). |
| `test_feedback_surface.py::test_every_background_job_is_registered` | No raw `QThread` outside the three named exceptions; use `_run_job` (D-107). |
| `test_law1_conformance.py` | No modal gate in front of Open, drop, Open Recent, or quit (D-088/D-089). |
| `test_overlay_registry.py` | The registry matches the drawn inventory (D-090). |
| `test_headless_core.py` | `core/` imports no PySide6 (rule 2). |
| `test_accessibility_i18n.py::test_every_extractable_literal_is_translatable` | 100 % of the literals `lupdate` can extract are wrapped (D-107). |
| `test_accessibility_i18n.py::test_the_shipped_dialogs_name_their_controls` | Every dialog's controls carry accessible names, checked after `show()` (D-107). |
| `test_ci_platform_config.py::test_no_benchmark_runs_on_ci` | Benchmarks stay in `tests/benchmarks`, which CI ignores. |
| `test_ci_platform_config.py` (platform rows) | Pinned runner images, no floating labels, no video library installed (D-075/D-086). |

When one of these fails, fix the code rather than the list. Where an exception is genuinely correct
— a decode thread is not a job — add it to the test's own exception table **with its reason**, so
the next reader can judge it instead of inheriting it.
