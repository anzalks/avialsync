# Formats

AvialView is intentionally open to lab-specific formats. It includes common video and tabular-data
support, while plugins can add other recordings without changing the application itself.

## Video

Open standard video files supported by your installed mpv/ffmpeg stack, including common MP4, MOV,
MKV, AVI, and WebM files. AvialView reads the video timing and uses actual frame timestamps where
available, which matters for variable-frame-rate recordings.

## Sensor and tracking data

Delimited text data can be imported through the guided importer. It lets you identify the time
column, time units, units for channels, missing-value sentinels, and timestamp details. Tracking CSV
files can be treated as frame-indexed when that is how the source was produced.

## Lab formats

Ask your lab for its AvialView plugin, or see the [plugin guide](plugin-guide.md) to write one.
Plugins describe how to recognise, read, and label a format; they do not need to change the core app.
