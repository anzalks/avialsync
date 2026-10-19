# Window composition plan

Written on `feat/window-composition` (based on `fix/prop-persistence` at `c144a78`); Stage A was
fast-forwarded into local `main` on 2026-10-19 and both branches were deleted locally.

Status: Stage A started 2026-10-19. Stage B depends on a decision that only the user can approve.

## Goal

Bring `ui/main_window.py` under the 1,000-line target from D-148 through composition only
(D-051). This must not change any user-visible behaviour, Qt connection semantics, job ownership,
undo recording or shutdown order.

## Measured state (2026-10-19, `c144a78`)

- 3,440 lines, which equals the ceiling in `tests/controller_private_access_baseline.json`.
  Lines 1–167 are imports and module helpers. `MainWindow` has 236 methods.
- 139 methods are thin, at 8 lines or fewer, and total 524 lines; most are D-066 delegators.
  97 methods are substantive and total 2,393 lines, including `__init__` at 508.
- Long-function exceptions in the baseline: `__init__` 508, `_accept_sync_proposal` 110,
  `_on_pane_right_clicked` 74, `_open_sync_wizard` 68.
- Tests make 940 private `window._*` accesses across 86 files, plus 47 `monkeypatch.setattr` on
  a window. The most-used are `_mutations` (98), `_job_manager` (39), `_left_tabs` (37),
  `_v_splitter` (31), `_sensor_cache_dirs` (22), `_all_actions` (22) and `_on_marker_clicked` (20).
- There are 32 modules under `ui/controllers/`, totalling 8,544 lines. The engineering-hardening
  branch set the precedent of a `QObject` component owned by the window (`WindowFeedback`).

### Why D-066 alone cannot reach the target

D-066 requires that one thin method stays on `MainWindow` per moved function, so connections and
instance monkeypatches still resolve against the window. Moving every substantive body out still
leaves roughly the following:

| What stays | Lines |
|---|---|
| Header and imports | ~170 |
| Today's thin methods | ~520 |
| A delegator for each of the 96 moved methods | ~400 |
| A construction shell | ~100 |
| Qt overrides | ~100 |
| **Total** | **~1,300–1,500** |

That is the floor of Stage A. Reaching under 1,000 needs Stage B, which changes where some
slots live.

## Binding constraints

- **D-051:** no Qt-slot mixins, and no partial-bound signal connections.
- **D-066:**
  - Moved code addresses the window as `window`, and calls the window's methods rather than
    sibling module functions, so instance patches still intercept.
  - Stage B changes this rule only for the named slices, and only with the proposed decision.
- **D-148:**
  - `JobManager` remains the only owner of worker lifetimes, started through `_run_job`.
  - New modules are capped at 500 lines and new functions at 60.
  - The private-access baseline only shrinks, and each slice lowers it in the same commit.
- **AGENTS traps:**
  - A worker signal must reach a `@Slot` on a `QObject` with UI-thread affinity, never an
    instance-level wrapper.
  - Shutdown runs `closeEvent` → `VideoGrid.shutdown()` → pane close, in that order.
  - Mutations go through the command bus.
  - Golden sync tests stay untouched.
- **AGENTS rule 4:** no test is weakened. Pointing a test at the new owner of the same behaviour,
  with the assertion unchanged, is allowed; it is named in the commit and in the decision.
- Rule 12: work only in this tree and on this branch.

## Stage A — within D-066 (no new decision needed)

The order runs from least coupled to most coupled, and each slice is self-contained. A slice
moves bodies into a controller module, leaves the delegator, lowers the
`main_window_lines`/private-access/long-function baselines, and passes the full suite before the
next one starts.

| Slice | Responsibility (current methods) | Destination | Approx. lines moved |
|---|---|---|---|
| A1 | Timebase: session start, base/effective/user offsets, epoch publishing, time mode (`session_start_time` … `_set_time_mode`) | Qt-free `ui/controllers/timebase.py`, unit-tested without a window | ~150 |
| A2 | Appearance and title: theme, font size, fullscreen, window title, dirty marker | `ui/controllers/appearance_controller.py` | ~120 |
| A3 | Exports and proxy: snapshot, data slice, clip, stimulus grid, `_generate_proxy` | `export_controller.py`; proxy to `video_controller.py` | ~150 |
| A4 | Overlays menu and state (`_build_overlays_menu` … `_apply_overlay_state`) | `ui/menus/overlays_menu.py` | ~80 |
| A5 | Pane context menu (`_on_pane_right_clicked`, 74 lines) | `ui/menus/pane_menu.py` | ~80 |
| A6 | Point editing and corrections (`_toggle_point_edit_mode` … `_adopt_point_edits`) | `corrections_controller.py` | ~200 |
| A7 | Identity repair (`_open_identity_panel` … `_refresh_identity_lane`) | `identity_controller.py` | ~350 |
| A8 | Alignment: nudges, badges, trigger evidence/read, sync wizard, proposal acceptance | new `alignment_controller.py`, split if over 500 lines | ~450 |
| A9 | Sources: video/sensor/channel removal, visibility, tracking and mapping changes | new `sources_controller.py` | ~300 |
| A10 | Construction: `__init__` (508 lines) split into builders that return small dataclasses of widgets plus a separate `wire_signals` step. The window keeps its attribute names, so 940 test accesses still resolve | `ui/window_build.py` (+ `ui/window_wiring.py`) | ~420 |

A10 comes last because construction order is load-bearing; the `__init__` comments record
several "set before X, which reads it" dependencies. Its test is a construction-order regression
that builds the window and compares the full signal connection inventory (sender, signal,
receiver) before and after.

Expected result of Stage A: about 1,400–1,500 lines, with every long-function exception gone
except a small construction shell. *(Measured result: 2,302 lines — see Progress for why.)*

## Stage B — coordinators own their slots (needs a decision)

**Proposed decision D-next-e · Coordinator objects for bounded responsibilities.** This narrows
D-066 for the slices listed, without reversing it:

- A responsibility moved in Stage A may become a `QObject` coordinator parented to the window,
  following `WindowFeedback`. It owns real `@Slot` receivers; signals connect to it directly; it
  is reached as a public attribute (`window.identity`, `window.alignment`, `window.sources`).
- Its delegators on `MainWindow` are removed.
- Tests that patched `window._x` patch `window.<coordinator>.x` instead, with the same
  assertions. Calls inside a coordinator go through `self` so patches still intercept.
- These stay on `MainWindow`:
  - Qt virtual overrides: `closeEvent`, `dropEvent`, `dragEnterEvent`, `resizeEvent`,
    `eventFilter`.
  - The rule 11 and rule 15 entry points `_run_job`, `_require` and `report_failure`.
  - Public methods used by controllers, plugins and the session (`source_readers`,
    `effective_offset`, `user_offset`, `registry`, and so on).

D-051 is still respected because these are objects the window owns, not mixins: `sender()` and
queued delivery behave normally on a `QObject` receiver. The D-066 objection, "re-owning every
Qt connection", is answered by moving one bounded responsibility at a time with its connection
inventory test, which is the approach D-148 asked for.

Slices B1–B4, each with the same gates as Stage A:
- B1: `window.identity`
- B2: `window.alignment`
- B3: `window.sources`
- B4: `window.corrections`, together with the appearance and export coordinators

Expected result: under 1,000 lines. The baseline's `main_window_lines` is set to the achieved
value, and D-148's target is recorded as met.

If D-next-e is not approved, stop after Stage A, record about 1,450 lines as the accepted end
state under D-066, and revise D-148's target.

## Validation (every slice)

- Full suite on Python 3.12 and 3.11. Golden sync untouched. Strict core and standard package
  mypy, Ruff, and warnings-as-errors docs.
- `tests/test_controller_boundaries.py` with lowered ceilings, `test_feedback_surface.py`
  (registered jobs), the Law 1 and Law 2 conformance tests, and action-authority tests.
- A signal connection inventory snapshot (new in A10, reused by B1–B4) proves connections are
  identical, apart from receivers that moved.
- Shutdown: the existing close and abandon tests, plus opening the demo session and quitting
  during a running import and decode, with no hang or crash.
- Benchmarks touched by window wiring (cursor update, plot pan/zoom, resize) stay within 20 %.
  Record startup-to-first-paint before and after Stage A.
- Launch the app (`conda run -n avialsync avialsync`, plus the demo) after each stage. The user
  runs the TESTING.md §6 manual smoke test on field data before merge.

## Risks

- **Construction order.** A builder that creates a widget earlier or later changes which signal
  sees which state. Mitigation: the A10 inventory test plus the existing empty-state and
  restore-session tests.
- **Silent test bypass.** A moved body calls a sibling function directly and stops honouring a
  patch. Mitigation: D-066 rule 2 review in Stage A, and the `self` calling rule in Stage B.
- **Worker-thread slots.** A coordinator receiving worker signals must live on the UI thread and
  use `@Slot`. Mitigation: check thread affinity in the job tests.
- **Test churn.** Stage B retargets up to a few hundred accesses mechanically, one slice per
  commit, never mixed with behaviour changes.
- **Merge conflicts.** Any other branch touching `main_window.py` conflicts. None is open; Stage A
  and the work it was based on are in `main`.

## Sequencing

Stage A (A1–A10), then the D-next-e decision, then Stage B. Moved code keeps its `tr()` wrapping
(AGENTS rule 17); translation itself is parked.

Commits are local and conventional (`refactor(ui): …`, `test: …`), with no push until the user
has reviewed them.

## Progress

- [x] A1 timebase (2026-10-19): `ui/controllers/timebase.py` holds `SessionTimebase` (as
  `window.timebase`: base offsets, declared epochs, trial spans, time mode) and the nine
  functions; MainWindow keeps delegators. 3,440 → 3,339 lines. Three controller private accesses
  removed from the baseline; three test accesses retargeted to `window.timebase` with unchanged
  assertions. Full suites: 4,583 passed (3.12), 4,582 passed (3.11).
- [x] A2 appearance (2026-10-19): `ui/controllers/appearance.py` holds the title, saved marker and
  theme/font handlers; action groups are passed in. 3,339 → 3,286 lines; no baseline allowance
  added. Full suites: 4,584 passed (3.12); 3.11 passed apart from the boundary test tripping on the
  uncommitted A3 file, which passed on re-run without it.
- [x] A3 proxy (2026-10-19, D-248): `ui/controllers/proxy_controller.py`; the duplicate
  `_proxy_worker`/`_proxy_thread` handles are gone (JobManager owns the worker). 3,286 → 3,235
  lines. Baseline gains the moved code's 8 private accesses under D-248. Exports were already
  delegators.
- [x] A4 overlays menu (2026-10-19): `build_overlays_menu`, `overlay_toggled` and
  `set_all_overlays` join `apply_overlay_state` in `ui/menus/view.py`. 3,235 → 3,176 lines.
  Full suites: 4,585 passed on both 3.12 and 3.11.
- [x] A5 pane menu (2026-10-19): `ui/menus/pane_menu.py`, split under the 60-line cap; the
  `_on_pane_right_clicked` long-function exception is gone. It had no test; `test_pane_menu.py`
  now drives every choice through a scripted menu. 3,176 → 3,105 lines. Full 3.12 suite passed.
- [x] A6 point editing (2026-10-19): `ui/controllers/point_edit_controller.py` (Fix Tracker mode,
  drag-to-command, correction lookup, revisit, restore); persistence stays in
  `corrections_controller`. 3,105 → 2,985 lines; 7 moved private accesses under D-248. Full
  suites: 4,593 passed (3.12), 4,592 passed (3.11).
- [x] A7 identity review (2026-10-19): `ui/controllers/identity_review.py` (dock creation and
  wiring, apply/remove/new group, braid jobs, identity lane). 2,985 → 2,766 lines; 35 moved
  private accesses under D-248. 1,099 identity tests and the full 3.12 suite passed.
- [x] A8 alignment (2026-10-19): `ui/controllers/alignment_controller.py` (frame nudges, badges,
  trigger evidence and its read job, camera re-mapping, trigger restore, the wizard); the small
  public queries stay on the window. 2,766 → 2,507 lines; 39 moved private accesses under D-248.
  The stale `_accept_sync_proposal`/`_open_sync_wizard` long-function exceptions are removed and
  `__init__`'s ceiling lowered to 493. Full suites: 4,595 passed (3.12) and 3.11 passed.
- [x] A9 sources (2026-10-19): `ui/controllers/sources_controller.py` (video/sensor removal,
  sensor re-mapping, channel/group/tracking/video visibility, focused and selected camera). Shared
  tracking-row routing is one helper instead of two copies. 2,507 → 2,303 lines; 49 moved private
  accesses under D-248. 363 targeted tests and the full 3.12 suite (4,595) passed.
- [x] A10 construction (2026-10-19): the 493-line `__init__` is 12 ordered phase methods
  (`_init_document_state` … `_finish_startup`, each ≤ 59 lines), cut at the original section
  boundaries with no reordering. The pure wiring blocks for annotations, the Sources sidebar and
  the transport/pane gestures are in `ui/window_wiring.py`, in their original order. The last
  long-function exception is gone. Verified by a construction inventory taken before and after
  (166 attributes and their types, every child object, the receiver count of every signal on
  every object — 4,460 connections — and the 78 actions): identical. 2,303 → 2,302 lines. Full
  suites: 4,597 passed (3.12), 4,596 passed (3.11).

### Stage A outcome (2026-10-19)

3,440 → 2,302 lines (−1,138); no function in `main_window.py` over 60 lines (four exceptions,
up to 508 lines, before). What remains, measured: ~210 header and class declarations; 480 lines
of construction phases, mostly the window's ~165 attribute declarations with their comments;
559 lines of 185 thin delegators kept by D-066; 736 lines in 50 window-level methods (close,
jobs, preconditions, bounds, detach, annotation entry points), 13–37 lines each.

The 1,400–1,500 estimate assumed construction could leave the class. It cannot without either
declaring every attribute twice (mypy requires each attribute on the class) or moving state into
typed state objects, which retargets a large share of the tests' 940 private accesses. Stage B
(D-next-e) as written would remove most delegators and, with state objects, reach roughly
1,500–1,700 lines; under 1,000 would need both and further moves. The baseline's private-access
total rose under D-248 while the window shrank, as recorded there.

