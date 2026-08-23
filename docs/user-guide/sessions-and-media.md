# Sessions, proxies, and the 3D view

The parts of day-to-day use that are not alignment, annotation, or import.

## Sessions

**File → Save Session…** writes a `.avv` file recording which sources you loaded, their offsets and
drift, any accepted mappings and the evidence behind them, your annotations, and the layout. **File
→ Open Session…** restores it.

A session stores *paths*, not copies. Your recordings stay where they are and are never modified,
which means a session is small and safe to share with a colleague — provided they can reach the
same files.

The session is also written automatically: periodically while you work, before the window closes,
and before a video pane is torn down. That last one is deliberate: losing a session
mid-experiment because a source was removed would cost everything since the last save.

### When files have moved

Opening a session whose files are no longer where they were shows the **Missing Files** dialog. Each
missing entry gets a **Browse…** button to point at its new location; the rest of the session loads
around it. A session with one moved file is not a broken session, so it does not refuse to open.

## Proxies

**File → Generate Proxy…** re-encodes a video so every frame is a keyframe.

Scrubbing normally costs one seek plus however many frames sit between the nearest keyframe and the
one you want. On long-GOP footage — a transcode with 250 frames between keyframes — that is the
difference between instant and noticeably slow. In a proxy there is nothing to decode forward: a
seek costs exactly one frame wherever it lands.

Worth doing for long-GOP or heavily compressed footage. Not worth doing for all-intra recordings,
which are already every-frame-keyframe and where a proxy would only cost disk. The lab's own
high-speed footage is usually already all-intra.

The proxy is written beside the source with a `_proxy` suffix, generation runs in the background
with progress, and it can be cancelled — a cancelled proxy deletes its partial file, so
nothing is left behind that looks finished.

## The 3D tracking view

Any complete channel triplet named `point_x`, `point_y`, and `point_z` becomes one point in the 3D
pane. Incomplete triplets stay ordinary time-series plots.

- **Drag** with the left mouse button to orbit.
- **Wheel** to zoom.
- **Fit View**, or a double-click in the view, re-frames the current pose.
- Drag the vertical splitter to give the 3D pane or the videos more room.

The pane draws the pose at the current time only — it never scans or renders a whole trajectory on a
clock tick.

Connections between points come from the session when it declares a skeleton — for an AOL folder,
that is the `skeleton:` block in `trial_config.yml`. An AOL session that declares none falls back to
the rig's own chain, from one toe up the forelimb to the head bar and down the other side, using
only the body parts that session's EKS export contains. When neither applies, AvialSync detects a
skeleton from the movement itself: two markers that keep the same distance apart
however the animal moves are on one rigid segment, and those are the pairs it joins. A detected
skeleton is drawn **dashed**, thinning as it runs away from the topmost point, and the pane says
`detected` beside the point count — it is a reading of your data, not something the recording
claimed. Names are never used to decide anatomy. Use **Bones:** in the pane header to keep the
detected skeleton (`Detected`), turn bones off entirely (`Off`), or return to `Auto`, which prefers
whatever the session declared.

## Plot navigation

Plots are a fixed oscilloscope-style window, not a scrolling strip. The trace fills left to
right and restarts at the left edge when the window completes.

- **Window limit** sets the span, in `ms`, `s`, `min`, or `h`. Pick the unit first: a smaller unit
  gives fine control, a larger one gives coarse.
- The single slider below the plots sets the visible span and controls every row together. Rows do
  not zoom or scroll independently — they share one time axis because comparing them is the point.
- **Reset Zoom** returns to the full loaded timeline.
- The small **×** beside a plot hides that row, which also unchecks it in the left panel.

Everything drawn goes through a decimation pyramid, so a 180-million-sample channel draws one
column per pixel instead of attempting every point. Gaps in the data are drawn as breaks, and NaN
is skipped, never plotted as zero.

## Appearance

**View → Theme** offers System, Dark, or Light. **View → Font Size** offers a system-relative size.

These change colours and text only. They do not reset or reinterpret your shared time, seek bar,
plot navigation, playback state, layout, or loaded data — an appearance change is never allowed to
disturb what you are looking at.

## Keyboard shortcuts

**Help → Keyboard Shortcuts** lists every registered shortcut, grouped by category, read from the
actions themselves — so it is accurate for the version you are running, unlike a list in a
document that drifts.

The ones worth knowing without looking:

| Key | Action |
|---|---|
| `M` | Flag the current frame |
| `Ctrl+E` | Export snapshot |
| `[` and `]` | Mark the start and end of a range |
| `F11` (`Ctrl+Cmd+F` on macOS) | Toggle fullscreen on the active video |
| `J` / `K` / `L` | Shuttle back, pause, shuttle forward |

`Ctrl+V` and `Ctrl+D` are deliberately *not* bound to opening files — those belong to paste and
duplicate everywhere else, and rebinding them would be a trap. Opening uses `Ctrl+Shift+V` for video
and `Ctrl+Shift+D` for data.
