# Formats

AvialSync is intentionally open to lab-specific formats. It includes common video and tabular-data
support, while plugins can add other recordings without changing the application itself.

## Video

AvialSync decodes video itself and needs nothing installed alongside it, so what it can open is
whatever its bundled FFmpeg supports — 272 video decoders, including H.264, HEVC, VP8/VP9, AV1,
MPEG-4, MJPEG, ProRes, DNxHD, FFV1, and DV. This no longer varies with how a machine's own FFmpeg
happened to be compiled.

Common containers — `.mp4`, `.m4v`, `.mov`, `.mkv`, `.webm`, `.avi`, `.mpg`, `.ts`, `.mts`,
`.m2ts`, `.wmv`, `.flv`, `.ogv`, `.3gp`, `.dv`, `.mxf`, `.vob`, `.y4m` — are recognised from the
file name. **A recording with an unfamiliar extension is still opened**: AvialSync reads its header
and accepts it if it genuinely holds video, so a rig that names its files something of its own
works without anyone extending a list.

Still images are deliberately refused even though FFmpeg would open a PNG as a one-frame video, and
tables, arrays, and audio are left to the loaders that understand them.

Raw formats such as `.bin` are the exception, and unavoidably so: they carry no header describing
resolution, pixel format, or rate, so nothing can infer how to read them. Those belong in a
[plugin](plugin-guide.md), which can declare the parameters and convert on import.

### Timing comes from the frames, not the container

AvialSync reads every frame's own presentation timestamp rather than trusting the rate a container
declares. That matters more often than it sounds: a camera running at a varying exposure trigger
routinely writes a file claiming a constant 30 fps, and its own timestamps prove otherwise.

Those timestamps decide whether a recording is treated as CFR or VFR, where a frame step lands, and
which frame is named at any moment. They are cached in the per-user cache folder after the first read, so
opening it again does not walk the file a second time.

## Sensor and tracking data

Delimited text data can be imported through the guided importer. It lets you identify the time
column, time units, units for channels, missing-value sentinels, and timestamp details. Tracking CSV
files can be treated as frame-indexed when that is how the source was produced.

### Pose estimates

**DeepLabCut and LightningPose** multi-index CSVs are recognised by their own header — a `scorer`
row above a `bodyparts` row — rather than by their file name, and are read as frame-indexed. Each
body part becomes a channel; any complete `name_x` / `name_y` / `name_z` triplet also becomes a
point in the 3D pane.

Correcting a point by hand writes `pose_csv_avialfix.csv` (for a `pose.csv`) beside the original — a plain
`frame,bodypart,x,y` table with a commented header, readable with
`pd.read_csv(path, comment="#")`. **The pose file itself is never modified**, so deleting the
corrections file restores exactly what the model predicted. Corrections can be exported either as a
corrected copy of the pose CSV, which anything that read the original will read unchanged, or as a
DeepLabCut `labeled-data` retraining set. See [Correcting a tracked
point](user-guide/index.md#correcting-a-tracked-point).

### Vicon Nexus motion capture

Drop a Vicon session folder containing `.c3d` trials, matching `.xcp` calibration files, and the
camera AVI files. AvialSync reads marker positions directly from C3D; it does not use companion CSV
exports. The XCP video-camera calibration projects the 3D markers into that camera's image, and the
session scanner pairs each trial to its AVI by the calibrated camera's device ID. Intrinsics,
Vicon radial distortion, and video-resolution scaling are applied before projection. The markers are
sampled onto the video frame grid and use the normal per-source tracking overlay controls. A trial
without a usable calibrated video-camera entry or a uniquely matching AVI is reported and left out
of the overlay rather than projected with guessed calibration. When importing a C3D separately,
assign its matching AVI as the overlay target; AvialSync reads that video's dimensions and scales
the XCP projection to its pixel grid.

To open one trial, copy its `.c3d`, matching `.xcp`, and camera AVI into a separate folder and drop
that folder onto AvialSync. The review dialog lists the paired video and tracking file, with the
Vicon labels, combined 3D-pose/2D-overlay role, and XCP calibration preselected. Confirm the rows to
load native XYZ markers in the 3D view and their calibrated projection on the paired video. If you
drop the files individually, choose **3D Marker Tracking** for the `.c3d`, select the XCP in the
**Calibration (XCP)** column, then choose the combined 3D-pose and 2D-overlay role for its AVI. The
`.xcp` is not imported as tracking data, and `.x2d` is not currently supported as a tracking source.

## Acquisition recordings

Electrophysiology and instrument recordings are read through [neo](https://neo.readthedocs.io), so
the formats it supports arrive in the same shape as everything else: continuous streams become
plots, and TTL lines become a square wave drawn from their edges rather than a dense trace.

**Open Ephys** folders are recognised as whole sessions. Drop the recording folder — or the folder
holding it and the cameras recorded beside it — and the streams, TTL lines, and videos are laid out
together on the recording's own clock, with wall-clock time taken from the recording's own
`sync_messages.txt` rather than assumed.

Both Open Ephys layouts are read, including the free text each one stores:

- **Binary format** (GUI v0.6 and later) — messages typed into the GUI's Message Center.
- **Original format** (`.continuous` files, earlier versions) — the messages saved in
  `messages.events`.

In both cases the recording's sync preamble is used to place the clock and is not listed as a
message: it is what the software wrote about the recording, not something a person typed.

## Neurodata Without Borders (NWB)

An `.nwb` file holds a whole session — electrophysiology, imaging, behaviour, trials — and
AvialSync opens it as one. Drop the file (or choose it with **File → Open**) and the review lists:

- **NWB Time Series**: every time series in the file, one plot row per column, named by where the
  series sits (`ophys.DfOverF.RoiResponseSeries.roi12`, `Position.SpatialSeries.x`) so that two
  series with the same name stay apart, and grouped in the channel list on those dots. Columns are
  named after what they measure where the file says: electrodes by their id (`ch17`), ROIs by
  theirs (`roi12`), spatial series by axis. Values are scaled by the file's `conversion`,
  `channel_conversion` and `offset`, and shown in its units (`volts` reads as V).
- **NWB Imaging**: each imaging series stored in the file (two-photon, one-photon, any
  `ImageSeries`) as its own video pane, named after the series. The frames are written once into a
  lossless copy in the cache, pixel for pixel, so 16-bit data keeps its full range for the
  display-level controls. The first open takes a moment per series; later opens are immediate.
- **Videos the file points to**: an `ImageSeries` that names an external video file is opened from
  beside the NWB file, placed at the time the series says its first frame was.

Everything is placed on the file's own clock, with no alignment step: every NWB timestamp counts
from the file's `timestamps_reference_time` (normally its `session_start_time`), which becomes the
session's zero, and times read as wall clock.

Trials, epochs, and any other interval table become a row that is 1 inside an interval and 0
outside it, plus one message per row listing its columns (`trials 3 · 12.3–14.1 s · condition=left`).
`IntervalSeries` (reward, licking epochs) become the same kind of row. Spike-sorted units become one
row per unit, high for an instant at each spike. Text annotations become messages.

What cannot be shown is listed when the file opens rather than skipped silently: series whose data is
not a signal over time (spike waveforms, frequency decompositions), a video the file names but that
is not beside it, and a start time recorded without a time zone (read as UTC).

Versions: NWB 2.x files stored as HDF5, including types from extensions, which are recognised from
the specification each file carries. **NWB 1.x** and **Zarr-backed NWB** are named as such when
dropped, with what to convert them to; files on DANDI must be downloaded first.

## Trigger and TTL files

Delimited text carrying pulses rather than data: a DAQ export with a time column and one or more
logical lines, or a camera log with one timestamp per exposure. Open these through **Align → Open
Trigger Evidence…** rather than as sensor data — they are evidence about *when things happened*,
and nothing in them is plotted.

AvialSync reads the header and offers every column that looks like a trigger line. You then say
what each one is, because the file cannot: whether a line is a camera's exposure strobe, an
external frame trigger, a shared sync pulse train, or a handful of landmarks. That declaration
decides which alignment models are available, so nothing is assumed for you — every column is
offered as a sync train until you say otherwise. See
[the alignment tutorial](tutorials/synchronization.md) for what each kind licenses.

One file may carry several lines about different cameras. What you declared is saved with the
session; the pulses are re-read from the file each time it loads.

## Lab formats

Ask your lab for its AvialSync plugin, or see the [plugin guide](plugin-guide.md) to write one.
Plugins describe how to recognise, read, and label a format; they do not need to change the core app.
