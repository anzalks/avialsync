# RECOVERY_PROMPT.md — single execution prompt for the post-refactor repair

**How to use this file.** Give your model exactly this instruction:

> Read `RECOVERY_PROMPT.md` in the repo root and execute it starting at the first unchecked task in
> the Progress Tracker. Do one task, run the Gate, commit, tick the box, then stop and report.

Everything the model needs is in this file. `RECOVERY_PLAN.md` holds the evidence behind each fix —
read it only if a task's reason is unclear. `AGENTS.md` remains the canonical rulebook.

---

## PART A — RULES (read these before every task, never skip)

**A1. Every command is prefixed with `conda run -n avialview`.** No exceptions. The system Python is
not the project Python.

**A2. The Gate.** After *every* task, run all four commands. All four must pass.

```bash
conda run -n avialview ruff check . && conda run -n avialview ruff format .
conda run -n avialview mypy src/avialview/core
conda run -n avialview mypy src/avialview
QT_QPA_PLATFORM=offscreen conda run -n avialview pytest -q --ignore=tests/benchmarks
```

After Phase 1 is finished, also run the benchmarks once per phase:
`conda run -n avialview pytest tests/benchmarks -q`

**A3. One task = one commit.** Conventional message, e.g. `fix(ui): keep drop-scan worker alive`.
Never combine two task IDs into one commit. Never move on with a red Gate.

**A4. Forbidden, always.**
- Do NOT add `# type: ignore` (only for a genuine mypy limitation, with a comment naming it).
- Do NOT add or restore a `[[tool.mypy.overrides]]` `ignore_errors` block.
- Do NOT delete, skip, `xfail`, or weaken any existing test to make something pass.
- Do NOT write `except Exception: pass`.
- Do NOT leave a `TODO` that acknowledges a crash — fix it or stop and report.
- Do NOT rename anything. `AvialView` is the brand, `avialview` is the identifier. That is settled.
- Do NOT refactor code the task does not name. Match the style of the file you are editing.

**A5. Never touch these.**
- `tests/test_sync_golden.py` and any golden fixture.
- `MasterClock` tick/drift logic in `core/timeline.py`.
- Which mpv embedding path is chosen (Qt OpenGL render API on Windows/macOS, native `wid` on Linux).
  Phase 5 reorders construction only — it must not change the choice.
- `locale.setlocale(locale.LC_NUMERIC, "C")` placement in `__main__.py`.
- `ui/theme.py`'s palette-only approach. Never add application-level QSS.

**A6. Scratch files.** Temporary scripts go in the OS temp directory, never in the repo root or
`src/`. Real tests go in `tests/test_*.py`.

**A7. If a task looks wrong or conflicts with `AGENTS.md`, stop and say so.** Do not improvise a
different design. Do not silently skip a task.

**A8. Report format after each task.** Three lines: what you changed, the Gate result, the commit
hash. Nothing else.

---

## PART B — PROGRESS TRACKER

Tick a box only after its Gate passed and its commit exists. Always resume at the first unticked box.

### Phase 0 — Green the gate
- [ ] 0.1 `zip(strict=True)` in `aol_eks_loader.py`
- [ ] 0.2 Wrap the long comment in `tests/test_ui_main.py`
- [ ] 0.3 Type the `config` dicts in `drop_worker.py`
- [ ] 0.4 Guard `benchmark.stats is None` in the benchmark tests
- [ ] 0.5 Delete `pytest_out.txt`, add it to `.gitignore`

### Phase 1 — Restore drag-and-drop and session persistence
- [ ] 1.1 Add the failing tests first (`tests/test_worker_lifetime.py`)
- [ ] 1.2 Add `MainWindow._run_job`
- [ ] 1.3 Route `_start_drop_scan` through `_run_job`
- [ ] 1.4 Route `_start_session_save` and `_start_session_load` through `_run_job`
- [ ] 1.5 Make the close-time autosave synchronous

### Phase 2 — AOL loader correctness
- [ ] 2.1 `AOLEncoderLoader` honours `anchor_date`
- [ ] 2.2 `AOLEncoderLoader` handles midnight rollover
- [ ] 2.3 Carry chunk boundaries in `AOLEncoderLoader`
- [ ] 2.4 Carry chunk boundaries in `AOLEksLoader`
- [ ] 2.5 Deterministic bodypart resolution in `AOLEksLoader`
- [ ] 2.6 Initialise `_col_mapping`; typed errors in both AOL loaders
- [ ] 2.7 Report real `rate_hz`

### Phase 3 — Bounded-memory streaming import
- [ ] 3.1 `PyramidBuilder.append` / `.finalize`
- [ ] 3.2 Streaming gap-mask
- [ ] 3.3 Rewrite `importer._build_bulk_channels` to be bounded
- [ ] 3.4 Rewrite `importer._build_channel_by_channel` to be bounded
- [ ] 3.5 Memory ceiling test

### Phase 4 — Cross-OS fluidity
- [ ] 4.1 `CREATE_NO_WINDOW` on every subprocess
- [ ] 4.2 `VideoPane` is inert, not broken, without libmpv
- [ ] 4.3 `PyramidReader.bounds()` replaces the private call in `plot_row.py`
- [ ] 4.4 UI heartbeat test

### Phase 5 — Architecture debt
- [ ] 5.1 Remove mypy suppressions, one module per commit (11 commits)
- [ ] 5.2 Break `engine` → `ui` imports in `player.py`
- [ ] 5.3 Split `main_window.py` into four controllers (4 commits)
- [ ] 5.4 Fix `core/registry.py`
- [ ] 5.5 Typed errors across `loaders/` and `importer.py`

### Phase 6 — Identity and documentation
- [ ] 6.1 `ChannelKey` identity
- [ ] 6.2 Update `ARCHITECTURE.md`, `HANDOUT.md`, `DECISIONS.md`, `BLUEPRINT.md`

---

## PHASE 0 — Green the gate

The Gate is red today. Nothing later can be trusted until it is green. These five tasks are
mechanical; make no other change.

### 0.1 — `src/avialview/loaders/aol_eks_loader.py`, line ~105
`dict(zip(self._xyz_channels, raw_xyz))` → `dict(zip(self._xyz_channels, raw_xyz, strict=True))`.
The two lists are appended in lockstep in the loop directly above, so `strict=True` is correct.
Commit: `fix(loaders): make EKS column zip strict`

### 0.2 — `tests/test_ui_main.py`, line ~231
One comment is 116 characters. Wrap it to two lines of ≤ 100.
Commit: `style(tests): wrap over-length comment`

### 0.3 — `src/avialview/engine/drop_worker.py`, lines ~169 and ~180
Two `config = {...}` locals are inferred as `dict[str, float]`, then get a list and a str assigned.
Annotate both explicitly:
```python
config: dict[str, Any] = { ... }
```
This file does not import `Any` yet — add `from typing import Any` to its imports.
Do NOT add `# type: ignore`.
Commit: `fix(engine): type drop-scan config dicts`

### 0.4 — `tests/benchmarks/test_bench_pyramid.py` (and any sibling benchmark doing the same)
`benchmark.stats` is `None` whenever benchmarks are disabled, so `pytest -x` crashes before it ever
reaches the UI tests. Guard it — keep the assertion, do not delete it:
```python
stats = benchmark.stats
if stats is None:
    pytest.skip("benchmark statistics unavailable (benchmarks disabled)")
assert stats["mean"] <= budget, (...)
```
Grep for `benchmark.stats[` across `tests/benchmarks/` and apply the same guard everywhere.
Commit: `test(bench): skip budget assertion when benchmarks are disabled`

### 0.5 — repo root
`pytest_out.txt` is a stale UTF-16 console capture of a failing run that got committed. Delete it and
add `pytest_out.txt` to `.gitignore`.
Commit: `chore: drop committed pytest output capture`

> **STOP after 0.5.** Run the full Gate *and* `conda run -n avialview pytest -x -q` (benchmarks
> enabled). Both must be green. Report, then continue.

---

## PHASE 1 — Restore drag-and-drop and session persistence

**The bug.** A `QObject` moved to a `QThread` with no owning Python reference is garbage-collected
before `QThread.started` fires, so its `run()` slot never executes. Three call sites in
`ui/main_window.py` do this: `_start_drop_scan` (~line 924), `_start_session_save` (~444),
`_start_session_load` (~499). Consequences today, all verified:
- Dropping any file does nothing at all.
- Saving a session writes no file, and leaves `_save_in_progress = True` forever, which permanently
  disables every later save.
- Loading a session does nothing.

Other job sites in this file are already correct because they store the worker in a dict
(`self._video_load_jobs[thread] = worker` etc.). You are making the three broken ones match.

### 1.1 — Write the failing tests FIRST
New file `tests/test_worker_lifetime.py`. Follow the fixture/style conventions of the existing
`tests/test_ui_main.py`. Four tests:

1. `test_drop_routes_single_csv` — build `MainWindow`; monkeypatch `_start_data_import` to append to
   a list; build a `QDropEvent` whose mime data carries `QUrl.fromLocalFile` of
   `examples/data/sensors.csv`; call `window.dropEvent(event)`; pump the Qt event loop until the list
   is non-empty or 5 s elapse; assert exactly one call and that its loader is `CSVLoader`.
2. `test_drop_routes_avv_session` — same shape, dropping a `.avv` file written to `tmp_path`,
   asserting `_start_session_load` ran.
3. `test_session_save_writes_file` — call `window._start_session_save(tmp_path / "s.avv")`, pump,
   assert the file exists **and** `window._save_in_progress is False`.
4. `test_second_save_is_allowed` — save to two different paths in sequence, pump, assert both files
   exist. This is the test that catches the permanent latch.

**Run them now. All four must FAIL.** If any passes, you have written the test wrong — fix the test
before touching any source file. Commit the failing tests:
`test(ui): cover background worker lifetime`

### 1.2 — Add `MainWindow._run_job`
In `src/avialview/ui/main_window.py`, add `self._jobs: dict[QThread, QObject] = {}` in `__init__`
next to the other `*_jobs` dicts (around line 78), and add this method near them:

```python
def _run_job(self, worker: QObject) -> QThread:
    """Own a worker/thread pair for the whole life of a background job.

    A QObject moved to a QThread with no Python reference is collected before
    ``QThread.started`` fires, so its ``run`` slot never runs at all.  Every
    background job started by this window must be registered here.
    """
    thread = QThread(self)
    worker.moveToThread(thread)
    self._jobs[thread] = worker
    thread.started.connect(worker.run)
    thread.finished.connect(lambda t=thread: self._jobs.pop(t, None))
    thread.finished.connect(thread.deleteLater)
    return thread
```

Commit: `fix(ui): add owned background job registry`

### 1.3 — Route `_start_drop_scan` through `_run_job`
In `_start_drop_scan` (~line 924) delete these three lines:
```python
thread = QThread(self)
worker.moveToThread(thread)
...
thread.started.connect(worker.run)
```
and replace with `thread = self._run_job(worker)`. Also delete the now-duplicated
`thread.finished.connect(thread.deleteLater)`. Keep **every** existing `worker.finished`,
`worker.error`, `worker.session_found`, and `thread.quit` connection exactly as it is, and keep
`thread.start()` at the end.
Test 1 and test 2 from 1.1 must now pass.
Commit: `fix(ui): keep the drop-scan worker alive so drops import again`

### 1.4 — Route session save and load through `_run_job`
Apply the identical edit to `_start_session_save` (~444) and `_start_session_load` (~499).

In `_start_session_save` additionally make the latch un-stickable — connect the reset to
`thread.finished` as well, not only to `on_finished`/`on_error`:
```python
thread.finished.connect(lambda: setattr(self, "_save_in_progress", False))
```
Tests 3 and 4 must now pass.
Commit: `fix(ui): restore session save and load`

### 1.5 — Make the close-time autosave synchronous
`closeEvent` (~line 877) calls `self._autosave()` and then closes the window immediately, so a
threaded save can never finish. At close time only, run the save inline:

```python
# Close-time autosave is the one legitimate blocking write: it happens after
# the final paint, it is bounded, and a worker thread cannot outlive the window.
from avialview.engine.session_worker import SessionSaveWorker
SessionSaveWorker(self._build_session_state(), autosave_path).run()
```
Keep the periodic `_autosave_timer` path threaded — change only the close path.
Commit: `fix(ui): flush the autosave before the window closes`

> **STOP after 1.5.** Gate + benchmarks. Then manually launch the app
> (`conda run -n avialview avialview`) and confirm by hand: drop a video, drop a CSV, drop an AOL
> session folder, save a session, reopen it. Report what worked and what did not.

---

## PHASE 2 — AOL loader correctness

**The bug.** `AOLEncoderLoader` receives `config["anchor_date"]` from `drop_worker.py` and never
reads it. Its timestamps are seconds-since-midnight (0–86400) while the AOL videos and EKS channels
are on an anchor-relative axis. Encoder velocity is therefore drawn at the wrong absolute time in
every AOL session. Separately, both AOL loaders validate chronology and de-duplicate **within each
50 000-row batch only**, which violates the `core/source.py` `read_chunks` contract: *"Chunks,
including their boundaries, must be globally chronological. Duplicate timestamps must keep the final
value."* `CSVLoader._read_batches` already implements this correctly — **copy its pattern verbatim**,
do not invent a different one.

### 2.1 — `anchor_date` in `AOLEncoderLoader`
File `src/avialview/loaders/aol_encoder_loader.py`.
- In `open()`: read `config.get("anchor_date")`, parse with `"%Y-%m-%d"`, convert to a UTC epoch, and
  store as `self._anchor_epoch`. Mirror the conversion in `csv_loader._normalize_time`'s
  `time_of_day` branch (lines ~166–176) so both agree.
- If `anchor_date` is absent or unparseable: set `self._anchor_epoch = 0.0` and set
  `self._anchor_provisional = True`. **Never guess a date** — AGENTS §Arch 8 forbids silently
  inventing alignment.
- In `read_chunks()`: emit `t = seconds_since_midnight + self._anchor_epoch`.

Test in `tests/test_aol_loaders.py`: `test_encoder_applies_anchor_date` — with
`anchor_date="2026-07-30"`, a row at `10:00:00:000` must land on the epoch for
2026-07-30T10:00:00Z, not on `36000.0`.
Commit: `fix(loaders): apply the AOL anchor date to encoder timestamps`

### 2.2 — Midnight rollover in `AOLEncoderLoader`
A recording crossing 00:00 currently raises `NonMonotonicTimeError`. Add the same rollover correction
`csv_loader.py` uses (lines ~178–182): where `np.diff(t) < -43200`, cumulatively add `86400.0`.
Apply it **before** the monotonicity check, and make it work across chunk boundaries (it depends on
2.3, so do 2.3 in the same or the next commit and re-verify).

Test `test_encoder_crosses_midnight`: rows at `23:59:59:500`, `00:00:00:500`, `00:00:01:500` produce
a strictly increasing array spanning the boundary.
Commit: `fix(loaders): handle midnight rollover in the AOL encoder log`

### 2.3 / 2.4 — Carry chunk boundaries
Files: `aol_encoder_loader.py`, then `aol_eks_loader.py`.
Read `csv_loader.py` lines 225–271 and reproduce that exact mechanism in each AOL loader:
hold `pending_time` / `pending_values`, prepend them to the next batch before validating, yield
`[:-1]`, and flush the retained tail after the loop ends.

Tests (one per loader): with `batch_size=4` in the config,
- a duplicate timestamp straddling the boundary is de-duplicated keeping the **last** value;
- a backward jump straddling the boundary raises `NonMonotonicTimeError` with the correct `row`.
Commits: `fix(loaders): carry chunk boundaries in the AOL encoder loader`
and `fix(loaders): carry chunk boundaries in the AOL EKS loader`

### 2.5 — Deterministic bodypart resolution
`aol_eks_loader.py` lines ~86–103 iterate `known_bodyparts`, a `set`. Python salts string hashes per
process, so which bodypart wins for an ambiguous column suffix changes run to run — which changes
channel names, cache keys, and session files.
Build the list in skeleton order instead, de-duplicated with `dict.fromkeys(...)`, and match
**longest name first** so `left_ear` beats `ear`.

Test `test_bodypart_resolution_is_deterministic`: run the loader in five subprocesses with different
`PYTHONHASHSEED` values and assert identical channel-name lists.
Commit: `fix(loaders): make EKS bodypart resolution deterministic`

### 2.6 — Guard uninitialised state, use typed errors
- `aol_eks_loader.py` `__init__`: add `self._col_mapping: dict[str, str] = {}`. Calling `channels()`
  or `read_all_chunks()` before `open()` must raise a typed error, not `AttributeError`.
- Replace the bare `raise ValueError(...)` / `KeyError` / `RuntimeError` in both AOL loaders with
  existing classes from `core/errors.py`: `SourceOpenError` for "not opened" and malformed input,
  `MissingColumnError` for an unknown channel, `FileUnreadableError` for an unreadable file. Add a
  new class only if none fits.
- Every message gets an actionable second sentence, e.g.
  `"No x/y/z coordinate columns found in <file>. Check that this is an EKS pose file."`
Commit: `fix(loaders): raise typed errors from the AOL loaders`

### 2.7 — Report real sample rates
Both AOL loaders return `rate_hz=None` ("irregular") even where the rate is known.
`AOLEksLoader.channels()` → `rate_hz=float(self._config.get("fps", 0.0)) or None`.
`AOLEncoderLoader.channels()` → the measured median rate, or `None` if genuinely irregular.
Commit: `fix(loaders): declare known AOL sample rates`

> **STOP after 2.7.** Gate + benchmarks. Load a real AOL session folder by hand and confirm the
> encoder velocity plot now sits on the same time axis as the videos.

---

## PHASE 3 — Bounded-memory streaming import

**The bug.** `engine/importer.py::_build_bulk_channels` (line ~141) collects **every** time chunk and
**every** value chunk for **every** channel into Python lists, then `np.concatenate`s each one. Peak
memory is roughly `8 bytes × samples × (1 + channels)` plus a transient copy — a 180 M-sample
4-channel import needs about 7 GB against an idle budget of 2.5 GB. `BLUEPRINT.md` lists this as an
open P0. `_build_channel_by_channel` (line ~205) has the same defect via `list(loader.read_chunks(...))`.

Phase 3 is the only phase that touches `core/`. Benchmarks must be unaffected or better.

### 3.1 — Incremental pyramid building
File `src/avialview/core/pyramid.py`. Add to `PyramidBuilder`:
- `append(self, t: np.ndarray, v: np.ndarray) -> None` — appends to the level-1 arrays on disk and
  folds the chunk into the running 16× / 256× / 4096× min/max extrema.
- `finalize(self) -> None` — flushes partial buckets and writes all level files atomically.
Keep `build_and_save(t, v)` and reimplement it as `append(t, v); finalize()` so no existing caller
changes. Levels must stay NaN-aware (`nanmin`/`nanmax`) and gap-aware — that is a hard-won trap in
`AGENTS.md`, do not regress it.

Test `tests/test_pyramid_streaming.py`: for three fixtures (dense regular, one containing a NaN
block, one containing a gap), assert that appending in 7 uneven chunks produces **byte-identical**
level arrays to a single `build_and_save`. Cover every level, not just level 1.
Commit: `feat(core): add incremental pyramid building`

### 3.2 — Streaming gap mask
`build_gap_mask(t)` needs the whole array. Add a streaming variant carrying the previous chunk's last
timestamp and the running median-interval estimate. Assert it equals the batch version on the same
three fixtures.
Commit: `feat(core): add streaming gap-mask construction`

### 3.3 — Bounded `_build_bulk_channels`
Rewrite so that per chunk it: validates the shared-timestamp invariant exactly as today, `append`s to
one `PyramidBuilder` per channel, and then **drops the chunk**. Accumulate only scalars
(`total_rows`, `total_nan`, `gap_count`, `t0`, `t1`) plus a **capped** gap-location list — and when
the cap is hit, `logger.warning` how many were dropped. Never truncate silently. Emit progress from
rows consumed, not from channel index.
Commit: `perf(engine): stream bulk channel imports without full materialisation`

### 3.4 — Bounded `_build_channel_by_channel`
Same treatment; replace `list(loader.read_chunks(channel))` with a streaming loop.
Commit: `perf(engine): stream legacy single-channel imports`

### 3.5 — Memory ceiling test
`tests/test_import_memory.py`: import a synthetic 20 M-sample × 4-channel fixture and assert peak
Python-side allocation stays under a fixed ceiling using `tracemalloc`. Do **not** add a new
dependency for this; if you believe one is required, stop and report instead — new dependencies need
a licence check in the PR description (AGENTS §Tech stack).
Also add a `tests/benchmarks/` entry recording p50/p95/p99 and peak memory for a 1 GB import.
Commit: `test(engine): bound import memory growth`

> **STOP after 3.5.** Gate + `conda run -n avialview pytest tests/benchmarks -q`. No benchmark may
> regress by more than 20 %. Report the pyramid-build number before and after.

---

## PHASE 4 — Cross-OS fluidity

### 4.1 — Hide child consoles on Windows
There is currently no `creationflags` anywhere in the tree, so every ffprobe/ffmpeg call pops a
console window in a windowed Windows build. Loading four cameras flashes four consoles. This is the
single most visible Windows hiccup.

Add to `src/avialview/runtime.py` (it imports `os`, `shutil`, `sys` today — you must also add
`import subprocess`):
```python
def subprocess_flags() -> int:
    """Return creation flags that keep child consoles hidden on Windows."""
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0
```
Pass `creationflags=subprocess_flags()` at every call site:
`loaders/video_standard.py` (~71, ~179), `engine/export.py` (~194), `engine/proxy.py` (~70),
`demo.py` (~110). Keep argument lists — never build a shell string (AGENTS trap).
Test: patch `subprocess.run`/`Popen` and assert each site passes `creationflags`.
Commit: `fix(runtime): hide child process consoles on Windows`

### 4.2 — `VideoPane` must be inert, not broken, without libmpv
`ui/video_pane.py` line ~101 does `if not probe_libmpv(self): return`, aborting `__init__` **after**
the layout is built but **before** `paint_canvas`, `overlay`, `lbl_name`, `lbl_osd` and
`lbl_no_footage` exist. Every later call then raises `AttributeError`. On a machine without libmpv,
D-013's guided dialog is followed by a crash cascade — which is exactly what D-013 exists to prevent.

Restructure `__init__` so all overlay/label/canvas widgets are created **before** the `probe_libmpv`
guard. After the guard returns early, the pane must show the "No Footage" placeholder and every
public method must be a safe no-op when `self.mpv is None`: `set_label`, `set_tracking_readers`,
`set_has_footage`, `open`, `play`, `pause`, `seek`, `frame_step`, `set_rate`, `close`.
**Do not change which embedding path is selected** — only the order of construction.

Test `tests/test_video_pane.py::test_pane_without_libmpv_is_inert`: monkeypatch `probe_libmpv` to
return `False`, construct the pane, call all ten methods, assert no exception and that the
no-footage label is visible.
Commit: `fix(ui): keep VideoPane usable when libmpv is unavailable`

### 4.3 — Public bounds accessor
`ui/plot_row.py` line ~254 calls `reader._load_level(1)` — a private `PyramidReader` method — only to
read the first and last timestamp. Add `PyramidReader.bounds() -> tuple[float, float] | None` to
`core/pyramid.py` reading just those two elements from the level-1 mmap, and use it. No behaviour
change: assert the coverage region is identical before and after on an existing fixture.
Commit: `refactor(core): expose pyramid bounds publicly`

### 4.4 — UI heartbeat test
This is the test that actually defends "fluid on every OS"; everything else in this phase is one
specific cause it catches. New `tests/test_ui_heartbeat.py`: build a populated window (2 fixture
videos + 4 channels), drive open → play 2 s → scrub → resize → theme switch while a 60 Hz `QTimer`
samples callback duration. Assert **no** UI-thread callback exceeds 30 ms (the hard ceiling in
`BLUEPRINT.md`) and p95 stays under 8 ms. Real paint events must be processed — do not assert on an
empty widget.
Commit: `test(ui): assert the UI heartbeat stays within budget`

> **STOP after 4.4.** Gate + benchmarks. If the heartbeat test fails, report the offending callback
> and its duration — do not relax the threshold.

---

## PHASE 5 — Architecture debt

Large but mechanical. Every task here is many small commits. Never batch them.

### 5.1 — Remove the mypy suppressions (11 separate commits)
`pyproject.toml` lines 75–137 hold 14 override blocks, 12 with `ignore_errors = true`, covering most
of the UI plus two built-in loaders. `AGENTS.md` forbids silencing a checker to ship.

Do them one module per commit, easiest first:
`ui.relink_dialog` → `ui.diagnostics` → `engine.export` → `ui.readout_panel` → `ui.video_grid` →
`loaders.csv_loader` → `loaders.neo_loader` → `ui.sidebar` → `ui.video_pane` → `ui.transport` →
`ui.plot_pane`.

For each: delete that module's block from `pyproject.toml`, run `conda run -n avialview mypy
src/avialview`, and **fix the real errors in the module**. Never re-add the block. Never add
`# type: ignore` except for a genuine mypy limitation (e.g. `**dict[str, object]` unpacking, a
missing third-party stub) with a one-line comment naming it. If a module needs more than ~30 real
fixes, commit what you have done, restore only that one block with a comment naming the remaining
error count, and record it in `HANDOUT.md` as known debt.
Commit each: `fix(types): type-check <module>`

### 5.2 — Break the `engine` → `ui` dependency
`engine/player.py` lines 13–16 import `avialview.ui.plot_pane`, `ui.transport`, `ui.video_grid`,
`ui.video_pane` at module scope, so `engine` cannot be exercised headlessly. Move all four under
`if TYPE_CHECKING:` — they are used only for annotations; the objects arrive as constructor
arguments. Also replace `self.transport._bounds` (line ~94) with a public `Transport.bounds()`
accessor you add to `ui/transport.py`.
Extend `tests/test_headless_core.py` to assert that importing `avialview.engine.player` does not
import `avialview.ui.plot_pane` at module scope.
Commit: `refactor(engine): remove module-scope UI imports from Player`

### 5.3 — Split `ui/main_window.py` (4 commits)
It is 2195 lines against a ~500 limit and owns drop routing, session persistence, import
orchestration, video queueing, export, snapshots, region stats, sync, menus, and shortcuts.

Extract along the seams that already exist, **moving code verbatim** — no logic changes:
1. `ui/controllers/drop_controller.py` — `dragEnterEvent`, `eventFilter`, `dropEvent`,
   `_start_drop_scan`, `_on_drop_*`, `_route_import_candidate`, `_process_drop_candidates`.
2. `ui/controllers/session_controller.py` — save / load / autosave / geometry / recent files /
   `_restore_session`.
3. `ui/controllers/export_controller.py` — snapshot, data export, video clip, region stats.
4. `ui/controllers/import_controller.py` — `_start_data_import`, `_load_video`,
   `_start_next_video_load`, `_on_video_*`.

`MainWindow` keeps widget construction, the menu/shortcut table, and controller wiring.
**After each extraction the full suite must pass unchanged.** If a test needs editing, you changed
behaviour — revert and redo.
Commit each: `refactor(ui): extract <name> controller from MainWindow`

### 5.4 — Fix `core/registry.py`
Five defects, one commit each or one commit total, your choice — but all five:
1. `_default_plugin_dirs()` returns only `~/.avialview/plugins`. Add the bundled `examples/plugins/`
   directory promised by `BLUEPRINT.md` Phase 5.
2. No `sys._MEIPASS` handling, so no loose plugin loads from a PyInstaller bundle. Mirror the
   existing pattern at `runtime.py` line ~30.
3. `_load_module` and the entry-point loop swallow failures silently — a broken third-party plugin
   vanishes with zero diagnostics. Collect them into `self.plugin_errors: list[tuple[Path, str]]` and
   surface them in `ui/diagnostics.py`'s report.
4. Module names use `abs(hash(path))`, which is salted per process. Use
   `hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]`.
5. The six built-ins are registered **twice** — hardcoded in `_discover()` *and* declared as entry
   points in `pyproject.toml` line 43. Keep the entry points as the single source, delete the
   hardcoded list, and fall back to it only when `entry_points()` returns nothing (source checkout
   without `pip install -e .`). **Record this choice in `DECISIONS.md`.**

Tests: a temp-dir plugin is discovered; a plugin that raises on import lands in `plugin_errors` and
does not break discovery of the others; discovery order is stable across runs.
Commit: `fix(core): harden plugin discovery`

### 5.5 — Typed errors everywhere else
Replace the remaining bare `ValueError` / `KeyError` / `RuntimeError` in `loaders/` and
`engine/importer.py` (lines ~56, ~154, ~161, ~164) with classes from `core/errors.py`. Every message
gets an actionable second sentence. Add a UI test that a malformed CSV surfaces that sentence in a
dialog rather than a bare `repr`.
Commit: `fix(errors): raise typed errors from loaders and the importer`

> **STOP after 5.5.** Gate + benchmarks. Report how many mypy suppressions remain, if any.

---

## PHASE 6 — Identity and documentation

### 6.1 — `(source_id, channel_id)` identity
Channel IDs are still bare global strings across `plot_pane.load_channels`, `set_channel_visible`,
`set_channel_unit`, the readout panel, the sidebar tree, and Parquet export. The AOL work made the
collision routine rather than theoretical: `drop_worker._collect_aol_candidates` enumerates
`manifest.eks_files` — one per camera — and every one produces channels named `nose_x`, `nose_y`, …
Two cameras' EKS files currently overwrite and remote-control each other.

Add a frozen `ChannelKey` dataclass to `core/source.py` (`source_id: str`, `channel_id: str`) with a
stable string form `f"{source_id}::{channel_id}"`. Thread it through every consumer listed above and
through the `.avv` schema — bump `schema_version` and write a migration mapping old bare names onto
the first matching source. Display the bare `channel_id` in the UI; key on the full key everywhere
else.

Fixtures required before this merges: two EKS files from two cameras with identical bodypart names,
and a Parquet export from two sources with **different** time axes (export long-form, or prove the
axes are identical before writing wide-form).
Commit: `feat(core): identify channels by source and channel id`

### 6.2 — Documentation catch-up
Six modules added by the refactor appear **zero** times in `ARCHITECTURE.md` and `HANDOUT.md`:
`engine/drop_worker.py`, `engine/session_worker.py`, `engine/export_worker.py`,
`loaders/aol_eks_loader.py`, `loaders/aol_encoder_loader.py`, `loaders/aol_session_loader.py`.

- `ARCHITECTURE.md §1`: add all six to the repository map. In §4, document the `read_all_chunks`
  bulk protocol as an **optional additive** extension of the frozen v1 contract — state explicitly
  that it is not part of v1.
- `HANDOUT.md`: module-map entries, plus a known-bugs section listing anything this prompt
  deliberately deferred.
- `DECISIONS.md`: one entry each for (a) the AOL loader family and its anchor-date semantics,
  (b) the `read_all_chunks` bulk protocol, (c) the registry's single registration mechanism (5.4),
  (d) the `ChannelKey` identity change.
- `BLUEPRINT.md` §"Full performance and accurate-streaming audit": update the P0 rows this work
  closes. **Do not mark a row complete without the benchmark evidence that row names.**
Commit: `docs: record the post-refactor module map and decisions`

> **STOP after 6.2.** Full Gate, full benchmarks, and the manual smoke checklist in `TESTING.md` §6.
> Report the final state of every box in the Progress Tracker.
