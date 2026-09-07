# Architecture

AvialSync is organised around a single promise: every visible item is inspected at one shared
experiment time. The implementation is separated so that expensive file work never interrupts the
desktop interface, and so laboratories can add readers without changing the viewer itself.

## Master timeline

`MasterClock` is the only owner of the current experiment time. Video panes, plots, annotations,
the data-stream coverage view, and exports subscribe to it; they do not each keep a competing clock.
The 3D tracking pane is another observer on that same update path; it has no timer or playback
state of its own.

Each source has a `TimeMap` that converts its own timestamps to the master timeline. The map can
contain an offset and an optional drift term. The raw source timestamps are retained. This separation
means a user can inspect a proposed alignment, accept it, or change it later without altering the
recording on disk.

## Main parts

| Part | Responsibility |
| --- | --- |
| `core/` | Headless timeline, cache, session, synchronization, command bus, settings schema, and plugin contracts. It does not import the Qt interface. |
| `loaders/` | Built-in readers for CSV, tracking, video, and optional scientific formats. Third-party readers use the same plugin contracts. |
| `engine/` | Background imports, cache construction, playback coordination, exports, and synchronization workers. |
| `ui/` | The desktop window, video panes, plots, sidebar, transport controls, dialogs, and the registries that keep actions, overlays, and feedback single-authored. |

## Loading and viewing a source

1. The loader registry asks available loaders whether they recognise a dropped file.
2. The appropriate loader is opened in a worker, not on the user-interface thread.
3. Time-series data is read in chunks and stored in a cache with display pyramids.
4. The UI receives source metadata, coverage, integrity information, and a path to the cache.
5. At a selected master time, the player asks every source for the corresponding source time.
   A video pane seeks to that video time and a plot queries only the appropriate display level.

Video is decoded in-process with PyAV, one worker thread per pane, and the decoded frame is blitted
by the pane itself — the same path on every platform. Dense traces use precomputed decimation pyramids instead of
passing full recordings to a plotting widget. This keeps navigating a long recording responsive
without reducing the precision used for readouts and exports.

The 3D pane is a view over the same cache, not a new loader or source type. It groups complete
`name_x`, `name_y`, and `name_z` triplets, performs one nearest-timestamp lookup per source, and
custom-paints only the current pose. It does not scan or render a full trajectory on a clock tick.
The 3D pane and video grid sit in a native side-by-side splitter, whose size is a local view
preference. Point names do not imply scientific topology, so the viewer never derives connections
from them. It does derive them from the trajectories: pairs whose separation holds steady across a
strided sample of the recording are joined by a minimum spanning tree, rooted at the topmost point
so the bones have a direction. A skeleton the session declared always wins, and a derived one is
drawn dashed and labelled `detected` rather than passed off as the recording's own (D-082).

For exact paused-frame verification, AvialSync reads the pixels the pane actually painted and
decodes a frame-index strip out of them, rather than trusting a returned seek command or a reported
timestamp. There is one rendering path on every platform and it is the same one in continuous
integration, so a headless run exercises what a desktop run does.
A pane's decode thread is stopped explicitly while the main window is still alive, rather than being
left to garbage collection or Qt child destruction.

## Synchronization design

Synchronization is evidence-based. The system stores raw event times, proposed matched event pairs,
an offset/drift fit, residual timing error, and confidence. The user previews that evidence in the
Sync Wizard — as a residual plot against the tolerance band that decided it, not only as a summary
line — and explicitly accepts a proposal before a `TimeMap` changes. The architecture never silently
invents a match or rewrites a source file.

## One authority per user-visible concept

Interaction state that used to be defined in several places is defined once, and everything that
presents it derives from that one definition rather than from a table kept beside it.

| Concept | Sole authority | What derives from it |
| --- | --- | --- |
| Every user-visible mutation | the command bus in `core/document.py` | dirty state, undo/redo, autosave |
| An action's label, category, shortcut, and enablement | the live `QAction` | the shortcuts dialog, the command palette, user shortcut overrides |
| Configurable values | `core/settings_schema.py` | the generated Preferences dialog, the View-menu radio groups |
| Graphics drawn over video | `ui/overlay_registry.py` | View → Overlays, the per-camera context menu, plugin overlays |

Commands carry inverse operations rather than state snapshots — a snapshot per edit would breach the
idle-memory budget. `core/` stays headless, so the bus is plain Python and the `QUndoStack` lives in
`ui/undo_adapter.py`.

## Never block, always inform

Two dirtinesses are tracked and neither is a gate. *Document dirty* — unsaved session changes — shows
as `[*]` in the title with a Save affordance. *Data dirty* — gaps, NaN or sentinel runs, missing
metadata, VFR declared as CFR, dropped frames, no accepted mapping — shows as a per-source quality
badge. A damaged file loads as far as it can and reports the rest; partial success beats refusal.

Work that can exceed roughly 500 ms reports through the status-bar activity area, the jobs panel, and
the notification strip, with cancel where the worker supports it; `QProgressDialog` is banned from
`src/`. Typed exceptions from `core/errors.py` reach the user through the single presenter in
`ui/feedback/error_presenter.py` as title, plain-language cause, and named recovery actions, with raw
text behind "Show details". Quitting is never gated on saving: a recovery snapshot is written
unconditionally to the platform's app-data location and the next launch says so, non-modally.

High-bit-depth video is windowed in the decode worker, never in the pane: `to_ndarray("rgb24")`
destroys 12-bit range inside swscale before any UI code runs, so display levels are a decode stage
rather than a filter applied afterwards, and the lookup table never runs on the UI thread.

## Session and extension boundaries

A `.avv` session stores source references, mappings, annotations, and accepted synchronization
provenance. It does not embed, modify, or replace the original recordings. Acquisition and scientific
analysis live outside the core viewer. Labs extend formats, event meaning, and optional analysis with
plugins.

The maintained detailed design record is in `ARCHITECTURE.md`, `BLUEPRINT.md`, and `DECISIONS.md` at
the repository root. Those documents record the implementation phases, performance requirements, and
settled architectural decisions.
