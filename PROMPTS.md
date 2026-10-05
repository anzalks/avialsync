# PROMPTS.md — kickoff prompts per phase

Model-agnostic: written for frontier coding agents (Claude Sonnet/Opus-class, GPT-5-class,
Gemini 3-class). Paste the Universal Preamble + the phase prompt into a fresh session.
Break each phase into the numbered tasks; run ONE task per agent session for clean context.

> **Completed phases.** Prompts for Phases 0–8, identity repair, and physical props were removed
> once their work shipped; they are in git history, and the plans they pointed into are in
> `archive/plans/`. Only the open phase has prompts here.

---

## Universal preamble (prepend to every session)

```
You are working on AvialSync. Before doing anything:
1. Read AGENTS.md fully — these are binding rules.
2. Read the current phase in BLUEPRINT.md and DECISIONS.md.
3. State a short plan (files, tests, risks) and wait for nothing — proceed unless the plan
   conflicts with AGENTS.md, in which case stop and report the conflict.
Hard rules recap: core/ never imports PySide6; UI thread never blocks; all plotting via the
pyramid; PyAV only for video (D-075 — never libmpv/QtMultimedia/OpenCV); pip must need no OS-level
install; prefer LGPL deps and escalate GPL binaries to DECISIONS.md; tests ship with code; never
weaken failing tests.
For CI, playback, or packaging work, distinguish hosted-runner correctness from local performance
certification and release validation. Preserve exact-frame evidence; do not hide a platform or
lifecycle failure with sleeps, skips, a native CI display override, or a weaker assertion.
Work in small increments and run `pytest -x -q` + `ruff check .` after each increment.
```

## Phase 9 prompts (interface design)

Branch: `feat/interface-design`. **The plan is `INTERFACE_DESIGN_PLAN.md`** — every prompt below is
a thin pointer into it. The plan carries the evidence, files, numbered steps, and acceptance
evidence; do not work from the prompt alone.

**Phase 9 preamble — prepend to the universal preamble above, for every Phase 9 session:**

```
You are working on AvialSync Phase 9 (interface design), branch feat/interface-design.
Read, in this order:
1. AGENTS.md in full — especially rules 13, 15, 17 and the theme / QSS rules.
2. INTERFACE_DESIGN_PLAN.md sections 0–5 (how to use it, objective and what
   D-166 changed, findings register, design rules, target layout, foundations).
   Then section 8 (tests you must amend, never weaken) and section 9 (decisions).
3. Your one work package in section 5, plus any package it depends on.
Then do exactly that package. Write the DECISIONS entry before moving a control,
renaming a label, or changing what a surface looks like structurally.
Never style with setStyleSheet for colour or weight: use QPalette roles,
theme.follow_palette, theme.set_bold, ui/icons.py, and ui/design_tokens.py.
A moved control is the same QAction before and after. Keep the 640x480 minimum
and the empty layout (D-127). Attach before/after screenshots from DS-0's script.
Check yourself against section 11 before reporting, and say which numbered steps
you completed and which remain.
```

- **P9.0 Isolated baseline**: "Do DS-0. Isolate the screenshot harness from real QSettings and
  the recovery snapshot first (F-36) — a capture must never overwrite the operator's unsaved work.
  Then capture every surface in Light and Dark at three sizes, fix the amber status colour (F-04),
  and confirm or dismiss the Light gutter labels (F-27)."
- **P9.1 Authority and strings**: "Do DS-1. Bind the sidebar Open buttons and the plot Reset button
  to their actions, give Reset Session a File-menu action (still undoable, never confirmed), wrap
  the constructor literals, and widen the i18n scan so they cannot return. No visual redesign."
- **P9.2 Tokens, roles, icons**: "Do DS-2. Build `ui/design_tokens.py` and the bundled SVG icons,
  record the licence, and give every button a role without moving it. One primary per surface;
  destructive marked by glyph as well as colour; no stylesheets."
- **P9.3 Bottom chrome**: "Do DS-3. Write D-A4 (amends D-126) first, then amend the tests in plan
  §8 to its policy. Five strips become three; loop and speed join the transport; status moves to
  the status bar behind the existing `set_status` API; the scrub track is cached, never per tick."
- **P9.4 Data Streams density**: "Do DS-4. Lane height follows density, the lane area is capped and
  scrolls, D-159 tints hold in both themes."
- **P9.5 Video pane chrome**: "Do DS-5. Step 1 is the `VideoPane.chrome_rects()` contract that
  `PaintCanvas._label_area` reads, because it finds the chrome by widget name today and D-166
  label avoidance breaks silently otherwise. Then the compact OSD, reserved zoom-tool rects,
  aspect-sized panes, and action-backed Snapshot/Fullscreen. The label paint budget holds."
- **P9.6 Inspector navigation**: "Do DS-6. A rail that never elides, Tasks in a status-bar popover,
  the page persisted, every page reachable by click, keyboard, and palette."
- **P9.7 Source cards**: "Do DS-7. Compact cards, timing behind a disclosure over the same spin
  boxes, one split Open button, Reset Session out of the Open group."
- **P9.8 Guided workflows**: "Do DS-8. Build `ui/step_panel.py`, then port one flow per commit:
  Wheel, Props header, Ladder/Belt/Ball, Fix Identities, alignment. Empty states on every page."
- **P9.9 Plot rows**: "Do DS-9. Write the D-094 redundant-encoding entry first. Hover row tools,
  lighter grid, legible gutters; plot benchmarks within 20 %."
- **P9.10 Numbers and time**: "Do DS-10. One decimal-separator policy in DECISIONS, applied through
  one formatter; file I/O stays locale-independent."
- **P9.11 Entry points**: "Do DS-11. Decide on a slim main toolbar; if it ships it holds live
  actions only and fits 640×480."
- **P9.12 Painted-surface accessibility**: "Do DS-12. Accessible interfaces for plot rows, lanes,
  video, and 3D; values computed on query, never pushed per tick."
- **P9.13 Onboarding**: "Do DS-13. First Session Tutorial in Help, docs links from step panels,
  docs screenshots refreshed with the isolated harness."
- **P9.14 Docking**: "Do DS-14 last. Splitters to docks with a one-time migration of saved
  proportions; workspaces; the 640×480 and empty-layout tests still pass. Own DECISIONS entry."

## Debugging prompt template (any phase)

```
Bug: <symptom>. Repro: <steps/fixture>. Expected vs actual: <...>.
First write a failing test that reproduces it, then fix, then show the test passing.
Do not touch golden sync assertions. If the fix changes behavior, update docs and DECISIONS.md.
For CI failures, also identify the boundary that failed (dependency/runtime, headless compositor,
decode evidence, lifecycle, or packaging); do not paper over it with retries outside the known
transient raw-capture case.
```
