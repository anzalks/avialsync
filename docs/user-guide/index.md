# User Guide

## Main areas of the window

- **Videos** show each available camera at the selected experiment time. The block under each video
  time shows timestamp-derived CFR/VFR rates, the nominal container rate when it differs, codec, and
  file size.
- **3D Tracking** shows complete XYZ tracking points beside the videos at the same experiment time.
  Drag the vertical splitter handle to give either view more space.
- **Plots** show sensor, electrode, and tracking values in a fixed oscilloscope-style time window.
  The trace grows from left to right and starts again at the left edge when the window completes.
  Set **Window limit** in `ms`, `s`, `min`, or `h`, then use the single slider to choose the shared
  visible span. A smaller limit gives fine adjustment; a larger unit gives coarse adjustment.
  Left-click a trace to move the shared playhead to that exact time across every view.
- **Data Streams** shows when every loaded file is available. A coloured span means the source has
  data; an empty span means it does not.
- **Shared time bar** moves every view together.
- **Left panel** has five tabs: **Sources** (files, visibility, offsets, properties),
  **Values**, **Messages** (prose the recording itself carries), **Changes** (everything you
  flagged, labelled, or corrected), and **Tasks** (what is loading, with a cancel where the work
  supports one — worth opening when something is taking longer than you expected).

## Where the detail lives

- Importing tables — separator, time format and unit, timezone, sentinels:
  [Tutorial: import sensor and recording data](../tutorials/importing-data.md)
- Aligning recordings: [Tutorial: align recordings](../tutorials/synchronization.md)
- Flagging frames and exporting: [Tutorial: flag frames and export](../tutorials/annotating-and-exporting.md)
- Sessions, proxies, the 3D view, plot navigation, shortcuts:
  [Sessions, proxies, and the 3D view](sessions-and-media.md)

## Aligning recordings

Three routes, in the order to try them — all covered field by field, with annotated screenshots, in
[Tutorial: align recordings](../tutorials/synchronization.md):

- **Offset** (left panel, per source) shifts a recording along the shared timeline in seconds.
  **Align → Nudge selected source earlier / later** (`Ctrl+Shift+Left` / `Right`) does the same by
  one step without leaving the keyboard, on whichever source is selected.
- **Drift** (left panel, per source) corrects a clock running fast or slow, in ppm. Reach for it
  when recordings agree at the start and separate by the end — a fixed offset cannot express that.
- **Align → Synchronize TTL / events…** fits the mapping from TTL pulses or frame triggers. Choose reference and target
  evidence, set the **TTL high threshold** (or tick **Use all samples as events** when the reference
  is already a list of event times), pick **Affine Fit** for two independent clocks or **Exact
  Index** when the reference triggered each exposure, then **Preview alignment** and read the match
  count and residual before **Accept mapping**. Nothing is applied until you accept it.

## Messages the recording carries

Many acquisition systems store prose alongside the samples — a note typed while the animal was
running, a line the software wrote when the session started. The **Messages** tab lists whatever
the loaded files carry, placed on the shared timeline, and the shared time bar shows them as their
own lane.

- **Messages are read-only.** They belong to the file and cannot be written back to it, so no cell
  in this tab can be edited. This is the difference from what the **Changes** tab holds, which is
  yours: authored, editable, and exported as your own work. The two never mix, so an exported
  annotation always says a person wrote it.
- **Selecting a row seeks the timeline** to that moment, the same as clicking a plot.
- **The filter box** narrows the list by message text, source, or stream name.
- **Notes with no time appear above the table**, not in it. A file header or a comment appended
  after the recording stopped has no place on the clock, and pinning it to the start would make it
  read as a description of the first sample.
- **Correcting a source's offset moves its messages with its samples**, because a note and the
  trace it describes are evidence from the same clock.

If the tab is empty, the loaded files carry no prose — or they were imported before AvialSync read
it, in which case re-importing once picks it up. See
[Troubleshooting](../troubleshooting.md#the-messages-tab-is-empty).

## Flagging and exporting

Covered in [Tutorial: flag frames and export](../tutorials/annotating-and-exporting.md).

- **Flag Frame** (`M`) records the current time *and*, for every loaded camera, that camera's exact
  frame index and presentation timestamp — which is what makes the export usable as a pose-model
  corrections list.
- Right-click a plot to add a marker at that moment without moving the playhead first.
- The **Changes** tab lists what you flagged; double-click a label to name it.
- **File → Export Changes…** writes your annotations, and any corrected pose data, out.
- **File → Export Snapshot / Trimmed Video Clip / Data Slice** cover images, media, and signals.
  Clips are copied rather than re-encoded, so they keep the original pixels.

## Useful controls

- **Flag Frame** creates an annotation at the current time. It appears in the **Changes** tab
  alongside any tracking corrections you have made.
- **Snapshot** writes a figure of the current moment for notes or reports: every displayed camera
  at the resolution it decoded at, the 3D pose, and the whole channel stack including rows you
  would have to scroll to see. It is composed rather than captured, so nothing is cut off at the
  edge of a pane and each camera is captioned with its own frame number, timecode, and format.
- **Fullscreen Toggle** expands the selected video view.
- Set **Window limit** and choose `ms`, `s`, `min`, or `h`, then drag the single slider below the
  plots. The slider is linear within that limit and controls every row; rows do not have separate
  scroll or zoom controls. The number updates immediately, plot refreshes are capped at the display
  cadence while dragging, and the final value renders on release, so rapid adjustment does not
  queue redraws.
- Select the small **×** beside a plot to hide it. This unchecks the same channel in the left panel.
- Unchecking a video or plot keeps it loaded but hidden through window resizing, grid changes, and
  fullscreen toggles. Hidden videos are paused until shown again, then resynchronize automatically.
- **Reset Zoom** expands the shared plot window to the full loaded timeline.
- **A/B** marks a time range for inspection or export.
- After accepting exact frame-trigger alignment, exact scrubs, pause, and frame-step land on those
  trigger timestamps for every synchronized video.

Use tooltips by resting the pointer over any button if you are unsure what it does.

## Correcting a tracked point

Pose estimates are sometimes wrong: an occluded nose lands on the wall, or a marker swaps between
two animals. Select **Fix Tracker** in the Data Streams header, or **Edit → Fix Tracker**
(`Ctrl+Shift+T`), to correct one by hand.

- Every video view accepts corrections while the mode is on, and playback stops so the frame you
  are aiming at stays still.
- Drag a marker to where the body part really is. The correction applies to that one frame of that
  one point; every other frame keeps the prediction it had.
- A corrected coordinate is drawn with a dotted ring, so a hand correction is never mistaken for
  model output. Turn the ring off under **View → Overlays → Hand-corrected marks** if you want to
  see the result plainly.
- **Edit → Undo** (`Ctrl+Z`) reverses corrections one drag at a time.
- Zooming with the wheel and panning with the middle mouse button keep working while the mode is on.

### Reviewing and exporting what you changed

The **Changes** tab lists everything you have done to the session in one place and in time order:
flagged frames, labelled ranges, and corrected tracking points. Each row says when it happened,
which recording it belongs to, and what it was — a correction names the body part, the coordinate,
and the video frame.

- Select a row to go back to it. AvialSync seeks there, selects the camera it belongs to, and rings
  the corrected point for a few seconds so you can see which one is meant.
- Double-click an annotation's detail to rename it.
- **Delete** removes the selected annotation, or restores a corrected point to what the model
  predicted. Both are undoable with `Ctrl+Z`.

**Export…** in that tab, or **File → Export Changes…**, writes your work out. Only recordings with
something to export are listed, each with a destination already filled in beside the data it came
from, which you can edit or choose with **Browse**. Three things can be written:

- **Annotations** — one CSV row per flag and camera.
- **Corrected pose data** — a full copy of the pose file with your corrections applied, for
  analysis. The scorer name is marked so the file never reads as raw model output, and a corrected
  point's likelihood is set to 1.0 so that code filtering on likelihood does not throw your
  correction away.
- **Retraining set (DeepLabCut)** — the corrected frames as `labeled-data`, with their images, ready
  to merge into a training set and retrain the network on its own mistakes. Every body part on a
  corrected frame is written, not just the one you moved, because a training label is a whole pose.
  Off by default: it decodes a video frame for each label.

Nothing is written until you choose it, and your original pose files are never modified.

### Where corrections are kept

Corrections are saved **next to the pose file**, in `<pose file>.avialfix.csv`, as soon as you make
them — there is no separate save step, and closing without saving the session does not lose them.
The file is an ordinary CSV of `frame,bodypart,x,y` with a commented header, so you can read it in
pandas (`pd.read_csv(path, comment="#")`) or a spreadsheet and see exactly what was changed by hand.

Your pose data is never modified. The imported CSV and its cache are not written to, so deleting the
corrections file restores exactly what the model predicted. Because the corrections live with the
recording rather than with the session, opening the same pose file in a different session — or on a
colleague's machine, if they have the data folder — brings them along.

The session file records only how many corrections each source had. If that number and the
corrections file disagree, or the file has gone missing, AvialSync says so instead of quietly
showing fewer points. If the recording sits somewhere that cannot be written — an archived
acquisition on read-only media — the corrections are kept in the session instead and you are told
so; save the session to keep them.

Plots and the 3D pane continue to show the imported prediction; the correction applies to the video
overlay.

## 3D tracking controls

Tracking files use the existing import path. Every complete channel triplet named `point_x`,
`point_y`, and `point_z` becomes one point in the 3D pane; incomplete triplets remain ordinary
time-series plots. The 3D pane does not guess connections between points.

- Drag with the left mouse button to orbit.
- Use the mouse wheel to zoom.
- Select **Fit View**, or double-click the view, to frame the current pose again.

## Appearance and font size

Use **View → Theme** to choose System, Dark, or Light, and **View → Font Size** to select a
system-relative text size. System follows your desktop, including a change made while AvialSync is
running, and returning to System from Dark or Light gives the appearance back to your desktop.

A switch reaches the plots — background, axis lines, tick numbers, axis titles and playhead — the
3D pose view, the pane boundaries you drag, and the controls the operating system draws, such as
scroll bars and drop-down lists.

These choices change colours, accent, and text presentation only. They do
not reset or reinterpret your shared time, seek bar, plot navigation, playback, layout, or loaded
data. A larger font may naturally reflow labels to remain readable.
