# AvialSync — Interface Design Plan (Phase 9)

> **Status: IN PROGRESS.** Branch `feat/interface-design`; DS-0 to DS-14 are complete.
> Screenshots in `docs/_static/screenshots/` are regenerated with the isolated harness (DS-13 step 3). This is the only open phase plan. Completed plans are in
> `archive/plans/`; their settled outcomes are in DECISIONS.md.
>
> **Revision 2 (2026-10-05).** Rebased on `feat/physical-props` at `32c1839`, so it includes D-166
> overlay label layout (`3c5b1c0`, `173bc4f`, `32c1839`). Every finding is now traced to a file and
> line, and each package lists the existing tests it must amend, not only the tests it adds.
>
> **Companion documents:** binding rules in AGENTS.md (they outrank this file); phase summary in
> BLUEPRINT.md Phase 9; kickoff prompts in PROMPTS.md §Phase 9.

---

## 0. How to use this document

You are an agent picking up **one** work package. Read AGENTS.md in full, then §1–§5 here, then
your package in §6 and any package it depends on. Do that package only, and check §11 before
reporting.

- **Evidence comes first.** Each package cites its findings by id (§2). If a finding no longer
  reproduces at the start of your session, say so and skip that step. Do not fix what is not
  broken.
- **Decisions come before code.** Any package that moves a control, renames a label, or changes
  what a surface looks like structurally writes its DECISIONS entry first (§9 lists them).
- **Amend tests, never weaken them.** §8 lists every existing test that pins a layout this plan
  changes. Amending one means its docstring states the new policy and cites the new decision, and
  the new assertion is at least as strong as the old one.
- Split a large package only at a numbered step, and report which steps remain.

---

## 1. Objective and what changed since revision 1

Phases 7 and 8 made the application correct and honest. The **visual design** has not caught up.
It reads as stock Qt with text buttons everywhere: controls are correct but arranged in ways that
cost height and attention, and several rule-15 identity violations survived Phase 7.

**Goal:** make the existing capability legible and dense enough for a 4-camera, 128-channel session
on a 1280×800 laptop window, without removing any command, shortcut, evidence lane, or persisted
state.

**Out of scope:** new analysis or formats; anything that changes timing, seek, or frame selection.

### What the D-166 commits settled, and what they now constrain

| Commit | What it did | Effect on this plan |
|---|---|---|
| `3c5b1c0` | `ui/label_layout.LabelLayout` places prop, wheel, and 3D labels after the geometry: inside the picture, clear of each other, of marks, and of the pane's name/OSD/zoom chrome | Overlay label collisions are **solved**; no package redoes them |
| `173bc4f` | Bounded nearest-free-spot search keeps labels apart at any font size within the paint budget | Large-font behaviour is covered; DS-5 must keep it that way |
| `32c1839` | Array overlap tests; 64-label frame 65 ms → 14 ms; placements bit-identical | `tests/test_label_layout.py::test_a_frame_full_of_labels_paints_within_the_ui_budget` becomes a budget DS-5 and DS-9 must not regress |

**The new constraint.** `PaintCanvas._label_area` (`ui/video_overlay.py:368`) finds the chrome
to avoid **by attribute name**: `lbl_name`, `lbl_osd`, `zoom_controls`. Any package that renames,
replaces, or re-parents those widgets breaks label avoidance silently: labels draw under the
header again and no test fails unless the header case is exercised. DS-5 therefore replaces the
name lookup with an explicit `VideoPane.chrome_rects()` contract before it touches the chrome.

---

## 2. Findings register

Evidence comes from the screenshots in `docs/_static/screenshots/` (generated 2026-10-05 17:52
from `3c5b1c0`) and from reading the code at `32c1839`. **Confirmed** means the cause is visible in
code; **Suspected** means only the screenshot shows it, and DS-0 confirms or dismisses it.

| Id | Finding | Evidence | State | Package |
|---|---|---|---|---|
| F-01 | Five full-width strips under the plots; ~2.5 plot rows visible at 1280×860 | `feature_light_theme.png`; `plot_header.py`, `transport.py` `Transport.__init__` | Confirmed | DS-3 |
| F-02 | Loop In/Out/Clear and Speed are injected into the Data Streams header, away from Play | `transport.py:1039` `evidence._add_header_controls(...)` | Confirmed | DS-3 |
| F-03 | App status lives in the Data Streams header; the real status bar holds only the activity area | `transport.py:780–830`; `main_window.py:1019` | Confirmed | DS-3 |
| F-04 | "Status: Ready" renders amber in Dark | `TimelineEvidence.set_status` (`transport.py:822`) reads the info colour from the label's own palette, which the previous busy stylesheet tinted | Confirmed (cause) | DS-0 |
| F-05 | Scrubber shows no coverage, annotations, or loop range | `transport.py:133` `JumpSlider` is a bare `QSlider` | Confirmed | DS-3 |
| F-06 | Duration 4.249 s beside time span 4.000 s with no explanation | `feature_light_theme.png` | Confirmed | DS-3 |
| F-07 | Data Streams lanes ~90 px each with only two sources | `feature_light_theme.png` | Confirmed | DS-4 |
| F-08 | OSD is a multi-line `QLabel` with a fixed stylesheet; it clips instead of eliding at 3 cameras | `video_pane.py:1019`; `video_timing.format_video_osd`; `feature_props_wheel_review.png` | Confirmed | DS-5 |
| F-09 | Camera name and OSD share one `QHBoxLayout` with a stretch and overlap on narrow panes | `video_pane.py:1024–1030` | Confirmed | DS-5 |
| F-10 | Zoom controls are text buttons "+", "−" and a reload glyph | `video_pane.py:1040–1060` | Confirmed | DS-2, DS-5 |
| F-11 | A single camera draws small in a large black field | `feature_light_theme.png` | Confirmed | DS-5 |
| F-12 | "Fullscreen Toggle" and "Play original" read as mechanisms, not commands | `view_toolbar.py:68` | Confirmed | DS-5 |
| F-13 | Six inspector tabs in a 280 px pane elide to "Sour…", "Mess…", "Chan…", "Tas" | `main_window.py:626–635`, `main_window.py:1146` (280 px default) | Confirmed | DS-6 |
| F-14 | Inspector pages scroll sideways by policy; Wheel page text is clipped | `sidebar.py:930`, `wheel_tab.py:34` (`ScrollBarAsNeeded`); `feature_props_wheel_review.png` | Confirmed | DS-8 |
| F-15 | Wheel placement: ~12 equally weighted buttons and multi-paragraph instructions | `wheel_panel.py` `_build_points`, `_build_actions`; screenshot | Confirmed | DS-8 |
| F-16 | Props header: kind combo, name field, Add, and a saved-props combo with no labels | `props_panel.py:93–121`; `feature_props_tab.png` | Confirmed | DS-8 |
| F-17 | Props, Tasks, Changes pages have no empty state | `feature_props_tab.png`, `feature_tasks_tab.png` | Confirmed | DS-8 |
| F-18 | **Rule 15 / D-092 violation still live:** sidebar "Open Videos" vs menu "Open Video(s)…"; sidebar "Open Sensor/Ephys Data" is a second literal | `sidebar.py:944–945` plain `QPushButton`s; `menus/file.py:33` | Confirmed | DS-1 |
| F-19 | Reset Session has **no menu action** and sits in the Open group with equal weight | `sidebar.py:946`; no entry in `menus/` | Confirmed | DS-1, DS-7 |
| F-20 | **Rule 15 twin:** plot header "Reset plots" and View "Reset Plot Zoom" share Ctrl+0 under two labels | `plot_header.py:55`; `menus/view.py:135` | Confirmed | DS-1 |
| F-21 | 52 user-facing literals passed to widget constructors without `tr()`; the i18n gate cannot see them | e.g. `plot_header.py` "Signals", "Live", "Rows", "Compact"; `transport.py` "Data Streams", "Hide", "Speed"; `video_pane.py` "No Footage"; `i18n.untranslated_calls` scans `USER_FACING_SETTERS` only | Confirmed | DS-1 |
| F-22 | Seven modules still construct `QSettings("AvialSync","AvialSync")` outside the settings schema | `transport.py`, `plot_pane.py`, `recent_files.py`, `shortcut_overrides.py`, `theme.py`, `workspaces.py`, `session_controller.py` | Confirmed | DS-1 (audit) |
| F-23 | Close/info/remove glyphs differ: "X", "×", "✕", "ⓘ" | `feature_light_theme.png` | Confirmed | DS-2 |
| F-24 | No primary / secondary / destructive distinction anywhere | all screenshots | Confirmed | DS-2 |
| F-25 | Offset and drift spin boxes always expanded on every source card | `sidebar.py` `VideoInfoWidget`, `SensorInfoWidget` | Confirmed | DS-7 |
| F-26 | Sensor card shows a raw temp path (`/var/folders/sc/…`) | `feature_light_theme.png` | Confirmed | DS-7 |
| F-27 | Light theme: plot gutter labels (name, unit, range) appear missing; Dark shows them | `feature_light_theme.png` vs `feature_tasks_tab.png`; `plot_row._update_channel_gutter`, `plot_theme` `setLabel(color=…)` | Suspected | DS-0, DS-9 |
| F-28 | Heavy black row separators and grid outweigh the traces in Light | `feature_light_theme.png` | Confirmed | DS-9 |
| F-29 | Trace identity is colour only; D-094 deferred redundant encoding to its own decision | DECISIONS D-094 | Confirmed | DS-9 |
| F-30 | Decimal separators mixed: spin boxes "0,000000 s", axes "0.5" | `feature_light_theme.png` | Confirmed | DS-10 |
| F-31 | No `QToolBar`; Phase 7 WP-10 promised an Align toolbar entry | `grep QToolBar` finds none | Confirmed | DS-11 |
| F-32 | Painted widgets (plot rows, lanes, video, 3D) expose nothing to assistive tech | no `QAccessibleInterface` in `ui/` | Confirmed | DS-12 |
| F-33 | Help has no First Session Tutorial though `docs/tutorials/first-session.md` exists | `menus/help.py` | Confirmed | DS-13 |
| F-34 | Four nested splitters, not docks; no multi-monitor layout | `ui/workspaces.py` docstring | Confirmed | DS-14 |
| F-35 | Video chrome colours are fixed stylesheets (white on translucent black) | `video_pane.py:1001–1033` | Confirmed; acceptable over video, needs a stated exception | DS-5 |
| F-36 | Screenshot tools do not isolate QSettings or the recovery snapshot, so a run can overwrite the operator's real unsaved-work snapshot | `tools/screenshot_kit.py` vs `tests/conftest.py:47`, `isolated_recovery_dir` | Confirmed | DS-0 |

---

## 3. Design rules for this phase

**Inherited, and the ones most likely to be broken:**

1. **No application QSS, and no per-widget stylesheet for colour or weight** on chrome that follows
   the theme. A stylesheet pins the palette, so a theme switch never reaches the widget. F-04 is
   that exact bug. Use `QPalette` roles, `theme.follow_palette`, `theme.set_bold`, and `ui/icons.py`.
   The one stated exception is the chrome painted *over video* (F-35), which is theme-independent
   by design because the picture behind it is.
2. **Themes stay appearance-only.** Layout changes here are product changes recorded in DECISIONS;
   a theme switch still changes only palette and font.
3. **One authority per label (rule 15).** A button that runs a menu command is an `ActionButton`
   on that `QAction`. Renaming it means renaming the action. D-126 kept Snapshot and Fullscreen as
   plain buttons to avoid long menu labels; this phase resolves that by shortening the action
   labels instead.
4. **Every overlay is registered (rule 13).** OSD and camera name stay behind `camera.osd` and
   `camera.name`.
5. **Accessibility and translation are gates (rule 17)**, now including constructor literals (DS-1).
6. **Layout floors:** the 640×480 compact viewport keeps every surface reachable; minimum width
   stays within the 1366 px laptop bound; the empty-window layout (D-127) holds.
7. **Budgets:** nothing new on the 60 Hz tick, no pyramid queries on ordinary ticks, and the label
   layout paint budget holds (`test_label_layout.py`).

**New in this phase:**

| Rule | Statement | Enforced by |
|---|---|---|
| R1 One strip per subject | Videos, plots, timeline, playback each get at most one control row; the window spends height on data | DS-3 policy test: plot area share at 1280×800 |
| R2 Visible hierarchy | At most one primary action per surface; destructive actions separated and marked by glyph as well as colour | DS-2 role-enumeration test |
| R3 Wrap, elide, then scroll | Text wraps or elides with full text in tooltip and accessible description; horizontal scroll is the last resort, kept only as the backstop `test_content_too_wide_is_scrollable_not_hidden` protects | DS-8 "no page needs horizontal scroll at minimum width" test |
| R4 One-line instructions | A guided panel shows the step, one sentence, and one primary next action; detail sits behind "More…" | DS-8 step-panel test |
| R5 Empty states | Every page that can be empty says what fills it and offers that action | DS-8 enumeration test |

---

## 4. Target layout

### 4.1 Main window: today and target (1280×800)

```
TODAY                                              TARGET
┌───────────┬──────────────────────────────┐       ┌────┬────────┬──────────────────────────────┐
│Sour|Val|… │ video panes                  │       │ ▣  │Sources │ video panes                  │
│(6 tabs    │                              │       │ ≡  │ cards  │  name · 00:01.234 · f 37   ⤢ │
│ elided)   ├──────────────────────────────┤       │ ✎  │        │                              │
│           │ Flag|Fix|3D|Play orig|Snap|… │ ①     │ ⚙  │        ├──────────────────────────────┤
│ source    ├──────────────────────────────┤       │    │        │ ⚑ ✎ ⊕ │ ◱ ⤢ ⛶   (icon tools) │ ①
│ cards     │ plot rows (≈2.5 visible)     │       │    │        ├──────────────────────────────┤
│ (offsets  ├──────────────────────────────┤       │    │        │ plot rows (≈4–5 visible)     │
│ expanded) │ Signals Live▾ … Fit Rows Reset│ ②    │    │        │                              │
│           │ Time span [4,000][s▾] ────●  │ ③     │    │        ├──────────────────────────────┤
│           ├──────────────────────────────┤       │    │        │ Live▾ span[4.000 s▾]──● FitY ⟲│ ②
│           │ Data Streams lanes (tall)    │       │    │        │ Data Streams ▾  (compact)    │ ③
│           ├──────────────────────────────┤       │    │        │  Video · cam1  ▬▬▬▬▬▬▬       │
│           │ DS Hide · Status · Loop · Spd│ ④     │    │        │  Data  · sig   ▬▬▬▬▬▬▬▬      │
│           ├──────────────────────────────┤       │    │        ├──────────────────────────────┤
│           │ ⏮Back ◀◀Prev ▶Play ▶▶Next …  │ ⑤     │    │        │⏮◀▶▶⏭ 00:01.234 ▕▔coverage▔▏ 04.249│ ④
│           │                              │       │    │        │  [ / ] ✕ loop   1.0×▾        │
└───────────┴──────────────────────────────┘       └────┴────────┴──────────────────────────────┘
 status bar: (empty unless a job runs)              status bar: Ready · jobs ▴ · Saved
 five strips under the plots (②–⑤ + ①)              three strips (①–④, ③ is header + lanes)
```

The rail at far left is DS-6's inspector navigation. Video tools (①) keep their D-126 place.

### 4.2 Transport row (DS-3)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ ⏮  ◀|  ▶ (primary)  |▶  ⏭ │ 00:00:01.234 │▕▒▒▒▒▒████████░░░░▲▒▒▒▒▒▒▒▒▒▕│ 00:00:04.249 │ [ ] ✕ │ 1.0×▾ │
│ jump  frame  play  frame jump  time entry    scrubber: coverage tint,    end (tooltip    loop   speed │
│                                              annotation ticks, loop span  explains it)          │
└──────────────────────────────────────────────────────────────────────────────────────────┘
 every glyph-only button: tooltip = accessible name = command-palette label (rule 15, rule 17)
```

### 4.3 Video pane header (DS-5)

```
┌───────────────────────────────────────────────┐   compact (default)   name · time · frame
│ camera_2.mp4 · 00:00:01.234 · f 37/119    ⊕⊖⟲ │   full                + CFR/VFR line, codec · size
│                                               │   off                 nothing (layer unchecked)
│           picture (aspect-sized pane)         │   narrow pane         name elides first, then time
│                                               │   zoom tools          always reserve their rect, so
└───────────────────────────────────────────────┘                       LabelLayout never moves on hover
 header rects come from VideoPane.chrome_rects() → PaintCanvas._label_area → LabelLayout
```

### 4.4 Guided step panel (DS-8)

```
┌ Wheel · Example ─────────────────────────── Step 5 of 12 ┐
│ ●●●●○○○○○○○○                                              │
│ Click point 2B in camera_3 (second end of bar 2).         │
│ [ Next point ]  (primary)            Undo click  Go to frame│
│ ▸ More…   (explanation, residuals, projected-mark legend) │
│ ⋯  Flip side · Discard clicks (destructive, in overflow)  │
└───────────────────────────────────────────────────────────┘
```

### 4.5 Source card (DS-7)

```
┌──────────────────────────────────────────┐
│ ☑ 🎞 camera_1.mp4          ⚠2   ⋯        │  ⋯ = Properties · Copy details · Remove (destructive)
│   H264 · CFR 30.00 · 4.0 s               │  ⚠ = quality badge, click expands findings
│   ▸ Timing  offset +0.000 s · drift 0 ppm │  disclosure opens the existing spin boxes
└──────────────────────────────────────────┘
```

---

## 5. Foundations

### D1 — Design tokens and control roles (`ui/design_tokens.py`)

| Token | Values | Notes |
|---|---|---|
| Spacing | 2 · 4 · 8 · 12 · 16 · 24 px | scaled by the Font Size preference ratio |
| Strip | height = one control + 2×4 px; margins 4 px | replaces ad-hoc `setContentsMargins(5,3,5,5)` |
| Card | padding 8 px; gap 4 px | sidebar cards, step panel |
| Type roles | body · caption (−1 step) · heading (bold) · numeric (system fixed font, tabular) | no new font files; numeric already uses `QFontDatabase.FixedFont` |
| Control roles | `primary` · `secondary` · `tool` · `destructive` | see below |
| Density | `comfortable` · `compact` | extends plot Rows; strips, lanes, and cards read it from `core/settings_schema.py` |

`apply_role(button, role)` is the only way to style a button:

| Role | Built from (no stylesheet) | Example |
|---|---|---|
| primary | `setDefault(True)` where the platform draws it; `theme.set_bold`; icon | Play, Next point, Open… |
| secondary | plain push button | Fit Y, Undo click |
| tool | `QToolButton`, icon only, `autoRaise`; text in tooltip, accessible name, palette | step buttons, zoom, row close |
| destructive | separated by a spacer or placed in an overflow; error glyph from `set_status_icon` | Reset Session, Remove source, Discard clicks |

### D2 — Icon set (`resources/icons/`)

A bundled SVG set, inked to the palette through `ui/icons.py`, which already re-inks standard
icons. Candidate: **Lucide (ISC)**; alternatives Material Symbols (Apache-2.0) and Phosphor (MIT).
The DECISIONS entry names the licence (AGENTS dependency policy). Data only: `QtSvg` already ships
with PySide6. Package via `pyproject` package data and the PyInstaller spec, and add a packaging
test that the icons are in the wheel and the bundle.

---

## 6. Work packages

Effort: **S** ≤ 1 session · **M** 2–3 sessions · **L** 4+ sessions.

### DS-0 — Isolated screenshot baseline and defect triage · S · depends on nothing

Fixes F-36 and triages F-04 and F-27.

| Step | Do | Files |
|---|---|---|
| 1 | Give the screenshot harness the test suite's isolation: `QSettings.setDefaultFormat(IniFormat)` + `setPath` to a temp dir and a redirected `recovery.recovery_dir`, so a capture can never overwrite the operator's settings or recovery snapshot | `tools/screenshot_kit.py` |
| 2 | Add a `--out` argument to `tools/generate_feature_screenshots.py` (default unchanged) | same |
| 3 | Capture every surface in Light and Dark at 1280×800, 1600×900, 640×480 into a dated folder outside `docs/` | — |
| 4 | F-04: fix `TimelineEvidence.set_status` to colour from the inherited palette (`theme._inherited_palette`) or `follow_palette`, never the label's own | `transport.py` |
| 5 | F-27: reproduce gutter labels in Light; fix in `plot_theme` / `plot_row` or dismiss with a reason | `plot_theme.py`, `plot_row.py` |
| 6 | Check F-08 and F-14 at 3 cameras and 280 px | — |

**Acceptance:** a test that switches busy → info and asserts the info colour equals `WindowText`
of the inherited palette in both themes; a Light-theme test asserting the gutter label colour
contrasts with the canvas; the harness leaves `QSettings` and `recovery_dir()` untouched (assert
file mtimes).

### DS-1 — Authority and strings sweep · S–M · depends on nothing

No visual redesign. It closes the rule 15 and rule 17 holes Phase 7 left (F-18 to F-22).

| Step | Do | Files |
|---|---|---|
| 1 | Sidebar Open buttons become `ActionButton`s on `_act_open_video` and the sensor action; delete the literals | `sidebar.py`, `main_window.py` |
| 2 | Add File → **Reset Session** as a `QAction`, still undoable and unconfirmed (UX_FOUNDATIONS WP-2); the sidebar button binds to it | `menus/file.py`, `sidebar.py` |
| 3 | Plot header Reset becomes an `ActionButton` on `_act_reset_zoom`; choose one label ("Reset Plots") | `plot_header.py`, `menus/view.py` |
| 4 | Wrap the 52 constructor literals in `tr()` | per §2 F-21 |
| 5 | Extend `i18n.untranslated_calls` beyond `USER_FACING_SETTERS` to string constants passed to the `QLabel`, `QPushButton`, `QCheckBox`, `QGroupBox`, `QRadioButton`, `QToolButton`, and `QAction` constructors and to `addItem` (combo entries such as "Compact", "Comfortable") | `i18n.py` |
| 6 | Audit the seven direct `QSettings` sites; move user preferences into `core/settings_schema.py`; leave purely mechanical state (splitter geometry, recent-file list) with a named exception list in the test | listed in F-22 |

**Acceptance:** a test asserting each sidebar and header button's text equals its action's text;
`translatable_ratio` stays at 100 % under the wider scan; a source scan allowing direct `QSettings`
construction only in the listed exceptions. DECISIONS: D-A1.

### DS-2 — Tokens, roles, and icons · M · depends on DS-0

Foundations D1 and D2; fixes F-10 (glyphs), F-23, F-24.

| Step | Do | Files |
|---|---|---|
| 1 | Write D-A2 (tokens, roles) and D-A3 (icon set and licence) | DECISIONS.md |
| 2 | Add `ui/design_tokens.py` with spacing, type roles, density, and `apply_role()` | new |
| 3 | Add the SVG icons and `icons.set_svg_icon(button, name)` sharing the re-ink follower | `resources/icons/`, `icons.py`, `pyproject.toml`, `packaging/avialsync.spec` |
| 4 | Assign a role to every existing button **without moving any**: one primary per surface; destructive marked | all `ui/` panels |
| 5 | Unify close, info, and remove onto one icon each | `sidebar.py`, `plot_row.py`, `video_pane.py` |

**Acceptance:** a test enumerating every `QAbstractButton` in a populated window asserts it has a
role and no surface has two primaries; a source scan finds no new `setStyleSheet`;
`tests/test_theme_switching.py` asserts every SVG icon re-inks; a packaging test finds the icons in
the wheel.

### DS-3 — Bottom chrome: five strips to three · L · depends on DS-2

Fixes F-01, F-02, F-03, F-05, F-06. **Amends D-126** (decision D-A4).

| Step | Do | Files |
|---|---|---|
| 1 | Write D-A4: plots row; Data Streams header + lanes; transport with loop and speed; status to the status bar | DECISIONS.md |
| 2 | Merge `PlotHeader` and the time-span row into one row (§4.1 ②); time-span value and unit combine into one field | `plot_header.py`, `plot_pane.py` |
| 3 | Move Loop In/Out/Clear and Speed from `evidence._add_header_controls` into the transport row (§4.2); remove `_add_header_controls` | `transport.py` |
| 4 | Step buttons become `tool` role with SVG icons; Play is `primary` and checkable (toggle semantics, UX_FOUNDATIONS WP-12 step 7) | `transport.py` |
| 5 | Move status into a `StatusLine` in `QStatusBar` beside `activity_bar`, keeping `Transport.set_status` / `status_text` as forwarding API (callers in `main_window.py`, `import_controller.py`, `video_controller.py`, `session_controller.py`) | new `ui/feedback/status_line.py`, `main_window.py` |
| 6 | Replace `JumpSlider` with a `ScrubBar` that paints a cached coverage/annotation/loop track under the handle; invalidate on change, never per tick | `transport.py` or new `ui/scrub_bar.py` |
| 7 | End-time tooltip explains duration vs plot span (F-06) | `transport.py` |

**Acceptance:** signal-level tests that every moved control emits the same signal or triggers the
same action; a policy test that the plot area's share of window height at 1280×800 rises
(assert the ordering, not pixels); a benchmark that a scrub tick does not repaint the track cache;
640×480 compact viewport passes. Tests amended per §8: `test_transport_layout.py` ×4,
`test_control_layout.py` ×1, `test_transport_resize.py` (A/B pins now relative to the new track).

### DS-4 — Data Streams density · S · depends on DS-2, DS-3

Fixes F-07.

| Step | Do | Files |
|---|---|---|
| 1 | Lane height from the density token (compact ≈ one caption line + 4 px) | `transport.py` `TimelineOverview` |
| 2 | Cap the lane area at N lanes, then scroll vertically; persist the cap per density | `transport.py`, settings schema |
| 3 | Lane labels elide with a tooltip (R3); D-159 tints with solid 2 px caps in both themes | `transport.py` |

**Acceptance:** 4 videos + 6 data sources show without scrolling at 1280×800 compact;
`test_coverage_lanes.py` and the lane tests in `test_transport_layout.py` pass unchanged.

### DS-5 — Video pane chrome · M · depends on DS-2

Fixes F-08, F-09, F-10, F-11, F-12, F-35.

| Step | Do | Files |
|---|---|---|
| 1 | **First:** add `VideoPane.chrome_rects()` and make `PaintCanvas._label_area` use it instead of looking up `lbl_name`/`lbl_osd`/`zoom_controls` by name | `video_pane.py`, `video_overlay.py` |
| 2 | One header widget: name · time · frame (compact), eliding name first; detail level off/compact/full stored with the registered `camera.osd` layer | `video_pane.py`, `video_timing.format_video_osd`, `overlay_registry.py` |
| 3 | Zoom tools become `tool` buttons; their rect is **always reserved** in `chrome_rects()`, whether or not hover shows them, so labels never jump | `video_pane.py` |
| 4 | Aspect-sized panes for 1–2 cameras (as D-153 does for the stimulus grid) | `video_grid.py` |
| 5 | Rename actions: "Fullscreen Toggle" → "Fullscreen"; "Play original" gets a descriptive tooltip and accessible description; Snapshot and Fullscreen become `ActionButton`s (resolves the D-126 exception) | `view_toolbar.py`, `menus/view.py` |
| 6 | Document the over-video stylesheet exception (F-35) in D-A5, or move the chrome to painted text | `video_pane.py` |

**Acceptance:** `test_label_layout.py::test_crowded_labels_stay_apart_inside_the_picture_and_off_the_header`
and the paint-budget test pass; a new test where a label anchored under the header lands outside
`chrome_rects()` for compact and full OSD; the OSD never exceeds pane width at 3 cameras × 1280 px;
the overlay registry inventory test and Law 2 conformance pass; golden sync untouched.

### DS-6 — Inspector navigation · M · depends on DS-2

Fixes F-13.

| Step | Do | Files |
|---|---|---|
| 1 | Write D-A6: page set and order (Sources, Values, Messages, Changes, Props) and Tasks' new home | DECISIONS.md |
| 2 | Replace text tabs with an icon + label rail beside a `QStackedWidget`; labels never elide; keyboard reachable; page persisted through the settings schema | `main_window.py` (thin), new `ui/inspector_nav.py` |
| 3 | Tasks moves to a status-bar popover anchored on `activity_bar` | `ui/feedback/jobs_panel.py`, `main_window.py` |
| 4 | Command palette gains "Show Sources/Values/…" actions | `menus/view.py` |

**Acceptance:** every former page reachable by click, keyboard, and palette; persisted page
restores; `test_sidebar_layout.py::test_the_sidebars_own_chrome_fits_its_minimum` passes with the
rail; screenshot tools updated (`_show_tab` in `generate_feature_screenshots.py` uses the rail).

### DS-7 — Source cards at scale · M · depends on DS-1, DS-2, DS-6

Fixes F-19 (placement), F-25, F-26.

| Step | Do | Files |
|---|---|---|
| 1 | Compact card (§4.5): kind icon, elided name with full path in tooltip, quality badge, visibility, one overflow menu | `sidebar.py` `VideoInfoWidget`, `SensorInfoWidget` |
| 2 | Offset and drift behind a "Timing" disclosure showing the current values inline; the same spin boxes (one authority), so D-087 drag coalescing is unchanged | `sidebar.py` |
| 3 | Open group: one primary split "Open…" button with Videos / Sensor data entries (both `ActionButton`-backed); Reset Session leaves the group for File and the overflow, `destructive` | `sidebar.py` |
| 4 | Show paths relative to the session folder or as `…/parent/name` | `sidebar.py`, `elided_label.py` |

**Acceptance:** 4 cameras + 12 files show every name and badge at 1280×800 compact; an offset drag
still records one undo command; `test_sidebar_layout.py` path and elision tests pass; the Law 1
conformance test still passes.

### DS-8 — Guided workflows and empty states · L · depends on DS-2, DS-6

Fixes F-14, F-15, F-16, F-17. One flow per commit.

| Step | Do | Files |
|---|---|---|
| 1 | `ui/step_panel.py` (§4.4): title, progress, one-sentence instruction, one primary, secondary row, overflow, "More…" disclosure, docs link | new |
| 2 | Wheel page onto it | `wheel_panel.py`, `wheel_tab.py` |
| 3 | Props header gets labels and order: Kind ▾ · Saved ▾ · [Name] [Add] | `props_panel.py` |
| 4 | Ladder, Belt, Ball editors onto the step panel | `props_panel.py`, `belt_placement_controls.py` |
| 5 | Fix Identities onto it | `identity_panel.py` |
| 6 | Alignment evidence flow onto it | `sync_wizard.py`, `sync_evidence_view.py` |
| 7 | Empty states for Props, Changes, Messages, Values, and the Tasks popover | respective panels |
| 8 | Text wraps to the panel width; `ScrollBarAsNeeded` remains as the backstop only | `wheel_tab.py`, `sidebar.py` |

**Acceptance:** existing wheel, prop, identity, and sync flow tests pass unchanged in behaviour; a
test asserting no inspector page's `sizeHint().width()` exceeds the 280 px default (so the
horizontal bar never appears in normal use) while
`test_content_too_wide_is_scrollable_not_hidden` still holds; an enumeration test that every
inspector page has an empty state naming its filling action.

### DS-9 — Plot rows · M · depends on DS-0, DS-2

Fixes F-27 (if confirmed), F-28, F-29.

| Step | Do | Files |
|---|---|---|
| 1 | Write D-A7: redundant encoding of channel identity (D-094's deferred structural change), either a dash cycle or a direct end-of-trace label | DECISIONS.md |
| 2 | Row close and row actions become `tool` buttons shown on hover/focus plus the row context menu; close-to-hide semantics and the sidebar link unchanged | `plot_row.py`, `plot_pane.py` |
| 3 | Lighter separators and grid in both themes | `plot_theme.py` |
| 4 | Implement D-A7 | `plot_row.py`, `plot_theme.py` |
| 5 | Default density shows more rows at 1280×800 | `plot_header.py` |

**Acceptance:** `tests/benchmarks/test_bench_plot_pane.py` within 20 %; `test_palette_cvd.py`
unchanged; a test asserting every visible trace carries a non-colour identifier.

### DS-10 — Numbers, units, and time · S · depends on nothing

Fixes F-30.

| Step | Do | Files |
|---|---|---|
| 1 | Write D-A8: either everything follows `QLocale` (spin boxes, axis ticks, readouts, OSD) or everything uses `.`. Note the import wizard already parses euro decimals, and file I/O stays locale-independent either way | DECISIONS.md |
| 2 | Apply it through one formatter in `ui/time_format.py` and a pyqtgraph `AxisItem.tickStrings` override | `time_format.py`, `plot_row.py`, spin-box sites |
| 3 | Trim precision: offsets show µs only when the source rate warrants it | `sidebar.py`, `offsets_panel.py` |

**Acceptance:** under a comma-decimal locale, a spin box, an axis tick, and the readout panel use
the same separator; session files are byte-identical before and after.

### DS-11 — Top-level entry points · S · depends on DS-2, DS-7

Fixes F-31.

| Step | Do | Files |
|---|---|---|
| 1 | Write D-A9: ship a slim main toolbar (Open…, Align, Add Prop, Command Palette, Fullscreen), or decide against one | DECISIONS.md |
| 2 | If shipped: `QToolBar` of `ActionButton`s / actions only, hideable, state persisted, fits 640×480 | `main_window.py`, `menus/view.py` |

**Acceptance:** toolbar entries are live actions; hiding persists; compact viewport test passes.

### DS-12 — Accessibility of painted surfaces · M · depends on nothing

Fixes F-32.

| Step | Do | Files |
|---|---|---|
| 1 | `QAccessibleInterface` for plot rows: name, unit, value at playhead (computed on query) | new `ui/accessible_views.py` |
| 2 | Data Streams lanes: lane name, coverage span, child events with time | same |
| 3 | Video panes: camera, time, frame; 3D pane: point count, view angles | same |
| 4 | Keyboard-only walkthrough reaching every primary action | tests |

**Acceptance:** `tests/test_accessibility_i18n.py` covers these widgets; no value is pushed per
tick (a test counts `QAccessible.updateAccessibility` calls during playback).

### DS-13 — Onboarding and help · S · depends on DS-8

Fixes F-33.

| Step | Do | Files |
|---|---|---|
| 1 | Help → First Session Tutorial (docs URL from `[project.urls]` + `tutorials/first-session`) | `menus/help.py`, `help_controller.py` |
| 2 | "Learn more" links from step panels to their docs pages | `step_panel.py` |
| 3 | Refresh docs screenshots with the isolated harness (DS-0) | `docs/_static/screenshots/` |

**Acceptance:** every Help item resolves to a `[project.urls]` URL or a shipped file; docs build
with warnings as errors.

### DS-14 — Docking and workspaces · L · depends on DS-3, DS-6 · last

Fixes F-34; carried from UX_FOUNDATIONS WP-11.

| Step | Do | Files |
|---|---|---|
| 1 | Write D-A10: which panes become docks; how `PaneProportions` minimum enforcement and the D-127 empty layout carry over | DECISIONS.md |
| 2 | Convert the four nested splitters to `QDockWidget`s with nesting | `main_window.py`, `pane_proportions.py`, `splitter.py` |
| 3 | One-time migration from saved splitter state to dock sizes (archived UX_FOUNDATIONS §7) | `session_controller.py`, `workspaces.py` |
| 4 | Named workspaces store dock state | `workspaces.py` |

**Acceptance:** a pre-migration QSettings layout restores into docks; workspace round-trip;
all of `test_ui_layout_resize.py` and `test_empty_layout.py` pass.

---

## 7. Charts

### 7.1 Dependency graph

```
DS-0 ─┬─────────────► DS-9 (gutter fix needs DS-0's triage)
      └─► DS-2 ─┬───► DS-3 ─┬─► DS-4
                │           └─────────────────────┐
                ├───► DS-5                        ├─► DS-14 (last)
                ├───► DS-6 ─┬─────────────────────┘
                │           ├─► DS-7 ─► DS-11
                │           └─► DS-8 ─► DS-13
                └───► DS-9
DS-1 ─────────► DS-7            DS-10, DS-12: independent, any time
```

### 7.2 Recommended schedule (focused sessions)

```
Week        1        2        3        4        5        6        7
DS-0     ███
DS-1     ███████
DS-10       ███
DS-2        ██████████
DS-3                 ████████████
DS-6                 ██████
DS-8                       ███████████████
DS-7                          ████████
DS-5                       ████████
DS-4                                ███
DS-9                                ██████
DS-12                                     ██████
DS-11                                     ██
DS-13                                        ███
DS-14                                           ██████████████
```

### 7.3 Risk matrix

| Package | Breakage risk | Why | Mitigation |
|---|---|---|---|
| DS-14 | High | Splitter geometry repair, minimum enforcement and empty layout are load-bearing (D-049, D-061, D-098, D-127) | Last; own decision; migration test first |
| DS-3 | High | Moves transport controls pinned by seven tests; status API has four callers | Keep `set_status` forwarding; amend tests per §8 with the decision |
| DS-5 | Medium | Chrome by attribute name feeds LabelLayout (§1) | Step 1 adds `chrome_rects()` before anything moves |
| DS-8 | Medium | Six flows, many signals (`PropsPanel` declares 25) | One flow per commit; behaviour tests unchanged |
| DS-2 | Medium | Touches every panel; tempting to use stylesheets | Role helper only; source-scan test |
| DS-9 | Medium | Plot paint path budgets | Benchmarks within 20 % |
| DS-0, 1, 4, 6, 7, 10–13 | Low | Additive or local | — |

### 7.4 Finding → package coverage

```
DS-0  F-04 F-27 F-36            DS-7  F-19 F-25 F-26
DS-1  F-18 F-19 F-20 F-21 F-22  DS-8  F-14 F-15 F-16 F-17
DS-2  F-10 F-23 F-24            DS-9  F-27 F-28 F-29
DS-3  F-01 F-02 F-03 F-05 F-06  DS-10 F-30
DS-4  F-07                      DS-11 F-31
DS-5  F-08 F-09 F-10 F-11 F-12  DS-12 F-32
      F-35                      DS-13 F-33
DS-6  F-13                      DS-14 F-34
```

---

## 8. Existing tests this plan amends

| Test | Pins today | Amended by | New policy |
|---|---|---|---|
| `test_transport_layout.py::test_seek_row_orders_playhead_ab_end_time_and_rate_controls` | playhead buttons left of time edit; A/B and rate placement | DS-3 (D-A4) | playhead · time · scrubber · end · loop · speed, in that order |
| `test_transport_layout.py::test_transport_status_does_not_block_controls` | status label in the transport | DS-3 | status line in the status bar never overlaps the activity area |
| `test_transport_layout.py::test_status_timer_is_owned_by_data_streams` | timer parent is `evidence` | DS-3 | timer parent is the status line; same deleted-label safety |
| `test_transport_layout.py::test_data_streams_header_buttons_have_explanatory_tooltips` | Loop and Speed in the header | DS-3 | header holds title, collapse, and density only; tooltips still asserted |
| `test_transport_layout.py::test_descriptive_transport_controls_leave_a_usable_slider_at_narrow_width` | text buttons | DS-3 | tool buttons; slider minimum unchanged or wider |
| `test_transport_resize.py` (5 tests) | A/B pins over `JumpSlider` | DS-3 | pins over the `ScrubBar` track |
| `test_control_layout.py::test_controls_sit_under_what_they_act_on` | D-126 row order | DS-3 | D-A4 row order |
| `test_sidebar_layout.py::test_the_sidebars_own_chrome_fits_its_minimum` | tab bar at minimum width | DS-6 | rail plus page at minimum width |
| `test_sidebar_layout.py::test_content_too_wide_is_scrollable_not_hidden` | backstop scroll policy | **not amended**; DS-8 adds a stronger sibling | — |
| `tools/generate_feature_screenshots.py::_show_tab` | tab text lookup | DS-6 | rail lookup |

---

## 9. Decisions this plan requires

Numbers are placeholders; assign the next free D-number when written.

| Placeholder | Package | Decides |
|---|---|---|
| D-A1 | DS-1 | Sidebar and header buttons are action-backed; Reset Session gains a menu action; constructor literals are gated; the `QSettings` exception list |
| D-A2 | DS-2 | Spacing, type, density tokens; the four control roles and how each is built without stylesheets |
| D-A3 | DS-2 | Icon set and licence |
| D-A4 | DS-3 | Bottom chrome order; amends D-126 |
| D-A5 | DS-5 | Video header, OSD detail levels, `chrome_rects()` contract, over-video stylesheet exception |
| D-A6 | DS-6 | Inspector page set, navigation, Tasks location |
| D-A7 | DS-9 | Redundant encoding of trace identity (D-094 follow-up) |
| D-A8 | DS-10 | Decimal separator policy |
| D-A9 | DS-11 | Main toolbar, yes or no |
| D-A10 | DS-14 | Docks, migration, empty layout under docks |

---

## 10. Performance and persistence

| Budget | Packages that touch it | Guard |
|---|---|---|
| Cursor update ≤ 2 ms ★ | DS-3 (scrub track), DS-12 | cached track; accessibility values on query only |
| Plot pan/zoom ≤ 16 ms ★ | DS-9 | `test_bench_plot_pane.py` within 20 % |
| Overlay label paint | DS-5 | `test_label_layout.py` budget test |
| UI callback ≤ 30 ms ceiling | DS-3, DS-4, DS-14 | `ui_heartbeat` distribution assertions |

Window layout, density, inspector page, toolbar visibility, OSD detail level defaults, and workspaces
persist in QSettings through `core/settings_schema.py`, never in `.avv`. Per-session overlay
visibility, including OSD detail if it is per camera, uses the existing overlay persistence. No
`.avv` schema bump is expected; if one becomes necessary it needs a backwards-compatible default.

---

## 11. Definition of done, per package

- [ ] The findings it cites are fixed or recorded as no longer reproducing.
- [ ] Acceptance tests exist and pass; amended tests follow §8 and cite the decision.
- [ ] DECISIONS entry written before code for any moved control, renamed label, or structural change.
- [ ] No `setStyleSheet` added for colour or weight outside the stated over-video exception.
- [ ] Before/after screenshots from the isolated harness attached to the PR.
- [ ] `pytest -x -q`, `ruff check .`, both mypy runs pass; affected benchmarks within 20 %.
- [ ] HANDOUT module map and user docs updated for what shipped.
- [ ] Conventional commit (`feat(ui): …`), no agent attribution.
