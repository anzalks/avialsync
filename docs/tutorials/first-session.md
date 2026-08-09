# Tutorial: inspect a first session

This example uses one camera and one sensor file. The same steps work with several cameras and many
recordings.

## 1. Load the camera

![Load the camera](../_static/screenshots/demo_step2_video_loaded.png)

Drag the video into the window. Its name appears in the left panel and its image appears in the video
area. The readout over the video shows its time, timestamp-derived CFR/VFR rate, nominal rate, codec,
and file size. Open **Video Properties** for resolution, duration, and the complete timing evidence.

## 2. Load the recording

![Load the recording](../_static/screenshots/demo_step3_csv_loaded.png)

Drag the sensor or tracking file into the same window. The import wizard opens for delimited text,
showing the first rows as it will read them. Getting the time column, its format, and its unit right
here is what keeps everything after this honest — [Import sensor and recording
data](importing-data.md) walks every field.

The traces appear below the video.

## 3. Find an event

Drag the shared time bar until you see a meaningful event. Watch the video, traces, and values in
the left panel together — they are all showing the same instant.

For a closer look, set **Window limit** and drag the slider below the traces. Every trace keeps the
same window: they sweep left to right together and restart together, because comparing them is the
point.

## 4. Mark it

Select **Flag Frame**, or press `M`, to create an annotation at the current time. It records more
than the time: for every camera loaded, it stores that camera's exact frame index. That is what
makes the exported list usable as a corrections file for retraining a pose model — see [Flag frames
and export](annotating-and-exporting.md).

## 5. Save an observation

Use **Snapshot** (`Ctrl+E`) to save the visible video and plots, or mark a range with `[` and `]`
and export a trimmed clip or a slice of the data.

Your source files are never modified. Offsets, mappings, and annotations live in the session file
beside them.

## Next

If your recordings do not line up, [align recordings](synchronization.md) covers offsets, drift, and
fitting an alignment from TTL or frame-trigger evidence.
