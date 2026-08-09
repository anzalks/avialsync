# Tutorial: flag frames and export

This covers marking moments in a recording — a dropped tracking point, a bad frame, an event worth
returning to — and getting them, or the media around them, out of AvialSync.

The frame-flagging workflow exists for a specific job: **producing a corrections list for retraining
a pose model**. The exported CSV names the exact frame in each camera, which is what a tool like
DeepLabCut or LightningPose needs to be told what to fix.

## Flag a frame

![The Flag Frame and Snapshot buttons on the Data Streams strip](../_static/screenshots/guide_flag_and_snapshot.png)

1. **Flag Frame** (shortcut `M`) records an annotation at the current time.
2. **Snapshot** (`Ctrl+E`) saves the current visual view as an image.

You can also click directly on a plot at the moment you care about, which adds a marker there
without moving the playhead first.

**What a flag actually stores.** Not just a timestamp: for every video loaded at that moment,
AvialSync records the file path, the exact frame index, and that frame's own presentation timestamp.
That is the point — "2.47 seconds" is ambiguous across four cameras with different offsets and
frame rates, while "camera_2.mp4, frame 74" is not. This is why the frame the app displays and the
frame number it reports are resolved by the same lookup: they cannot disagree.

## Mark a range

![The A and B range markers in the transport bar](../_static/screenshots/guide_ab_range.png)

1. **`[`** sets the start of a range at the current time.
2. **`]`** sets the end.

Use `×` to clear it. A range is what the clip and data-slice exports operate on, and it also drives
A/B loop playback for reviewing the same span repeatedly.

## Review and label what you flagged

The **Annotations** tab in the left panel lists everything you have marked. Double-click a row's
label to name it — `occluded`, `bad_paw`, `stim_onset`, whatever your analysis needs. **Delete**
removes the selected row.

## Export

Everything is under **File**, and each export is a distinct job:

| Export | What you get | Use it for |
|---|---|---|
| **Export Annotations (CSV)…** | One row per (marker, camera): `label`, `comment`, `t_master`, `video_path`, `frame_index`, `media_timestamp` | A corrections list for pose-model retraining |
| **Export Snapshot…** | The current composed view as an image | Figures, notes, lab reports |
| **Export Trimmed Video Clip…** | The marked range, copied out of the source | Sharing a moment without re-encoding it |
| **Export Data Slice…** | The marked range of the loaded signals | Analysis in another tool |

A marker with no video loaded still exports, with the video columns left empty — so a flag is never
silently dropped for lack of a camera.

**Clips are copied, not re-encoded.** The exported video holds the original pixels rather than a
second generation of them, which matters when someone measures from it later. The cut is aligned to
the nearest keyframe at or before your start point, because a clip beginning mid-GOP would have no
frame to decode from.

## What is not exported

AvialSync does not write your analysis, and it never modifies a source recording. Offsets, drift,
accepted mappings, and annotations live in the session file (`.avv`) beside your data — so the
alignment a colleague sees is the one you accepted, with the evidence behind it.
