# Data Output Schema — for AvialSync integration

Describes what this toolbox writes to disk, so an [AvialSync](https://avialsync.readthedocs.io/en/stable/index.html)
`SessionSource`/`TimeSeriesSource` plugin (see the
[plugin guide](https://avialsync.readthedocs.io/en/stable/plugin-guide.html)) can load it. AvialSync
defines no fixed manifest format — plugins parse whatever a lab's data looks like — so this
document is that contract for this toolbox's output.

## 1. Two layers, only one is machine-readable

Saving an `Analysis_Set` (`my_analysis.save(path)`) produces:

- **Primary file** — `<export_filename>` (default `optical_flow_and_MI.mat`): the whole
  `Analysis_Set` object graph (`Experiment` → `Recording` → `Video` → `ROI` →
  `Extracted_Data`), saved with `-v7.3` (HDF5). This holds ROI geometry, labels, source video
  paths and provenance, but as serialized MATLAB **classdef instances** (MCOS) with circular
  `parent_h` back-references and `dynamicprops` — not something `scipy.io.loadmat`/`h5py` can
  deserialize generically. **Do not target this file directly**; it needs MATLAB (or a
  from-scratch MCOS/HDF5 decoder) to read.
- **`data_root` folder** — `<export_filename stem>_data/` by default (e.g.
  `optical_flow_and_MI_data/`), next to the primary file (`Analysis_Set.set_default_data_root`).
  Every extracted metric and reference thumbnail is externalized here as a plain, single-variable
  `-v6` MAT-file (`Extracted_Data.saveobj`, `write_roi_metric`) — trivially readable with
  `scipy.io.loadmat`. **This is the integration surface** for a plugin.

## 2. `data_root` folder layout

```
<data_root>/
  <experiment_folder>/            sanitized basename of Experiment.path
    <recording_folder>/           sanitized basename of Recording.path
      <video_type>/                sanitized Video.video_types (camera/channel name, e.g. EyeCam)
        thumbnail.mat               one reference frame for this video (optional)
        <roi_id>__<metric>.mat       one file per (ROI, metric)
        <roi_id>__<metric>.mat
        ...
```

Always exactly 3 levels deep (experiment/recording/video_type), regardless of any extra raw
folder nesting (e.g. `Analysis_Set.expdate`) — only path *basenames* are used
(`resolve_roi_data_folder.m`).

- **Sanitization**: any character outside `[A-Za-z0-9_\-.]` becomes `_`; an empty name becomes
  `unknown` (folders) or `x` (fallback). Because of this, the sanitized folder name may not equal
  the raw experiment/recording folder name exactly (spaces, parentheses, etc. become `_`).
- **`roi_id`**: positive integer (< 2^53), the last element of `ROI.ROI_location`. Deterministic
  (SHA-256-derived, `generate_roi_id.m`) for ROIs copied via `Analysis_Set.batch_set_rois`; an
  arbitrary unique id otherwise. Not guessable from the ROI's name alone.
- **`metric`**: sanitized dynamic-property/metric name — `motion_index`, `optical_flow`,
  `flow_kinematics`, or a custom name passed to `Video.analyse(..., varname)`.
- Filename regex: `^(\d+)__(.+)\.mat$` (`parse_roi_data_filename.m`).

## 3. Contents of a `<roi_id>__<metric>.mat` file

- Single variable: `roi_metric_data` (`write_roi_metric.m` / `read_roi_metric.m`).
- A plain numeric array, **no time column**, **no header/metadata** — exactly what the
  extraction function returned for that ROI.
- Row count `T` = number of extracted frames for that video (all frames, or FFmpeg keyframes
  only if `Video.use_only_keyframes` was set for that video).
- Row order = ascending frame order in the source video.
- Column layout by built-in metric (`get_metric_column_names` in `Video.m`):

  | metric | columns (in order) |
  |---|---|
  | `motion_index` | `MI` |
  | `optical_flow` | `MI`, `MeanFlow`, `TopFlow`, `DirCoh`, `Brightness` |
  | `flow_kinematics` | `MI`, `MeanFlow`, `TopFlow`, `DirCoh`, `Brightness`, `Axial`, `Lateral`, `Speed`, `PeakSpeed`, `Drift` |
  | custom | whatever shape the custom function returns |

- `thumbnail.mat` also stores its single frame under `roi_metric_data`, as an `H x W double`
  grayscale image (CLAHE-enhanced first frame). One per video/camera folder, no `roi_id`.

## 4. Timestamps are not in `data_root` — reconstruct them

No file under `data_root` carries a time axis. To build `(timestamp_array, value_array)` pairs
for AvialSync's `read_chunks()`, reconstruct per video/camera (`Video.set_timestamps.m`), in the
priority order the toolbox itself uses:

1. A sibling **`<video_type>-relative times.txt`** file (tab-delimited, LabVIEW-style), if present
   next to the recording (in the recording folder or its parent). Columns: `frame_idx`,
   `relative_ms`, `absolute_time` (format `dd-MM-yyyy;HH:mm:ss.SSSS`), plus a trailing unused
   field. Relative timestamps are in the file's 2nd column (÷1000 for seconds); absolute time
   comes from the 3rd column.
2. Otherwise, derived from the raw video file itself: `frame_index / FrameRate` (via
   `VideoReader`), or actual FFmpeg keyframe packet times if `use_only_keyframes` was set.
3. Absolute start time, if not from the times.txt file, is inferred from the recording
   folder/path naming, or unavailable.

This provenance is also duplicated per-video inside the primary `.mat`
(`Video.extraction_context.<metric>.time_axis` / `.absolute_time_axis` / `.sampling_rate`), but
that file is the non-machine-readable Layer A from §1 — prefer reconstructing from the raw video
or the `times.txt` file over depending on it.

## 5. What `data_root` does *not* give you

- **ROI geometry/labels**: `ROI_location` (`[X Y width height id]` for rectangles, `[X Y id]` for
  pose-tracking points) and the human-readable ROI name (e.g. `"Whisker"`) exist only on the
  `ROI` object in the primary `.mat`. `data_root` filenames give you `roi_id` and `metric` only —
  no name. A `roi_id → label` lookup table isn't exported separately today.
- **Source video path**: `Video.path` (the original video file) is not duplicated under
  `data_root`. In practice the raw video usually lives at
  `<video_folder>/<experiment>/[…]/<recording>/<video_type><ext>` — the same experiment/recording/
  video_type basenames `data_root` uses, unsanitized — but this is a convention, not a guarantee
  (sanitization can collide, and `expdate`/pattern-matched nesting can add extra folder levels the
  primary `.mat` alone records precisely via `Video.path`).

## 6. Suggested AvialSync `SessionSource` mapping

Given AvialSync's plugin model (`SessionSource.scan(path, registry)` → `SessionLayout` +
`SessionItem`s; a `TimeSeriesSource` declaring `channels()` and yielding
`(timestamp_array, value_array)` chunks, with timestamps required to be monotonically increasing):

- **Session root** → `data_root/<experiment_folder>/<recording_folder>/`.
- **`SessionItem`** → one per `<video_type>` subfolder (one camera/channel stream).
- **`channels()`** → one channel per `<roi_id>__<metric>.mat` found in that folder
  (`thumbnail.mat` is a static reference image, not a time-series channel).
- **`read_chunks()`** → `value_array = scipy.io.loadmat(path)['roi_metric_data']` (columns per
  §3's table); `timestamp_array` synthesized per §4 — it is not in the file, so this step needs a
  decision (import `times.txt` if present, else probe the source video's frame rate).
- **ROI label metadata** (optional, for nicer channel names) → requires resolving `roi_id` against
  the primary `.mat`'s `ROI` objects (MATLAB, or a bespoke MCOS parser); not resolvable from
  `data_root` alone today.

## 7. Stability / cleanup notes

- The folder layout is fully deterministic from `(data_root, Experiment.path, Recording.path,
  Video.video_types)` — a plugin can walk it without ever opening the primary `.mat`.
- `Analysis_Set.cleanup_extracted_data()` prunes `data_root` entries (folders/files) that no
  longer match the live `Analysis_Set` tree or whose `roi_id` no longer exists on that video —
  i.e. `data_root` is not append-only; files can disappear across re-saves. `thumbnail.mat` is
  never pruned as a "stray" file.

## Reference source (this repo)

`Analysis_Set.m` (`save`, `set_default_data_root`, `cleanup_extracted_data`) ·
`Extracted_Data.m` (`saveobj`/`loadobj`, `bind_lazy_metric`) ·
`Video.m` (`set_timestamps`, `build_extraction_metadata`, `build_video_extraction_context`,
`get_metric_column_names`) · `helper_functions/resolve_roi_data_folder.m` ·
`helper_functions/resolve_roi_data_path.m` · `helper_functions/resolve_video_thumbnail_path.m` ·
`helper_functions/write_roi_metric.m` · `helper_functions/read_roi_metric.m` ·
`helper_functions/parse_roi_data_filename.m` · `helper_functions/generate_roi_id.m`
