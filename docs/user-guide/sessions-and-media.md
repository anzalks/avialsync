# Sessions, proxies, and the 3D view

The parts of day-to-day use that are not alignment, annotation, or import.

## Sessions

**File → Save Session…** writes a `.avv` file recording which sources you loaded, their offsets and
drift, any accepted mappings and the evidence behind them, your annotations, and the layout. **File
→ Open Session…** restores it.

Use **Reset Session** in the **Sources** tab's **Open Files** section to close every loaded source and
clear annotations, messages, synchronization evidence, and timeline state before opening or dropping a
different recording. It does not modify your recordings, sidecar caches, or an already-saved `.avv` file.

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

## Undoing what you did

**Edit → Undo** (`Ctrl+Z`) and **Redo** (`Ctrl+Shift+Z`) cover every change you make to a session:
an offset, an accepted mapping, a flagged frame, a channel you hid, a tracking correction. The Edit
menu names the specific thing it is about to reverse, so you can tell what `Ctrl+Z` will take back
before pressing it.

Loading a file is not an edit and does not enter the undo history. Neither does anything that only
affects appearance.

## Nothing blocks you, and nothing is lost on quit

AvialSync never puts a dialog between you and a file, and never asks you to save before doing
something else.

- **A damaged or partly-unreadable file still opens**, as far as it can be read, and reports what it
  could not read rather than refusing the whole thing.
- **Quitting always quits.** There is no "save your changes?" prompt in front of Open, a drag and
  drop, Open Recent, or the close button, and a wedged import cannot trap you in a window that
  refuses to close. A recovery snapshot is written on quit and on each autosave instead, and the
  next launch offers it back: a line in the notification strip naming when the work is from, with a
  **Restore** button beside it. Restoring loads it as an unsaved session, so the title keeps its
  `[*]` until you save it somewhere you chose. **Dismissing the offer declines it without deleting
  anything** — the snapshot stays until a later quit replaces it in the ordinary way. The autosave
  interval and whether a snapshot is kept at all are under **Preferences → Storage**.
- **Long work is never modal.** Imports, proxy generation, and exports report in the status area and
  the **Tasks** tab, with a cancel where the work supports one, and you can keep using the window
  while they run.

## Preferences

**File → Preferences…** collects everything configurable in one dialog, generated from the
application's own settings list, so each entry carries its explanation and its own **Reset to
default**. It holds the theme and font size, the colour-vision-safe trace palette, whether the A–B
range loops, live plot presentation, whether body-part names are drawn by default, whether display
levels for high-bit-depth video are chosen automatically, the autosave interval, and whether a
recovery snapshot is kept.

The View menu still offers theme, font size, and time display directly; they are the same settings,
not a second copy.

## Overlays on the video

**View → Overlays** switches every graphic drawn over a camera view: tracking points, body-part
names, the track legend, hand-corrected marks, the camera name, and the timecode and format
readout. Anything a plugin draws appears here too — nothing is drawn over your video that you
cannot account for.

Right-click a video pane and use **Overlays on this camera** to override one camera without changing
the others; **Follow the View menu** puts it back. Overlay choices are remembered with the session.

Two are listed but cannot be switched off, and say why when you ask: the **No Footage** placeholder,
because hiding it would leave an empty pane looking like a camera that simply had nothing to show,
and the **Fix Tracker handles**, because hiding them would leave that mode nothing to grab.

## Named layouts

**View → Workspace → Save Current Layout…** stores the window geometry, every splitter position, and
the selected inspector tab under a name; picking that name later restores it. Aligning two
recordings wants tall plots and small video, and checking a tracking overlay wants the opposite —
this is so you do not rearrange the splitters each time.

A layout belongs to you and your screen, not to the recording, so workspaces are kept with your
application settings rather than in the `.avv` file. **Delete Layout…** removes one.

## Finding a command

**Help → Commands…** opens a searchable list of everything the application can do, with each entry's
current shortcut beside it. Type part of a name to filter. It is built from the live menu actions,
so it cannot list a command that does not exist or miss one that does — useful for the overlay
switches in particular, which are otherwise three levels into a menu.

## Keyboard shortcuts

**Help → Keyboard Shortcuts** lists every registered shortcut, grouped by category, read from the
actions themselves — so it is accurate for the version you are running, unlike a list in a
document that drifts. **Shortcuts can be rebound there**: your choice is stored per action and
layered over the default, so a later release that changes a default still reaches you if you never
expressed a preference for that one.

The ones worth knowing without looking:

| Key | Action |
|---|---|
| `M` | Flag the current frame |
| `Ctrl+E` | Export snapshot |
| `[` and `]` | Mark the start and end of a range |
| `F11` (`Ctrl+Cmd+F` on macOS) | Toggle fullscreen on the active video |
| `J` / `K` / `L` | Shuttle back, pause, shuttle forward |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo, redo |
| `Ctrl+Shift+T` | Fix Tracker |
| `Ctrl+Shift+←` / `→` | Nudge the selected source earlier or later |

`Ctrl+V` and `Ctrl+D` are deliberately *not* bound to opening files — those belong to paste and
duplicate everywhere else, and rebinding them would be a trap. Opening uses `Ctrl+Shift+V` for video
and `Ctrl+Shift+D` for data.

## Appearance

**View → Theme** offers System, Dark, or Light. **View → Font Size** offers a system-relative size.

System follows your desktop, including a change you make while AvialSync is running, and switching
back to System from Dark or Light hands the appearance to your desktop again.

A switch reaches everything on screen: the plot background, axis lines, tick numbers and axis
titles, the playhead, trace and marker colours, the 3D pose view, the pane boundaries you drag, and
the controls the operating system draws for us — scroll bars, check boxes, drop-down lists, and the
window frame.

These change colours and text only. They do not reset or reinterpret your shared time, seek bar,
plot navigation, playback state, layout, or loaded data — an appearance change is never allowed to
disturb what you are looking at.

Text drawn over video is the one deliberate exception: the camera label, the on-screen readout and
the "No Footage" placeholder stay light on a dark backing in every appearance, because they sit on
your footage rather than on an application surface. A video frame does not get lighter because the
application did.

Trace colours come from a palette checked in colour-blindness-simulated space, and colour never
carries meaning on its own — a trace is always identified by its label as well. If you prefer the
older colours, turn off **Colour-vision-safe trace palette** in Preferences.
