# AvialSync — UX Foundations Plan (Phase 7)

> **Status:** in progress on branch `ux_foundations`, based on v0.1.6.
> **WP-0 landed**: launch and teardown responsiveness — two pre-existing
> architecture-rule-3 violations, construction 373 ms → 41 ms and zero UI stalls.
> **WP-1 landed in full**: the command bus, dirty state, the session-named title,
> hot exit, and step 4's routing of every listed mutation through the bus via
> `ui/mutation_target.py`.
> **WP-2 landed**: the Edit menu, driven by the document rather than a second
> `QUndoStack` (D-097).
> **WP-4 landed**: the overlay registry and View → Overlays, six layers, session
> schema v6 → v7 (D-090).
> **WP-5 landed**: the activity bar, notification strip, and Tasks panel; the
> modal `QProgressDialog` is gone from `src/` (D-091).
> **WP-6 landed**: the typed error presenter and the data-quality findings.
> **WP-7 landed**: the settings schema and a generated Preferences dialog.
> **WP-8 landed**: the empty state, Help destinations, and a reportable About.
> **WP-9 landed**: display levels driven by the depth the file declares (D-093
> amended with the measurement, which contradicted its prediction).
> **WP-11 landed in part**: the channel filter, adaptive prefix grouping, and
> grouped visibility. Dock widgets and named workspaces remain.
> **WP-12 landed in part**: the colour-vision-safe palette (D-094 amended; the
> mechanism it originally stated was wrong). i18n and the accessibility sweep
> remain.
> **WP-3 landed in part**: the command palette. Remappable shortcuts and the
> single-label authority remain, the latter wanting the `main_window` split
> D-051 governs.
>
> **Remaining: WP-3 (shortcuts, labels), WP-10 (alignment evidence),
> WP-11 (docks, workspaces), WP-12 (i18n, accessibility).**
>
> **Ordering note.** WP-4 was taken before WP-3 despite the graph. Its real
> dependency on the action registry was only that overlay entries be registered
> actions, which the existing `_reg` helper already provides, and the overlays
> were the most visible defect in the running application — nine body-part names
> painted across the animal with no way to turn them off. WP-3 remains worth
> doing and still owns the command palette, shortcut remapping, and the
> single-label authority.
>
> Step 4 was initially deferred and that was a mistake worth recording: without it
> `document.is_dirty` was permanently False in the running application and the
> `[*]` marker was dead code, so WP-1's entire user-visible half did nothing. The
> lesson for later packages is to split a package at a boundary that still leaves
> something observable working, not between the machinery and its only callers.
> **Companion documents:** binding rules in AGENTS.md §Architecture rules 10–17; phase entry in
> BLUEPRINT.md Phase 7; settled choices in DECISIONS.md D-087 … D-094; per-package kickoff prompts
> in PROMPTS.md §Phase 7 prompts.
>
> This file is the *executable* plan. AGENTS.md says what you may not do; this says what to do,
> in what order, and how you know you are finished.

---

## 0. How to use this document

**You are an agent picking up one work package.** Do exactly this:

1. Read AGENTS.md in full. It outranks this file. If anything here conflicts with it, stop and
   report the conflict rather than choosing.
2. Read §1–§4 below (objective, laws, ledger, foundations). They are short and they apply to every
   package.
3. Find your work package in §5. Read **only** that package plus any package listed as its
   dependency.
4. Do the package. One package per session. Do not start a second one.
5. Check yourself against §10 (Definition of Done) before reporting.

**Rules for this phase specifically:**

- Every package lists **Files to create** and **Files to modify**. Do not touch files outside that
  list without saying why in your report.
- Every package lists **Acceptance evidence**. A package is not done because the app launches. It
  is done when its listed tests exist and pass.
- Where this document names a class, method, or setting key, **use that exact name.** Multiple
  models rotate through this codebase and naming entropy is a real failure mode (AGENTS.md §9).
- This document sketches APIs as *signatures and responsibilities*, never as implementation. Write
  the implementation yourself, in the style of the module you are touching.
- If a package looks bigger than one session, split it at a **numbered step boundary** listed in
  the package, finish the steps you started, and report exactly which step numbers remain. Never
  leave a half-written step.
- **Never weaken an existing test to make a new one pass.** §3 is the list of behaviours that
  already work and must still work.

---

## 1. Objective

AvialSync is engineering-sound and interaction-incomplete. The engine keeps a single master clock,
decodes off the UI thread, and never invents a timestamp. The interface around that engine is
missing the layers that let a person work confidently: nothing tracks whether the session has
unsaved changes, nothing can be undone, long imports freeze the window behind a modal dialog,
errors are raw exception strings, half the overlays drawn on video cannot be turned off, and
12-bit footage is crushed to 8 bits before any control could act on it.

Phase 7 adds **seven pieces of shared infrastructure** and then wires the missing behaviour onto
them. It is deliberately not 33 separate fixes. Building these one symptom at a time is how a
codebase acquires a fifth `QSettings` call site and a sixth error-dialog dialect.

**Out of scope for Phase 7:** new analysis, new file formats, new plugin surface, acquisition,
anything that changes what a timestamp means. This phase changes how the user reaches existing
capability, plus one genuine capability gap (high-bit-depth display, WP-9) that no interface work
could fix from above.

---

## 2. The two product laws introduced by this phase

These are new **non-negotiable principles** (BLUEPRINT 10 and 11). They are stated here in full
because most of the work packages exist to satisfy them.

### Law 1 — Never block, always inform

> **The application never refuses to open a file, and never blocks the user to tell them
> something. It informs them and stays out of the way.**

"Dirty" is ambiguous in English, so this plan defines both meanings and applies the law to both:

| Term | Means | How the user learns | What is NEVER allowed |
|---|---|---|---|
| **Document dirty** | The session has unsaved changes — offsets, annotations, layout, an accepted sync fit. | `[*]` in the window title; a **Save** affordance in the status bar. | A modal "save your changes?" gate in front of File → Open, drag-and-drop, Open Recent, or quit. |
| **Data dirty** | The *source itself* has quality problems — gaps, NaN or sentinel runs, missing container metadata, VFR declared as CFR, dropped frames, no accepted TimeMap. | A per-source quality badge in the sidebar, expandable to the specific findings; a Data Streams lane already shows coverage and gaps. | Refusing to load the file. Silently "fixing" it. A blocking dialog before the data appears. |

Consequences that follow, and that you must not undo:

- **Opening always proceeds.** With unsaved changes, the open happens *and* a non-modal bar offers
  Save / Save As / Discard, with Discard undoable until the session closes.
- **Quitting always proceeds, and never loses work.** This extends the existing
  `MainWindow.closeEvent` contract ("Always close" — see the docstring in `ui/main_window.py`) into
  data safety: quit writes a **recovery snapshot** unconditionally, including for a session that
  was never saved and has no path. On next launch the user is *informed* that unsaved work was
  recovered and may restore or discard it. This is "hot exit"; see D-089.
- **A damaged or unusual file loads as far as it can.** Partial success beats refusal. What could
  not be read is reported per-source, never as a dialog that stops the session appearing.
- **The one permitted modal** in this phase is a dialog the user explicitly asked for (Preferences,
  Import Wizard, Export options, Align). Progress is never modal (D-091). Errors are never modal
  unless the user must choose between named recovery actions, and even then the session stays open
  behind it.

### Law 2 — Nothing is drawn over video that the user cannot turn off

> **Every graphic composited on top of a video frame is a registered overlay layer with a
> checkbox in View → Overlays, a stable id, a persisted per-session visibility state, and a
> default. No exceptions, including for overlays a plugin contributes.**

Today this is violated in both directions. `ui/video_overlay.py::PaintCanvas` carries
`set_point_labels_visible()` and `set_legend_visible()`: `set_legend_visible` has **no caller at
all**, and `set_point_labels_visible` has exactly one, in `tests/test_video_pane_timing.py` — so
both are reachable only from a test and **neither has any production control surface**. Meanwhile
the OSD text and the camera name label are drawn with no toggle at all. Adding the next overlay
without a registry adds the next unreachable method.

See WP-4 for the registry and the exact inventory to migrate.

---

## 3. Compatibility ledger — nothing in this list may regress

Phase 7 is additive. Every item below already works and is protected by an existing test, a
benchmark, or a DECISIONS entry. If a package cannot be done without breaking one of these, the
package is wrong — stop and report.

**Timing and correctness**

1. One master clock; no UI component keeps independent time state (AGENTS rule 1).
2. The frame shown for master time `t` is the last frame with `pts <= t`
   (`core/video_timing.py::frame_index_at`, D-084). Frame caches stay keyed by integer index.
3. `tests/test_sync_golden.py` untouched and passing.
4. Raw source timestamps are never rewritten; alignment is a mapping, applied only on explicit
   acceptance (AGENTS rule 8).
5. Per-source `TimeMap` (offset + drift) for every source, video and time-series alike (D-045).

**Architecture**

6. `core/` does not import PySide6, enforced by a test (AGENTS rule 2). This constrains WP-1 —
   see the note in §4.
7. `MainWindow` is split by **composition**, never by Qt-slot mixins (D-051). Slot thread affinity
   is load-bearing; `tests/test_ui_main.py::test_drop_real_video_completes_async_open` is the guard.
8. No file IO, parsing, or decoding on the UI thread (AGENTS rule 3).
9. All plotting through the decimation pyramid; never more points than pixels (AGENTS rule 4).
10. All sources enter through the plugin ABCs in `core/source.py` (AGENTS rule 5).
11. PyAV is the only video path (D-075, D-086). No `mpv`, QtMultimedia, or OpenCV import returns.

**Existing UI behaviour**

12. Themes stay appearance-only: palette, accent, font. They may not change widget style, control
    metrics, shortcut or input behaviour, seek semantics, plot navigation, playback state, or
    layout state (AGENTS §Coding standards). The CVD palette in WP-12 is a legal theme change; the
    redundant encoding in the same package is a data-visualisation change and is gated separately.
13. The shortcuts dialog derives from live `QAction` objects and cannot drift from real bindings
    (D-022.6). WP-3 extends this; it must not replace it with a hardcoded table.
14. Plot presentation modes (Review / Sweep / Scope), the shared time-span control, per-channel
    gutters, Y-mode stability, and the retained current+previous sweep pages (PLOT_UX_PLAN.md §2).
15. Data Streams lanes: named, conditional, click-to-seek, palette-derived colours, time-indexed
    event lookup (D-027, D-047).
16. The window always closes; jobs are asked to cancel and abandoned if wedged
    (`ui/main_window.py::closeEvent`). WP-1 adds a recovery write *before* teardown, in the ordering
    that docstring already establishes — state is captured before `video_grid.shutdown()` clears it.
17. `.avv` session round-trip for every currently persisted field. WP-1 bumps the schema; the
    migration must be one-way-compatible per §7.
18. **Reset Session (0.1.6)** returns the workspace to empty without modifying recordings, sidecar
    caches, or a saved `.avv` file, and cancels pending loads rather than letting them land in the
    cleared workspace — `_session_generation` is the guard that makes late arrivals safe. Covered by
    `tests/test_ui_main.py`. WP-1, WP-2, and WP-5 all touch this function; none may weaken those
    properties. Making it undoable (WP-2) must not make it slower to reach or add a confirmation.

**Performance** — every budget in BLUEPRINT §Performance budgets. See §6 for which this phase
touches and by how much.

---

## 4. The seven foundations

Each work package builds or consumes exactly one of these. Nothing in Phase 7 introduces an eighth
mechanism for the same job.

| # | Foundation | Lives in | Answers |
|---|---|---|---|
| F1 | **Document + command bus** — every user-visible mutation is a command with an inverse | `core/document.py` | What changed? Is it saved? Can it be undone? |
| F2 | **Settings registry** — one typed schema, `QSettings` behind it | `core/settings_schema.py` + `ui/preferences_dialog.py` | What is configurable, what is the default, how is it reset? |
| F3 | **Action registry** — id, label, category, default shortcut, icon, enablement | extend `main_window.py`'s existing `_reg()` into `ui/action_registry.py` | What can the user do, what is it called, what key runs it? |
| F4 | **Overlay registry** — id, label, group, default, per-session visibility | `ui/overlay_registry.py` | What is drawn over the video, and how is it turned off? |
| F5 | **Feedback surface** — activity area, jobs panel, notifications, error presenter | `ui/feedback/` | What is the app doing, what finished, what went wrong, what can I do about it? |
| F6 | **Presentation/string layer** — `tr()`, accessible names, locale formatting | pass across `ui/` | What does it say, in whose language, to whom? |
| F7 | **Display pipeline seam** — levels/LUT between decode and QImage | `engine/display_pipeline.py` | What does a 12-bit pixel look like on an 8-bit screen? |

**F1's constraint, stated once because it catches everyone:** `core/` may not import PySide6
(AGENTS rule 2, enforced by test). So `QUndoStack` cannot live in `core/`. The pattern is a
**headless command bus in `core/document.py`** — plain Python, fully unit-testable without Qt — and
a thin **`ui/undo_adapter.py`** that wraps each core command in a `QUndoCommand` and pushes it onto
a `QUndoStack` owned by the window. Do not invert this. Do not import Qt into core "just for the
enum".

---

## 5. Work packages

Twelve packages plus WP-0. The dependency graph is in §8. Each is sized for one agent session.

---

### WP-0 — Launch and teardown responsiveness — **DONE**

**Foundation:** none; it predates them. **Depends on:** nothing.

Added after a field report of "UI thread blocked for 4584 ms" on launch followed
by `QThread: Destroyed while thread '' is still running` on close. Both were
**pre-existing in the shipped v0.1.6**, not Phase 7 regressions — the release tag
reproduces the startup stall at 266–272 ms under the same probe. Recorded here
because they are architecture-rule-3 violations and this plan is the vehicle for
that class of work.

**What was wrong**

1. `LoaderRegistry.__init__` imported every built-in loader inline, inside
   `MainWindow.__init__`. Profiling put 469 ms of a 509 ms construction there —
   `neo` (224 ms, pulling scipy and quantities) and the AOL EKS loader (212 ms,
   pulling h5py). Module IO on the UI thread. Cold, behind on-access virus
   scanning, the same work took over four seconds before a window appeared.
2. A decode thread is `QThread(self)`, parented to its pane. When
   `_shutdown_decoder`'s 3 s wait timed out, the pane was destroyed with a
   running QThread as its child, which Qt warns about and can abort on.

**What was done.** Discovery is deferred behind `ensure_discovered()` and warmed
by `start_warmup()` on a background thread, with every public accessor —
including `plugin_errors`, now a property — waiting on the same lock (D-095). A
decode thread that outruns its timeout is detached from its parent and retained
until it finishes, the mechanism `job_manager` already uses, and threads are now
named (D-096).

**Measured.** `MainWindow` construction **373 ms → 41 ms**; UI heartbeat **one
~280 ms stall per launch → zero stalls**.

**Evidence.** `tests/test_startup_responsiveness.py`. The startup test asserts
the *shape* — `MainWindow.__init__` returns with `_discovered` still false —
rather than a wall-clock budget, which would be flaky on a loaded CI machine and
could pass by accident.

**Note for later packages.** WP-5 will touch `job_manager`'s abandon path and
WP-9 will touch `video_pane`'s decode threads. Both must preserve D-096:
a running QThread is never destroyed, and the window always closes.

---

### WP-1 — Document, command bus, and dirty state

**Foundation:** F1. **Depends on:** nothing. **Blocks:** WP-2, WP-7, WP-10.

**Goal.** Make "the session has changed" a fact the application can observe, and make quitting
lossless.

**Files to create**

- `src/avialsync/core/document.py`
- `tests/test_document.py`
- `tests/test_hot_exit.py`

**Files to modify**

- `src/avialsync/core/session.py` — schema bump, see §7
- `src/avialsync/ui/controllers/session_controller.py` — recovery snapshot, autosave without a path
- `src/avialsync/ui/main_window.py` — title, and the recovery write inside `closeEvent`

**What to build**

1. A `Command` protocol in `core/document.py`: a stable `command_id`, a human `label` used verbatim
   in the Edit menu ("Set offset for cam2.mp4 to 1.240 s"), an `apply(state)` and a `revert(state)`.
2. A `Document` holding the session state plus an ordered command log, exposing at minimum:
   `execute(command)`, `is_dirty`, `dirty_changed` observer registration (a plain callback list —
   **not** a Qt signal; core is headless), `mark_saved()`, and `recovery_payload()`.
3. **Commands store inverse operations, never state snapshots.** This is a hard requirement, not a
   preference. A snapshot of a session with 128 channels of pyramid metadata per undo step would
   consume the 2.5 GB idle-RAM budget within roughly twenty edits. An offset command is a source id
   and two floats. Cap the log at 200 entries, discarding oldest.
4. Route these mutations through `execute()` — this is the complete Phase 7 list, do not expand it
   without a DECISIONS entry: per-source offset and drift; annotation add / delete / relabel /
   retime; source add and remove; accepted sync proposal; per-source and per-channel visibility;
   video and plot row order (once WP-11 lands); overlay visibility (once WP-4 lands); and
   **Reset Session** (see below).
   - **Reset Session (added in 0.1.6) is the most destructive action in the application** and it
     must be in this list. `session_controller.reset_session()` cancels pending loads, removes every
     pane, and calls `annotation_store.clear()` and `message_store.clear()` — it discards every
     annotation the user has made. It is reachable from a plain sidebar button
     (`sidebar.py::btn_reset_session`, "Reset Session") with no confirmation and, today, no undo.
     Do not add a confirmation dialog; make it one undoable command (WP-2).
   - `reset_session` increments `window._session_generation`, which is the guard that invalidates
     in-flight async loads (`session_controller` compares it before applying a completed load).
     The `Document` must not duplicate that counter — read it, do not shadow it.
5. Window title becomes `<session name> — AvialSync` with Qt's `[*]` placeholder, driven by
   `setWindowModified()`. Untitled sessions read `Untitled — AvialSync`. Today the title is the
   constant string `"AvialSync"` and never changes.
6. **Coalescing is mandatory.** A `QDoubleSpinBox` drag emits `valueChanged` continuously. Dirty
   notification must be debounced (reuse the 20 Hz presentation limit established by D-047) or a
   title repaint storm will violate the ≤ 8 ms UI-callback target during an offset drag. Undo must
   also merge a continuous drag into **one** undoable command, not two hundred.
7. **Hot exit (D-089).** `session_controller.autosave()` currently returns early when
   `window._session_path is None`, so an unsaved session has no protection at all. Change this:
   - Autosave to the real path when one exists, as today.
   - Otherwise write a recovery snapshot to the platform app-data location
     (`QStandardPaths.AppDataLocation`), atomically, never into the user's own directories.
   - `closeEvent` writes a final recovery snapshot unconditionally, in the existing ordering — state
     is captured *before* `video_grid.shutdown()`, exactly as the current docstring requires.
   - On launch, if a recovery snapshot exists and is newer than its session file, show a
     **non-modal** bar: "Unsaved work from &lt;time&gt; was recovered." with Restore and Discard.
     Never a modal, never a startup gate (Law 1).
   - **Reset Session interacts with this and the interaction is a trap.** `reset_session()` sets
     `_session_path = None` and empties the workspace. A naive hot exit then writes an *empty*
     recovery snapshot over a good one the moment the user resets and quits — turning a safety net
     into the data loss it exists to prevent. Rule: a reset clears the recovery snapshot rather than
     overwriting it with emptiness, and an empty workspace never produces a snapshot at all.
     `tests/test_hot_exit.py` must cover reset-then-quit explicitly.
8. Quitting still never prompts. That is the point of step 7.

**Acceptance evidence**

- `tests/test_document.py`: apply/revert round-trips to identical state for every command type;
  the log caps at 200; a coalesced drag produces exactly one command.
- `tests/test_hot_exit.py`: an untitled session with one annotation, closed without saving, leaves
  a recovery snapshot that reloads to the same state.
- The existing headless-core guard still passes — `core/document.py` imports no Qt.
- A pytest-qt test asserting a 200-step offset drag emits at most 2 title updates.

**Budget impact.** Undo log ≈ 80 bytes/command × 200 ≈ 16 KB. Recovery write is one small JSON on
the existing off-thread `SessionSaveWorker` path (D-046). No hot path touched, **provided** step 6
is honoured.

**Notes from the implementation** (kept because they constrain WP-2 and WP-4):

- `ui/mutation_target.py` holds the one `MutationTarget` implementation. It drives the *widget* the
  user drove, not just the model behind it — a spin box still showing an undone value lies about the
  session — and it holds `MainWindow._recording_suspended` down while replaying, or an undo re-emits
  the signals that record commands and the stack never unwinds.
- Mutations are logged with `Document.record`, not `execute`: the widget has already done the work
  by the time its signal arrives.
- Source add/remove is recorded when a source **lands**, not when it is requested. A file that fails
  to open is not a change to the session, and undoing it would try to close a pane that never
  appeared. `_session_restoring` suppresses this for the length of a session load, or a restored
  session would come up dirty and offer to unload what the file said to load.
- Deleting an annotation retains the `Marker` object itself, not just its `MarkerRecord`. Rebuilding
  one from the record silently drops the colour index and the per-video frame snapshots.
- `_reset_session` captures its snapshot inside a guard. Reset is the escape hatch a user reaches
  for when the workspace is already in a state they want gone, which is exactly when a snapshot is
  most likely to fail; losing undo is acceptable, refusing to clear is not.
- `set_overlay_visible` raises `NotImplementedError` until WP-4 exists. It is declared rather than
  omitted so the target still satisfies the protocol.

---

### WP-2 — Undo/redo and the Edit menu

**Foundation:** F1. **Depends on:** WP-1.

**Files to create:** `src/avialsync/ui/undo_adapter.py`, `tests/test_undo.py`.

**Files to modify:** `src/avialsync/ui/main_window.py`, `src/avialsync/ui/annotations.py`,
`src/avialsync/ui/sidebar.py`.

**What to build**

1. `undo_adapter.py` wraps a `core.document.Command` in a `QUndoCommand` and pushes it to a
   `QUndoStack` owned by `MainWindow`. Undo text comes from the command's `label` — do not invent a
   second labelling scheme.
2. A real **Edit** menu: Undo (`Ctrl+Z`), Redo (`Ctrl+Shift+Z` and `Ctrl+Y`), then Select All and
   Delete for the focused list where meaningful. There is no Edit menu today, which on macOS is a
   visible platform-conventions violation. Register through F3 once WP-3 lands; until then use the
   existing `_reg()` helper so the shortcuts dialog picks them up.
3. Destructive actions become undoable rather than confirmed: the sensor `✕`, the video close
   button, annotation **Delete**, and — most importantly — **Reset Session** push commands.
   **Do not add confirmation dialogs** — they violate Law 1's spirit and undo is the better answer.
   - Reset Session is the priority here. It is one sidebar click, it clears every pane, every
     annotation, and every recorded message, and today nothing warns and nothing recovers it. As a
     single undoable command ("Reset session") it becomes safe without becoming annoying.
   - Reset is the one command whose inverse legitimately needs bulk state rather than a small
     inverse op. That is fine and is not a violation of step 3 in WP-1: cap it at **one** retained
     pre-reset snapshot, held only while it sits on the undo stack, and drop it when the command is
     evicted. Do not generalise snapshotting to other commands.
4. Undo is session-scoped and cleared on session load.

**Acceptance evidence.** `tests/test_undo.py`: delete a source and undo restores it with its
offset, drift, visibility, and channel states intact; **Reset Session followed by undo restores the
panes, annotations, and messages**; undo depth survives an autosave; the stack clears on load. The
existing reset-session coverage in `tests/test_ui_main.py` stays green.

**Budget impact.** None. No hot path.

---

### WP-3 — Action registry, command palette, remappable shortcuts

**Foundation:** F3. **Depends on:** nothing. **Blocks:** WP-4 (menu), WP-8, WP-10.

**Files to create:** `src/avialsync/ui/action_registry.py`,
`src/avialsync/ui/command_palette.py`, `tests/test_action_registry.py`.

**Files to modify:** `src/avialsync/ui/main_window.py`,
`src/avialsync/ui/shortcuts_dialog.py`, `src/avialsync/ui/sidebar.py`,
`src/avialsync/ui/transport.py`.

**What to build**

1. Promote the existing `_reg(action, category)` helper in `main_window.py` into a real registry
   carrying: stable `action_id`, canonical `label`, `category`, `default_shortcut`, optional `icon`,
   and an `enabled_when` predicate.
2. **The registry becomes the single authority for a command's user-facing label.** Today the menu
   says `"Open Video(s)…"` and the sidebar button says `"Open Videos"`. After this package both read
   the same registry entry and cannot drift (D-092).
3. Command palette on `Ctrl+Shift+P`: fuzzy match over the registry, showing category and current
   shortcut, respecting `enabled_when`.
4. Shortcut remapping: user overrides layered over defaults, persisted through F2 once WP-7 lands
   (until then, a single `QSettings` key under `shortcuts/`). `shortcuts_dialog.py` becomes
   editable — **keep it deriving from live `QAction`s** (D-022.6); add editing, do not replace the
   derivation with a hardcoded table.
5. Conflict detection: assigning an already-bound key warns inline and names the current owner. It
   does not refuse (Law 1).

**Acceptance evidence.** `tests/test_action_registry.py`: every registered action has a unique id
and a non-empty label; no two default shortcuts collide; the palette lists exactly the enabled
actions; a remapped shortcut survives a restart; the shortcuts dialog still renders from live
actions.

**Budget impact.** Registry build is one-time at construction. Fuzzy match over ~60 actions is
microseconds, and runs only while the palette is open.

**Note.** This package is the natural seam for the `main_window.py` split that BLUEPRINT still
lists as an open P2 maintainability item. Read D-051 first — composition only, never mixins.

---

### WP-4 — Overlay registry and View → Overlays

**Foundation:** F4. **Depends on:** WP-3. **This package implements Law 2.**

**Files to create:** `src/avialsync/ui/overlay_registry.py`, `tests/test_overlay_registry.py`.

**Files to modify:** `src/avialsync/ui/video_pane.py`, `src/avialsync/ui/video_overlay.py`,
`src/avialsync/ui/video_grid.py`, `src/avialsync/ui/main_window.py`,
`src/avialsync/core/session.py`.

**What to build**

1. An `OverlayLayer` descriptor: stable `overlay_id`, `label`, `group`, `default_visible`, and
   whether the layer is per-camera or global.
2. A `View → Overlays` submenu, generated from the registry, with one checkbox per layer, grouped.
   Include **Show All** and **Hide All**. Every entry is a registered action (F3), so overlays are
   reachable from the command palette and individually bindable to a key.
3. Per-camera overrides live in the video pane's context menu (which already exists in
   `main_window.py`, near the "Fullscreen this camera" action) under the same labels. The View menu
   sets the default for all cameras; the context menu overrides one.
4. Visibility persists in `.avv` per session (§7) and toggles through the command bus (F1), so it
   is undoable.
5. **Migrate the existing inventory.** This is the complete list; each becomes a registered layer:

   | Overlay id | Label | Group | Default | Today |
   |---|---|---|---|---|
   | `tracking.points` | Tracking points | Tracking | on | drawn, no toggle |
   | `tracking.point_labels` | Body-part names | Tracking | off | `set_point_labels_visible()` exists, **called only from a test** |
   | `tracking.legend` | Track legend | Tracking | on | `set_legend_visible()` exists, **no caller at all** |
   | `tracking.skeleton` | Skeleton | Tracking | on | drawn via `ui/tracking_skeleton.py`, no toggle |
   | `camera.name` | Camera name | Chrome | on | drawn, no toggle |
   | `camera.osd` | Timecode / fps readout | Chrome | on | drawn, no toggle |
   | `camera.no_footage` | "No Footage" placeholder | Chrome | on, **not user-hideable** | D-010 contract |

   `camera.no_footage` is registered but **locked visible** — hiding it would let a blank pane be
   mistaken for black footage, which D-010 exists to prevent. Show it greyed with an explanatory
   tooltip rather than omitting it, so the inventory stays complete and the reason is visible.
6. **The registry is the extension point.** A plugin contributing an overlay registers a layer and
   gets its checkbox automatically. Document this in the plugin guide under `docs/`. Anything drawn
   over video without registering is a rejected PR (AGENTS rule 13).
7. Delete no drawing code. This package adds the control surface; it does not change what any
   overlay looks like.

**Acceptance evidence.** `tests/test_overlay_registry.py`: every layer drawn by `PaintCanvas` and
`VideoPane` has a registry entry — assert by enumerating the registry against a hardcoded expected
inventory, so adding an unregistered overlay fails the test; toggling a layer hides it in the
painted output; visibility round-trips through `.avv`; `camera.no_footage` cannot be hidden;
a per-camera override does not disturb the other panes.

**Budget impact.** A visibility check per layer per paint — a boolean lookup inside the existing
20 Hz-throttled `_flush_osd_update`. Unmeasurable. Hiding layers is strictly *faster* than today.

---

### WP-5 — Feedback surface: activity, jobs, notifications

**Foundation:** F5. **Depends on:** nothing.

**Highest value per hour in this phase** — the model already exists in `ui/job_manager.py` (state
tracking, cooperative cancel, stall detection). Only the view is missing.

**Files to create:** `src/avialsync/ui/feedback/activity_bar.py`,
`src/avialsync/ui/feedback/jobs_panel.py`, `src/avialsync/ui/feedback/notifications.py`,
`tests/test_feedback_surface.py`.

**Files to modify:** `src/avialsync/ui/main_window.py`, `src/avialsync/ui/job_manager.py`
(signals only — do not change its threading), and every site that raises a modal progress dialog.

**What to build**

1. A status-bar activity area: current job name, progress, elapsed, ETA, and a cancel button wired
   to the existing `JobManager` cancel path.
2. An expandable jobs panel: running and recently finished jobs, with outcome and duration.
3. A non-modal notification strip for terminal outcomes ("Proxy generated", "Export failed —
   Show details"), auto-dismissing on success, sticky on failure.
4. **Delete the modal `QProgressDialog`** — `main_window.py`'s `self._progress_dialog` for imports
   and the proxy-generation dialog. Both already run on JobManager; the modality is gratuitous. The
   budget allows 60 s for a 1 GB CSV import, which today is a full minute of frozen application
   (D-091).
   - **`_progress_dialog` has a second reader you must update in the same change.**
     `session_controller.reset_session()` (added in 0.1.6) disconnects the import worker's
     `progress` signal from `window._progress_dialog.setValue` and then closes the dialog. Deleting
     the attribute without touching `reset_session` leaves a dangling reference that fails only when
     someone resets during an import. Route it through the activity area instead, and keep the
     cancel-on-reset behaviour that code already implements — it is correct.
   - `reset_session` also calls `window._job_manager.cancel_all()`. The jobs panel must show that
     as cancellation, not as failure.
5. ETA derived from observed progress rate, shown only once it is stable enough not to jitter.
6. Update rate capped at 20 Hz, matching D-047. Never repaint the activity area from the 60 Hz
   clock tick.

**Acceptance evidence.** `tests/test_feedback_surface.py`: a long import leaves the window
responsive — assert via the existing `ui_heartbeat` helper that no UI callback exceeds 30 ms during
a simulated 1 GB import; cancel from the activity bar stops the job; a failed job leaves a sticky
notification; no `QProgressDialog` remains in `src/` (assert by grep inside the test).

**Budget impact.** Improves it. Removes a 60-second UI block. The 20 Hz activity repaint is far
below the ≤ 8 ms per-callback target.

---

### WP-6 — Typed error presenter and data-quality badges

**Foundation:** F5. **Depends on:** WP-5. **Implements the second half of Law 1.**

**Files to create:** `src/avialsync/ui/feedback/error_presenter.py`,
`src/avialsync/ui/quality_badge.py`, `tests/test_error_presenter.py`.

**Files to modify:** all `QMessageBox` call sites found by
`grep -rn "QMessageBox\." src/avialsync/ui/` (there are 40+), plus `src/avialsync/core/errors.py`.

**What to build**

1. A presenter mapping each typed exception in `core/errors.py` to **title + plain-language cause +
   named recovery actions**. Today's shape is `f"Could not do X:\n{msg}"` — an exception string in a
   box with an OK button, which AGENTS.md §Errors already forbids ("actionable text").
2. Standard recovery actions: **Locate file…**, **Retry**, **Open log**, **Copy diagnostics**, and a
   collapsed **Show details ▾** carrying the raw exception and traceback.
3. **Loading is never refused (Law 1).** A source that fails partially loads what it can. What
   failed becomes a per-source finding, not a dialog.
4. `quality_badge.py`: the "data dirty" indicator. Per source, aggregating findings the loaders
   already detect — gap count, NaN and sentinel runs, missing container metadata, VFR declared as
   CFR, dropped frames, no accepted TimeMap. Click expands to the specific findings with a
   jump-to-time for each. Reuse `SourceInspection`, which `ui/sidebar.py` already carries.
5. Errors surface in the notification strip by default. A modal is permitted **only** when the user
   must choose between named recovery actions.

**Acceptance evidence.** `tests/test_error_presenter.py`: every exception type in `core/errors.py`
has a presenter mapping — assert by enumeration, so a new exception type without a mapping fails
CI; a video with a missing sidecar still opens and reports a finding; no `QMessageBox` remains
outside the presenter and explicitly user-invoked dialogs.

**Budget impact.** None. Badge state is computed once at load from data the loaders already
produce, and is event-driven — **never sampled on the clock tick.**

---

### WP-7 — Settings registry and Preferences

**Foundation:** F2. **Depends on:** WP-1. **Blocks:** WP-9 (defaults), WP-11, WP-12.

**Files to create:** `src/avialsync/core/settings_schema.py`,
`src/avialsync/ui/preferences_dialog.py`, `tests/test_settings_schema.py`.

**Files to modify:** the scattered `QSettings("AvialSync", "AvialSync")` call sites —
`ui/theme.py`, `ui/plot_pane.py`, `ui/recent_files.py`,
`ui/controllers/session_controller.py`.

**What to build**

1. One typed schema: key, type, default, label, group, help text. `QSettings` stays the backing
   store — this is a schema over it, not a replacement.
2. **The Preferences dialog is generated from the schema**, not hand-built. A hand-built dialog is
   how "Reset to default" gets forgotten. There is no Preferences window at all today; real
   preferences are scattered across View-menu radio groups and five `QSettings` call sites.
3. Groups: Appearance (theme, font, palette), Playback, Plots, Overlays (defaults for WP-4),
   Video Display (defaults for WP-9), Shortcuts (from WP-3), Storage (cache location, autosave
   interval, recovery).
4. Per-setting and global **Reset to default**.
5. Existing View-menu radio groups (Theme, Font Size, Time Display) stay where they are — they are
   frequently used and belong in the menu — but read their values from the registry.
6. Diagnostics gains a settings dump. It is worth its weight the first time a user files a bug.

**Acceptance evidence.** `tests/test_settings_schema.py`: every schema key has a default and a
label; every currently persisted key appears in the schema, so nothing is orphaned; reset restores
defaults; a settings round-trip survives a restart; no `QSettings` construction remains outside the
registry.

**Budget impact.** None. Reads are cached at construction.

---

### WP-8 — Empty state, Help, About

**Foundation:** F3. **Depends on:** WP-3.

**Files to create:** `src/avialsync/ui/empty_state.py`, `tests/test_empty_state.py`.

**Files to modify:** `src/avialsync/ui/main_window.py`.

**What to build**

1. An empty-state view when no sources are loaded: the drop target, the three real entry points,
   and a **Try the demo session** button that runs the existing demo generator in-process on a
   worker. That generator is currently reachable only as `avialsync demo` on a command line the
   target user may never open — it is the best onboarding asset in the project and it is hidden.
2. Help menu gains: **Documentation** (readthedocs), **First Session Tutorial**, **Report a
   Problem** (prefilled with the diagnostics dump), **Check for Updates**. The installers are
   unsigned and side-loaded, so having no update channel is a real problem. Today the Help menu is
   Shortcuts, Diagnostics, About — a dead end.
3. About gains: version, git commit, Python / Qt / PySide6 / PyAV / pyqtgraph versions, licence
   link, and **Copy to clipboard**. Today it is three lines of plain text, so every bug report you
   receive is missing the version.
4. **Cite this software.** `CITATION.cff` was added in 0.1.6 and `tools/prepare_release.py` keeps
   its version in step with the package. Surface it: a Help → **Cite AvialSync…** item offering the
   citation as text and BibTeX, read from the shipped `CITATION.cff` rather than retyped, so it
   cannot drift from the file the release process maintains. For a tool used to produce published
   figures this is not decoration.
5. Read the project URLs from `pyproject.toml`'s `[project.urls]` (Homepage, Documentation, Source,
   Issues, Changelog) rather than hardcoding them — they were repointed during the 0.1.6 cycle and
   hardcoded copies would have silently gone stale.

**Acceptance evidence.** `tests/test_empty_state.py`: the empty state appears with zero sources and
disappears on first load; the demo button produces a loadable session; About reports the installed
version.

**Budget impact.** None.

---

### WP-9 — High-bit-depth display pipeline

**Foundation:** F7. **Depends on:** WP-4 (its controls are overlay-adjacent) and WP-7 (defaults).

**This is the only package that touches a measured hot path. Benchmark before you ship, not after
(AGENTS rule 9).**

**Files to create:** `src/avialsync/engine/display_pipeline.py`,
`src/avialsync/ui/levels_panel.py`, `tests/test_display_pipeline.py`,
`tests/benchmarks/test_display_pipeline_bench.py`.

**Files to modify:** `src/avialsync/engine/pyav_reader.py`,
`src/avialsync/ui/video_pane.py`, `src/avialsync/core/session.py`,
`tools/make_fixtures.py`.

**The problem, stated precisely.** `engine/pyav_reader.py::to_rgb_array` does
`frame.to_ndarray(format="rgb24")`. For 12-bit greyscale, swscale performs the 12→8 bit reduction
*there*, with a fixed shift. **The dynamic range is destroyed before any UI code sees the frame.**
A brightness slider bolted onto the pane would be stretching data that has already been thrown
away. The fix must be upstream, in the worker.

**What to build**

1. `display_pipeline.py` sits between decode and `QImage`:
   - **High-bit-depth sources:** `to_ndarray(format="gray16le")` at native depth → apply a
     65536-entry `uint8` LUT by numpy fancy indexing → emit `QImage.Format_Grayscale8`.
   - **8-bit colour sources:** unchanged `rgb24` path. An identity LUT short-circuits the stage
     entirely, so ordinary footage pays nothing.
2. Controls in `levels_panel.py`: window/level (min/max), gamma, auto-levels from a frame
   histogram, optional false-colour LUT, and per-camera or linked-across-cameras level groups.
   Persist in `.avv` (§7); defaults in the settings registry (WP-7).
3. **The LUT runs in the decode worker, never on the UI thread.** Applying it in `paintEvent` turns
   a 2 ms budget into a 3 ms violation on every frame.
4. `PyAVReader._store` caches `av.VideoFrame` **pre-conversion** — keep it that way. A levels change
   then costs a re-conversion, not a re-decode. Add a second-level cache of converted 8-bit buffers
   keyed by `(frame_index, levels_generation)`, invalidated when levels change.
5. Levels-slider drags coalesce at 20–30 Hz, exactly as `plot_pane` already coalesces span drags.
6. Add a 12-bit greyscale fixture with known pixel values to `tools/make_fixtures.py` if one does
   not already exist. That file shells out to `ffmpeg` deliberately — it is a build-time generator,
   not part of the app. Use `-fps_mode`, never `-vsync`.

**Expected performance, and why — verify, do not assume**

- 1440×1080 = 1.56 M pixels. A 16→8 bit LUT gather is one pass, roughly 1–3 ms on one core.
- `Format_Grayscale8` writes **one third the bytes** of `Format_RGB888` on both the conversion and
  the upload, because swscale's gray→RGB triplication disappears. For greyscale sources this path
  is plausibly **faster than what ships today**.
- Caching frames at native 12-bit depth is 2 bytes/px against rgb24's 3 — **less** memory.
- The unknown worth measuring: whether `to_ndarray(format="gray16le")` is as cheap in PyAV's
  swscale path as `rgb24`. Benchmark it. If it is not, the fallback is to keep the native
  `av.VideoFrame` and index its planes directly.

**Acceptance evidence**

- `tests/test_display_pipeline.py`: a 12-bit fixture with known pixel values maps through a known
  window to the expected 8-bit output; an identity LUT is bit-identical to today's `rgb24` path for
  8-bit input; levels round-trip through `.avv`.
- `tests/benchmarks/test_display_pipeline_bench.py`: per-frame conversion time for the 8-bit and
  12-bit paths, plus the cache-resident drag-scrub path, against §6's numbers.
- The exact-frame golden tests still pass — the pipeline must not change *which* frame is shown,
  only how its pixels are mapped. D-084 is untouched by this package.

**Budget impact.** See §6. The one number that moves is cache-resident drag scrub.

---

### WP-10 — Alignment: evidence view, direct manipulation, Align menu

**Foundation:** F1 + F3. **Depends on:** WP-1, WP-3.

**Files to create:** `src/avialsync/ui/align_panel.py`,
`src/avialsync/ui/sync_evidence_view.py`, `tests/test_align_panel.py`.

**Files to modify:** `src/avialsync/ui/sync_wizard.py`,
`src/avialsync/ui/main_window.py`, `src/avialsync/ui/sidebar.py`.

**What to build**

1. Promote alignment to a top-level **Align** menu and a toolbar entry. It currently sits in the
   File menu between *Open Sensor/Ephys Data…* and *Save Session…*. Alignment is not a file
   operation — it is the reason this product exists.
2. **Show the evidence.** `sync_wizard.py` reports a fit as one sentence of numbers: matched count,
   offset, drift ppm, max residual. BLUEPRINT principle 8 requires presenting "the matched
   evidence". That sentence is the *header*; the view underneath needs a residual scatter with the
   tolerance band drawn, matched vs. rejected events on a shared axis, and a before/after preview
   on the real timeline. Users are currently asked to accept a scientific correction on faith in
   four numbers.
3. The evidence plot obeys AGENTS rule 4 — decimate or cap; never more points than pixels.
4. **Direct manipulation.** Offset is a `QDoubleSpinBox`, 0.05 s steps, ±86400 s range. Aligning by
   eye is the most common real workflow and has no direct path today. Add: drag a trace or video
   lane along the timeline with live residual feedback, arrow-key nudge at frame granularity, a
   modifier for coarse/fine. The spinbox stays as numeric entry, not as the primary interaction.
5. Convert the modal wizard into a dock panel. Propose → inspect → adjust → re-inspect is
   iterative; an `OK/Cancel` modal fights it.
6. A persistent per-source confidence badge: "aligned ±3 ms, 47 events, 2026-08-14".
   **Event-driven from the accepted TimeMap — never sampled on the 60 Hz tick.**
7. Acceptance still requires an explicit user action (AGENTS rule 8), and now routes through the
   command bus so it is undoable (WP-1).

**Acceptance evidence.** `tests/test_align_panel.py`: the evidence view renders matched and
rejected events for a fixture with a known fit; a drag alignment produces the same TimeMap as the
equivalent spinbox entry; acceptance is undoable; `tests/test_sync_golden.py` untouched and passing.

**Budget impact.** None on the clock tick, given step 6. The evidence view is a panel, decimated
like any plot.

---

### WP-11 — Sidebar at scale, reordering, docking, workspaces

**Foundation:** F1 + F2. **Depends on:** WP-1, WP-7.

**Files to modify:** `src/avialsync/ui/sidebar.py`, `src/avialsync/ui/main_window.py`,
`src/avialsync/ui/video_grid.py`, `src/avialsync/core/session.py`.

**What to build**

1. Sidebar: filter field, sort, group-by-kind, collapse-all, multi-select for bulk visibility.
   The spec targets 4 cameras plus 128 channels at 50 kHz — today that is a vertical scroll of
   hundreds of checkboxes with no search, no sort, and no grouping.
2. **Virtualise the channel list above ~200 rows.** Constructing hundreds of widgets at load
   competes with the ≤ 3 s cached-session-open budget.
3. Drag reordering (`InternalMove`); order persists to `.avv` and drives both the video grid and
   the plot row order. Today camera order is load order and cannot be changed.
4. `QDockWidget` for sidebar / annotations / messages / jobs, with `setDockNestingEnabled`, so a
   multi-monitor rig can put video on one screen and traces on another. Named workspace layouts
   persist through the settings registry. **Splitter state must migrate** — see §7.
5. Reordering and visibility route through the command bus, so both are undoable.

**Acceptance evidence.** Filter narrows to matching channels; reorder round-trips through `.avv`;
a saved workspace restores dock geometry; a 128-channel fixture opens within the 3 s budget; the
existing splitter-state restore path still works for pre-migration sessions.

**Budget impact.** Neutral to positive — virtualisation reduces load-time widget construction.
`QDockWidget` chrome is marginally heavier to paint than `QSplitter`; not measurable at these sizes.

---

### WP-12 — Accessibility, internationalisation, colour

**Foundation:** F6. **Depends on:** WP-7. **Do this last** — it should touch final copy, not copy
you are about to rewrite.

**Files to modify:** every module under `src/avialsync/ui/`, plus `src/avialsync/ui/theme.py`,
`src/avialsync/ui/tracking_colors.py`, `.github/workflows/ci.yml`.

**Files to create:** `src/avialsync/resources/i18n/avialsync_en.ts`, `tests/test_i18n.py`,
`tests/test_accessibility.py`, `tests/test_palette_cvd.py`.

**What to build**

1. **i18n and error copy are the same pass**, because both mean touching every user-facing string
   exactly once. Doing them separately means doing it twice. There is currently not one `self.tr()`
   or `QTranslator` in the codebase — every string is hardcoded English and untranslatable without
   a rewrite, and that ceiling gets more expensive every week.
2. Wrap at construction sites; generate `.ts`/`.qm`; add `lupdate` to CI so a new untranslated
   string fails the build. Locale-aware number and date formatting — the import wizard already
   handles euro decimals, so the locale problem is half-acknowledged already.
3. Accessibility: `setAccessibleDescription` and `setStatusTip` throughout. Today there are 25
   `setAccessibleName` calls across ~40 modules and **zero** of the other two. Custom-painted
   widgets — Data Streams lanes, plot panes, video panes — need a `QAccessible` interface; they
   currently expose nothing at all to a screen reader. Verify full keyboard traversal.
4. **Colour.** `theme.py::marker_color` is thoughtfully built — evenly spaced hues, offset clear of
   the defect red, palette-derived lightness. But even hue spacing is precisely the pattern that
   collapses under deuteranopia: in a 7-step wheel, hues near 0.07 and 0.36 are a red/green pair
   that merge into one colour. **Separation in hue is not separation in CVD space.** Replace with a
   palette validated under simulated deuteranopia, protanopia, and tritanopia — Okabe–Ito is the
   settled answer. `tracking_colors.py::POINT_COLORS` is a hardcoded 10-colour Material list with
   several confusions and gets the same treatment.
5. **Redundant encoding**: dash pattern per trace, marker glyph per annotation category, direct
   labels. Colour must never be the only carrier of meaning — in a scientific viewer where colour
   encodes channel identity, that is a correctness problem, not a preference.
6. **Scope note.** Swapping the palette is a legal theme change (themes are palette/font-only).
   Redundant encoding changes what a plot looks like structurally and therefore needs its own
   DECISIONS entry before it ships. Do not fold it in silently.
7. Icons with text labels for the transport's bare glyphs — `[`, `]`, `◀`, `▶`, `✕`, `–1s`, `+1s`,
   `⚠`. `[` and `]` for A/B in-point is editor jargon a neuroscientist has no reason to know, and a
   tooltip is currently the only explanation. Toggle-button semantics for Play/Pause and Hide/Show
   instead of swapping label text.

**Acceptance evidence.** `tests/test_i18n.py`: no bare user-facing string literal in a `set*Text`
call outside `tr()`, asserted by an AST scan; `tests/test_accessibility.py`: every interactive
widget has an accessible name and description; `tests/test_palette_cvd.py`: the minimum perceptual
distance between palette entries under all three CVD simulations exceeds a stated threshold.

**Budget impact.** None. `tr()` resolves at construction, not per frame.

---

## 6. Performance invariants

Phase 7 must leave every budget in BLUEPRINT §Performance budgets intact. Expected effect:

| Budget | Effect | Reason |
|---|---|---|
| Plot pan/zoom ★ ≤ 16 ms | **None** | No package touches the pyramid query or the plot paint path. The sync evidence scatter (WP-10) is a panel and decimates like any plot. |
| Cursor update per tick ★ ≤ 2 ms | **None, if disciplined** | Two ways to break it, both forbidden above: routing dirty-state through the 60 Hz tick (WP-1 step 6) and sampling the sync-confidence badge on the tick (WP-10 step 6). Both are event-driven by construction. |
| 3D pose sample ★ ≤ 2 ms | **None** | Untouched. |
| Scrub, exact seek ≤ 250 ms | **None** (measured 117 ms) | A 1–3 ms LUT inside a worker already doing a seek plus up to a 250-frame GOP decode is noise. |
| **Scrub, drag ≤ 50 ms** | **3 ms → ~6 ms** | The only number that moves. Today's 3 ms is a cache hit, and `PyAVReader._store` caches `av.VideoFrame` *pre-conversion*, so a hit that was free now pays a LUT. Still ~8× under budget. Mitigated by WP-9's converted-buffer cache. |
| Cached session open ≤ 3 s | **None** | Session IO is already off-thread (D-046). WP-11 virtualisation helps. |
| First CSV import 1 GB ≤ 60 s | **None to throughput; large improvement to experience** | Same work, no longer behind a modal (WP-5). |
| Pyramid build ★ ≤ 2.5 s | **None** | Untouched. |
| **Idle RAM ≤ 2.5 GB** | **Net neutral to better** | Undo ≈ 16 KB at a 200-command cap with inverse-op commands. Caching 12-bit frames at native depth is 2 bytes/px against rgb24's 3 — WP-9 *reduces* frame-cache memory on the sources it targets. |
| UI callback ≤ 8 ms target / 30 ms ceiling | **Improves** | WP-5 removes a 60-second modal block and several smaller ones. |

**Three specific ways to get this wrong.** Each has been seen in real codebases:

1. **Snapshot-based undo** instead of inverse commands → blows the idle-RAM budget. WP-1 step 3.
2. **A dirty signal per `valueChanged`** → title repaint storm during an offset drag, violating the
   8 ms callback target. WP-1 step 6.
3. **Applying levels on the UI thread** "because it's just a LUT" → turns a 2 ms budget into a 3 ms
   violation on every frame. WP-9 step 3.

**Benchmark policy.** Only WP-9 requires new benchmarks. WP-1, WP-5, and WP-10 require a
`ui_heartbeat` assertion that no UI callback exceeds 30 ms under their respective loads. Everything
else needs no performance evidence; do not add ceremonial benchmarks for construction-time code.

---

## 7. Persistence and schema migration

`.avv` schema goes **v6 → v7**. New fields, all optional with defaults, so a v6 file loads
unchanged:

| Field | From | Default if absent |
|---|---|---|
| `overlays` — per-layer, optionally per-camera visibility | WP-4 | each layer's `default_visible` |
| `display_levels` — per-source window/level/gamma/LUT, and link groups | WP-9 | identity (today's appearance) |
| `source_order` — explicit video and plot row order | WP-11 | load order (today's behaviour) |
| `annotation_categories` — category, tag, colour index per marker | WP-12 | uncategorised |
| `workspace` — named dock layouts | WP-11 | current single layout |

Rules:

- **Loading a v6 file must produce byte-identical behaviour to today.** A v6 session with no
  `display_levels` renders exactly as it renders now. This is the test.
- Saving always writes v7. There is no downgrade path; say so in the release notes.
- The recovery snapshot (WP-1) uses the same schema plus a `recovered_at` timestamp and the
  original path when there was one.
- Window geometry, splitter state, dock layouts, recent files, shortcuts, and settings stay in
  `QSettings` and out of `.avv`. That boundary is already correct — `core/session.py` documents it
  — and this phase does not move it.
- WP-11 changes the layout model from splitters to docks. Migration: if a `QSettings` splitter
  state exists and no dock state does, restore the splitter proportions into the equivalent dock
  sizes once, then write dock state thereafter. Do not discard a user's layout silently.

---

## 8. Sequencing and dependencies

```
WP-1  Document + dirty ──┬── WP-2  Undo + Edit menu
                         ├── WP-7  Settings ──┬── WP-9  Display levels
                         │                    ├── WP-11 Sidebar / docks
                         │                    └── WP-12 A11y / i18n / colour
                         ├── WP-10 Align
                         └── WP-11

WP-3  Action registry ───┬── WP-4  Overlays ──── WP-9
                         ├── WP-8  Empty state / Help
                         └── WP-10

WP-5  Feedback ────────────── WP-6  Errors + quality badges
```

**Recommended order.** WP-1 and WP-3 first — they unblock the most, and WP-3 is the natural seam
for the `main_window.py` split that BLUEPRINT still lists as an open P2 maintainability item. The
UX goal and the maintainability goal are the same work here. Then **WP-4**, because Law 2 is an
explicit product requirement and the dead `set_*_visible` APIs are evidence the gap is already
causing drift. Then WP-5 (highest value per hour — the JobManager model is already built), WP-6,
WP-2, WP-7. WP-9 can start once WP-4 and WP-7 land, gated on its own benchmark. Then WP-8, WP-10,
WP-11. **WP-12 last**, so it translates final copy.

**WP-1, WP-3, and WP-5 are independent of each other** and may be done in any order, or
concurrently by different sessions.

---

## 9. Required test evidence

Beyond each package's own listed tests, Phase 7 is not complete until these hold:

1. The headless-core guard still passes — `core/document.py` and `core/settings_schema.py` import
   no Qt.
2. `tests/test_sync_golden.py` untouched and passing.
3. `tests/test_ui_main.py::test_drop_real_video_completes_async_open` passing — the D-051 guard on
   slot thread affinity, which WP-3's `main_window.py` restructuring will stress.
4. A **Law 1 conformance test**: with unsaved changes present, File → Open, drag-and-drop, Open
   Recent, and quit each proceed without a modal gate.
5. A **Law 2 conformance test**: enumerate the overlay registry against the expected inventory in
   WP-4, so adding an unregistered overlay fails CI.
6. A **schema test**: a v6 fixture session loads and renders identically to today.
7. No `QProgressDialog`, and no `QMessageBox` outside the error presenter and explicitly
   user-invoked dialogs (grep assertions).
8. `ui_heartbeat` under a simulated 1 GB import shows no UI callback above 30 ms.
9. All benchmarks within 20 % of their pre-phase values, except the drag-scrub path, which is
   allowed the documented 3 ms → ~6 ms in §6 and no more.

---

## 10. Definition of done, per work package

Every AGENTS.md Definition-of-Done item applies unchanged. Additionally, for this phase:

- [ ] The package's listed **Acceptance evidence** exists as real tests and passes.
- [ ] No item in §3 (compatibility ledger) regressed.
- [ ] `pytest -x -q`, `ruff check .`, and both `mypy` invocations pass on the files touched.
      **Confirm the conda env name before running** — AGENTS.md says `avialsync`; verify it exists
      on the machine you are on and report the discrepancy rather than guessing at a substitute.
- [ ] HANDOUT.md updated in the same commit if the package changed a module's public API, added a
      trap, or fixed a listed bug (AGENTS.md §Task protocol 1).
- [ ] DECISIONS.md updated if you made a choice a future agent must not reverse.
- [ ] Docs updated if user-visible behaviour changed.
- [ ] Conventional commit: `feat(ux): …` / `fix(ux): …`. **No agent attribution anywhere git can
      see it** — AGENTS.md §Definition of Done is binding on this.
- [ ] Your report names the work package, the step numbers completed, and the step numbers left.

---

## 11. Traps specific to this phase

- **`core/` cannot import PySide6.** It is enforced by a test. `QUndoStack` goes in `ui/`, the
  command bus in `core/`. Do not import Qt into core "just for the enum". (§4, F1.)
- **`MainWindow` must not be split with Qt-slot mixins.** D-051 records this being implemented,
  measured, and reverted: `QObject.sender()` returned `None` inside an inherited slot, and a queued
  connection silently became direct, building widgets on a worker thread. Composition only. WP-3
  will tempt you here.
- **`session_controller.autosave()` returns early when `_session_path is None`.** That single line
  is why unsaved work has no protection today. It is the first thing WP-1 changes.
- **Reset Session (0.1.6) is a loaded gun that three packages touch.** One sidebar click clears every
  pane, annotation, and recorded message with no confirmation and no undo. WP-1 must route it through
  the command bus and must not let a reset-then-quit overwrite a good recovery snapshot with an empty
  workspace; WP-2 must make it undoable; WP-5 must update its `_progress_dialog` handling when that
  dialog is deleted. Read `session_controller.reset_session()` in full before touching any of the
  three — it is ~105 lines and it disconnects signals by name.
- **Overlay toggles that already exist have no production caller.** On `PaintCanvas`,
  `set_legend_visible()` has no caller at all and `set_point_labels_visible()` has exactly one, in
  `tests/test_video_pane_timing.py`. Nothing in `src/` invokes either. Wire them through the
  registry; do not write new parallel toggles beside them, and do not delete the test caller.
- **`to_ndarray(format="rgb24")` destroys 12-bit range inside swscale**, before any UI code runs.
  A pane-level brightness control cannot fix this. WP-9 must change the conversion, not add a
  filter after it.
- **`PyAVReader._store` caches `av.VideoFrame`, not RGB arrays.** This is load-bearing for WP-9: it
  means a levels change costs a re-conversion, not a re-decode. Do not "optimise" it into caching
  converted output without adding the `levels_generation` key.
- **The 20 Hz presentation rate limit (D-047) is the established pattern** for anything that
  updates from a hot path. Reuse it in WP-1, WP-5, and WP-9. Do not invent a second throttle.
- **`tools/make_fixtures.py` shells out to `ffmpeg` deliberately** — it is a build-time fixture
  generator, not part of the app. WP-9's 12-bit fixture belongs there and may use it. Use
  `-fps_mode`, never `-vsync`.
- **Themes are appearance-only.** WP-12's palette swap is legal; its redundant encoding is not a
  theme change and needs its own DECISIONS entry.
