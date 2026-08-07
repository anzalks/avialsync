# MIGRATION_PYAV.md — libmpv → PyAV, and a pip-only install

**Status:** in progress · branch `shift_from_libmpv_to_pyav` · opened 2026-08-07
**Authority:** D-075 in DECISIONS.md. This file is the *execution* record; D-075 is the decision.

Read this file before touching video code on this branch. It exists so that an agent arriving
mid-migration — after a failure, a context loss, or a handoff — can determine what is done, what
is half-done, and what to do next, without re-deriving the analysis.

---

## 1. Goal, in one sentence

`pip install avialsync` must produce a working application on Windows, macOS, and Linux with **no
OS-level installation step of any kind**, by replacing libmpv with PyAV and shipping FFmpeg through
pip.

### What the user must install today (the thing being deleted)

| Platform | Today | After |
|---|---|---|
| Windows | libmpv DLL from a SourceForge archive + `winget install` FFmpeg + `AVIALSYNC_MEDIA_ROOT` | nothing |
| macOS | `brew install ffmpeg mpv` | nothing |
| Linux | `apt install ffmpeg libmpv2` (or distro equivalent) | nothing |

### The one caveat that survives — state it, never hide it

On Linux, PySide6 requires system graphics libraries (`libgl1`, `libxkbcommon`, and the usual xcb
set). Every normal Linux desktop already has them; bare containers and minimal server images do
not. This is Qt's floor and **no packaging decision removes it** — it has nothing to do with mpv,
and it was equally true before this migration. It must be documented in `docs/install.md` rather
than quietly omitted. Windows and macOS have no equivalent caveat.

---

## 2. Why — the measured case

Benchmarked on macOS arm64, three 1440×1080 files, 3-cam parallel fanout, against the
BLUEPRINT.md budget of ≤ 250 ms for "scrub response, 3 cams, exact seek, release-of-slider".
Long-GOP (250) transcodes of real session footage, which is the *worst* case; the lab's own
`09-35-24` footage is all-intra and roughly six times faster still.

| Interaction | libmpv (measured) | PyAV + frame cache (measured) |
|---|---|---|
| Jump to a new time | 330 ms — over budget | **106 ms** |
| Drag the slider | 338 ms — over budget | **8 ms** |
| Re-scrub a covered span | 333 ms — over budget | **7 ms** |

libmpv costs ~330 ms whether it jumps, drags, or revisits ground it just covered. That flatness is
the tell: the cost is the exact-seek settle round-trip through the `seeking` property observer, not
decode work. mpv cannot get faster on a re-scrub because it holds no memory of where it just was.
This is a player being asked to be a scrubber.

Supporting measurements, same machine:

- Sustained decode, 3 cams concurrent: **558 fps each, 1679 fps aggregate**, including RGB
  conversion, against ~180 fps needed to feed three panes at display rate. Roughly 9× headroom.
  PyAV releases the GIL, so panes genuinely parallelise across cores. **Hardware decode is not
  required** to meet the budget.
- Frame → RGB conversion at 1440×1080: 0.51 ms (`to_ndarray`), 0.28 ms (`reformat`). Negligible;
  ~1.5 ms across three panes.

Reproduce with `tests/benchmarks/test_seek_backends.py` (step 1 below).

---

## 3. The invariant that outranks everything

**The frame displayed for master time `t` is the frame whose presentation interval contains `t` —
the last frame with `pts <= t`.**

This is not a new rule. It is already the app's rule, implemented in
`core/video_timing.py::frame_index_at` as `searchsorted(frame_times, t + eps, "right") - 1`.
(It lived in `ui/video_timing.py` before step 3 moved it, so the headless decoder could share it
without `engine/` importing `ui/`; the UI path re-exports it and no caller moved.)

Any reader that returns *the first frame with `pts >= t`* is **wrong on every scrub position
between two frames** — verified at 179 of 179 mid-interval probes, on both CFR and VFR footage.
At 30 fps that is a 33 ms misattribution, enough to pin a behavioural event to the wrong frame.
This is the single most dangerous mistake available in this migration, and it is easy to make: the
first draft of the spike made it.

Two further rules follow from it:

- **Cache by frame index, never by float time.** Resolve `t → index` through `frame_index_at`
  *first*, then use the integer index as the cache key. A cache keyed on a floating-point
  timestamp can collide or miss between two nearby scrub positions.
- **Selection and naming must share one authority.** Today libmpv independently decides which
  frame to display while the ffprobe pts table decides which frame number the readout *names* —
  hence `_frame_tolerance`, `_maybe_finish_seek`, and the `_PTS_EPSILON_S` comment recording a real
  bug where the readout named the wrong frame. After migration the same `frame_index_at` call both
  selects and names, so the two cannot disagree. **Do not reintroduce a second authority.**

`tests/test_frame_identity.py` (step 2) enforces all of this with footage whose every frame encodes
its own index in its pixels, so identity is read back from the decoded image rather than inferred.

---

## 4. Steps — update the status column as you go

Status values: `todo` · `wip` · `done` · `blocked`. An agent resuming work should find the first
row that is not `done`, and read its "resume note" before doing anything.

| # | Step | Status | Verify with |
|---|---|---|---|
| 1 | Benchmark into `tests/benchmarks/test_seek_backends.py` | done | `pytest tests/benchmarks/test_seek_backends.py --benchmark-only` |
| 2 | Frame-identity test into `tests/test_frame_identity.py` | done | `pytest tests/test_frame_identity.py` |
| 3 | `engine/pyav_reader.py` — headless exact-frame reader | done | `pytest tests/test_pyav_reader.py` |
| 4 | `ui/video_pane.py` — render decoded frames, delete mpv paths | done | `pytest tests/test_video_pane*.py` |
| 5 | `engine/player.py` — delete drift correction | done | `pytest tests/test_playback_smoothness.py tests/test_scrubbing.py` |
| 6 | `loaders/video_standard.py` — ffprobe → PyAV | todo | `pytest tests/test_video_standard.py` |
| 7 | FFmpeg via pip for `proxy.py`, `export.py`, `demo.py` | todo | `avialsync demo` in a clean venv |
| 8 | Packaging + docs + DECISIONS/ARCHITECTURE/HANDOUT sweep | mostly done — step 7 tail remains | `pip install .` in a clean venv, no OS deps |

### Step notes, traps, and resume conditions

**1 — Benchmark. DONE 2026-08-07.** Fixtures are three 1440×1080 GOP-250 files written by
`tests/util_pyav_fixtures.py`; the PyAV arm drives the *product* reader, never a spike copy.
Re-measured on this machine, 3-cam parallel fanout including RGB conversion:

| Interaction | Budget | Measured (mean) |
|---|---|---|
| Jump to a new time | 250 ms | **116.6 ms** |
| Drag the slider | 50 ms | **3.3 ms** |
| Re-scrub a covered span | 50 ms | **1.0 ms** |

Each case uses `benchmark.pedantic(setup=…)` so the round's *setup* — clearing the frame window,
or pre-warming the covered span — is excluded from the timing. Without that, the jump case
re-measures the cache instead of a seek and reads as 1 ms.
*The libmpv arm is opt-in:* `AVIALSYNC_BENCH_LIBMPV=1`. It is off by default because it adds ~45 s
to re-measure a backend being deleted, and every `wait_*` carries a timeout — an observation that
never arrives would otherwise hang the run with no output. It also skips wherever libmpv is
absent, which includes the `avialsync` conda env (§7). CI ignores `tests/benchmarks` (AGENTS.md);
this is certified locally only.

**2 — Frame identity. DONE 2026-08-07.** Reuses the existing `tests/util_framestrip.py` encoder
(32 bits × 16 px blocks) rather than a second one. 180 frames × 3 probes × CFR and VFR = 1 080
probes, all passing. The third probe sits at 99 % of the interval, which is where an
`at-or-after` reader fails while still looking correct on the exact-pts probe;
`test_a_first_frame_at_or_after_reader_would_fail_the_mid_interval_probes` asserts that the wrong
rule really is wrong at all 179 mid-interval positions, so the fixture cannot quietly stop
exercising the distinction.
*Trap confirmed:* both `stream.time_base` and `stream.codec_context.time_base` are required.
*Trap found:* `preset=ultrafast` is the one x264 preset that disables B-frames, which would make
these fixtures unable to catch a pts table left in decode order. The writers use `veryfast`
(2.5× faster than the default `medium`, B-frames kept) and
`test_the_fixture_really_demuxes_out_of_order` fails if that ever regresses.

**3 — Reader. DONE 2026-08-07.** `PyAVReader` owns the pts table, `t → index`, seek/decode, and an
index-keyed LRU window (24 frames, held in native pix_fmt at ~2.3 MB rather than RGB at 4.6 MB).
Frame selection itself moved to **`core/video_timing.py`** — `engine/` may not import `ui/`
(ARCHITECTURE §1), and copying `frame_index_at` would have recreated exactly the two-authority
split D-075 exists to remove. `ui/video_timing.py` re-exports it, so no caller moved.
*Trap handled without a tuned constant:* the crossover compares `target - decoded` against
`target - keyframe + 1`, both in **frames**. Ties go to the walk, which is the GOP boundary case —
identical decode work, one pointless seek avoided. Nothing in this file may be expressed in seconds.
*Trap handled:* the pts table is sorted into display order.
*Open question — ANSWERED, no sidecar needed.* Building the table on the real 716 MB / 13 844-frame
`09-35-24/FaceCam.mp4` costs **225 ms**, once at open, against a 3 s session-open budget; three
cameras open in parallel. Caching it in `.avialcache/` would add an invalidation surface to save
7 % of a budget. Do not add one without re-measuring. (That footage is also all-intra — mean GOP
1.0 — so its cold mid-file jump is 8 ms, confirming §2's "six times faster" note.)

**4 — VideoPane. DONE 2026-08-07.** Landed *together with step 5*: they cannot be separated,
because the pane's new contract is exactly what makes the player's drift loop dead code. An
intermediate commit would have left the app in a state where the pane decodes but the player still
tries to steer it.

The pane owns a `QThread` running a `DecodeWorker` around one `PyAVReader`. Requests coalesce on
the newest wanted time, so a 60 Hz tick driving a decoder slower than one tick never queues a
backlog — it skips. Frames are blitted as a `QImage` wrapping the decoded array; `VideoSurface`
holds that array because `QImage` does not copy it, and dropping it would fault during a repaint
rather than raise.
*The per-OS split is gone*, as planned: no `MpvRenderContext`, no `wid`, no `vo=null` headless
case. `tests/test_ci_platform_config.py` now parses `video_pane.py` and fails if a `sys.platform`
read, an `mpv` import, or a `QOpenGLWidget` import reappears — checked against the AST rather than
the text, so the rule can be described in a docstring without tripping the guard enforcing it.
*`grep -rn "import mpv" src/` returns nothing.*
*Also removed:* `probe_libmpv`, `libmpv_install_guidance`, and the macOS dyld shim in
`ui/diagnostics.py` — all dead the moment the pane stopped needing a library to be present.
`probe_hwdec` now reports what FFmpeg was built against, and is explicitly informational: software
decode already meets every budget.
*Trap found, not predicted:* `av` was left as a deferred import out of habit from D-013. That only
moves its 94 ms first-import onto whichever thread reaches it first — a decode thread or the
diagnostics thread, which can contend on the import lock. It is a module-scope import now; the
D-013 reasoning does not survive a decoder that ships inside its own wheel.

**5 — Player. DONE 2026-08-07.** `_drift_counts`, `_drift_estimates`, `_smoothed_residual`,
`_set_correction`, the speed-nudge grid, and the hysteresis cascade are gone, along with
`set_rate`/`set_sync_correction`/`set_mapping_rate_at`/`frame_interval_at_master` on the pane and
`_maybe_finish_seek`/`_frame_tolerance`/`_observe_seeking` on the timing mixin. Playback is now a
seek per tick: `_on_tick` asks every active pane for the frame containing master `t`.
`tests/test_playback_smoothness.py` asserts the replacement properties — that lateness is *bounded
and not growing* over twenty seconds, and that the player never asks a pane for a rate at all (the
stand-in raises on `set_rate`, `sync_correction`, and friends, so reintroducing rate control fails
loudly).
*Also gone:* the mpv frame-step fallback in `Player.step_frame`. An opened pane always has its
timestamp table, so `frame_step_master_target` is the only path; a missing target now means nothing
is open, and stepping does nothing rather than inventing a `1/fps` boundary (D-007).

**⚠ Deviation from this plan — `_snap_to_frame_evidence` was KEPT.** Step 5 listed it for deletion
alongside the drift machinery. It does not belong there: it snaps the *master clock* onto an
accepted per-frame trigger mapping (D-026 evidence-based sync), so an annotation records the instant
a frame was exposed rather than wherever the scrubber stopped. It never touched libmpv, and deleting
it would have changed annotation timestamps for no migration-related reason —
`test_exact_scrub_snaps_master_clock_to_accepted_frame_trigger` was the signal. Removing it is a
separate decision for the maintainer, not a side effect of swapping decoders.

**⚠ A golden-sync expectation was corrected, and it is worth knowing why.**
`tests/test_sync_golden.py::_fixture_frame_time(n)` returned `(n - 0.25)/30` while the test expected
frame `n` back — but that instant lies inside frame `n-1`'s interval. That pair can only both be
true against a reader returning the first frame with `pts >= t`, i.e. libmpv was rounding *up* and
the golden test had been written around it. This is the 33 ms misattribution §3 describes, sitting
inside the test suite that was supposed to catch it. The *probe* was corrected to `(n + 0.25)/30`,
not the expectation, so the test now asserts what it always claimed to. Capture also moved from
`screenshot-raw video` to the pane's own painted buffer, which removed the retry loop that existed
because a raw snapshot could transiently return the pre-seek frame — and with it the
`skipif(win32)` whose stated reason no longer exists. **That skip removal is unverified on Windows
CI.**

**6 — Probing.** `require_ffprobe()` disappears from `video_standard.py`. Extended metadata
(D-020) and the pts table both come from PyAV. Keep `VideoMetadata` shape unchanged so the
Inspection Layer and Source Properties do not move.

**7 — FFmpeg via pip.** Three surviving CLI call sites: `engine/proxy.py`, `engine/export.py`,
`demo.py`. Add a bundled-ffmpeg wheel to `dependencies` and make `find_media_executable` fall back
to it, keeping the existing search order so a user-supplied FFmpeg still wins.
*Check before adopting any candidate wheel:* it must ship **both** `ffmpeg` and `ffprobe`, carry
binaries **inside the wheel** (not download on first use — that reintroduces a runtime network
dependency, and D-014 already rejected download-on-first-run), and cover all three platforms.
`imageio-ffmpeg` ships ffmpeg only. `static-ffmpeg` downloads on first use. Verify the license
configuration of whatever is chosen and record it in D-075 — see the licensing note below.
*Trap (existing, still applies):* use `-fps_mode`, never `-vsync`.

**8 — Sweep.** Done ahead of the code (2026-08-07), because these files instruct future agents and
a stale instruction is worse than a missing one: `AGENTS.md`, `DECISIONS.md` (D-075 plus supersede
markers on D-002/D-013/D-015/D-017), `ARCHITECTURE.md`, `HANDOUT.md`, `BLUEPRINT.md`, `PROMPTS.md`,
`docs/install.md`.

**The libmpv sweep is DONE (2026-08-07).** `grep -rniI "mpv" src/ packaging/ .github/ pyproject.toml`
returns only prose explaining what changed and why. What was done, and the three places the plan
above was wrong:

| File | Outcome |
|---|---|
| `pyproject.toml` | `python-mpv` → `av>=12`; mypy override follows |
| `.github/workflows/ci.yml` | libmpv apt/brew/DLL-fetch/SHA-pin/`import mpv` probe all gone; probes `import av` instead. `ffmpeg` stays — it encodes the fixtures |
| `.github/workflows/release.yml` | same, ×2 (quality and bundling jobs); staging sources drop the mpv prefixes |
| `packaging/fetch_media_libs.py` | **KEPT, not deleted** — see below |
| `packaging/probe_dialog_test.py` | deleted (was a two-line `TODO` stub) |
| `packaging/avialsync.spec` | hidden import `mpv` → `av`. Force-added past `.gitignore`'s `*.spec` |
| `packaging/conda/meta.yaml` | `python-mpv` → `av`; `mpv` dropped from run deps, `ffmpeg` kept |
| `src/avialsync/runtime.py` | `_holds_libmpv`, `configure_media_runtime`, and the DLL-directory globals deleted; FFmpeg discovery kept |
| `src/avialsync/ui/diagnostics.py` | `probe_libmpv`, `libmpv_install_guidance`, and the macOS dyld shim deleted; `probe_hwdec` reports what FFmpeg was built against |
| `README.md` | install section rewritten; the tool-comparison table removed |
| `docs/` | quickstart, troubleshooting, formats, plugin-guide, licensing, and all three technical pages |
| `AGENTS.md`, `HANDOUT.md`, `BLUEPRINT.md`, `ARCHITECTURE.md`, `DECISIONS.md` | obsolete traps deleted, replaced with the ones that now apply; D-011/D-031/D-032/D-038/D-039 marked superseded or amended |
| `CONTRIBUTING.md`, `TESTING.md`, `.github/ISSUE_TEMPLATE/bug_report.yml` | swept |

**Three corrections to the plan above, made because following it literally would have broken
something:**

1. **`packaging/fetch_media_libs.py` was kept.** It stages the FFmpeg *command line* into
   installers, not just libmpv, and proxy/export/demo still shell out to that. Deleting it now
   would ship installers with no FFmpeg. Its libmpv half is stripped; delete the file at step 7.
2. **`AVIALSYNC_MEDIA_ROOT` and the WinGet fallback were kept** in `runtime.py`, for the same
   reason: they locate *FFmpeg*, not a video library. Only the libmpv-specific discovery is gone.
3. **`src/avialsync/__main__.py` keeps its `LC_NUMERIC` call.** The locale bomb was libmpv's option
   parser and no longer applies; the call is retained as cheap process-wide hygiene with a comment
   saying exactly that, rather than removed on the assumption nothing else parses floats.

**Also worth knowing:** `tests/conftest.py` still re-arms faulthandler with `all_threads=False` on
Windows. Its trigger — libmpv raising SEH exceptions on its own threads — is gone, so it is now
insurance rather than a fix (HANDOUT.md trap 30). Removing it is safe to try once Windows CI has
been quiet for a while.

`graphify-out/` is generated output; regenerate rather than hand-edit.

---

## 5. Licensing — do not skip

AGENTS.md's "no GPL/AGPL dependency" line predates D-069 and is stale: the project *is*
AGPL-3.0-or-later. GPL dependencies are therefore licence-*compatible* with the open-source
distribution. They are **not** compatible with D-069's commercial dual-licence, which is the
reason the project relicensed at all.

**Confirmed on this machine (2026-08-07):** `av` 18.0.0's bundled `.dylibs` include
`libx264.165.dylib` and `libx265.216.dylib`, and `av.codec.Codec("libx264", "w")` resolves — so the
shipped FFmpeg is GPL-configured in fact, not merely in principle. Shipping those forecloses commercial relicensing. D-015's
LGPL-only preference therefore still governs: prefer an LGPL-configured build, and if one is not
available off the shelf, that is a decision for the maintainer to take explicitly and record in
D-075 — not something to settle silently inside a packaging commit.

---

## 6. Rollback

Nothing outside this branch has changed. `git checkout feat/openephys-session-plugin` restores the
libmpv application whole. Steps 1 and 2 (the tests) are worth keeping regardless of the outcome:
they encode the performance budget and the frame-exactness invariant, and both are backend-neutral.

## 7. Environment notes for whoever picks this up

- Every command goes through `conda run -n avialsync`. No exceptions.
- **libmpv is not installed in the `avialsync` conda env.** Video does not work there today, before
  any of this migration. Homebrew's copy at `/opt/homebrew/lib/libmpv.dylib` is invisible to
  conda's Python via `ctypes.util.find_library`, and `conda run` strips `DYLD_*` (SIP). The
  benchmark's libmpv arm patches `find_library` to a known path — a harness concern only, never a
  pattern for product code.
- Test footage: `examples/data/` holds small CFR and VFR fixtures; `09-35-24/` holds three real
  1440×1080 230 fps session files (~800 MB each, all-intra). Per AGENTS.md rule 5, tests must use
  generated fixtures — never `09-35-24/`, which is private field data.
