# Video Extraction Toolbox — output schema for AvialSync

Reference for the AvialSync loader reading output from the behaviour
**video-extraction-toolbox** (MATLAB). The toolbox extracts optical-flow and
motion-energy metrics from behaviour videos, per ROI, per camera.

Everything below was measured from a real export (60 files, 3 cameras, 40
experiments across 5 recording days), not inferred from source.

Implemented by `loaders/aol_video_extraction_loader.py` (§1–§8) and
`loaders/aol_metric_loader.py` (§9). See DECISIONS.md D-081 and D-080.

---

## 1. Where the files are

The toolbox writes results back into the acquisition tree, next to the other
per-recording tool outputs:

```
<run>/<date>/<experiment>/<recording>/
├── FaceCam.mp4
├── pose-2d/default_sv/FaceCam_eks.h5
├── pose-3d/default_sv/
├── predictions/default_sv/FaceCam.csv
└── video-extraction/<variant>/          ← this document
    ├── FaceCam.mat
    ├── FaceCam.metadata.json
    ├── FrontCam.mat
    ├── FrontCam.metadata.json
    ├── SideCam.mat
    └── SideCam.metadata.json
```

`<variant>` mirrors the `default_sv` level of the pose outputs and defaults to
`default`. One `.mat` + one `.metadata.json` per camera. A camera with no
extracted metrics produces no file at all.

The same tree can be emitted under a separate root instead of in place, so a
plugin must not assume the `pose-2d` siblings exist.

---

## 2. File format

| File | Format | Read with |
|---|---|---|
| `<Camera>.mat` | MATLAB **v7.3**, which is HDF5 | `h5py` |
| `<Camera>.metadata.json` | UTF-8 JSON, single line | `json` |

**`scipy.io.loadmat` will not open the `.mat`.** It handles MAT ≤ 7.2 only; v7.3
is HDF5 and needs `h5py` (or `mat73`).

> Read labels and identifiers from the **JSON**, and only the numeric arrays from
> the HDF5. MATLAB stores cell/char arrays as HDF5 object references to `uint16`
> arrays, so pulling strings out of the `.mat` means dereferencing and
> `chr()`-decoding every one. The JSON carries the same values as plain types.
> The JSON is written whenever the `.mat` is, so treating it as required is safe.

---

## 3. HDF5 layout

Shapes below are **as `h5py` reports them**. MATLAB is column-major and declares
HDF5 dataspaces in C order, so every shape is reversed from the MATLAB view. This
is the single most common way to get this wrong.

| Dataset | h5py shape | dtype | MATLAB view | Meaning |
|---|---|---|---|---|
| `metrics/<metric>` | `(n_roi, n_col, n_frames)` | `float64` | `[n_frames × n_col × n_roi]` | the numbers |
| `timestamps` | `(1, n_frames)` | `float64` | `[1 × n_frames]` | seconds from recording start |
| `absolute_times` | `(1, n_frames)` | `float64` | `[1 × n_frames]` | POSIX seconds (UTC) |
| `sampling_rate` | `(1, 1)` | `float64` | scalar | nominal fps |
| `roi_ids` | `(n_roi, 1)` | `float64` | `[1 × n_roi]` | stable integer ROI ids |
| `roi_coordinates` | `(4, n_roi)` | `float64` | `[n_roi × 4]` | `x, y, width, height` in pixels |
| `roi_labels` | `(n_roi, 1)` | object refs | cell | ROI names — **use the JSON** |
| `metric_columns/<metric>` | `(n_col, 1)` | object refs | cell | column names — **use the JSON** |
| `metric_column_source/<metric>` | `(N, 1)` | `uint16` | char | provenance tag — **use the JSON** |
| `source/*` | `(N, 1)` | `uint16` | char | paths and camera name — **use the JSON** |
| `#refs#/*` | — | — | — | HDF5 internals, ignore |

Indexing a single channel from `metrics/<metric>`:

```python
values = arr[roi_index, column_index, :]  # 1-D, length n_frames
```

`len(timestamps) == n_frames` held for every file measured.

### Ragged fallback

If the ROIs of one camera disagree on array shape, `metrics/<metric>` is written
as a MATLAB **cell** (`1 × n_roi`) instead of a 3-D array, and `h5py` reports
`dtype == object`. This did not occur in any of the 60 measured files, but a
robust plugin should detect `dtype == object` and either dereference per ROI or
decline the file rather than mis-index it.

---

## 4. JSON sidecar

```json
{
  "tool": "video-extraction-toolbox",
  "variant": "default",
  "camera": "FaceCam",
  "metrics": ["flow_kinematics"],
  "metric_columns": {
    "flow_kinematics": ["MI","MeanFlow","TopFlow","DirCoh","Brightness",
                        "Axial","Lateral","Speed","PeakSpeed","Drift"]
  },
  "metric_column_source": { "flow_kinematics": "file" },
  "n_rois": 7,
  "roi_labels": ["Jaw","Whisker","Nose","Wheel","Caudal Forelimb","Eye","Trunk"],
  "roi_ids": [452952480448816, 542401452481478, 360664289382792, "..."],
  "source": {
    "video_path": ".../2026-05-08/experiment_1/09-35-24/FaceCam.mp4",
    "recording_path": ".../09-35-24/",
    "experiment_path": ".../2026-05-08/experiment_1/",
    "video_folder": ".../run_20260625_153823/",
    "data_root": ".../saved_analysis_data",
    "camera": "FaceCam",
    "placed_on": "2026-08-21 17:44:02"
  }
}
```

Ordering of `roi_labels`, `roi_ids` and `metric_columns[m]` matches the array
axes exactly: `roi_labels[i]` names `metrics[m][i, :, :]`, and
`metric_columns[m][j]` names `metrics[m][:, j, :]`.

### `metric_column_source` — read this

Column labels are not always a recorded fact. The tag says where they came from:

| Value | Meaning | Trust |
|---|---|---|
| `file` | stored next to the numbers at write time | authoritative |
| `context` | recorded by the extractor at extraction time | authoritative |
| `table` | inferred now from metric name + measured column count | **an inference** |
| `mismatch` | a stored label list disagreed with the data and was rejected | **suspect** |

In the measured export this was `file` for 30 files and `table` for 30. Both were
correct, but only the first 30 are self-certifying. Surface this in the UI or logs
rather than dropping it — a `table` label means "something 10 columns wide turned
up and the 10-name table for this metric was applied".

---

## 5. Channel model

One `(ROI, column)` pair is one AvialSync channel. For a 7-ROI camera with the
10-column `flow_kinematics` metric that is **70 channels** from one file.

ROI labels are user-entered and not guaranteed unique within a camera — fall back
to `roi_ids[i]`, which is stable and unique by construction, on collision.

> **AvialSync note.** The schema suggests a `"{roi_label}/{column}"` channel id.
> AvialSync uses `"{roi}_{column}"` instead: a channel name becomes a cache
> filename verbatim (`PyramidBuilder` writes `cache_dir / f"{channel_id}_t.npy"`
> with no sanitisation), so a slash would be a path separator on POSIX and is
> illegal on Windows. Two metrics in one file can also share a column name
> (`motion_index` and `flow_kinematics` both emit `MI`), so the metric is
> inserted before falling back to the ROI id. See D-081.

### `flow_kinematics` columns

| # | Name | Meaning |
|---|---|---|
| 1 | `MI` | motion energy, sum of squared pixel differences |
| 2 | `MeanFlow` | mean optical flow magnitude |
| 3 | `TopFlow` | 95th percentile flow magnitude |
| 4 | `DirCoh` | directional coherence |
| 5 | `Brightness` | mean brightness |
| 6 | `Axial` | signed flow along the ROI's principal axis of movement |
| 7 | `Lateral` | signed flow perpendicular to that axis |
| 8 | `Speed` | mean magnitude, ROI's own null floor subtracted |
| 9 | `PeakSpeed` | 95th percentile magnitude, null floor subtracted |
| 10 | `Drift` | `Axial` smoothed over ~0.5 s |

Columns 6–7 are **signed**; a back-and-forth sweep changes sign. Columns 8–9 have
a per-ROI noise floor subtracted and are clipped at zero, so a still ROI reads 0.

Two other metrics exist in the toolbox and may appear as additional `metrics/`
groups: `motion_index` (1 column, `MI`) and `optical_flow` (5 columns, `MI`
through `Brightness`). Do not hard-code 10.

---

## 6. Time base

Two parallel axes, same length as the data:

- `timestamps` — seconds from recording start, first sample `0.0`
- `absolute_times` — POSIX seconds UTC, e.g. `1778229326.312`

Measured across all 60 files: **strictly increasing, no duplicates, no
regressions.** So the `NonMonotonicTimeError` path should not trigger on
well-formed toolbox output — but keep the check, since these come from per-camera
hardware timestamp files that can be truncated.

`absolute_times` is the one to use for cross-source alignment; it comes from the
camera's own timestamp log, not from `sampling_rate × index`. For a
`SessionSource`, `anchor_epoch` is `absolute_times[0]` and `camera_fps` is
`sampling_rate`.

Measured: ~230 fps, ~13 840 frames, ~60.2 s per recording. Frame counts vary
slightly between cameras of the same recording (13834–13844), so **do not assume
cameras share a frame count or a common time grid.**

> **AvialSync note.** An AOL session's master axis is seconds since midnight UTC
> (D-045), not raw POSIX. `AOLSessionSource` passes both `anchor_epoch` and the
> camera's rebased `start_epoch`; the loader subtracts the anchor from an
> absolute axis, or adds the camera start to a relative one. Only the loader
> knows which axis the file actually carried, so the choice is made there rather
> than guessed at scan time.

### NaNs

**Every file starts with a NaN in `MI`.** `MI` is a frame-difference metric, so
frame 1 has no predecessor. Exactly 1 NaN in column 1, zero in the others.

The plugin contract requires NaNs be preserved. Do not drop, forward-fill or
zero that first sample — dropping it silently shifts the channel one frame
against every other source in the session.

---

## 7. Session-level notes

- `anchor_epoch` = `absolute_times[0]`, already UTC POSIX seconds
- `camera_fps` = `sampling_rate` (~230 Hz measured; do not hard-code)
- These are **timeseries**, not pose. The existing `pose-2d` / `pose-3d` outputs
  in the same recording folder are the `"overlay2d"` / `"pose3d"` roles; ROI
  metrics are neither and should be plain channels.
- One recording yields up to 3 files (FaceCam, FrontCam, SideCam), each an
  independent `SessionItem`, each with its own frame count and time vector.

---

## 8. The per-ROI store (upstream of the export)

Upstream of the exported files, the toolbox keeps one small file per
`(ROI, metric)` under its `data_root`, mirroring the acquisition tree:

```
<data_root>/<date>/<experiment>/<recording>/<Camera>/
├── thumbnail.mat                          reference frame for the camera
├── 284424020841330__flow_kinematics.mat   <roi_id>__<metric>.mat
└── 542401452481478__flow_kinematics.mat
```

These are MATLAB **v6**, so `scipy.io.loadmat` reads them directly:

- `roi_metric_data` — `[n_frames × n_col]` for that one ROI
- `roi_metric_columns` — optional cell of column names; **absent on older files**

There is no timestamp vector here and no ROI geometry — that lives on the
analysis object. Prefer the exported `video-extraction/` files; this store is
documented only because it is what the exporter reads from.

> **AvialSync note.** `AOLMetricLoader` reads this store, and an export
> supersedes it for the same camera: both hold the same numbers, so importing
> both would plot every ROI twice — once on real timestamps and once on
> timestamps synthesised from `index / fps`.

---

## 9. Measured reference values

From the validation export used to write this document:

| Property | Observed |
|---|---|
| files | 60 (`.mat` + `.metadata.json` pairs) |
| cameras | `FaceCam`, `FrontCam`, `SideCam` |
| metrics | `flow_kinematics` only |
| columns | 10, every file |
| ROIs per camera | 5, 6 or 7 |
| frames | 13 834 – 13 844 |
| duration | ~60.2 s |
| sampling rate | 229.998 Hz |
| timestamps | strictly increasing, no duplicates, 0 regressions |
| `len(timestamps) == n_frames` | true, every file |
| ragged/cell metrics | 0 |
| first sample NaN in `MI` | 60 / 60 files |
| `metric_column_source` | `file` ×30, `table` ×30 |
