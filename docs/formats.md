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
which frame is named at any moment. They are cached beside the video after the first read, so
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

Correcting a point by hand writes `<pose file>.avialfix.csv` beside the original — a plain
`frame,bodypart,x,y` table with a commented header, readable with
`pd.read_csv(path, comment="#")`. **The pose file itself is never modified**, so deleting the
corrections file restores exactly what the model predicted. Corrections can be exported either as a
corrected copy of the pose CSV, which anything that read the original will read unchanged, or as a
DeepLabCut `labeled-data` retraining set. See [Correcting a tracked
point](user-guide/index.md#correcting-a-tracked-point).

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

## Lab formats

Ask your lab for its AvialSync plugin, or see the [plugin guide](plugin-guide.md) to write one.
Plugins describe how to recognise, read, and label a format; they do not need to change the core app.
