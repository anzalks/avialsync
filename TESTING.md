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
  a stack trace, never a reason to raise the job timeout or silently skip the test.
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
  empty-lane suppression, native splitter handles, label-gutter coverage clipping, collapse/restore, and
  persisted view preference. Tests assert that a master-clock update repaints only the playhead and
  stays inside the ≤2 ms cursor path. Theme tests require readable tooltip colours, platform-accent
  retention in explicit appearances, native-control behavior in System mode, and a Light → System
  palette-toggle path.
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
  plots, transport, and sidebars remain legible after each switch.
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

Per PR: 3 OS × (ruff, mypy, unit+GUI offscreen, fast benchmarks ★). ffmpeg installed via
OS package managers/choco/brew. Nightly: big-fixture benchmarks + packaging smoke.
Release tag: full matrix + build wheel, sdist, PyInstaller bundles, attach to release, publish PyPI.
