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
- **Left panel** has four tabs: **Sources** (files, visibility, offsets, properties),
  **Values**, **Messages** (prose the recording itself carries), and **Annotations**
  (the frames you flagged).

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
- **Drift** (left panel, per source) corrects a clock running fast or slow, in ppm. Reach for it
  when recordings agree at the start and separate by the end — a fixed offset cannot express that.
- **Synchronize…** fits the mapping from TTL pulses or frame triggers. Choose reference and target
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
  in this tab can be edited. This is the difference from **Annotations**, which are yours: authored,
  editable, and exported as your own work. The two never mix, so an exported annotation always says
  a person wrote it.
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
- The **Annotations** tab lists what you flagged; double-click a label to name it.
- **File → Export Annotations (CSV)** writes one row per (marker, camera).
- **File → Export Snapshot / Trimmed Video Clip / Data Slice** cover images, media, and signals.
  Clips are copied rather than re-encoded, so they keep the original pixels.

## Useful controls

- **Flag Frame** creates an annotation at the current time.
- **Snapshot** saves the current visual view for notes or reports.
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

## 3D tracking controls

Tracking files use the existing import path. Every complete channel triplet named `point_x`,
`point_y`, and `point_z` becomes one point in the 3D pane; incomplete triplets remain ordinary
time-series plots. The 3D pane does not guess connections between points.

- Drag with the left mouse button to orbit.
- Use the mouse wheel to zoom.
- Select **Fit View**, or double-click the view, to frame the current pose again.

## Appearance and font size

Use **View → Theme** to choose System, Dark, or Light, and **View → Font Size** to select a
system-relative text size. These choices change colours, accent, and text presentation only. They do
not reset or reinterpret your shared time, seek bar, plot navigation, playback, layout, or loaded
data. A larger font may naturally reflow labels to remain readable.
