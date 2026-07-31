# RECOVERY_PLAN.md — post-refactor rule-violation ledger and repair plan

> Audit date: 2026-07-30. Baseline commit: `4e4fac5`.
> Scope of the refactor being repaired: commits `600dfbc..4e4fac5` (AOL loaders, `drop_worker`,
> `session_worker`, `export_worker`, `importer` bulk path, `main_window` rewrite, `video_grid` rework).
> Canonical rules: `AGENTS.md`. Phase status: `BLUEPRINT.md`. Settled choices: `DECISIONS.md`.
>
> This document is written to be executed by an agent with limited context. Every task names the
> exact file, the exact change, the exact test, and the exact command that proves it. Work the waves
> in order. Do not reorder. Do not batch waves.

---

## 0. Standing rules for whoever executes this plan

1. **One task = one commit.** Conventional message (`fix(ui): …`). Never combine two task IDs.
2. **Every command is prefixed with `conda run -n avialview`.** No exceptions (AGENTS §How to run things).
3. **After every task run the gate:**
   ```bash
   conda run -n avialview ruff check . && conda run -n avialview ruff format .
   conda run -n avialview mypy src/avialview/core
   conda run -n avialview mypy src/avialview
   QT_QPA_PLATFORM=offscreen conda run -n avialview pytest -q --ignore=tests/benchmarks
   ```
   All four must pass before you move to the next task. If a task's own new test is the only
   failure, finish that task. If anything *else* broke, revert the task and re-do it.
4. **Never weaken a test, never add `# type: ignore`, never add a `[[tool.mypy.overrides]]`
   `ignore_errors` entry** to make a gate pass (AGENTS §Coding standards). Removing such
   suppressions is itself a task in this plan (W5-1).
5. **Do not refactor anything not named in the task.** Style entropy across models is a known
   failure mode here (AGENTS §Task protocol 9).
6. **Scratch files go in the OS temp dir, never in the repo root or `src/`** (AGENTS §Task protocol 11).
   New tests go in `tests/test_*.py`.
7. **If a task requires reversing a settled decision, stop and write a `DECISIONS.md` proposal
   instead.** Do not silently diverge.
8. Golden sync tests (`tests/test_sync_golden.py`) must stay untouched and green throughout.

---

## 1. Violation ledger

Severity: **S0** = user-visible broken feature or data-correctness bug · **S1** = architecture rule
broken, will bite at scale · **S2** = hygiene / gate / documentation debt.

| ID | Sev | Rule broken | Evidence |
|---|---|---|---|
| ~~V-01~~ | **FIXED** (merge) | AGENTS §Coding standards (Qt object ownership) | **Drag-and-drop is dead.** `main_window.py:924` `_start_drop_scan` creates `worker = DropScanWorker(...)`, calls `moveToThread`, and keeps **no Python reference**. The wrapper is collected before `thread.started` fires, so `DropScanWorker.run` never executes. Reproduced offscreen: dropping `examples/data/sensors.csv` accepts the event and routes **zero** imports; adding a single `self._x = (worker, thread)` line makes the same drop route `CSVLoader` correctly. |
| ~~V-02~~ | **FIXED** (merge) | Same root cause as V-01 | **Session save, session load, and autosave are dead**, and save is *permanently* disabled after the first attempt. `_start_session_save` (`main_window.py:444`) and `_start_session_load` (`:499`) drop the worker the same way. Reproduced: `_start_session_save()` writes no file and leaves `_save_in_progress = True` forever, so every later save short-circuits at `:445`. `closeEvent` calls `_autosave()` and then immediately closes, so even a fixed worker could not finish. |
| ~~V-03~~ | **FIXED** `dfb7e57` | AGENTS §Arch 3 + BLUEPRINT P0-streaming + idle-RAM budget ≤ 2.5 GB | `importer.py:141 _build_bulk_channels` accumulates **every** time chunk *and* every value chunk for **every** channel in Python lists, then `np.concatenate`s each. Peak ≈ `8 bytes × N × (1 + C)` plus a transient copy: a 180 M-sample 4-channel import needs ~7 GB before the first pyramid level is written. BLUEPRINT explicitly lists "replace complete-channel accumulation with bounded builders/backpressure" as an open P0. The refactor moved it from per-channel to all-channels-at-once, i.e. it got worse. |
| ~~V-04~~ | — | **WITHDRAWN — this was an incorrect finding.** | Original claim: `AOLEncoderLoader` ignores `config["anchor_date"]` so the encoder lands on a different axis from video/EKS. **Verified false against the real session** (`…/2026-05-08/experiment_1/09-35-24`): videos cover master `[34526.312 … 34586.502]`, 3D EKS `[34526.312 … 34586.499]`, encoder `[34526.082 … 34586.964]` — all on the same seconds-since-midnight-UTC axis, with the encoder correctly bracketing the cameras by ~0.2–0.5 s. `drop_worker` **subtracts** `anchor_epoch` from video/EKS start epochs, which puts them on exactly the axis `_parse_wall_clock` already produces. Adding the anchor to encoder timestamps would have shifted it ~20.6 days out of alignment. `anchor_date` is genuinely unused, but the behaviour is correct; the fix is a comment recording *why*, not a code change. |
| V-04a | S1 | AGENTS §Arch 1 + trap "timezone-naive timestamps" | Real remainder of the original V-04: `AOLEncoderLoader` has no midnight-rollover handling. Video/EKS master time is epoch-derived and therefore continues past 86400 across midnight, while the encoder's seconds-since-midnight axis wraps to 0 — a backward jump that raises `NonMonotonicTimeError` and desynchronises any session crossing 00:00. The encoder must *unwrap* past 86400 to stay on the video axis. |
| V-04b | S1 | AGENTS §Task protocol 6 (cross-platform / defensive parsing) | `drop_worker._collect_aol_candidates` derives an EKS camera name with `eks_file.name.split("_")[0]`. For the real file `_eks.csv` this is the **empty string**, and `"" in vid_name` matches *every* video, so the first video's epoch is always selected. It happens to be correct here only because all three cameras share one start epoch; with per-camera epochs it would silently mis-time EKS data. |
| V-05 | S1 | AGENTS §Arch 3 + BLUEPRINT P0-streaming | `AOLEksLoader.read_chunks(ch)` calls `read_all_chunks()`, i.e. one **full CSV re-scan per channel**. A 5-bodypart file has 15 channels → 15 passes. Only `read_all_chunks` is fast-pathed by the importer; anything else (region stats, export, a plugin host that calls the frozen v1 API) pays 15×. |
| ~~V-06~~ | **FIXED** `3d6d914` | AGENTS §Coding standards ("raise typed exceptions from `core/errors.py`") | `aol_eks_loader.py:83`, `aol_encoder_loader.py:74,78`, `csv_loader.py:58,61`, `importer.py:56,154,161,164` raise bare `ValueError`/`KeyError`/`RuntimeError`. The UI has no way to turn these into actionable dialogs, so they surface as raw `str(e)` in a `QMessageBox`. |
| V-07 | S2 | AGENTS §Coding standards ("Never silence a type/lint error") | `pyproject.toml:75–137` carries **14** `[[tool.mypy.overrides]]` blocks, 12 of them `ignore_errors = true`, covering `ui.transport`, `ui.sidebar`, `ui.plot_pane`, `ui.video_pane`, `ui.video_grid`, `ui.readout_panel`, `ui.relink_dialog`, `ui.diagnostics`, `engine.export`, `loaders.csv_loader`, `loaders.neo_loader`. That is most of the UI and two built-in loaders type-unchecked by policy. |
| ~~V-08~~ | **FIXED** `cdfaa39` | AGENTS §DoD ("`pytest -x`, `ruff check .`, `mypy` all pass") | The gate is red right now: `ruff check .` → 2 errors (`aol_eks_loader.py` `zip()` without `strict=`, `tests/test_ui_main.py:231` E501). `mypy src/avialview` → 2 errors in `drop_worker.py:172,181` (`config` dict inferred as `dict[str, float]`, then assigned a list and a str). `pytest -x` on the full suite **crashes** because `tests/benchmarks/test_bench_pyramid.py:59` subscripts `benchmark.stats` which is `None` whenever benchmarks are disabled. |
| V-09 | S1 | AGENTS §Coding standards ("No new module > ~500 lines") | `ui/main_window.py` is **2195 lines** and owns drop routing, session persistence, import orchestration, video load queueing, export, snapshots, region stats, sync wizard, menus and shortcuts. BLUEPRINT already lists this as P2-maintainability; the refactor grew it. `ui/transport.py` is 836. |
| ~~V-10~~ | **FIXED** `02c6c5a` | AGENTS §Arch 5 + BLUEPRINT Phase 5 (plugin API v1) | `core/registry.py` — (a) `_default_plugin_dirs()` returns only `~/.avialview/plugins`; the bundled `examples/plugins/` directory promised by BLUEPRINT Phase 5 is never scanned; (b) no `sys._MEIPASS` handling, so **no loose plugin loads from a PyInstaller bundle**; (c) `_load_module` and the entry-point loop swallow failures and `return None`/`continue` — a broken third-party plugin vanishes with zero diagnostics; (d) module names are built from `abs(hash(path))`, which is salted per process, so bundle names are non-reproducible; (e) the six built-ins are hardcoded in `_discover()` *and* declared as entry points in `pyproject.toml:43`, so they are registered twice by two different mechanisms. |
| ~~V-11~~ | **FIXED** `0d5c378` | AGENTS trap "NEVER `import mpv` at module top level (D-013)" — the guard is incomplete | `ui/video_pane.py:101` `if not probe_libmpv(self): return` aborts `__init__` **after** the layout exists but **before** `paint_canvas`, `overlay`, `lbl_name`, `lbl_osd`, `lbl_no_footage` are created. Every later call — `set_label`, `set_tracking_readers`, `set_has_footage`, `_update_osd` — then raises `AttributeError`. On a machine without libmpv the guided dialog is followed by a crash cascade, which is exactly what D-013 exists to prevent. |
| V-12 | S1 | AGENTS §Task protocol 1 ("any PR that changes a module's public API … must update HANDOUT.md in the same commit") | Six new modules (`engine/drop_worker.py`, `engine/session_worker.py`, `engine/export_worker.py`, `loaders/aol_eks_loader.py`, `loaders/aol_encoder_loader.py`, `loaders/aol_session_loader.py`) appear **zero** times in `ARCHITECTURE.md` and **zero** times in `HANDOUT.md`. `DECISIONS.md` records no entry for the AOL format family or for the bulk `read_all_chunks` loader protocol. |
| V-13 | S1 | ARCHITECTURE §1 layering | `engine/player.py:13–16` imports `avialview.ui.plot_pane`, `ui.transport`, `ui.video_grid`, `ui.video_pane` at module scope. The engine layer depends on the UI layer, so `engine` cannot be tested or reused headlessly. `player.py:94` also reads `self.transport._bounds`, a private attribute of another widget. |
| ~~V-14~~ | **FIXED** `cdfaa39` | AGENTS §Task protocol 6 (cross-platform paranoia) | No `subprocess` call in the tree passes `creationflags=CREATE_NO_WINDOW` (grep: zero hits). `loaders/video_standard.py:71,179` (ffprobe), `engine/export.py:194` and `engine/proxy.py:70` (ffmpeg) therefore pop a console window on every probe/export in a windowed Windows build. Multi-camera load = one flashing console per camera. This is the single most visible "hiccup" on Windows. |
| V-15 | S1 | `core/source.py` `read_chunks` contract ("Chunks, **including their boundaries**, must be globally chronological. Duplicate timestamps must keep the final value.") | `CSVLoader._read_batches` implements this correctly by carrying the last row across batches. Neither AOL loader does: `AOLEksLoader.read_all_chunks` and `AOLEncoderLoader.read_chunks` validate monotonicity and de-duplicate **within each batch only**. A backward jump or a duplicate timestamp that straddles a 50 000-row boundary is silently accepted. |
| ~~V-16~~ | **FIXED** `dfb7e57` | BLUEPRINT P1-identity | Channel IDs remain globally unique strings (`plot_pane.load_channels`, `set_channel_visible`, `set_channel_unit`, readout, Parquet export all key on the bare name). The AOL work makes the collision routine rather than theoretical: `_collect_aol_candidates` enumerates `manifest.eks_files` — one per camera — and each produces channels named `nose_x`, `nose_y`, … . Loading two cameras' EKS files makes them overwrite and remote-control each other. |
| ~~V-17~~ | **FIXED** `dfb7e57` | Encapsulation / AGENTS §Arch 4 | `ui/plot_row.py:254` calls `reader._load_level(1)` — a private `PyramidReader` method — just to read the first and last timestamp. |
| V-18 | S2 | AGENTS §Arch 9 ("fitting is deterministic") | `AOLEksLoader.open` iterates `known_bodyparts`, a `set`, to strip model prefixes from column names. With hash randomization the chosen bodypart for an ambiguous suffix differs run to run, so channel names — and therefore cache keys and session files — are not reproducible. |
| V-19 | S2 | `ChannelInfo` contract | Both AOL loaders and `CSVLoader` report `rate_hz=None` ("irregular") even when the rate is known exactly (`config["fps"]` for EKS, 1 kHz-class wall clock for the encoder). Gap detection and any rate-dependent presentation fall back to the 10× median heuristic unnecessarily. |

**Not violations — confirmed still healthy, do not "fix" these:**
`core/` is PySide6-free (`mypy src/avialview/core` strict passes clean). No top-level `import mpv`.
No `shell=True`, no `QApplication.processEvents()`, no application-level QSS (`theme.py:226` clears it).
`locale.setlocale(LC_NUMERIC, "C")` is correctly placed in `__main__.py:36`. `MasterClock` is driven from
`time.monotonic()` deltas with drift hysteresis (`player.py:289`). Video probing is off-thread and
serialized against native pane creation. Plot rows query through `PyramidReader`, not raw arrays.
381 non-benchmark tests pass.

---

## 2. Repair waves

### Wave 0 — make the gate green (nothing else can be trusted until this is done)

| Task | File | Change | Proof |
|---|---|---|---|
| **W0-1** | `src/avialview/loaders/aol_eks_loader.py:105` | `dict(zip(self._xyz_channels, raw_xyz))` → add `strict=True`. The two lists are built in lockstep, so `strict=True` is correct and will now assert it. | `conda run -n avialview ruff check .` |
| **W0-2** | `tests/test_ui_main.py:231` | Wrap the 116-char comment to ≤ 100 chars. | same |
| **W0-3** | `src/avialview/engine/drop_worker.py:169–185` | Annotate both `config` locals as `dict[str, Any]` (import `Any` from `typing`). Do **not** add `# type: ignore`. | `conda run -n avialview mypy src/avialview` |
| **W0-4** | `tests/benchmarks/test_bench_pyramid.py:59` (and every sibling benchmark that subscripts `benchmark.stats`) | Guard the budget assertion: `stats = benchmark.stats;` `if stats is None: pytest.skip("benchmarks disabled")`. Do **not** delete the assertion — the ★ mark stays enforced when benchmarks run. | `QT_QPA_PLATFORM=offscreen conda run -n avialview pytest -x -q` completes |
| **W0-5** | repo root | Delete the committed `pytest_out.txt` (a stale UTF-16 console capture of a failing run) and add it to `.gitignore`. | `git status` clean |

**Wave 0 done when:** all four gate commands in §0.3 pass, plus `pytest -x -q` with benchmarks enabled.

---

### Wave 1 — S0 bugs: restore drag-and-drop and session persistence

> Root cause for W1-1 and W1-2 is identical: a `QObject` moved to a `QThread` with no owning
> reference. Fix it once, in one place, and route both call sites through it.

**W1-1 — add an owned job registry to `MainWindow`.**
File: `src/avialview/ui/main_window.py`.
Add one helper next to the other job dicts:

```python
def _run_job(self, worker: QObject, *, on_done: Signal | None = None) -> QThread:
    """Own a worker + thread pair for their whole lifetime.

    A QObject moved to a QThread with no Python reference is collected before
    ``QThread.started`` fires, so its ``run`` slot never executes.  Every
    background job in this window must be registered here.
    """
    thread = QThread(self)
    worker.moveToThread(thread)
    self._jobs[thread] = worker  # <- the reference that keeps it alive
    thread.started.connect(worker.run)
    thread.finished.connect(lambda t=thread: self._jobs.pop(t, None))
    thread.finished.connect(thread.deleteLater)
    return thread
```

Initialise `self._jobs: dict[QThread, QObject] = {}` in `__init__`.

**W1-2 — route `_start_drop_scan` (`:924`) through `_run_job`.** Delete its local
`thread = QThread(self)` / `worker.moveToThread(thread)` / `thread.started.connect(...)` lines and
call `thread = self._run_job(worker)` … `thread.start()`. Keep every existing `worker.finished` /
`worker.error` / `session_found` connection exactly as-is.

**W1-3 — route `_start_session_save` (`:444`) and `_start_session_load` (`:499`) through `_run_job`.**
Additionally: in `_start_session_save`, move `self._save_in_progress = False` into a
`thread.finished` connection as well as `on_finished`/`on_error`, so a worker that dies for any
reason cannot latch the flag permanently.

**W1-4 — make `closeEvent` autosave synchronous.**
File: `main_window.py:877`. `_autosave()` currently starts a thread and the window closes
immediately. On close, call the save **directly** (`SessionSaveWorker(state, path).run()` inline) —
this is the one legitimate blocking write, it happens after the last paint, and it is bounded.
Add a comment saying why.

**W1-5 — tests.** New file `tests/test_worker_lifetime.py`:
- `test_drop_routes_single_csv` — build `MainWindow`, monkeypatch `_start_data_import` to record
  calls, synthesise a `QDropEvent` carrying `examples/data/sensors.csv`, call `w.dropEvent(ev)`,
  pump the event loop until the recorder is non-empty or a 5 s deadline passes, assert exactly one
  `(path, CSVLoader)` call. **This test fails on today's code** — confirm that before you fix it.
- `test_drop_routes_avv_session` — same, with a `.avv` file, asserting `_start_session_load` runs.
- `test_session_save_writes_file` — call `_start_session_save(tmp_path/"s.avv")`, pump, assert the
  file exists **and** `_save_in_progress is False`.
- `test_second_save_after_first_is_allowed` — save twice in a row, assert two files.

**Wave 1 done when:** the four new tests pass, `pytest` is green, and a manual drop of a video, a
CSV, and an AOL session folder into a real window loads each one.

---

### Wave 2 — S0 accuracy: make the AOL plugins correct

**W2-1 — `AOLEncoderLoader` must honour `anchor_date`.**
File: `src/avialview/loaders/aol_encoder_loader.py`.
- In `open()`, resolve `config["anchor_date"]` (`"%Y-%m-%d"`) to a UTC epoch exactly the way
  `csv_loader._normalize_time`'s `time_of_day` branch does. Store it as `self._anchor_epoch`.
- If `anchor_date` is absent, `self._anchor_epoch = 0.0` **and** set a `provisional` flag the UI can
  surface — do not silently invent a date (AGENTS §Arch 8).
- In `read_chunks`, emit `t = seconds_since_midnight + self._anchor_epoch`.
- Add midnight-rollover handling identical to `csv_loader.py:178–182` (`dt < -43200` → `+86400`),
  applied **before** the monotonicity check.
- Test `tests/test_aol_loaders.py::test_encoder_applies_anchor_date`: a 3-row fixture at
  `23:59:59:500`, `00:00:00:500`, `00:00:01:500` with `anchor_date="2026-07-30"` must produce a
  strictly increasing epoch array spanning the midnight boundary.

**W2-2 — carry chunk boundaries in both AOL loaders (contract V-15).**
Files: `aol_encoder_loader.py`, `aol_eks_loader.py`.
Copy the pattern from `csv_loader._read_batches` verbatim: hold `pending_time` / `pending_values`,
prepend them to the next batch, yield `[:-1]`, flush the tail after the loop. Do not invent a
different mechanism — consistency over preference (AGENTS §Task protocol 9).
Test: a fixture whose duplicate timestamp and whose backward jump each straddle a batch boundary
(use `batch_size=4` in config) must de-duplicate / raise `NonMonotonicTimeError` respectively.

**W2-3 — `AOLEksLoader.read_chunks` must not re-scan per channel.**
Same file. Cache the single pass: on first call materialise nothing, but make `read_chunks` iterate
`read_all_chunks()` **once** and yield only the requested channel *while the importer is using the
bulk path* — i.e. leave `read_all_chunks` as the primary and document `read_chunks` as the
compatibility shim. The real fix is that the importer already prefers `read_all_chunks`
(`importer.py:59`); make `read_chunks` log a warning naming the O(channels) cost so a plugin author
sees it. **Do not** cache the whole file in memory to make it fast.

**W2-4 — deterministic bodypart resolution.**
`aol_eks_loader.py:87–98`: replace `known_bodyparts = set()` with a list built in skeleton order and
de-duplicated with `dict.fromkeys`, then match **longest-name-first** so `left_ear` wins over `ear`.
Test: a skeleton containing both `ear` and `left_ear` yields the same channel names on 5 consecutive
runs with different `PYTHONHASHSEED` values.

**W2-5 — initialise `_col_mapping` in `__init__`** (`aol_eks_loader.py:32`) so `channels()` /
`read_all_chunks()` before `open()` raise a typed `SourceNotOpenedError`, not `AttributeError`.

**W2-6 — declare real sample rates (V-19).** `AOLEksLoader.channels()` → `rate_hz=self._fps`
(from config). `AOLEncoderLoader.channels()` → leave `None` only if the file's median interval is
genuinely irregular; otherwise report the measured rate.

**Wave 2 done when:** `tests/test_aol_loaders.py` covers anchor-date, midnight rollover, boundary
duplicates, boundary backward-jump, and hash-seed determinism, and all pass.

---

### Wave 3 — S0 streaming: bounded-memory import

**W3-1 — stream the pyramid builder.**
File: `src/avialview/core/pyramid.py`. Add an incremental API alongside `build_and_save`:
`PyramidBuilder.append(t: np.ndarray, v: np.ndarray)` and `PyramidBuilder.finalize()`, appending
each chunk to the level-1 `.npy` on disk and folding it into the running 16×/256×/4096× extrema.
`build_and_save` stays and becomes `append(t, v); finalize()` so no existing caller changes.
Levels must stay NaN-aware (`nanmin`/`nanmax`) and gap-aware (AGENTS trap).
Tests: for three fixtures (dense regular, NaN block, gapped), assert `append`-in-N-chunks produces
**byte-identical** level arrays to a single `build_and_save`. Add the NaN-block and all-level golden
coverage BLUEPRINT's P0-accuracy row asks for while you are here.

**W3-2 — make `build_gap_mask` incremental.** It currently needs the whole `t` array. Add a
streaming variant that carries the previous chunk's last timestamp and the running median interval
estimate. Assert equality with the batch version on the same three fixtures.

**W3-3 — rewrite `importer._build_bulk_channels` to be bounded.**
File: `src/avialview/engine/importer.py`. Per chunk: validate the shared-timestamp invariant exactly
as today, then immediately `append` to one `PyramidBuilder` per channel and **drop the chunk**.
Accumulate only scalars (`total_rows`, `total_nan`, `gap_count`, `t0`, `t1`) and a **bounded**
gap-location list (cap it, and `log()` the cap — never truncate silently). Emit progress from bytes
or rows consumed, not from channel index.
Apply the same treatment to `_build_channel_by_channel` (`:205` `list(loader.read_chunks(...))`).

**W3-4 — memory test.** `tests/test_import_memory.py`: import a synthetic 20 M-sample × 4-channel
fixture and assert peak RSS growth stays under a fixed ceiling (measure with `tracemalloc` for the
Python-side arrays; a resident-set check via `psutil` is acceptable only if `psutil` is already a
dev dependency — do not add a dependency for this without a licence line in the commit message).
Add a `pytest --benchmark-only` entry recording p50/p95/p99 and peak RSS for a 1 GB import, per
BLUEPRINT's P0-streaming evidence requirement.

**Wave 3 done when:** the streaming/batch equality tests pass, the memory ceiling test passes, and
no existing pyramid or import test changed.

---

### Wave 4 — cross-OS fluidity

**W4-1 — kill the Windows console flash (V-14).**
New helper in `src/avialview/runtime.py`:

```python
def subprocess_flags() -> int:
    """Return creation flags that keep child consoles hidden on Windows."""
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0
```

Pass `creationflags=subprocess_flags()` at every `subprocess.run`/`Popen` site:
`loaders/video_standard.py:71,179`, `engine/export.py:194`, `engine/proxy.py:70`, `demo.py:110`.
Test: assert each call site passes `creationflags` (patch `subprocess.run` and inspect kwargs) — a
behavioural test is not possible headlessly.

**W4-2 — `VideoPane` must be fully constructed even without libmpv (V-11).**
File: `ui/video_pane.py:101`. Restructure `__init__` so the overlay/label/canvas widgets are built
**before** the `probe_libmpv` guard, and the early return leaves a pane that renders the
"No Footage" placeholder and no-ops every command. Every public method (`set_label`,
`set_tracking_readers`, `set_has_footage`, `open`, `play`, `pause`, `seek`, `frame_step`, `close`)
must be safe with `self.mpv is None`.
Test `tests/test_video_pane.py::test_pane_without_libmpv_is_inert`: monkeypatch `probe_libmpv` to
return `False`, construct the pane, call all nine methods, assert no exception and that
`lbl_no_footage.isVisible()`.

**W4-3 — remove the UI-thread `np.load` at plot-row creation (V-17).**
Add `PyramidReader.bounds() -> tuple[float, float] | None` to `core/pyramid.py` that reads only the
first and last element of the level-1 time mmap. Replace `plot_row.py:254`'s `reader._load_level(1)`
with it. Add `PyramidReader.is_empty()` if needed. No behaviour change; assert the coverage region
is identical before/after on an existing fixture.

**W4-4 — heartbeat test.** `tests/test_ui_heartbeat.py`: drive a populated window (2 videos +
4 channels) through open → play 2 s → scrub → resize → theme switch, sampling a 60 Hz `QTimer` and
asserting no single UI-thread callback exceeds **30 ms** (AGENTS budget hard ceiling) and the p95
stays under 8 ms. This is the test that actually defends "fluid on all OS"; everything else in this
wave is a specific cause it will catch.

---

### Wave 5 — architecture debt

**W5-1 — delete the mypy suppressions (V-07), one module per commit.**
Order (easiest first): `ui.relink_dialog`, `ui.diagnostics`, `engine.export`, `ui.readout_panel`,
`ui.video_grid`, `loaders.csv_loader`, `loaders.neo_loader`, `ui.sidebar`, `ui.video_pane`,
`ui.transport`, `ui.plot_pane`. For each: remove its `[[tool.mypy.overrides]]` block from
`pyproject.toml`, run `conda run -n avialview mypy src/avialview`, and **fix the reported errors in
the module** — never re-add the suppression, never add `# type: ignore` except for a genuine mypy
limitation with a one-line comment naming the limitation. If a module needs more than ~30 real
fixes, stop, commit what is done, and note the remainder in `HANDOUT.md`.

**W5-2 — break `engine` → `ui` imports (V-13).**
File: `engine/player.py`. Replace the four module-scope `avialview.ui.*` imports with `TYPE_CHECKING`
imports plus duck-typed parameters (the class already accepts these as constructor arguments — it
only needs the names for annotations). Replace `self.transport._bounds` (`:94`) with a public
`transport.bounds()` accessor added to `ui/transport.py`.
Test `tests/test_headless_core.py`: extend the existing PySide6-free assertion to also assert
`import avialview.engine.player` does not import `avialview.ui.plot_pane` at module scope.

**W5-3 — split `ui/main_window.py` (V-09).** Target: no module over ~500 lines. Extract along the
seams that already exist, one commit each, moving code **verbatim** (no logic changes):
1. `ui/controllers/drop_controller.py` — `dragEnterEvent`, `eventFilter`, `dropEvent`,
   `_start_drop_scan`, `_on_drop_*`, `_route_import_candidate`, `_process_drop_candidates`.
2. `ui/controllers/session_controller.py` — save/load/autosave/geometry/recent-files/`_restore_session`.
3. `ui/controllers/export_controller.py` — snapshot, data export, video clip, region stats.
4. `ui/controllers/import_controller.py` — `_start_data_import`, `_load_video`,
   `_start_next_video_load`, `_on_video_*`.
`MainWindow` keeps widget construction, the menu/shortcut table, and the controller wiring.
After each extraction the full test suite must pass **unchanged** — if a test needs editing, you
changed behaviour; revert and redo.

**W5-4 — fix the registry (V-10).** File: `core/registry.py`.
- `_default_plugin_dirs()` returns `[user_dir, bundled_examples_dir]`, where the bundled dir is
  resolved from `sys._MEIPASS` when frozen and from the package location otherwise (mirror the
  existing pattern in `runtime.py:30`).
- Replace `abs(hash(path.resolve()))` with a stable digest (`hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]`).
- Collect load failures into `self.plugin_errors: list[tuple[Path, str]]` instead of discarding them,
  and surface them in `ui/diagnostics.py`'s report.
- Pick **one** registration mechanism for the six built-ins. Recommended: keep the
  `pyproject.toml` entry points as the single source and delete the hardcoded list in `_discover()`,
  with a fallback to the hardcoded list only when `entry_points()` returns nothing (source checkout
  without `pip install -e .`). Record the choice in `DECISIONS.md`.
- Tests: a temp-dir plugin is discovered; a plugin that raises on import is recorded in
  `plugin_errors` and does not break discovery; discovery order is stable across runs.

**W5-5 — typed loader errors (V-06).** Add `SourceNotOpenedError`, `MalformedSourceError`, and
`UnknownChannelError` to `core/errors.py` if absent, and replace every bare
`ValueError`/`KeyError`/`RuntimeError` in `loaders/` and `engine/importer.py` with them. Give each
message an actionable second sentence ("Choose a different timestamp column in the import wizard.").
Add a UI test that a malformed CSV produces a dialog containing that sentence, not a bare repr.

---

### Wave 6 — channel identity (V-16) and documentation (V-12)

**W6-1 — `(source_id, channel_id)` identity.** This is the largest remaining item and BLUEPRINT
already specifies the outcome. Introduce a `ChannelKey` frozen dataclass in `core/source.py`
(`source_id: str`, `channel_id: str`) with a stable `str` form (`f"{source_id}::{channel_id}"`), and
thread it through `plot_pane.load_channels`, `set_channel_visible`, `set_channel_unit`,
`readout_panel`, the sidebar tree, and the session `.avv` schema (bump `schema_version`, add a
migration that maps old bare names onto the first matching source). Display the bare `channel_id` in
the UI; use the key everywhere else.
Fixtures required before merging: two EKS files from two cameras with identical bodypart names, and
a Parquet export from two sources with different time axes (export long-form, or prove the axes are
identical first).

**W6-2 — documentation catch-up.**
- `ARCHITECTURE.md §1`: add the six new modules to the repository map, and document the
  `read_all_chunks` bulk loader protocol in §4 as an **optional additive** extension of the frozen
  v1 contract (it is not part of v1; say so explicitly).
- `HANDOUT.md`: module map entries + a known-bugs section listing anything this plan deliberately
  deferred.
- `DECISIONS.md`: one entry each for (a) the AOL loader family and its anchor-date semantics,
  (b) the `read_all_chunks` bulk protocol, (c) the registry's single registration mechanism (W5-4),
  (d) the `ChannelKey` identity change.
- `BLUEPRINT.md §Full performance audit`: update the P0 rows this plan closes; do not mark a row
  complete without the benchmark evidence it names.

---

## 3. Suggested sequencing

Waves 0 and 1 are the whole "it's broken" story and should land first and fast — they are small,
mechanical, and each has a test that fails today. Wave 2 restores scientific correctness for AOL
sessions. Wave 3 is the only wave that touches `core/`, so it needs benchmarks unaffected-or-improved
before it merges. Wave 4 is what the user will actually feel as "fluid". Waves 5 and 6 are the debt
the refactor left; they can be interleaved with feature work as long as W5-1 proceeds module by
module and never re-adds a suppression.

Rough effort, for a model working task-by-task: W0 ≈ 1 session, W1 ≈ 1, W2 ≈ 2, W3 ≈ 3, W4 ≈ 2,
W5 ≈ 5, W6 ≈ 3.

## 4. Do not touch

- `tests/test_sync_golden.py` and any golden fixture.
- `core/timeline.py` `MasterClock` tick/drift logic — it is correct and benchmarked.
- The mpv embedding strategy (Qt OpenGL render API on Windows/macOS, native `wid` on Linux) — D-011,
  D-038. W4-2 restructures construction order only; it must not change which path is chosen.
- `locale.setlocale(LC_NUMERIC, "C")` placement in `__main__.py`.
- `theme.py`'s palette-only approach — no application-level QSS, ever.
- The naming table in `AGENTS.md §Naming`.

---

## Status — 2026-07-31

Worked after the local P3.5 branch was merged in (`73c8dbc`). One task per
commit, full gate green after each.

**Closed**

| ID | Commit | What changed |
|---|---|---|
| V-01, V-02 | merge `73c8dbc` | `_run_job` owned-worker registry adopted from this branch; drag-and-drop and session save/load work again. |
| V-03 | `dfb7e57` | `ChannelStage` streams parser chunks to disk; peak import memory is one chunk per channel. |
| V-06 | `3d6d914` | 18 bare builtins → typed errors; new `LoaderContractError`; AST guard test. |
| V-08 | `cdfaa39` | Gate is green: ruff clean, mypy full **0** errors, 561 tests passing. |
| V-10 | `02c6c5a` | `examples/plugins/` + `sys._MEIPASS` scanned, failures logged, stable module names. |
| V-11 | `0d5c378` | Missing libmpv no longer leaves a half-built pane that AttributeErrors. |
| V-14 | `cdfaa39` | `CREATE_NO_WINDOW` everywhere ffprobe/ffmpeg spawn. |
| V-16 | `dfb7e57` | `ChannelKey(source_id, channel_id)` identity throughout. |
| V-17 | `dfb7e57` | Bounded `PyramidReader` read API; `_load_level` guarded private. |

**Also closed since**

| ID | Commit | What changed |
|---|---|---|
| V-12 | `ARCHITECTURE.md` | `channel_reader`, `recent_files`, `runtime`, and the three plot helpers added; schema noted as v6. |
| V-13 | `89307ba` | All eight `engine` -> `ui` imports deferred under `TYPE_CHECKING`; `Transport.bounds` replaces the `_bounds` reach-in. AST guard test added. |
| V-19 | this commit | `CSVLoader` reports `rate_hz` when the sample proves regular sampling, and still `None` when it does not. The AOL encoder's `None` was already correct and documented. |

**Still open**

| ID | Why it is still open |
|---|---|
| V-04a, V-04b | Encoder midnight rollover and the EKS camera-token match. Both need a real session crossing 00:00 to verify against. |
| V-05 | `AOLEksLoader.read_chunks` re-scans the CSV per channel. Only the bulk path is fast; the frozen v1 API still pays N passes. |
| V-07 | 11 `ignore_errors` mypy overrides. Removing them exposes ~56 pre-existing Qt/stub errors — a wave of its own. |
| V-09 | `ui/main_window.py` is ~2 500 lines. A mixin split was implemented and **reverted**: inherited `@Slot` methods lose `sender()` and get direct instead of queued connections, which put `video_grid.add_pane` on a worker thread. See D-051 — it must be done as QObject composition. |

| V-15 | AOL loaders validate monotonicity within a batch only. |
| V-18 | `AOLEksLoader.open` iterates a `set`, so channel names are not reproducible under hash randomisation. |

**Not from this ledger, also open:** the P3.5/P4.6 populated-workload
measurements, and Phase 6 (P6.1 coverage, P6.2 community files, P6.3 release).
