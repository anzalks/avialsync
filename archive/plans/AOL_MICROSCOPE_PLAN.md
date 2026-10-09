# AOL microscope trials and AVI camera sessions — implementation plan

Status: **implemented and smoke-checked on 2026-10-09; real camera/trial pairing remains unverified.**

- **Branch:** `feat/aol-microscope-trials` in `/Users/anzalks/Documents/kinochronix`.
  The original linked-worktree path was superseded at the user's direction; all changes were
  transferred and verified in the requested checkout before implementation continued.
- **Base:** cut from `review/file-handling-performance` at `a7b3b1c`, because this plan is
  written against that branch's `video_standard.py`. Rebase onto `main` once that branch has
  merged.
- **When it ships:** move this file to `archive/plans/` and add a row to its README.

Read AGENTS.md, HANDOUT.md, and DECISIONS.md D-052, D-085, D-110, D-113, D-160, D-190 – D-196
and D-199 – D-201 before you start. Rules here add to AGENTS.md; they never relax it.

---

## 0. Binding rules for this work (read first)

### 0.1 The user's recordings are irreplaceable
The recordings in the main checkout's untracked `data/` (and `09-35-24/`) are **not** test
fixtures and are **not** in this worktree.

- Never write, move, rename, touch or delete anything under them. Open every real file with
  `h5py.File(path, "r")` or a read-only stream. Nothing the loaders build (caches, proxies,
  sidecars) may land beside a recording (D-160).
- Tests use synthetic files written into `tmp_path` (AGENTS.md task protocol rule 5). Never
  point a test, fixture or default at a real recording.
- The one real-data step is the smoke check in §10. It needs the user's go-ahead in that
  session, and it runs only with a temporary cache root and a before/after snapshot of the data
  folders. Any difference is a stop-and-report, not a fix.
- If a real file looks unreadable or missing, say so and stop. Do not regenerate or
  substitute it.

### 0.2 The microscope-controller repository is strictly read-only and never a code source
The lab's controller lives at `~/Documents/Antoine_lab_work/microscope_controller`.

- **Read-only.** No edits, no new files, and no git command that changes its state (`checkout`,
  `switch`, `pull`, `fetch`, `stash`, `reset`, `clean`, `commit`, `worktree`). Do not run its
  MATLAB, Rust, Python or test code: they can write output files.
- **No code from it, anywhere.** Do not copy, translate or port its code (MATLAB, Rust or
  otherwise) into AvialSync, its tests, its docs, a commit message or a comment. That covers
  algorithms expressed line by line in another language too. AvialSync's readers are written
  from the **file layout** described in §2, which was measured on the data files themselves.
- You may *read* its prose documentation to understand behaviour, chiefly
  `docs/advanced_doc/Hardware-Synchronization.md` and
  `docs/advanced_doc/Rig-Specific-Systems.md`. Cite a fact from it by file and section in a
  comment or D-entry, stated in your own words. The facts this plan needs are already
  summarised in §2.4.

---

## 1. What this plan delivers

All of it is scoped to **one trial at a time**:

0. **The AOL encoder's angle is no longer shown.** `encoder_angle` stops appearing as a plot
   row. It is still loaded, hidden, because the wheel prop turns from it (§3.2).
1. **AOL camera sessions recorded as AVI** (`.avi` beside `<Cam>-relative times.txt`) are
   recognised and play at their true rate. The cameras are aligned the way the MP4 sessions
   are, plus per-frame timing and one shared start (§4).
2. **Microscope-controller trials** (one `HH-MM-SS/` folder = one trial) open as a session
   (§5–§6):
   - the raw ribbon-scan ROIs, **tiled into one mosaic view**, which is the primary view;
   - where the lab's ROI analysis exists, its cell masks and traces, **shown the way NWB ROIs
     are** (D-193): an ROI grid view plus one plot row per cell.
3. **One trial, chosen by the user** (§7–§8):
   - dropping or opening a trial folder loads that trial;
   - dropping an experiment folder lists its trials and loads exactly the one picked;
   - with a camera recording loaded, AvialSync finds the trial it belongs to and, once the user
     accepts, aligns the trial to the cameras under the trigger assumption in §2.4.

**Out of scope:**

| What | Why |
|---|---|
| `params.mat` wheel fields (`behaviour/encoder/*`) | Per the user, wheel data comes only through the existing encoder path (§6.3). |
| `params.mat` `mc_log` | Windows clock, not hardware-synced, unknown zero (§2.4). |
| `thin_mask.mat`, `consolidated_offsets.mat`, `mc_confidence_score.mat` | Analysis output. |
| `*.swc`, `*.bkp`, `*.fig`, `*.png`, `*.pptx` | Not recording data. |
| `Reference_Stack.*`, `thumbnail_archive.mat` | Not recording data. |
| `sync_drift_report.csv` | Not part of this work. |
| `clock_calibration.mat` corrections | Lab-side clock fits, not part of this work. |

None of these may be claimed or loaded by the new scanners.

---

## 2. Verified facts about the data

Facts in §2.1–§2.3 were measured read-only on the user's recordings on 2026-10-09. Build
fixtures that reproduce these shapes. Anything marked **assumption** must be named as such in
the code comment and in the D-entry.

### 2.1 AVI camera recording (`09-54-35/`)

| File | Content |
|---|---|
| `FaceCam.avi`, `FrontCam.avi`, `SideCam.avi` | MJPEG, 1440×1080, container rate 230/1. Frames 2313 / 2318 / 2325, about 10.06 / 10.08 / 10.11 s. |
| `<Cam>-relative times.txt` | One row per stored frame, **whitespace (tab) separated**: `index  relative_ms  dd-mm-yyyy;HH:MM:SS.ffff`, e.g. `1	0.000	24-06-2026;09:54:40.5520`. Row count equals the container frame count exactly, and the index runs 1..N with no gaps. **All three cameras carry the identical first stamp `09:54:40.5520`**. |
| `camera_module_timing_report.mat` | MATLAB v7.3. `timing_report/camera_frame_count` [2325, 2318, 2313], `camera_frame_rates_hz` [230, 230, 230], `camera_device_duration_s`, `camera_names` (cell of char), `camera_trigger_enabled` = 1, `external_trigger_enabled` = 1. Its `datetime` fields are MATLAB objects (MCOS) that h5py cannot decode; skip them. |

There is no `trial_config.yml`, `encoder_log.txt`, `params.mat` or `labeled_videos/`.

The stamp column is the camera PC's **local time with no zone**: the folder is named
`09-54-35` and the first frame is 5.5 s later.

The MP4 reference session `09-35-24/` (repo root, git-ignored) has the same layout: 3 cameras
whose first stamps are identical (`09:35:26.3120`), plus `trial_config.yml`
(`hardware.camera_fps: 230.0`), `encoder_log.txt`, `camera_module_timing_report.mat` and a
behaviour-only `params.mat`. That `trial_config.yml` is why the bug in §3.1 never showed on MP4
sessions.

### 2.2 Microscope-controller trial (`<date>/experiment_N/<HH-MM-SS>/`)

`2026-09-03/experiment_2/` holds 16 trials, all structurally identical:

| File | Content (h5py axis order; MATLAB order is reversed) |
|---|---|
| `RibbonScan_ROI_<rrrr>_repeat_<pppp>_timepoints_<T>.mat` | v7.3. One dataset `volume`, `uint16`, shape **(C=2, T=184, Y=15 lines, X=51 px)**, chunks (2, 20, 15, 51), compressed (~400 KB). 96 files per trial (ROI 0001–0096), with `repeat_0001` only. |
| `params.mat` | v7.3. Mostly MATLAB classdef objects (`ScanParams`, `AolParams`, …) that h5py **cannot decode**; never depend on them. The readable fields are below. |
| `roi_activity/` | **Present in 1 of 16 trials** (12-33-56). The lab's ROI analysis; see §2.3. |
| others | `thin_mask.mat`, `consolidated_offsets.mat`, `mc_confidence_score.mat`, `*.swc`, `structure_reference.bkp`: out of scope. |

Readable `params.mat` fields. Cells are object-reference datasets; dereference element 0.

| Path | Meaning |
|---|---|
| `controller/aol_params` | Present in every trial. Use it as the **signature** (do not decode). |
| `timings/timing_FIFO/STARTTIME` | One float: UTC epoch in **ms**. 12-33-56 → `1788431641335` = 10:34:01.335 UTC = 12:34:01 CEST, 5.3 s after the folder name. |
| `timings/timing_FIFO/line_time` | `uint64`, length **T × R × L** = 184 × 96 × 15 = 264 960, in **5 ns ticks**. The span is 10.0013 s, which equals `timings/summary{1}`. |
| `timings/timing_FIFO/trial_time` | Empty in this data. |
| `timings/summary` | cell; element 0 = trial duration in s (10.00133). |

**Timing contract (verified).** Reshape `line_time` frame-major as `(T, R, L)` and multiply by
5e-9 s.
- **Per-ROI time:** ROI *r*'s time in frame *t* is the mean of its *L* line times. This
  reproduces the lab's `roi_activity/ROI_000{1,5,9}…/frame_time_s` to 1.8e-15 s.
- **Mosaic time:** the lab's mosaic `frame_time_s` is the **frame midpoint**, the mean over
  all R × L lines of the frame, to 1.2e-5 s.
- **Rates:** one frame takes 54.32 ms to scan, and the period is 54.35 ms (≈18.4 Hz).

### 2.3 The lab's ROI analysis (`roi_activity/`)

| File | Content |
|---|---|
| `hybrid_mosaic_repeat_<p>_activity.mat` | The mosaic-level analysis: **this is the NWB-like ROI data.** |
| `ROI_<rrrr>_repeat_<p>_activity.mat` | Per ribbon ROI. Same field names, in single-tile (15×51) coordinates. In this data every one has **empty** `masks` / `roi_traces` / `kept_roi_idx` (no cell kept). |
| `*.fig`, `*.png` | Figures: ignore. |

`hybrid_mosaic_…_activity.mat`, read-only, measured on 12-33-56:

| Field | Shape / meaning |
|---|---|
| `mosaic_info/source_roi_map` | `(150, 510)` uint16: the ribbon ROI number at every mosaic pixel, 0 = empty tile. **Authoritative tile layout.** |
| `mosaic_info/tile_size` | [51, 15] (width, lines). |
| `mosaic_info/mosaic_grid_size` | [10, 10]. |
| `masks` | cell of K = 11 logical `(150, 510)` masks in **mosaic coordinates**. A mask may span tiles: mask 11 covers ribbon ROIs 3, 4 and 5. |
| `roi_traces` | `(184, 11)` float32: one trace per mask. Also `roi_traces_raw` and `neuropil_traces`, same shape. |
| `frame_time_s` | `(1, 184)`: frame midpoint (above). |
| `contours`, `neuropil_masks` | cells per mask. |
| `mosaic_roi_report/source_roi_id` | **10** entries for **11** masks. Never assume equal lengths, and never index one by the other. |
| `projection`, `activity_movie*`, `activity_data_*` | Derived images and movies: not loaded. |
| `correction_info/green_channel` | 2 (MATLAB 1-based). |

**Measured tile order:** ribbon ROI *r* (1-based) sits at grid row `(r−1) mod 10`, column
`(r−1) div 10`, i.e. **column-major**. Tiles 97–100 are empty. Mask pixels follow the same
coordinates: `roi_traces[:, 0]` correlates 0.88 with the mean of `activity_data_pre` under
mask 0.

**Channel colour: settled by the lab's record (user decision, 2026-10-09).**
- **Green is h5py/0-based index 1; red is index 0.**
- **Source:** the lab's analysis records `green_channel = 2` (MATLAB 1-based).
- **Supporting pixels:** raw ribbon tile 5 correlates 0.30 with the lab's pre-processed mosaic
  on index 1 and −0.06 on index 0.
- **Applies to:** every trial from this controller, including the 15 without `roi_activity/`.

Rule for the implementation (§5.3):
- a trial's own `correction_info/green_channel` wins;
- otherwise use the rig default above;
- names stay editable through the D-195 channel UI.

Mind the off-by-one: MATLAB's channel `n` is 0-based index `n − 1`.

### 2.4 Synchronisation facts from the controller's documentation (paraphrased)

From `Hardware-Synchronization.md` §1 and §1.3–§1.5 and `Rig-Specific-Systems.md` §1, read only.
No code was taken.

- **Master clock.** The imaging clock (FPGA 200 MHz, 5 ns) is the reference, and
  `line_time` is latched by it. Line 0 is latched at the trial trigger.
- **`STARTTIME`.** The Windows clock read at trial start, a few ms after the trigger. It is
  absolute, but coarser than the line clock.
- **Encoder.** Hardware-triggered at trial start and end; first sample 0–2 ms after the
  trigger. Its host-side "system" timestamps are packet-reception times and must not be used
  for alignment.
- **MC log.** Windows clock, started manually, not hardware-synced, drifts by tens of ms.
  Hence out of scope.
- **Cameras.** Start is hardware-triggered from the imaging system's trigger (an FPGA edge to
  the camera PC, which generates each camera's frame pulses). Stop is **not** triggered, so the
  camera runs past the imaging window. Indeed the 09-54-35 cameras run 10.06–10.11 s against a
  10.00 s trial. Camera clock ±50 ppm, which is 0.5 ms over a 10 s trial.
- **Camera PC clock.** The camera PC is a separate machine. Its wall clock is not synced to the
  imaging PC.

**Working assumption (from the user, binding for this plan):** the microscope controller's
trigger starts **all cameras at once**, and that start is the trial's line-clock zero. So:
- every camera's frame 0 shares one instant;
- the camera PC's wall clock is used **only to find** which trial a recording belongs to, never
  to place the cameras against the trial;
- the documented camera start-delay calibration (`camera_start_offset_s` in a lab
  `clock_calibration.mat`) is not applied (no such file in this data). §11 lists it as a
  follow-up.

### 2.5 No real camera–trial pair exists
The AVI recording is from 24-06-2026 and the trials are from 2026-09-03; no trial has camera
files beside it. The pairing in §8 is **built and wired against fixtures**. 09-54-35 is the
real example of the camera half, and 12-33-56 of the trial half. State in the PR that the pairing
is not yet verified on a real pair.

---

## 3. Existing AOL loader corrections (do these first)

### 3.1 A forced 30 fps on sessions without `trial_config.yml`

`AOLManifest.camera_fps` defaults to `30.0`, and `_video_items` sends `config["fps"] =
manifest.camera_fps` whenever it is above zero. `VideoStandardLoader.open` treats `config["fps"]`
as an override and rescales every frame time by `container_fps / override`. So 09-54-35 (230
fps, no `trial_config.yml`) plays **7.67× slow**: 10 s becomes 77 s. MP4 sessions never showed
it, because their `trial_config.yml` declares 230.

Fix: record whether a rate was *declared* (`camera_fps: float | None = None`, or a
`camera_fps_declared` flag; match the module's style), and send `fps` only when declared.
Audit every reader of `manifest.camera_fps` and `SessionLayout.camera_fps`
(`grep -rn camera_fps src/`); `SessionLayout.camera_fps = 0.0` already means unknown.

Test: an AOL fixture folder with a non-30 fps video and no `trial_config.yml`. Its loaded
duration must equal the container duration within one frame.

### 3.2 `encoder_angle` is loaded but not shown (user decision, 2026-10-09)

Today `AOLEncoderLoader` (`loaders/aol_encoder_loader.py`) imports two channels,
`encoder_velocity` and `encoder_angle`, and both become plot rows. The user does not want the
angle shown.

**Why it cannot simply be dropped.** The angle is the wheel prop's driver:
- it is the `RotaryHint.channel` (D-113, `aol_session_loader._rotary_hint`);
- `ui/prop_motion.py` reads its samples to turn the wheel;
- `core/wheel.py` / `core/wheel_check.py` / `core/wheel_file.py` store and check positions
  against it.

So keep loading it, and make it **hidden by default**.

- **Use the existing visibility mechanism.** Per-channel visibility already exists
  (`PlotPane.set_channel_visible` / `is_channel_visible`, routed through the command bus in
  `core/commands.py` / `core/document.py`). Do not add a second hide mechanism.
- **Let the loader say it.** The loader is the one that knows the angle is a driver, not a
  readout, so it declares the channel hidden by default. Recommended shape: add a defaulted
  field to `ChannelInfo` (e.g. `shown: bool = True`, appended last so every existing
  constructor still works), and have the plot create a `shown=False` row hidden.
  - This is a plugin-API addition in `core/`: mypy `--strict`, a HANDOUT.md API note, and a
    D-entry.
  - If the implementer finds an existing per-channel default-visibility hook, use that
    instead and say so.
- **Keep the existing state machinery.** A saved session that shows the angle keeps showing it,
  and the user can still show it from the channel list. The default applies only to a fresh
  load, and undo/dirty state are unchanged.
- **The angle stays data.** Hiding the row must not drop its reader, cache or pyramid: the
  wheel prop, the Add Wheel dialog's channel list, and wheel checks all still find
  `encoder_angle`. Verify this in `prop_motion.py` and `ui/controllers/wheel_controller.py`.
- **Applies everywhere.** It covers a bare `encoder_log.txt` too, since it is a property of
  the loader, not of the session.

Tests:
- A fresh AOL load shows `encoder_velocity` and does not show `encoder_angle`.
- `encoder_angle` is still readable and drives a wheel binding.
- The Add Wheel dialog still offers it.
- Showing it, then saving and reopening, keeps it shown.
- Undo of show restores hidden.
- Update any existing test that asserts the angle row is visible: explain the change in the
  commit; do not weaken unrelated assertions (AGENTS.md task protocol rule 4).

---

## 4. AVI camera sessions, aligned like the MP4 ones

Prefer new small modules (e.g. `loaders/aol_camera_timing.py`) over growing
`aol_session_loader.py`, which is already 1 010 lines (AGENTS.md ~500-line guidance).

### 4.1 Detection and discovery
- Use one constant `_CAMERA_SUFFIXES = (".mp4", ".avi")`, matched case-insensitively.
- Apply it in `is_aol_session` (still filesystem-only; it runs on drop), `_add_root_videos`,
  and the `labeled_videos` fallback.
- If an `.mp4` and an `.avi` share a stem, keep the `.mp4` (an existing session must not
  change) and add a `layout.warnings` line naming the ignored file (D-085).
- Match each root video to its timing file by **exact camera stem**
  (`FaceCam.avi` ↔ `FaceCam-relative times.txt`). `_camera_label_from_labeled` splits on `_`,
  which suits labelled renders, not raw files. Add a test with a camera name containing `_`.

### 4.2 Per-frame timing from `*-relative times.txt`, for MP4 and AVI alike
`read_frame_timestamps` (video_standard.py) reads a comma-separated
`frame_number,timestamp_ns` file. The AOL format is different, so **do not pass it as-is**.

- Add `read_aol_relative_times(path) -> RecordedFrames | None`. It splits rows on whitespace:
  - column 0 is the frame counter;
  - column 1 is relative **milliseconds** (/1e3);
  - column 2 is the wall-clock stamp (start only).
- Share the validation semantics of `RecordedFrames`: ≥ 2 rows, finite, strictly increasing,
  rebased to frame 0, and `dropped` from counter steps > 1. Factor the shared checks out of
  `read_frame_timestamps` into one private helper; do not duplicate them. Anything malformed
  returns `None` with a warning, which degrades the import and never refuses it.
- Wiring: set `config["frame_timestamps"] = <path>` and `config["frame_timestamps_format"] =
  "aol_relative_ms"`. `_bind_recorded_frame_times` dispatches on the format, and the default
  stays the existing CSV reader. Writing a converted sidecar is **forbidden** (D-160). Both
  keys are part of the cache key; that is intended.
- Apply it to every AOL camera, MP4 included. This is one authority for AOL camera timing; say
  so in the D-entry, since it slightly changes existing MP4 sessions, for the better.
- When per-frame timing is bound, it wins over any `fps` override. Log the choice.

### 4.3 One shared start for all cameras (the trigger assumption, §2.4)
Today each camera gets its own `source_epoch` from its own first stamp. Under the assumption,
every camera of a session starts at **one** instant:
- `session camera start` = the **median** of the cameras' first stamps. In both real sessions
  they are identical, so the median equals them.
- Every camera's `SessionItem.source_epoch` is that one value. Per-frame times then come from
  each camera's own relative-times file.
- If the stamps spread by more than one frame period, add a `layout.warnings` line naming the
  spread. It is camera-PC stamping noise under this assumption, and worth seeing.
- Keep the existing wall-clock reading and axis convention (stamps labelled UTC, the encoder on
  seconds since midnight; D-052, D-110). This change makes the cameras share their start; it
  does not move the session's axis. See §8.3 for why no re-anchoring is needed.

### 4.4 Cross-check with `camera_module_timing_report.mat`
If present, read `camera_names`, `camera_frame_count` and `camera_frame_rates_hz` with h5py.
Decode the char cells and skip every MCOS/`datetime` field. Any disagreement between the
report, the timing file's rows and the container's frame count becomes a `layout.warnings`
line. A read failure is a warning, never an error.

### 4.5 Tests
- AVI-only folder → detected, 3 cameras each matched to its timing file.
- Parser: ms→s, tab and space separators, dropped-counter detection; non-increasing, empty
  and one-row files → `None`.
- Exact mapping: frame *k*'s master time = shared start + `relative_ms[k]/1e3`, and the
  duration equals the timing span, not 30 fps.
- Shared start: three cameras with stamps 0, +1 ms and +2 ms → one epoch (the median); a
  20 ms spread → warning.
- `.mp4` + `.avi` with the same stem → `.mp4` kept, plus a warning. A report mismatch → warning;
  the session still loads.
- Fixture videos are written with PyAV into `tmp_path`. Set **both** `stream.time_base` and
  `stream.codec_context.time_base` (AGENTS.md trap). Use MJPEG/AVI if the installed PyAV can
  mux it; skip, with the reason stated, only if it cannot.

---

## 5. Trial reader and the tiled ribbon-scan view

### 5.1 `loaders/aol_microscope_trial.py` (headless, read-only, no Qt)

```python
@dataclass(frozen=True)
class MicroscopeTrial:
    folder: Path
    start_epoch: float  # STARTTIME / 1e3 (UTC s), for matching only
    duration: float  # timings/summary{1}
    roi_files: tuple[Path, ...]  # sorted by ROI number parsed from the name
    repeat: int
    timepoints: int  # T (filename, checked against the dataset)
    lines: int  # Y
    width: int  # X
    channels: int  # C
    frame_times: np.ndarray  # (T,) frame midpoints, s from the trigger
    roi_frame_times: np.ndarray | None  # (T, R), s from the trigger
    timing_source: str
    warnings: tuple[str, ...]
```

- `is_microscope_trial(path)`: cheap. It needs `params.mat` and at least one
  `RibbonScan_ROI_*_repeat_*_timepoints_*.mat` (glob first), and only then opens `params.mat`
  to check that `controller/aol_params` exists. Never claim on the `.mat` extension.
- `read_trial(path)`: does the `STARTTIME`, `summary` and `line_time` work of §2.2. It checks
  every ROI file's `volume` shape against the first and against `timepoints_<T>`. A
  mismatched ROI file is dropped with a warning; the rest of the trial loads (D-085).
- **Fallback:** if `len(line_time) != T × R × L`, or there is more than one repeat, do not
  guess. Use `frame_times = k × duration / T`, set `roi_frame_times = None` and
  `timing_source = "uniform over trial duration (line clock unreadable)"`, and add a warning.
  The source is loaded but flagged (data dirty), never refused.
- Name the constant `_LINE_TICK_S = 5e-9` and cite §2.2 / the controller doc section in the
  comment, in your own words.

### 5.2 Mosaic layout
- If the trial has `roi_activity/hybrid_mosaic_*_activity.mat`, read
  `mosaic_info/source_roi_map` and `tile_size`: that is the layout.
- Otherwise compute the **same rule** measured in §2.3: grid side `ceil(sqrt(R))`, tile
  *r* at row `(r−1) mod side`, column `(r−1) div side`, and empty tiles NaN. Test that the
  computed layout equals `source_roi_map` for a 96-ROI fixture built like the real one.
- **No gutters**, unlike D-193's NWB grid. The lab's cell masks are defined on the gutterless
  mosaic and can cross tile borders, so gutters would break mask coordinates. The view also
  then matches the lab's own figures pixel for pixel. Record this in the D-entry.

### 5.3 `loaders/aol_ribbon_scan.py` → `AOLRibbonScanSource(ImagingSource)`: the tiles view
This is the trial's **primary** view: every ribbon ROI tiled in one picture per frame.

- `display_name()` is the kind of data (AGENTS.md naming; reuse the existing imaging kind).
  The rig goes in `SessionItem.label`, e.g. `"12-33-56 — 96 ROIs tiled (AOL ribbon scan)"`.
- `can_open` returns 0.0 for single files. Only the session scanner instantiates it, with the
  trial folder in config, and it never claims a lone `RibbonScan_*.mat`.
- **Memory.** A trial is about 54 MB of `uint16` (96 × 2 × 184 × 15 × 51 × 2 B).
  - `open()` reads all ROI volumes once and then closes every handle; do not hold 96 h5py
    files open.
  - `open()` runs on the import worker (AGENTS.md rule 3), through the path other imaging
    sources use.
  - Each frame and channel is assembled on request into a float32 mosaic, with NaN on empty
    tiles.
  - Benchmark it in `tests/benchmarks/` against "Lazy imaging random plane ≤ 50 ms".
- **Axes.** Stored `(C, T, Y, X)`; set `ImagingMetadata.shape`/`axes` honestly (D-194).
  `channel_count = 2`.
- **Channel names**, per the lab's record (§2.3):
  - if the trial's `roi_activity` holds `correction_info/green_channel`, its 1-based value
    `n` makes index `n − 1` "Green" and the other "Red";
  - otherwise use the rig default: index 1 "Green", index 0 "Red";
  - name the default as one module constant, with a comment citing §2.3.
- **Frame times.** One mosaic frame carries one time: the **frame midpoint**, the same
  convention as the lab's mosaic. Worst-case tile error is ±27 ms (half a frame). Say so in
  `timing_source`, e.g. `"line clock, frame midpoint (tiles ±27 ms)"`.
- `source_epoch` comes from §7/§8: the trial's own `STARTTIME` when opened alone, and the
  cameras' shared start once paired.

### 5.4 Tests
Use synthetic v7.3-like files written into `tmp_path` with h5py; `scipy.io` cannot write v7.3,
and the readers do not need it. Put a helper in `tests/` that writes:
- `volume` datasets `(C, T, Y, X)` `uint16`, valued `ROI·1000 + t + 500·c`, so tile placement,
  frame order and channel are asserted exactly;
- `params.mat` with `controller/aol_params` (a placeholder dataset), `STARTTIME`, `line_time`
  built from a known frame period, ROI dwell and line period, and `timings/summary` as a
  **cell object-reference dataset**, the way MATLAB stores it (`h5py.ref_dtype`, targets under
  `#refs#`, `MATLAB_class` attributes).

Assert:
- the detector accepts the fixture and rejects unrelated `.mat` folders and a lone
  `RibbonScan` file;
- per-ROI times and frame midpoints are exact;
- the fallback warns;
- a corrupt ROI file is dropped with a warning;
- the computed layout matches a `source_roi_map`;
- empty tiles are NaN;
- channel naming: with no `roi_activity`, index 1 is "Green" and index 0 "Red"; with
  `green_channel = 1`, index 0 is "Green" (proves the file value wins and the 1-based
  conversion is right);
- every file handle is closed after `open()`. On Windows an open handle blocks deleting
  `tmp_path`.

---

## 6. ROI analysis shown like NWB ROIs, and wheel data

### 6.1 Cell ROIs: grid view (`hybrid_mosaic_*_activity.mat`)
Show the lab's cell masks the way D-193 shows NWB plane-segmentation ROIs:
- one ROI-grid imaging item, one tile per mask;
- each tile shows **raw pixels** (green channel of the §5.3 mosaic) inside the mask's
  bounding box, NaN outside the mask;
- tiles sit on a near-square grid with D-193's gutters, since this grid is per cell, not
  per scan tile.

**Reuse, don't duplicate.** Read `loaders/nwb_roi_grid.py` and factor the mask → tile
geometry and the grid packing into one shared helper used by both NWB and AOL. One authority
for "how an ROI grid looks" (AGENTS.md rule 15 spirit, D-193).

- Masks are read once at open. A frame is one crop per mask from the in-memory raw volumes.
- A mask spanning several ribbon tiles (mask 11 spans ROIs 3–5) is cropped from the mosaic,
  which is exactly why §5.2 keeps mosaic coordinates.
- Label: `"12-33-56 — 11 cell ROIs (lab ROI analysis)"`.

### 6.2 Cell ROIs: traces as plot rows
- `roi_traces` `(T, K)` → K channels on `frame_time_s`. Same origin as §5.3, verified as the
  frame midpoint.
- One channel per mask, named `roi_<k>` (`k` = 1-based mask index). Channel names become cache
  filenames, so keep them Windows-safe (AGENTS.md trap).
- Put the ribbon-ROI number(s) the mask covers, read from `source_roi_map` under the mask (not
  from `mosaic_roi_report`, which has a different length), in the channel's description.
- Also offer `roi_traces_raw` and `neuropil_traces` as separate items. If the import dialog
  supports default-unchecked items, leave them unchecked; otherwise offer `roi_traces` only.
- Look first at how NWB `RoiResponseSeries` reach the plot (`loaders/nwb_session.py`,
  `nwb_loader.py`) and follow the same loader pattern.

### 6.3 Per-ribbon analysis files and the wheel
- **Per-ribbon `ROI_<rrrr>_…_activity.mat`.** When `masks` / `roi_traces` are non-empty, the
  masks are in that tile's 15×51 coordinates. Offset them into mosaic coordinates by the tile
  position and treat them like §6.1–§6.2. All are empty in this data, so validate on fixtures
  only. Empty files contribute nothing, with no warning.
- **Wheel.** Use **only the existing encoder path**: `encoder_log.txt` through
  `AOLEncoderLoader` and its `RotaryHint` (D-113).
  - Shown: `encoder_velocity`.
  - Loaded but hidden, for the wheel prop: `encoder_angle` (§3.2).
  - Not loaded (user decision): `params.mat` `behaviour/encoder/*` and the analysis file's
    `encoder_data`.
  - A trial opened without a camera session has no wheel row; that is expected.

### 6.4 Tests
Use a synthetic `hybrid_mosaic` file with
- a known `source_roi_map`,
- 3 masks, one spanning two tiles,
- known traces, with `mosaic_roi_report` deliberately shorter than the mask count.

Assert:
- grid tiles equal the raw crop under each mask, with NaN outside;
- traces arrive as K channels on the right times;
- descriptions name the right ribbon ROIs;
- the shared helper produces identical NWB grid output before and after the refactor (run the
  existing `tests/test_nwb_roi_grid.py` unchanged);
- empty per-ribbon files are a no-op.

---

## 7. One trial at a time: the session scanners

### 7.1 `loaders/aol_microscope_session.py` → `AOLMicroscopeTrialSource(SessionSource)`
- Register it in `_BUILTIN_SESSIONS` (core/registry.py), guarded like the others.
- `can_open` = `is_microscope_trial`. `AOLSessionSource` must not claim a trial folder, and
  vice versa; test both directions.
- `scan(path)` returns:
  - the tiled ribbon-scan item (§5.3);
  - if `roi_activity/hybrid_mosaic_*` exists, the ROI-grid item and the trace item(s) (§6).
- It reads metadata and file names only.
- With no camera session loaded:
  - `session_epoch = anchor_epoch = trial.start_epoch`;
  - every item declares `source_epoch = trial.start_epoch`;
  - all times are seconds from the trigger.
- Trial warnings go to `layout.warnings`.
- Out-of-scope files are not items. Check through `ui/controllers/drop_controller.py` that the
  registry does not pick them up one by one when the folder is dropped.
- If a camera session is already loaded when a trial is dropped, the trial loads as above and
  the §8 pairing proposal is offered for it at once.

### 7.2 Dropping an experiment folder
`experiment_N/` holds many trials plus a 473 MB `Reference_Stack.tif` and figures. Dropping it
must **not** load every trial, and the TIFF loader must not grab the reference stack as a side
effect.

- Recognise it as a folder whose **direct children** include at least one microscope trial.
- Present the trials and load **exactly one**. Read `drop_controller.py` and the import dialog
  first, and use the selection surface that already exists. Add no modal unless the drop flow
  already shows one (AGENTS.md rules 10–12).
- Each row shows the trial name, plus its `Log.txt` "Recording @ HH-MM-SS" lines when present
  (ROI count, duration, rate, notes such as "with cam"). Parse `Log.txt` defensively: it is
  free text and may be missing.
- Default selection: the §8 match for a loaded camera, if any. Otherwise nothing is selected,
  and nothing loads until the user picks.

### 7.3 Tests
- A trial fixture yields exactly the expected items with the trial epoch, and ignores derived
  files.
- An experiment fixture with 3 trials results in one trial's items, and the reference TIFF is
  not loaded.
- A missing or garbled `Log.txt` still lists the trials.

---

## 8. Pairing a camera recording with its trial

### 8.1 Finding the trial
- The user sets the microscope's saved-data folder once, as a setting in
  `core/settings_schema.py` (one authority, D-092).
- With a camera session loaded, the action "Find microscope trial" searches
  `<saved>/<date>/experiment_*/<HH-MM-SS>/`, reading `params.mat` metadata only, as a job
  (`MainWindow._run_job`, rule 11).
- The action registers its precondition with `MainWindow._require` (a camera session loaded),
  so it greys out with a reason (rule 15).
- Its place in the UI follows Phase 9 conventions and the user's preference for visible
  buttons over hidden menus. Read HANDOUT.md's interface section.
- **Camera start**, for matching only: the cameras' shared first stamp (§4.3). It is camera-PC
  local time.
- **Time zone, derived and never guessed.** Each trial carries its rig's UTC offset: the
  folder name is local `HH-MM-SS` and `STARTTIME` is UTC, so `offset = round_to_15min(folder −
  STARTTIME)`. For 12-33-56 that is +2 h, with a ~5 s setup residual.
  - Use the offset only if it is consistent across the day's trials.
  - Otherwise ask through the existing time-zone choice (AGENTS.md trap).
  - Assumption: the camera PC uses the same zone as the controller PC. Say so in the
    proposal.
- **Match.**
  - Candidate: the trial whose `[STARTTIME, STARTTIME + duration]` contains the converted
    camera start; failing that, the nearest `STARTTIME` within a tolerance. The PCs are not
    clock-synced, so default to ±10 s and make it a setting.
  - Zero candidates, or two within tolerance → say so with the nearest times, and pair nothing.
  - Only the day of the camera stamp is searched; handle a session that crosses midnight.

### 8.2 Aligning the pair (the user's trigger assumption)
**The trial is placed on the cameras, not the cameras on the trial.** By assumption, the
controller's trigger, which is line-clock zero, started every camera, so line-clock zero is
the cameras' shared frame 0.

- Once paired, every trial item's time zero is the camera session's shared start, on the
  camera session's own axis. The cameras, encoder log, EKS and every existing item keep the
  placement they already have.
- `STARTTIME` and the camera PC stamp are **evidence only**. The proposal shows:
  - camera start (local) and STARTTIME (UTC);
  - the derived offset and the residual (expected: seconds of PC clock difference);
  - the trial folder;
  - camera duration vs trial duration. The cameras should run a little longer, since the stop
    is not triggered.
- Nothing changes until the user accepts (AGENTS.md rule 8). Apply the placement through the
  existing accepted-mapping path, so it is undoable and dirty-tracked (rule 14). Find that path
  (sync acceptance / TimeMap, D-201) and reuse it; do not add a second mechanism.
- Camera duration shorter than the trial, or longer by more than 1 s → a warning in the
  proposal, never a block.

### 8.3 Why no re-anchoring is needed (user question 6, answered)
AvialSync reads a camera stamp such as `09:54:40.552` and labels it UTC. It is really the
camera PC's local time (UTC+2 in summer). Inside a camera session this is harmless: the
cameras, encoder log and EKS all sit on the same, consistently labelled clock, so they align
with each other. It would only matter when combined with a source on a true UTC clock, such as
the trial's `STARTTIME`, which would then sit two hours away.

"Re-anchoring" meant relabelling the camera stamps as local time and converting them to true
UTC. That would shift every existing saved session's absolute times by the zone offset.
§8.2 makes this unnecessary: the trial is placed on the cameras' trigger instant, and the zone
is needed only to *find* the trial, derived per §8.1. **Existing sessions are not
re-anchored.** Record this reasoning in the D-entry.

### 8.4 Tests (fixtures only; §2.5)
- Matching: containment, nearest within tolerance, none, and two candidates → no pairing.
- Offset derivation: +2 h, a half-hour zone, inconsistent offsets → ask, and a midnight
  crossing.
- Disabled with no camera loaded.
- After acceptance, trial frame 0 lands exactly on the cameras' shared start and no camera,
  encoder or EKS placement moves.
- Undo restores the unpaired placement.
- Camera shorter than the trial → warning.

---

## 9. Order of work

Do one slice per session if possible, and run the suite after each (AGENTS.md task protocol).

| Slice | Content | Depends on |
|---|---|---|
| S1 | §3.1 fps fix + test | — |
| S1b | §3.2 `encoder_angle` hidden by default | — |
| S2 | §4.1 AVI detection/matching | S1 |
| S3 | §4.2–4.4 relative-times timing, shared start, report cross-check | S2 |
| S4 | §5.1–5.2 trial reader, layout, synthetic v7.3 helper | — |
| S5 | §5.3 tiled ribbon-scan source + benchmark | S4 |
| S6 | §6.1–6.2 shared ROI-grid helper (NWB unchanged) + AOL cell grid + traces | S5 |
| S7 | §7 session scanner, experiment-folder choice | S5 (S6 for ROI items) |
| S8 | §8 pairing | S3, S7 |
| S9 | Docs, D-entries, smoke check (§10) | all |

---

## 10. Verification and docs

Checks for every slice:

```bash
QT_QPA_PLATFORM=offscreen conda run -n avialsync pytest -x -q
conda run -n avialsync ruff check --fix . && conda run -n avialsync ruff format .
conda run -n avialsync mypy src/avialsync/core
conda run -n avialsync mypy src/avialsync
```

In the worktree, use `PYTHONPATH=~/Documents/kinochronix-aol-microscope/src`, since the env's
editable install points at the main checkout. Run `python tools/make_fixtures.py` once inside a
fresh worktree. Check Python 3.11 (`avialsync311`) before pushing; CI minutes are scarce, so
push once.

**Smoke check on real data (S9, read-only, needs the user's go-ahead).**
1. **Before:** `find <main>/data/09-54-35 <main>/data/2026-09-03 -type f -exec stat -f '%N %z %m'
   {} + | sort > <scratch>/before.txt` (macOS `stat`). The scratch folder is outside both
   repositories.
2. **Cache:** point the cache at a fresh temporary directory; find the override in
   `core/cache.cache_root()`.
3. **Open:** a headless script kept in the scratch folder opens `09-54-35/` and `12-33-56/`
   through the session scanners. Report and compare:
   - **cameras:** about 10.06 / 10.08 / 10.11 s, about 230 Hz, one shared start, no warnings;
   - **tiled view:** 184 frames over about 10.0 s, mosaic 150×510, index 1 "Green" and
     index 0 "Red";
   - **cell ROIs:** 11, with 11 traces of 184 samples;
   - **another trial** (e.g. 12-23-08) has no ROI items and uses the computed layout.
4. **After:** repeat step 1 and `diff`. **Any difference → stop and report.**

The controller repository is not part of the check and must not be opened by it.

### Completed verification record

- `QT_QPA_PLATFORM=offscreen conda run -n avialsync pytest -x -q --ignore=tests/benchmarks`:
  **3,603 passed, 2 skipped**.
- `tests/benchmarks/test_bench_aol_ribbon.py`: **94.4 μs median** to assemble one full-size
  150×510 frame from 96 ROI files (30 ms budget).
- `ruff check .`, `ruff format .`, `mypy src/avialsync/core`, and `mypy src/avialsync` passed.
- A full unfiltered `pytest -x -q` run stopped in the existing NWB benchmark cache guard: its
  cache root was under `avialsync-screenshots-*`, while that benchmark asserts the test cache
  path contains `avialsync-cache-*`. The benchmark passes alone; the non-benchmark suite passes.
- Read-only smoke check used the requested repo's `data/09-54-35` and
  `data/2026-09-03/experiment_2` with an isolated temporary cache. It loaded three AVI cameras
  (2,313 / 2,318 / 2,325 frames; 10.052 / 10.074 / 10.104 s) without layout warnings, the
  184-frame 150×510 ribbon mosaic and 11 ROI traces from `12-33-56`, and one ribbon source from
  `12-23-08`. Before/after file-size and modification-time snapshots matched exactly.
- The plan's camera-to-controller pairing is still not verified on a real same-session pair.
  The camera and microscope-controller repositories were not used as code sources or modified.

Docs in the same change (AGENTS.md task protocol rule 1):
- **HANDOUT.md:**
  - new modules;
  - AOL camera layouts (MP4/AVI, relative times, shared start);
  - microscope trial and ROI analysis support;
  - the 30 fps bug fixed;
  - the pairing assumption and its evidence.
- **`docs/formats.md`:** both layouts, what is read and what is ignored, timing claims with
  their precision (tiles ±27 ms; camera stop untriggered), and that the pairing is unverified
  on a real pair.
- **DECISIONS.md**, next free D-numbers (D-201 was the latest when this was written):
  - (a) declared vs default camera rate;
  - (b) AOL relative times as the per-frame timing authority for all AOL cameras, with no
    converted sidecar;
  - (c) cameras share one start (trigger assumption);
  - (d) microscope trial = one session, one trial at a time, derived analysis ignored except
    the ROI analysis;
  - (e) mosaic layout without gutters and frame-midpoint times;
  - (f) cell ROIs reuse the NWB grid helper;
  - (g) pairing places the trial on the cameras, the zone is derived, and existing sessions
    are not re-anchored;
  - (h) channel naming per the lab's record: index 1 green, index 0 red, and a trial's own
    `green_channel` wins;
  - (i) `encoder_angle` loaded but hidden by default, and why it cannot be dropped (wheel
    driver, D-113).

---

## 11. Remaining questions for the user (do not decide alone)

1. **Real pair.** A camera recording and its trial from the same session, to verify §8 on
   real data. Also: where does the camera PC save, relative to the controller's saved-data
   folder?
2. **Camera start delay.** The controller documents a known camera start delay
   (`camera_start_offset_s`, one imaging cycle, in a lab `clock_calibration.mat`). Should a
   follow-up apply it when that file exists?

---

## Kickoff prompt for the implementing session

```
You are implementing AOL_MICROSCOPE_PLAN.md in AvialSync on branch feat/aol-microscope-trials,
in the worktree ~/Documents/kinochronix-aol-microscope (never the shared main folder). Read
AGENTS.md fully, then this plan (§0 first), then HANDOUT.md and the DECISIONS.md entries it
cites. The user's recordings are irreplaceable: never write to them; tests use synthetic files
in tmp_path only. The microscope-controller repository is strictly read-only and is never a
source of code: do not copy, translate or port anything from it. Do slice <S#> only. State a
short plan (files, tests, risks), implement it, run pytest/ruff/mypy, and commit with a
conventional message and no agent attribution. Anything this plan marks as an assumption or
lists in §11 is not yours to decide: leave it as specified and report it.
```
