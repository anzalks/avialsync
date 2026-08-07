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
`ui/video_timing.py::frame_index_at` as `searchsorted(frame_times, t + eps, "right") - 1`.

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
| 1 | Benchmark into `tests/benchmarks/test_seek_backends.py` | todo | `pytest tests/benchmarks/test_seek_backends.py --benchmark-only` |
| 2 | Frame-identity test into `tests/test_frame_identity.py` | todo | `pytest tests/test_frame_identity.py` |
| 3 | `engine/pyav_reader.py` — headless exact-frame reader | todo | `pytest tests/test_pyav_reader.py` |
| 4 | `ui/video_pane.py` — render decoded frames, delete mpv paths | todo | `pytest tests/test_video_pane*.py` |
| 5 | `engine/player.py` — delete drift correction | todo | `pytest tests/test_player*.py` |
| 6 | `loaders/video_standard.py` — ffprobe → PyAV | todo | `pytest tests/test_video_standard.py` |
| 7 | FFmpeg via pip for `proxy.py`, `export.py`, `demo.py` | todo | `avialsync demo` in a clean venv |
| 8 | Packaging + docs + DECISIONS/ARCHITECTURE/HANDOUT sweep | todo | `pip install .` in a clean venv, no OS deps |

### Step notes, traps, and resume conditions

**1 — Benchmark.** Must run both backends when libmpv is present and skip cleanly when it is not.
Guard the whole libmpv arm with `pytest.importorskip`. Note that CI ignores `tests/benchmarks`
(AGENTS.md); this is certified locally only.

**2 — Frame identity.** Encode the frame index as flat black/white column blocks (16 bits across
the width); large flat blocks survive H.264 intact, so no OCR is needed. Probe three positions per
frame: exact pts, mid-interval, and just before the next frame. Must cover CFR *and* VFR.
*Trap:* when writing fixtures with PyAV you must set **both** `stream.time_base` and
`stream.codec_context.time_base`, or `mux()` rejects every packet with `EINVAL` (errno 22).

**3 — Reader.** Owns: pts table, `t → index` resolution, seek/decode, LRU frame window.
Headless — no PySide6 import, so it is testable without Qt.
*Trap:* the forward-decode-vs-reseek crossover must be measured in **frames against GOP size**,
not in seconds. A fixed 2-second window at 230 fps walks ~460 frames forward where a re-seek costs
~125, and that alone pushed the jump case from 106 ms to 293 ms — over budget.
*Trap:* B-frame content demuxes in decode order; the pts table must be sorted into display order.
*Open question, must be measured before step 4:* building the pts table costs one full demux pass.
The fixture is 180 frames; real session files are ~13 800. Measure on `09-35-24` and, if it is slow,
cache the table in the existing `.avialcache/` sidecar rather than rebuilding per open.

**4 — VideoPane.** This deletes the per-OS split entirely: no `MpvRenderContext`, no `wid`
embedding, no `vo=null` headless special case. All three platforms take one path — decode to
`QImage`, blit. Keep the pane as the ownership boundary. The shutdown ordering dance
(`_release_mpv_render_context` before `terminate`) disappears with the render context.
*Resume note:* if this step is half-done, the pane will import `mpv` lazily somewhere; grep for
`import mpv` — the migration is complete only when that returns nothing outside of tests.

**5 — Player.** Delete `_drift_counts`, `_drift_estimates`, `_smoothed_residual`, the speed-nudge
grid, and the hysteresis cascade. They exist only to chase a clock the app does not own. Once the
app decodes, it *is* the clock: on each tick, ask every pane for the frame containing master `t`.
Sync becomes exact by construction rather than a tuned control loop. `_snap_to_frame_evidence` and
`estimated-vf-fps` observation go with them.
*Do not* delete the master clock itself or `TimeMap` — those are unrelated and still correct.

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

**Still to do, and deliberately deferred because their content depends on code that does not exist
yet.** Verify each with `grep -rn 'libmpv\|python-mpv'` before declaring the migration complete:

| File | What changes |
|---|---|
| `pyproject.toml` | drop `python-mpv`, add `av` + the ffmpeg wheel |
| `.github/workflows/ci.yml` | drop the libmpv DLL fetch + `import mpv` probe; drop `choco install ffmpeg` if the wheel covers fixtures |
| `.github/workflows/release.yml` | drop `fetch_media_libs.py` staging and the LGPL flavour assertion for libmpv |
| `packaging/fetch_media_libs.py` | delete |
| `packaging/probe_dialog_test.py` | delete — no missing-libmpv case remains |
| `packaging/avialsync.spec` | drop libmpv binaries. **`.gitignore` ignores `*.spec` — force-add it or the change is silently dropped and CI breaks** |
| `src/avialsync/runtime.py` | `_holds_libmpv`, `configure_media_runtime`, `AVIALSYNC_MEDIA_ROOT`, the WinGet fallback |
| `src/avialsync/ui/diagnostics.py` | delete `libmpv_install_guidance()` and its callers |
| `README.md` | install section |
| `docs/quickstart.md`, `docs/troubleshooting.md` | the "install libmpv" routes |
| `docs/licensing.md` | libmpv LGPL attribution → PyAV/FFmpeg attribution (see §5) |
| `docs/technical/architecture.md`, `docs/technical/performance.md`, `docs/technical/development.md` | mirror the root docs |
| `CONTRIBUTING.md:86` | the `LC_NUMERIC`-before-libmpv note — check whether it still applies to PyAV |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | drops the libmpv version field |

`graphify-out/` is generated output; regenerate rather than hand-edit.

---

## 5. Licensing — do not skip

AGENTS.md's "no GPL/AGPL dependency" line predates D-069 and is stale: the project *is*
AGPL-3.0-or-later. GPL dependencies are therefore licence-*compatible* with the open-source
distribution. They are **not** compatible with D-069's commercial dual-licence, which is the
reason the project relicensed at all.

Upstream PyAV wheels bundle libx264 and libx265 — i.e. a GPL-configured FFmpeg (confirmed by
inspecting `av-18.0.0`'s `.dylibs`). Shipping those forecloses commercial relicensing. D-015's
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
