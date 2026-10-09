# AOL microscope trials and AVI camera sessions — implementation plan

Status: **open**, not started. Branch `plan/aol-microscope-trials` holds only this plan.
Implement on a new branch cut from it (or from `main` once `review/file-handling-performance`
has merged, since this plan was written against that branch's `video_standard.py`).
When the work ships, move this file to `archive/plans/` and add a row to its README.

Read AGENTS.md, HANDOUT.md, and DECISIONS.md D-085, D-110, D-160, D-190 – D-196 and D-199
before you start. Rules here add to AGENTS.md; they never relax it.

---

## 0. Data safety (read first, binding)

The real recordings described below are **irreplaceable** and live in the user's untracked
`data/` folder of the main checkout. They are **not** in this worktree and are **not** test
fixtures.

- Never write, move, rename, touch or delete anything under any `data/` directory. Open
  every real file with `h5py.File(path, "r")` or a read-only stream. Nothing the loaders
  build (caches, proxies, sidecars) may land beside a recording (D-160).
- Tests use synthetic files written into `tmp_path` (AGENTS.md task protocol rule 5).
  Never point a test, fixture or default at `data/`.
- The one real-data step is the smoke check in §9. It runs only with an
  explicit temporary cache root, and it compares a full listing and mtime snapshot of the
  data folder before and after the check. Any difference is a stop-and-report, not a fix.
- If a real file looks unreadable or missing, say so and stop. Do not regenerate or
  substitute it.

---

## 1. What this plan delivers

Two independent capabilities, both scoped to **one trial at a time**:

1. **AOL camera sessions recorded as AVI**, with per-frame timing from the camera's
   `*-relative times.txt`, are recognised and play at their true rate.
2. **Microscope-controller trials** (one `HH-MM-SS/` folder = one trial) open as a session:
   one imaging item (all ROIs tiled) plus the wheel encoder and motion-correction log as time
   series, all on the trial's own absolute clock. A trial is loaded either
   - by dropping or opening the trial folder itself, or
   - by finding, from a loaded camera recording, the single trial in the microscope's
     saved-data folder whose acquisition window contains the camera's first frame.

Never load every trial of an experiment folder at once. A dropped experiment folder offers its
trials and loads exactly the one the user picks (§7).

Out of scope here: the lab's derived analysis output (`roi_activity/`, `thin_mask.mat`,
`consolidated_offsets.mat`, `mc_confidence_score.mat`, `*.swc`, `*.bkp`, `*.fig`, `*.png`,
`Reference_Stack.*`, `thumbnail_archive.mat`, `*.pptx`). None of it may be claimed or loaded
by the new scanner. Where §10 lists it as a follow-up, that needs its own decision.

---

## 2. Verified facts about the data

Every number here was measured read-only on the user's recordings on 2026-10-09. Build
fixtures that reproduce these shapes. Anything marked **inferred** must be treated as an
assumption: name it in the code comment and in the D-entry.

### 2.1 Camera recording (`<HH-MM-SS>/`, e.g. `09-54-35/`)

| File | Content |
|---|---|
| `FaceCam.avi`, `FrontCam.avi`, `SideCam.avi` | MJPEG, 1440×1080, container rate 230/1, 2313 / 2318 / 2325 frames, ≈10.06–10.11 s |
| `<Cam>-relative times.txt` | One row per stored frame, **whitespace (tab) separated**: `index  relative_ms  dd-mm-yyyy;HH:MM:SS.ffff` — e.g. `1	0.000	24-06-2026;09:54:40.5520`. Row count equals the container frame count exactly for all three cameras. Index runs 1..N with no gaps in this recording. |
| `camera_module_timing_report.mat` | MATLAB v7.3. `timing_report/camera_frame_count` = [2325, 2318, 2313], `camera_frame_rates_hz` = [230, 230, 230], `camera_device_duration_s`, `camera_names` (cell of char), `camera_trigger_enabled`, `external_trigger_enabled`, plus MATLAB `datetime` objects (MCOS, **not decodable** with h5py; ignore them). |

No `trial_config.yml`, no `encoder_log.txt`, no `labeled_videos/`.

The wall-clock column is **local time with no zone**: the folder is named `09-54-35`
and the first frame is stamped `09:54:40.552`, about 5.5 s later. This matches the microscope
convention in §2.2, where the folder name is local time and `STARTTIME` is UTC.

### 2.2 Microscope-controller trial (`<date>/experiment_N/<HH-MM-SS>/`)

There are 16 trials under `2026-09-03/experiment_2/`. All 16 are structurally identical:

| File | Content (h5py order; MATLAB order is reversed) |
|---|---|
| `RibbonScan_ROI_<rrrr>_repeat_<pppp>_timepoints_<T>.mat` | v7.3. One dataset `volume`, `uint16`, shape **(C=2, T=184, Y=15, X=51)**, chunks (2, 20, 15, 51), compressed (~400 KB on disk). There are 96 files per trial (ROI 0001–0096), and every trial has only `repeat_0001`. |
| `params.mat` | v7.3. Mostly MATLAB classdef objects (`ScanParams`, `AolParams`, `StackParams`, …) that h5py **cannot decode**; do not depend on them. The readable parts are listed below. |
| others | `thin_mask.mat`, `consolidated_offsets.mat`, `mc_confidence_score.mat` (all written days later by analysis), `hybrid_scan.swc`, `simplified_neuron.swc`, `structure_reference.bkp`, and optionally `roi_activity/` — all out of scope (§1). |

Readable `params.mat` fields. Cells are object-reference datasets, so dereference element 0:

| Path | Shape / meaning |
|---|---|
| `controller/aol_params` | Exists in every trial. Use it as the **signature** dataset (do not decode it). |
| `timings/timing_FIFO/STARTTIME` | One float: **UTC epoch in milliseconds**. 12-33-56 → `1788431641335` = 2026-09-03 10:34:01.335 UTC, i.e. 12:34:01 CEST, 5.3 s after the folder name. |
| `timings/timing_FIFO/line_time` | `uint64`, length **T × R × L** = 184 × 96 × 15 = 264 960, in **5 ns ticks** from trial start. The span is 2.0003e9 ticks = 10.0013 s, which equals `timings/summary{1}` = 10.00133 s. |
| `timings/summary` | cell; element 0 = trial duration in s (10.00133). |
| `behaviour/encoder/wheel_angle`, `wheel_speed` | (1, 10001) float64 each. |
| `behaviour/encoder/wheel_speed_time` | (1, 10001) float64, **seconds from trial start**: 0.0016 … 10.0012. Some trials hold 10 002 samples, so never hard-code the length. |
| `behaviour/encoder/wheel_system_time` | 0.104 … 10.104: a second clock offset by about 0.1 s. Not used (see §10). |
| `mc_log/Time` | (N, 1), N ≈ 5 700, seconds 0 … ≈10.18, **irregularly sampled**. |
| `mc_log/{X,Y,Z}_{correction,difference}` | (N, 1) each: six motion-correction channels on `mc_log/Time`. |
| `controller/rig_params/encoder_wheel_radius` | 0.0125 (m, **inferred**). |
| `controller/rig_params/camera_record_trigger` | `PXI1Slot6/port0/line0`: the microscope hardware-triggers camera recording. |

**Timing contract (verified, not inferred).** Reshape `line_time` frame-major as
`(T, R, L)` and multiply by 5e-9 s. ROI *r*'s time for frame *t* is the mean of its *L*
line times. In 12-33-56 this reproduces the lab's own `roi_activity/ROI_000{1,5,9}…/frame_time_s`
to 1.8e-15 s. One frame takes 54.32 ms to scan all 96 ROIs, and the frame period is
54.35 ms (≈18.4 Hz, matching `Log.txt`'s "@18 Hz").

**Inferred (state these as assumptions):**
- Channel index 1 (0-based) is green: the lab's analysis records `green_channel = 2` (1-based).
  Channel 0 is probably the red PMT (`controller/red_pmt` exists). Name channel 1 "Green" and
  leave channel 0 unnamed until the user confirms (D-195: never invent names).
- `wheel_speed_time`, `mc_log/Time` and `line_time` share zero = `STARTTIME`. The
  `line_time` end matches `timings/summary`, but the other two are inferred.
- Units of `wheel_speed` are unknown. Leave the unit empty and do not convert.
- The `line_time` layout is verified only for `repeat_0001`. With more than one repeat, or
  whenever `len(line_time) != T × R × L`, fall back (§5.3).

### 2.3 The two example folders do not belong together

The camera folder is from 24-06-2026 and the trials are from 2026-09-03; none of these
trials has camera files beside it, even where `Log.txt` says "with cam". **No real pair exists
to validate §8.** Matching is proven on fixtures only, and §10 asks the user for a real pair.

---

## 3. Bug to fix first: a forced 30 fps on sessions without `trial_config.yml`

`AOLManifest.camera_fps` defaults to `30.0`, and `_video_items` passes
`config["fps"] = manifest.camera_fps` whenever it is above zero. `VideoStandardLoader.open`
treats `config["fps"]` as an override and rescales every frame time by `container_fps /
override`. A 230 fps AOL camera with no `trial_config.yml` therefore runs 7.67× slow: 10 s
becomes 77 s.

Fix: the manifest records whether a rate was *declared*. Make `camera_fps: float | None = None`,
or keep the float and add a `camera_fps_declared: bool`; match whichever the module's style
favours. Send `fps` only when it was declared. Check every reader of `manifest.camera_fps`
and of `SessionLayout.camera_fps` (`grep -rn camera_fps src/`); `SessionLayout.camera_fps = 0.0`
already means "unknown".

This changes behaviour for any existing MP4 session that has no `trial_config.yml`. That is
correct, but it is a change: say so in the D-entry and in HANDOUT.md known bugs (fixed).

Test: an AOL fixture folder whose videos are encoded at a non-30 rate with no
`trial_config.yml`. Assert that the loaded duration equals the container duration within one
frame. The fixture videos are 640×360 (AGENTS.md traps); that is fine here because rate is the
point.

---

## 4. AVI camera sessions (`loaders/aol_session_loader.py`)

### 4.1 Detection and discovery
- Use one module constant `_CAMERA_SUFFIXES = (".mp4", ".avi")`, matched case-insensitively.
- `is_aol_session`: a root video with one of those suffixes (or `labeled_videos/`) plus at
  least one `*-relative times.txt`. Keep the check filesystem-only; it runs on drop.
- `_add_root_videos` and the `labeled_videos` fallback use the same suffix set. Skip
  dot-files as before.
- If an `.mp4` and an `.avi` share a stem, keep the `.mp4` (an existing session's choice must
  not change) and add a `layout.warnings` line naming the ignored file (D-085).
- Match each video to its timing file by **exact camera stem** (`FaceCam.avi` ↔
  `FaceCam-relative times.txt`). `_camera_label_from_labeled` splits on `_`, which is right for
  labelled renders but not a matching rule for raw files; use `video.stem` for root videos.
  Today `video_start_epochs` is filled through `_camera_label_from_labeled`, and that happens
  to work for these names. Keep it working and add a test with a camera name containing `_`.

### 4.2 Per-frame timing from `*-relative times.txt`
`read_frame_timestamps` (video_standard.py) reads a comma-separated
`frame_number,timestamp_ns` file. The AOL file is a different format, so **do not pass it
through as-is**.

- Add `read_aol_relative_times(path) -> RecordedFrames | None` in the AOL session module, or a
  small sibling module if that file would grow past AGENTS.md's ~500-line guidance (it is
  already 1 010 lines, so prefer a new `loaders/aol_camera_timing.py`). Parse whitespace-split
  rows: column 0 is the frame counter, column 1 is relative **milliseconds** (divide by 1e3),
  and column 2 is the wall clock (used only for row 0 start, as now).
- Reuse `RecordedFrames` and its validation semantics: at least 2 rows, finite, strictly
  increasing, rebased to the first frame, and `dropped` from counter steps > 1. Factor the
  shared checks out of `read_frame_timestamps` into one private helper instead of duplicating
  them. Return `None` with a warning on anything malformed (a degraded import, never a
  refusal).
- Wiring: `VideoStandardLoader._bind_recorded_frame_times` reads `config["frame_timestamps"]`
  as a path. Add `config["frame_timestamps_format"] = "aol_relative_ms"`. The loader dispatches
  on it, and the default stays the existing CSV reader. The alternative of writing a converted
  sidecar is **forbidden** (D-160). Both keys are hashed into the cache key; that is
  intended.
- `start_time` stays 0. The camera is placed by `SessionItem.source_epoch`, as today (D-110).
- Do not send `fps` when per-frame timing is bound (§3 already ensures this when no config is
  declared). If both are present, per-frame timing wins and the override is skipped. Log it.

### 4.3 Cross-check with `camera_module_timing_report.mat`
If present, read `timing_report/camera_names`, `camera_frame_count` and
`camera_frame_rates_hz` with h5py. Decode the char cells; skip every MCOS/`datetime` field.
For each camera, if the timing file's row count or the container's frame count differs from
the report, add a `layout.warnings` line. If the report says the camera was externally
triggered, record that on the manifest; §8 uses it. Read failures are warnings, never errors.

### 4.4 Wall clock is local, not UTC (do not change silently)
Today `build_manifest` parses the wall clock and tags it `tzinfo=UTC`. For this rig it is
local time (§2.1). Re-anchoring existing AOL sessions would move every saved session's
placement, so **do not change that default in this work.** §8 resolves the zone explicitly
for matching. Record the discrepancy in the D-entry and in HANDOUT.md as a known issue, with
the AGENTS.md trap ("Timezone-naive timestamps: force an explicit user choice") as the
eventual fix.

### 4.5 Tests (`tests/test_aol_avi_session.py`, or extend `test_aol_loaders.py`)
- AVI-only folder is detected; the manifest lists the 3 cameras with matched timing files.
- The relative-times parser covers ms→s, tab and space separators, dropped-counter detection,
  non-increasing rows → `None`, an empty file → `None`, and a short file → `None`.
- Loaded video exact mapping: the master time of frame *k* equals `relative_ms[k]/1e3` plus
  the epoch, and the duration equals the timing file's span, not 30 fps.
- `.mp4` + `.avi` with the same stem → `.mp4` kept, plus a warning.
- Report mismatch → warning present; session still loads.
- Fixture videos: write them with PyAV into `tmp_path` (set **both** `stream.time_base` and
  `stream.codec_context.time_base` — AGENTS.md trap). Use MJPEG in `.avi` if the installed
  PyAV can mux it; check `av.codecs_available`, and skip with a stated reason only if it
  cannot.

---

## 5. Microscope trial reader and imaging source

New modules. Keep each under ~500 lines.

### 5.1 `loaders/aol_microscope_trial.py` (headless, no Qt)
Pure readers returning plain dataclasses, all read-only:

```python
@dataclass(frozen=True)
class MicroscopeTrial:
    folder: Path
    start_epoch: float          # STARTTIME / 1e3, UTC seconds
    duration: float             # timings/summary{1}
    roi_files: tuple[Path, ...] # sorted by ROI number parsed from the name
    repeat: int
    timepoints: int             # T, from the filename, checked against the dataset
    lines: int                  # Y
    width: int                  # X
    channels: int               # C
    roi_frame_times: np.ndarray | None  # (T, R) seconds from start, or None (fallback)
    warnings: tuple[str, ...]
```

- `is_microscope_trial(path) -> bool`: cheap. It needs `params.mat` plus at least one
  `RibbonScan_ROI_*_repeat_*_timepoints_*.mat` (glob first). Only then open `params.mat` and
  check that `controller/aol_params` exists. Never claim on the `.mat` extension alone.
- `read_trial(path) -> MicroscopeTrial`: parses `STARTTIME`, `summary`, and `line_time`
  (→ `(T, R, L)` × 5e-9, mean over L). It also checks every ROI file's `volume` shape against
  the first and the filename's `timepoints_<T>`. A mismatched ROI file is dropped with a
  warning, never a failure of the whole trial (D-085).
- `read_encoder(path)` and `read_mc_log(path)` return arrays plus time vectors. Dereference
  cell refs; tolerate an empty or missing cell with a warning.
- Name the tick constant (`_LINE_TICK_S = 5e-9`) with a comment citing the verification
  (span = `timings/summary`).

### 5.2 `loaders/aol_ribbon_scan.py` → `AOLRibbonScanSource(ImagingSource)`
One imaging item per trial that **tiles every ROI into one picture per frame**, consistent
with D-193 (`loaders/nwb_roi_grid.py`). Reuse its layout and gutter conventions instead of
inventing new ones: read that module first and factor a shared grid-layout helper if one
does not already exist.

- `display_name()` is the kind of data (AGENTS.md naming), e.g. reuse the existing imaging kind.
  The rig goes in the `SessionItem.label`, e.g. `"12-33-56 — 96 ROIs (AOL ribbon scan)"`.
- `can_open` returns 0.0 for a single file. This source is only ever instantiated by the
  session scanner with an explicit config (the trial folder). It must never claim a lone
  `RibbonScan_*.mat`.
- Memory: a trial is 96 × 2 × 184 × 15 × 51 × 2 B ≈ 54 MB of `uint16`. Read all ROI volumes
  once in `open()`. `open()` runs on the import worker (AGENTS.md rule 3) through the
  existing job path, so check how other imaging sources are opened before adding anything.
  Then close every file handle. Do not hold 96 open h5py files.
- Assemble each frame on request from the in-memory volumes into a float32 grid with NaN
  gutters (D-193). This is a cheap copy of 96 small tiles; budget it against "Lazy imaging
  random plane ≤ 50 ms" with a benchmark in `tests/benchmarks/`.
- Axes: stored `(C, T, Y, X)`; set `ImagingMetadata.shape`/`axes` honestly (D-194).
  `channel_count = 2`, `channel_names = ("", "Green")` per §2.2.
- **Frame times:** ROIs within one frame are scanned up to 54 ms apart, and one mosaic frame
  can carry only one time. Use the **mean line time across all ROIs of that frame** (frame
  midpoint), so the worst-case error for any tile is ±27 ms (half a frame). Put this in
  `timing_source`, e.g. `"line clock (frame midpoint; ROIs ±27 ms)"`, so the viewer states it.
  Per-ROI exact times stay available on `MicroscopeTrial.roi_frame_times` for the follow-up in
  §10.
- `source_epoch = trial.start_epoch`; frame times are seconds from `STARTTIME`.

### 5.3 Fallback when the line clock does not fit
If `len(line_time) != T × R × L`, or more than one repeat exists, do not guess a layout. Use
uniform times `t = k × duration / T`, set `timing_source = "uniform over trial duration
(line clock unreadable)"`, and add a warning to the layout. That is a loaded-but-flagged
source (data dirty), never a refusal.

### 5.4 Tests (`tests/test_aol_microscope_trial.py`, `tests/test_aol_ribbon_scan.py`)
Write a **synthetic v7.3-like** trial into `tmp_path` with h5py. `scipy.io` cannot write
v7.3, and none is needed: the readers use h5py only. Use a `tests/` helper that writes:
- `volume` datasets of `(C, T, Y, X)` `uint16` with a known per-ROI, per-frame value pattern
  (e.g. value = ROI·1000 + t), so tile placement and frame order are asserted exactly;
- `params.mat` with `controller/aol_params` (any placeholder dataset), `timings/timing_FIFO/
  STARTTIME|line_time` and `timings/summary`, the encoder and `mc_log` as **cell
  object-reference datasets**, exactly as MATLAB stores them (`h5py.ref_dtype`, targets
  under `#refs#`), plus the `MATLAB_class` attributes;
- `line_time` built from a known frame period, ROI dwell and line period.

Assert:
- the detector accepts the trial and rejects a folder of unrelated `.mat` files and a lone
  `RibbonScan` file;
- per-ROI times equal the mean of the line block, and mosaic times equal the frame midpoint;
- the fallback path engages on a wrong-length `line_time` and warns;
- a corrupt ROI file is dropped with a warning while the rest load;
- channel order and axes match;
- every file handle is closed after `open()` (on Windows an open handle blocks deletion of
  `tmp_path`, which would make this test fail there).

---

## 6. Trial time series and the session source

### 6.1 Time series
Add a time-series loader for a trial's `params.mat` streams. First check whether an existing
loader pattern for "one file, several named channels with their own time vectors" already
fits, e.g. how `AOLVideoExtractionLoader` or the NWB loader handles irregular timestamps.
Prefer extending that pattern over a new mechanism.

- **Wheel:** `wheel_angle` and `wheel_speed` on `wheel_speed_time`. Fill `SessionLayout.rotary`
  (`RotaryHint`) the same way the AOL encoder does, if it fits. Unit of speed stays empty
  (§2.2).
- **Motion correction:** six channels on `mc_log/Time` (irregular; do not resample).
- Both declare `source_epoch = trial.start_epoch`.
- Use a separate item and label per stream, so the user can uncheck them in the import dialog.

### 6.2 `loaders/aol_microscope_session.py` → `AOLMicroscopeTrialSource(SessionSource)`
- Register it in `_BUILTIN_SESSIONS` (core/registry.py), guarded like the others.
- `can_open(path)` uses `is_microscope_trial`. Check its score against `AOLSessionSource`,
  which must not claim a trial folder, and vice versa. Add a test for both directions.
- `scan(path)` returns one imaging item and the time-series items. It sets
  `session_epoch = anchor_epoch = trial.start_epoch` and forwards trial warnings into
  `layout.warnings`. The scan opens nothing heavy: it reads `params.mat` metadata and file
  names only.
- Out-of-scope files in the folder are not items, and the registry must not pick them up one
  by one when the folder is dropped. Verify that through `drop_controller`.

### 6.3 Tests
- Dropping (scanning) a synthetic trial yields exactly 1 imaging item + the series items, all
  with the trial's epoch.
- Labels carry the trial name.
- Derived files present in the folder are ignored.

---

## 7. One trial at a time: dropping an experiment folder

An experiment folder (`experiment_N/`) holds many trials plus a 473 MB `Reference_Stack.tif`
and analysis figures. Dropping it must **not** load 16 trials, and must not let the TIFF loader
grab the reference stack as a side effect.

- Recognise an experiment folder as one whose child directories contain at least one
  microscope trial (by `is_microscope_trial`, checking children only, not recursively).
- Present the trials and load **exactly one**. Read `drop_controller.py` and the import
  dialog first, and use whatever selection surface already exists. Do not add a modal unless
  the existing flow already shows a dialog for the drop (AGENTS.md rules 10–12). Each row
  shows the trial name and, if `Log.txt` exists, its matching "Recording @ HH-MM-SS" lines
  (ROI count, duration, rate, note such as "with cam"). Parse `Log.txt` defensively: free
  text, may be missing.
- Default selection: the trial matched to a loaded camera (§8) if there is one. Otherwise
  none is pre-selected, and nothing loads until the user picks.
- Never auto-load "all".

Tests: an experiment folder fixture with 3 trials results in a single trial's items; the
reference TIFF is not loaded; and `Log.txt` absent or garbled still lists the trials.

---

## 8. Finding the trial for a loaded camera recording

Goal: with an AOL camera session loaded, the user points at the microscope's saved-data
folder once (remembered in `core/settings_schema.py`; D-092 gives it one authority).
AvialSync then proposes the one trial that belongs to the video.

Evidence and rule (rule 8: evidence-based, never silently applied):
- The camera start instant is the first frame's wall clock from §4.2 (local, naive).
- The trial window is `[STARTTIME, STARTTIME + duration]` (UTC).
- **Time zone:** do not guess. The trial itself proves its rig's offset: its folder name
  `HH-MM-SS` is local time and `STARTTIME` is UTC, so `offset = round_to_15min(folder_local −
  STARTTIME_utc)`. For 12-33-56 that is +2 h, and the residual of ~5 s is the setup delay
  seen on both rigs. Use that offset only if it is consistent across the candidate trials.
  If it is ambiguous, ask the user through the existing timezone choice (AGENTS.md trap). Say
  in the proposal which offset was used and why.
- The candidate is the trial whose window contains the converted camera start, or failing
  that, the one whose `STARTTIME` is nearest, within a tolerance (default ±10 s; make it a
  setting). The microscope hardware-triggers the camera (`camera_record_trigger`), so expect
  the camera start to fall at or just after `STARTTIME`. Show the residual.
- Zero or several candidates → say so with the nearest times; load nothing.
- The proposal shows the camera start, trial window, offset, residual and folder. Nothing
  loads until the user accepts it, and the result is one trial added to the current session.
- Where this action lives (menu item, source-card button) follows Phase 9 conventions. Read
  HANDOUT.md's interface section and the user's preference for visible buttons over hidden
  menus. Register its precondition with `MainWindow._require` (a camera session loaded) so it
  greys out with a reason (rule 15).
- The search walks `<saved dir>/<date>/experiment_*/<HH-MM-SS>/`. Use the date from the
  camera's wall clock to read only that day's folder, and read `params.mat` metadata only. Run
  it as a job (`MainWindow._run_job`, rule 11).

Tests (fixtures only; §2.3):
- exact containment;
- nearest within tolerance;
- none;
- two equidistant trials → no proposal;
- offset derivation, including a half-hour zone;
- inconsistent offsets → asks;
- day boundary (camera at 23:59:58 local, trial after midnight UTC);
- the action is disabled with no camera loaded.

Real-data validation is **blocked** until the user provides a camera recording and its trial
from the same session. State this in the PR; do not claim the feature verified on real data.

---

## 9. Order of work, verification and docs

Do one slice per session if possible. Run the suite after each one (AGENTS.md task protocol).

| Slice | Content | Depends on |
|---|---|---|
| S1 | §3 fps fix + test | — |
| S2 | §4.1 AVI detection/matching + tests | S1 |
| S3 | §4.2–4.3 relative-times parser, loader dispatch, report cross-check + tests | S2 |
| S4 | §5.1 trial reader + synthetic v7.3 helper + tests | — |
| S5 | §5.2–5.3 ribbon-scan imaging source + benchmark | S4 |
| S6 | §6 time series + session source + registry + tests | S5 |
| S7 | §7 experiment-folder trial choice + tests | S6 |
| S8 | §8 camera → trial matching + tests | S3, S6 |
| S9 | Docs + D-entries + smoke check | all |

Checks before each commit:

```bash
QT_QPA_PLATFORM=offscreen conda run -n avialsync pytest -x -q
conda run -n avialsync ruff check --fix . && conda run -n avialsync ruff format .
conda run -n avialsync mypy src/avialsync/core
conda run -n avialsync mypy src/avialsync
```

In a worktree use `PYTHONPATH=<worktree>/src`, because the env's editable install points at the
main checkout. Run `python tools/make_fixtures.py` once inside a fresh worktree. Also run
3.11 (`avialsync311`) before pushing (CI minutes are scarce; push once).

**Smoke check on real data (S9, read-only).** Run it only after the user agrees to it in that
session.
1. Before: `find <data>/09-54-35 <data>/2026-09-03 -type f -exec stat -f '%N %z %m' {} +
   | sort > /tmp/<scratch>/before.txt` (macOS `stat`).
2. Point the cache at a fresh temporary directory; check `core/cache.cache_root()` for the
   override mechanism.
3. Open `09-54-35/` and one trial folder through the session scanners in a headless script
   kept in the scratch folder, never in the repo. Report each camera's duration and fps, the
   trial's imaging shape, frame-time span and channel names, and the series lengths. Expect
   cameras ≈10.06–10.11 s at ≈230 Hz, imaging 184 frames over ≈10.0 s, and encoder ≈10 001
   samples.
4. After: repeat step 1 and `diff`. **Any difference → stop and report** (CLAUDE.md data
   rule).

Docs in the same change (AGENTS.md task protocol rule 1):
- HANDOUT.md: new modules in the module map; supported AOL layouts (MP4/AVI cameras, relative
  times, microscope trial); the 30 fps bug fixed; the local-vs-UTC known issue (§4.4).
- `docs/formats.md`: both layouts, what is read, what is ignored, and the timing claims and
  their precision (±27 ms tile time).
- DECISIONS.md, using the next free D-numbers at implementation time (D-201 was the latest when
  this was written). Cover: (a) declared vs default camera rate; (b) AOL relative-times as a
  per-frame timing format, no converted sidecar; (c) microscope trial = one session,
  one-trial-at-a-time, derived analysis files ignored; (d) mosaic frame time = frame midpoint
  and the fallback; (e) camera→trial matching evidence and timezone derivation.

---

## 10. Open questions for the user (do not decide these alone)

1. Is channel 0 the red PMT? Until confirmed, it stays unnamed.
2. What are the units of `wheel_speed`, and what does `wheel_system_time` represent?
3. Should a follow-up offer **one ROI at its exact line-clock times** (no ±27 ms) beside the
   mosaic?
4. Should the derived `roi_activity/*_activity.mat` traces (ΔF/F-like `roi_traces`,
   `frame_time_s`) ever be loadable? They are empty for 12-33-56 (no ROI kept).
5. A real camera recording and its microscope trial from the same session, to validate §8.
   Where does the camera software save relative to the microscope's saved-data folder?
6. Should the AOL camera wall clock be re-anchored from "assumed UTC" to local time with an
   explicit zone (§4.4)? That shifts existing saved sessions, so it needs a migration decision.

---

## Kickoff prompt for the implementing session

```
You are implementing AOL_MICROSCOPE_PLAN.md in AvialSync. Read AGENTS.md fully, then this plan,
then HANDOUT.md and the DECISIONS.md entries it cites. Work in your own git worktree beside the
main checkout, never in the shared folder. The user's data/ folder is irreplaceable: never write
to it; tests use synthetic files in tmp_path only. Do slice <S#> only. State a short plan
(files, tests, risks), implement it, run pytest/ruff/mypy, and commit with a conventional
message and no agent attribution. Anything this plan marks "inferred" or lists in §10 is not
yours to decide: leave it as specified and report it.
```
