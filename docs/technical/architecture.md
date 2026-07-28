# Architecture

AvialView is organised around a single promise: every visible item is inspected at one shared
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
| `core/` | Headless timeline, cache, session, synchronization, and plugin contracts. It does not import the Qt interface. |
| `loaders/` | Built-in readers for CSV, tracking, video, and optional scientific formats. Third-party readers use the same plugin contracts. |
| `engine/` | Background imports, cache construction, playback coordination, exports, and synchronization workers. |
| `ui/` | The desktop window, video panes, plots, sidebar, transport controls, and dialogs. |

## Loading and viewing a source

1. The loader registry asks available loaders whether they recognise a dropped file.
2. The appropriate loader is opened in a worker, not on the user-interface thread.
3. Time-series data is read in chunks and stored in a cache with display pyramids.
4. The UI receives source metadata, coverage, integrity information, and a path to the cache.
5. At a selected master time, the player asks every source for the corresponding source time.
   A video pane seeks to that video time and a plot queries only the appropriate display level.

Video playback is provided by libmpv. Dense traces use precomputed decimation pyramids instead of
passing full recordings to a plotting widget. This keeps navigating a long recording responsive
without reducing the precision used for readouts and exports.

The 3D pane is a view over the same cache, not a new loader or source type. It groups complete
`name_x`, `name_y`, and `name_z` triplets, performs one nearest-timestamp lookup per source, and
custom-paints only the current pose. It does not scan or render a full trajectory on a clock tick.
The 3D pane and video grid sit in a native side-by-side splitter, whose size is a local view
preference. Point names do not imply scientific topology, so the viewer never invents skeleton
connections.

For exact paused-frame verification, AvialView checks decoded raw video against a fixture's frame
strip rather than trusting a returned seek command or a displayed image. Production uses libmpv's
Qt OpenGL render API on Windows/macOS and native `wid` embedding on Linux; displayless continuous
integration uses libmpv's null video output so it can verify decoding and timeline correctness
without pretending to certify desktop rendering.
Video clients are closed explicitly while the main window is still alive, allowing libmpv's event
thread to stop cleanly.

## Synchronization design

Synchronization is evidence-based. The system stores raw event times, proposed matched event pairs,
an offset/drift fit, residual timing error, and confidence. The user previews that evidence in the
Sync Wizard and explicitly accepts a proposal before a `TimeMap` changes. The architecture never
silently invents a match or rewrites a source file.

## Session and extension boundaries

A `.avv` session stores source references, mappings, annotations, and accepted synchronization
provenance. It does not embed, modify, or replace the original recordings. Acquisition and scientific
analysis live outside the core viewer. Labs extend formats, event meaning, and optional analysis with
plugins.

The maintained detailed design record is in `ARCHITECTURE.md`, `BLUEPRINT.md`, and `DECISIONS.md` at
the repository root. Those documents record the implementation phases, performance requirements, and
settled architectural decisions.
