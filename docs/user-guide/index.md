# User Guide

## Main areas of the window

- **Videos** show each available camera at the selected experiment time.
- **3D Tracking** shows complete XYZ tracking points beside the videos at the same experiment time.
  Drag the vertical splitter handle to give either view more space.
- **Plots** show sensor, electrode, and tracking values in a fixed oscilloscope-style time window.
  The trace grows from left to right and starts again at the left edge when the window completes.
- **Data Streams** shows when every loaded file is available. A coloured span means the source has
  data; an empty span means it does not.
- **Shared time bar** moves every view together.
- **Left panel** lists files, visibility controls, offsets, properties, values, and annotations.

## Useful controls

- **Flag Frame** creates an annotation at the current time.
- **Snapshot** saves the current visual view for notes or reports.
- **Fullscreen Toggle** expands the selected video view.
- Drag the single **Window** slider below the plots for continuous shared X-axis zoom. It controls
  every plot row; rows do not have separate scroll or zoom controls.
- Select the small **×** beside a plot to hide it. This unchecks the same channel in the left panel.
- **Reset Zoom** expands the shared plot window to the full loaded timeline.
- **A/B** marks a time range for inspection or export.

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
