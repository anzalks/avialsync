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
- **Data Streams** shows when every loaded file is available. A coloured span means the source has
  data; an empty span means it does not.
- **Shared time bar** moves every view together.
- **Left panel** lists files, visibility controls, offsets, properties, values, and annotations.

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
