# AvialView Plot UX Refinement Plan

Status: **approved target, not yet implemented**

Governing decisions: D-042 and D-044

Primary modules: `ui/plot_pane.py`, `ui/plot_row.py`, `ui/plot_sweep.py`,
`ui/transport.py`, `ui/main_window.py`, `ui/theme.py`

This document is the implementation contract for refining AvialView's scientific plots and
timeline controls. It deliberately separates the target presentation from the current working
implementation. An agent must not describe any item here as shipped until code, tests, and
`HANDOUT.md` have been updated together.

## 1. Objective

Make recorded-data review and ECG/oscilloscope-style playback clear, stable, attractive, and
keyboard-accessible without removing any existing capability or weakening the timing/performance
architecture.

This is a presentation and interaction refactor. It is not permission to change source timestamps,
accepted `TimeMap` mappings, exact video seeks, frame-trigger alignment, pyramid data, annotation
semantics, or export results.

## 2. Compatibility ledger — nothing in this list may be lost

The implementation must preserve:

- One `MasterClock` and one authoritative `t_master` for video, plots, readouts, 3D, annotations,
  A/B state, and Data Streams.
- One shared plot duration and one shared horizontal navigator for every visible channel. No plot
  row may gain an independent horizontal scrollbar, pan state, or X zoom.
- The existing fixed `0…duration` page coordinates and current clear-and-restart presentation,
  retained as **Scope** style.
- A continuous duration slider plus a typed numeric value and `ms` / `s` / `min` / `h` units.
- Per-channel close buttons routing through the existing sidebar checkbox. Closing never unloads
  data or creates a second visibility state.
- Play/pause, exact and approximate scrubbing, frame stepping, Home/End, jumps, rate selection,
  A/B loop, measurements, annotations, gaps, coverage, snapshot, fullscreen, reset zoom, status,
  readouts, and every documented shortcut.
- Existing Data Streams evidence: named source coverage, accepted Sync/TTL events, data gaps,
  annotations, event detail, collapse/resize, click-to-seek, and mapped no-footage bounds.
- Pyramid-only plotting, NaN/gap-aware envelopes, hidden-row skipping, coalesced slider/resize
  refresh, and paint-only cursor updates between committed window changes.
- System/Dark/Light and font preferences through palette/font APIs. No application-level QSS and no
  theme-dependent changes to control metrics, shortcuts, navigation, or scientific state.
- `.avv` backward compatibility. New view preferences must be optional and have explicit defaults.

If an implementation step cannot preserve an item above, stop and report the conflict instead of
silently simplifying the feature.

## 3. Terminology and display states

Use these names consistently in code, tests, UI, and docs:

- **Review:** the complete fixed-duration page containing the master cursor is visible. No
  left-to-right reveal clip hides data. This is the presentation while paused, exact-seeking, or
  inspecting a scrubbed location.
- **Sweep:** playback advances left-to-right. The previous page remains visible until overwritten;
  a narrow eraser gap and playhead distinguish new data from the retained previous pass.
- **Scope:** compatibility presentation matching D-042: playback advances left-to-right, the
  unreached portion is blank, and the next page clears/restarts at the left edge.
- **Strip/Roll:** new data enters at the right and old data translates left. This is explicitly out
  of scope for the first implementation because it reintroduces moving X-axis labels.

The user chooses the live playback style, **Sweep** or **Scope**. Sweep is the default for a fresh
preference; Scope remains selectable. While playback is paused or the user is scrubbing, plots use
Review presentation without changing the stored live-style choice. Resuming playback returns to
the selected live style.

All modes use the same page selection:

```text
page_start = bounds_start + floor((t_master - bounds_start) / duration) * duration
page_end   = page_start + duration
display_x  = absolute_master_time - page_start
```

Clamp the first/last partial page to the authoritative master bounds without inventing data.
Annotations, measurements, gaps, and coverage remain stored in absolute master time and are only
mapped to display coordinates for painting.

## 4. Target plot anatomy

```text
Signals       Live: Sweep | Scope       Time span  [10.0] [s] ─────       Y [Fit all]

×  ECG          mV    ±2.0  │ waveform
×  Trigger       V     0–5  │ waveform
×  Position     px    ±120  │ waveform
                              └ one shared master-time axis

Data Streams
source labels │ coverage / sync / gap / annotation lanes
              │ full-session navigator + playhead + draggable visible-window rectangle

playback controls        master time / seek        A/B loop / rate
```

Rules:

- Only the bottom visible plot shows X tick labels and the shared X-axis title.
- The plot header shows the page's formatted master-time range using the existing
  `TimeDisplayMode`. Individual rows do not repeat `Sweep (s)`.
- A fixed channel gutter aligns every row and contains close/hide, channel label, unit, and current
  Y scale/range. The close control is small, has an accessible name and tooltip, and becomes more
  prominent on hover/focus.
- Many channels use one vertical channel-list scrollbar and a shared row-height control. This is
  not a second horizontal navigator. Channel grouping/tree behaviour remains available.
- Plot actions live in the plot header. Video actions live with video/main actions. Annotation
  actions live with annotation tools. Existing actions/signals and shortcuts are moved or proxied,
  not deleted.

## 5. Shared time-span control

The control is labelled **Time span**, not **Window limit**.

- Retain one numeric editor, one unit selector, and one continuous horizontal slider below or in the
  plot header. Remove only redundant duplicate text that repeats the same value.
- Changing the unit converts the displayed number without changing the duration. For example,
  `10 s` becomes `10000 ms`, not `10 ms`; `120 s` becomes `2 min`.
- Slider movement changes duration continuously. Use a logarithmic or piecewise-monotonic mapping
  so millisecond precision remains usable when a recording also permits minute/hour windows.
- The selected unit defines the useful adjustment scale. Clamp against source/timeline limits and
  show the resulting value immediately; commit expensive refresh work at the existing capped
  cadence and on release.
- Keyboard entry, arrow adjustment, wheel adjustment, plus/minus plot zoom, reset zoom, and session
  restoration must all update the same duration authority.
- Enter or a valid editing completion commits the value and releases editor focus to the plot or
  playback surface. Space must then play/pause immediately.

No time-span action may create per-row X state.

## 6. Data Streams becomes the single global navigator

Extend the existing Data Streams view; do not replace its evidence model.

- Preserve all named conditional evidence lanes and their accessible/event-detail behaviour.
- Add a full-session overview and a visible-window rectangle whose width reflects the shared plot
  duration and whose position reflects the current page.
- Clicking seeks through the existing transport/player path.
- Dragging the rectangle preserves the playhead's fractional position inside the page and seeks the
  master clock to the corresponding position in the moved page. During interaction, coalesce
  approximate seeks/refreshes and issue the existing exact seek on release. Rectangle width is
  display-only and follows the time-span authority; it has no independent resize state.
- The playhead, A/B region, source bounds, gaps, annotations, and accepted sync evidence remain in
  absolute master time.
- There is still only one horizontal navigation surface for all plots. Individual channel rows
  remain X-linked and non-interactive horizontally.
- Retain Data Streams collapse, splitter resize, label gutter, status, and empty-lane suppression.

The old normalized seek slider may remain during an incremental migration, but the final UI must
not present two equal-looking controls for the same master-time navigation. Its signal/API can
remain as an internal compatibility adapter.

## 7. Vertical scale and channel interaction

Time scale is global; amplitude scale may be channel- or channel-type-specific.

Each row supports:

- **Fit once:** compute an appropriate visible range, then freeze it.
- **Auto:** continuously fit as the reviewed page changes; this is explicit, not the hidden default.
- **Manual:** preserve a user-set range and vertical offset.

During normal playback, a fitted/manual Y range must not jump merely because the sweep advances.
`Reset Plot Zoom` remains the single QAction authority and resets the shared time span plus channel
Y state to documented defaults. Existing `reset_zoom()` callers remain valid or receive a
compatibility adapter.

Show unit and active scale/range in the channel gutter. Provide a clipping/out-of-range indicator
instead of silently hiding clipping through continuous auto-range. Direct manipulation or a
context menu may adjust a selected channel, but it must not alter other channels unless the action
is explicitly `Fit all`.

## 8. Trace and overlay visual language

- Render raw/near-raw data as one trace.
- Render decimated `vmin`/`vmax` as one unambiguous envelope: a subtle filled band or vertical
  min–max strokes per display column. Never use a midpoint-only trace and never draw extrema as two
  unrelated equal-weight signals.
- Use restrained, theme-aware traces. Colour communicates source/type/selection/bad-channel/event
  meaning; it is not an arbitrary rainbow assigned only by row index.
- Show subtle major vertical time divisions and a quiet zero/reference line where meaningful.
  Avoid a full-strength X/Y grid repeated in every row.
- Give playhead, sweep edge, A/B measurements, gaps, selection, and annotations distinct semantic
  roles with colour plus shape/label. Do not depend on colour alone.
- Prefer one shared event line or faint span through the stack. Do not rebuild strong duplicate
  annotation/gap objects for every row when a shared or pooled item communicates the same event.
- No-data and gap regions remain honest: never connect a trace across a known gap.

All colours must derive from palette roles plus a small semantic palette maintained in the UI
layer. Scientific/source data and `core/` never own UI colours.

## 9. Workspace and transport hierarchy

- Consolidate Sources, Values/Readout, and Annotations into one inspector with tabs or equivalent
  collapsible sections; preserve every existing panel and signal.
- Reduce permanent borders and nested group boxes. Use consistent spacing and row heights while
  retaining native control styling.
- Separate transport visually into playback, master-time navigation, and loop/rate groups.
- Move `Reset Zoom` to the plot header, Snapshot/Fullscreen to video/main actions, and annotation
  actions to the annotation area. During migration, old buttons may proxy the same QAction.
- There remains one QAction or transport-signal authority per command. Never duplicate business
  logic because the visible button moved.

## 10. Focus and keyboard contract

- Space remains the window-scoped Play/Pause shortcut except while the user is actively editing
  text.
- Enter accepts valid time/time-span text and moves focus out of the editor.
- Do not solve shortcut conflicts by assigning `NoFocus` to every button, slider, and combo box.
  Buttons and selectors must remain reachable by Tab and expose accessible names/tooltips.
- Preserve arrows/comma/period frame step, Shift+arrows and J jumps, K pause, L rate step,
  Home/End, A/B keys, M, reset zoom, theme, fullscreen, export, and help.
- Add keyboard traversal tests for plot header → channel gutter → Data Streams → transport, in
  addition to shortcut tests.

## 11. Performance invariants

The redesign must remain bounded by visible pixels and visible objects:

- Ordinary 60 Hz ticks move only the playhead, sweep clip/gap, and cheap visible readouts.
- Do not query the pyramid on each tick. Query only on committed page/duration/density/source
  changes, as in D-042.
- Sweep retains only the current and immediately previous display-page buffers needed for overwrite;
  never accumulate historical curve objects.
- Hidden/collapsed rows and panels receive no formatting, sampling, query, or overlay work.
- Bucket dense overview events to display pixels, index visible events by time, and pool/reuse
  graphics items.
- Resize and slider storms remain trailing-edge/coalesced. No `QApplication.processEvents()` and no
  synchronous IO or parsing enters the UI thread.
- Keep the populated cursor path at ≤2 ms, plot interaction/paint at ≤16 ms, and every UI callback
  below the 30 ms hard ceiling. Add p95/p99 and maximum Qt-heartbeat delay to the representative
  manual/performance report.

## 12. Persistence and migration

Add optional view fields only after their defaults and migration tests are defined:

- selected live style (`sweep` default for a fresh preference; `scope` remains supported),
- shared duration,
- per-channel or per-channel-type Y mode/range/offset,
- channel row height/grouping/visibility,
- inspector/Data Streams collapse and splitter preferences.

Scientific session state and machine-local presentation preferences must stay separated following
existing conventions. Old `.avv` files load without a schema error. Existing `plot_x0`/`plot_x1`
compatibility values remain readable. Never persist sweep phase, transient playhead pixels, cached
geometry, or a second channel visibility state.

## 13. Implementation slices

Complete and verify one slice before starting the next:

1. **Characterization:** lock every compatibility-ledger behaviour with tests; capture current
   signals, shortcuts, session round-trip, query counts, focus-after-entry, and performance baselines.
2. **View state:** introduce explicit Review/Sweep/Scope presentation state without changing the
   visible default in that slice; keep absolute time authoritative.
3. **Plot anatomy:** channel gutter, one bottom X axis, formatted page range, vertical channel
   scrolling, and compatibility adapters for row close/visibility.
4. **Sweep rendering:** retain previous page, bounded eraser gap, Scope compatibility, gaps and
   overlays at wrap boundaries.
5. **Time span:** unit conversion and log/piecewise continuous mapping; one authority for typed,
   slider, shortcut, reset, and restored changes.
6. **Global navigator:** visible-window rectangle integrated into Data Streams; drag coalescing and
   exact release; retain evidence lanes.
7. **Y scale and traces:** fit/auto/manual modes, stable playback ranges, units/clipping, single
   min/max envelope, semantic colours and restrained grids.
8. **Workspace hierarchy and focus:** move/proxy actions, inspector organization, transport groups,
   Tab accessibility, and shortcut arbitration.
9. **Persistence and certification:** migrations, theme/state round-trips, populated performance
   benchmarks, full golden sync, cross-platform manual smoke.

Do not combine slices 2–8 into one rewrite. Prefer extracting small UI helpers over extending a
module beyond the repository size limits.

## 14. Required test evidence

At minimum, the implementation PR series must prove:

- Every compatibility-ledger item remains reachable and has the same signal/semantic result.
- Review shows the complete current page; Sweep preserves old data until overwritten; Scope retains
  the clear/restart behaviour; all modes agree on page and cursor time.
- All rows share duration, page, navigator, and X link through close/hide, add/remove, reload,
  resize, theme switch, save/load, and playback transitions.
- Unit changes preserve duration; slider mapping is monotonic and usable at ms/s/min/h scales.
- Navigator drag preserves playhead phase, uses approximate coalesced seeks, and issues one exact
  release; rectangle width always reflects the shared duration.
- Fit/Auto/Manual Y state behaves as documented and does not jump during ordinary playback.
- Gaps, annotations, measurements, A/B, coverage, and accepted TTL evidence land at the same
  absolute master times in every presentation.
- Enter releases editor focus; Space resumes playback; Tab reaches sliders, combos, buttons, and
  channel controls; all prior shortcuts still work.
- Theme changes preserve plot/navigation state and use no application-level QSS.
- Populated cursor, redraw, query-count, overview-density, resize-storm, and Qt-heartbeat benchmarks
  meet `BLUEPRINT.md` budgets with no regression over 20%.
- `tests/test_sync_golden.py` remains untouched-and-passing for any playback/seek interaction change.

## 15. Definition of done

The refinement is complete only when:

- the manual field-data checklist in `TESTING.md` passes on all three target platforms;
- a user can distinguish Review, Sweep, Scope, time-span adjustment, master navigation, and
  per-channel Y scaling without consulting a manual;
- no existing command, shortcut, evidence lane, export, readout, or session state was removed;
- the representative 4/32/128-channel workloads remain responsive without UI freezes;
- `HANDOUT.md` is changed from “planned” to “implemented” only for actually completed slices.
