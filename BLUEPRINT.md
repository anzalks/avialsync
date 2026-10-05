# AvialSync — Project Blueprint (v1)

> Name: **AvialSync** (final). Casing rules are binding — see AGENTS.md §Naming.
> Open-source, GUI-first tool to scrub time-synced multi-camera video + dense time series.
> License: AGPL-3.0-or-later (D-069). Stack: Python 3.11–3.12, PySide6, PyAV, pyqtgraph, numpy, polars.

---

## Non-negotiable design principles (every phase, every agent, every PR)

1. **One master clock.** All UI state derives from a single absolute time `t_master` (float seconds, UTC epoch). Sources map to it via `t_source = t_master + offset + drift_rate * (t_master - t_ref)`.
2. **Never block the UI thread.** Decoding, file IO, cache building → worker threads. PyAV releases the GIL during decode, so panes genuinely decode in parallel. The UI thread only issues requests and paints.
3. **Never draw more points than pixels.** All plotting goes through the decimation pyramid.
4. **Modular loaders.** Every data source (video or time series) enters through a plugin interface. CSV and standard video are just the built-in plugins.
5. **Dependencies must be AGPL-compatible.** PySide6 (LGPL), PyAV (BSD, bundling a GPL-configured FFmpeg), pyqtgraph (MIT), numpy/polars (BSD/MIT). The project is AGPL-3.0-or-later and single-licensed (D-076), so GPL dependencies are fine; PyQt stays banned on user-freedom grounds, not licence-compatibility ones. New deps require a licence check in the PR.
6. **Sync correctness > frame completeness** during playback; exact frames when paused/stepping.
7. **Binary cache.** Text formats are parsed once → cached as mmap-able binary in one per-user cache folder (one entry per source: raw arrays + pyramid levels + metadata JSON), never beside the recording (D-160).
8. **Evidence-based alignment.** TTL/event alignment preserves raw timestamps and presents the
   matched evidence, offset/drift fit, residuals, and confidence before the user accepts it.
   Ambiguous evidence is surfaced, never silently guessed.
9. **Speed and timing accuracy are co-equal.** Synchronization extraction is chunked, matching is
   deterministic, and every new timing path requires a ground-truth fixture and benchmark.
10. **Never block, always inform.** Opening a file is never refused and never gated. The user is
    told when the *document* is dirty (unsaved changes) and when the *data* is dirty (gaps, NaN
    runs, missing metadata, unverified alignment) — told, not stopped. A damaged file loads as far
    as it can. Quitting always proceeds and always writes a recovery snapshot, so nothing is lost
    and nothing prompts (P7, D-088/D-089).
11. **Nothing is drawn over video that the user cannot turn off.** Every overlay is a registered
    layer with a checkbox in View → Overlays, a persisted visibility, and a default — plugin
    overlays included. The one locked layer is the D-010 "No Footage" placeholder, because hiding
    it would let a blank pane read as black footage (P7, D-090).
12. **One authority per user-visible concept.** Actions, settings, and overlays each have exactly
    one registry that owns their label, default, and behaviour. Two places defining the same
    user-facing string is how "Open Video(s)…" and "Open Videos" came to coexist (P7, D-092).
13. **Accessibility and translatability are build gates.** Strings are translatable and interactive
    widgets are described from the moment they are written, not in a cleanup phase. Categorical
    colour is validated in CVD space and never the sole carrier of meaning (P7, D-094).

## Performance budgets (engineering-certified where marked ★)

| Metric | Budget |
|---|---|
| Scrub response (3 cams, exact seek, release-of-slider) | ≤ 250 ms |
| Scrub response, drag (3 cams, cache-resident span) | ≤ 50 ms (D-075) |
| Plot pan/zoom frame time ★ | ≤ 16 ms |
| Full populated cursor update per tick ★ | ≤ 2 ms |
| 3D pose sample (128 XYZ points) ★ | ≤ 2 ms |
| Cached session open (3 cams + 4×50 kHz ch) | ≤ 3 s |
| First CSV import 1 GB (with progress) | ≤ 60 s |
| Pyramid build 180 M samples ★ | ≤ 2.5 s (revised, D-024) |
| Idle RAM, session loaded | ≤ 2.5 GB |
| Any UI-thread callback | target ≤ 8 ms, hard ceiling 30 ms |

Benchmarks live in `tests/benchmarks/`, run locally via `pytest --benchmark-only`, where the raw
★ marks are enforced without a multiplier. GitHub Actions verifies the representative scientific
session's correctness across platforms but does not use shared hosted machines to certify speed.

### Measured scrub baseline (2026-08-07, D-075)

macOS arm64, three 1440×1080 files, 3-cam parallel fanout, long-GOP (250) worst case. The lab's own
all-intra footage is roughly six times faster than the figures below.

The PyAV column is what `tests/benchmarks/test_seek_backends.py` measures against the shipped
reader — re-run it to reproduce. **The libmpv column is a record, not a re-measurable result**: the
comparison arm was deleted with the last of libmpv (D-086). These figures were taken once, on the
hardware named above, and stand as the reason D-075 was made.

| Interaction | libmpv | PyAV + frame cache | Budget |
|---|---|---|---|
| Jump to a new time | 330 ms | 117 ms | 250 ms |
| Drag the slider | 338 ms | 3 ms | 50 ms |
| Re-scrub a covered span | 333 ms | 1 ms | 50 ms |

**libmpv missed the 250 ms scrub budget on every interaction.** It costs ~330 ms whether it jumps,
drags, or revisits ground it just covered — that flatness is the exact-seek settle round-trip
through the `seeking` property observer, not decode work, and it cannot improve on a re-scrub
because mpv holds no memory of where it just was. This is what motivated D-075. Sustained decode
measured 1679 fps aggregate across three concurrent panes against ~180 fps needed to feed them, so
hardware decode is not required to hold these numbers.

---

## Delivered phases

Detail for every phase below lives in DECISIONS.md (the settled choices), HANDOUT.md (module map,
behaviour, traps), git history, and `archive/plans/` (the executable plans, kept as record).

| Phase | Delivered | Decisions |
|---|---|---|
| 0 Foundation | Repo, tooling, 3-OS CI, PyInstaller artifacts, deterministic ground-truth fixtures (`tools/make_fixtures.py`) incl. VFR, dropped-frame, no-metadata, timestamp-pathology, NaN/gap, split recordings | D-001, D-018, D-023, D-029, D-030 |
| 1 Core engine | MasterClock, TimeMap, session model, source ABCs, NaN/gap-aware pyramid, hardened binary cache, CSV and video loaders | D-001, D-004 – D-010, D-019 |
| 2 Playback MVP | Decode-and-blit video pane, pyramid-fed plots, transport, 60 Hz clock, exact seek on release, golden sync test | D-007, D-035, D-043, D-075, D-084 |
| 3 Multi-source + perf | Video grid, channel rows, inspector, per-source offsets/drift, import pipeline with cancel, proxies, startup diagnostics; P3.5 accuracy/streaming/UI-freeze hardening (measurement open, below) | D-024, D-040, D-045 – D-048, D-060 – D-063 |
| 4 UX completeness | Sessions + autosave, keyboard map, frame step, annotations, readouts, region export, A/B loop, import wizard, relink, theming, Timeline Evidence lanes; P4.6 Review/Sweep/Scope plots (certification open, below) | D-020, D-022, D-027, D-034, D-042, D-044, D-054 – D-057 |
| 5 Plugins + packaging | Plugin API v1, drop-in plugins, session plugins, PyPI + installers from one tag, Read the Docs, PyAV migration (no OS media install); P5.4 evidence-based TTL/event sync | D-012, D-016, D-025, D-026, D-028, D-033, D-036, D-037, D-039, D-068, D-075, D-076 |
| 6 Release + community | Coverage targets, CONTRIBUTING, code of conduct, templates, release workflow | — |
| 7 UX foundations | Command bus + undo, settings registry + Preferences, live-action shortcuts + command palette, overlay registry, feedback surface, error presenter + quality badges, empty state + Help/About, 12-bit display levels, Align menu + evidence view, sidebar at scale + workspaces, a11y/i18n/CVD palette | D-087 – D-107 |
| 8 Alignment on evidence | Session zero, method on the record (schema v9), trigger evidence, model ladder, trigger plugins, non-modal evidence dialog | D-108 |
| Identity repair | Accepted identity flips over declared lanes, one edit program, braid UI, single corrected pose export | D-141 – D-145 |
| Physical props | Wheel, belt, ball, ladder in one Props inspector and `_prop.toml` sidecar; on `feat/physical-props` | D-149, D-154 – D-157, D-162 – D-166 |

### Standing requirements carried forward from delivered phases

These were phase exit criteria and remain binding; tests and docstrings cite them.

- **Phase 5:** release signing/notarization is stubbed behind secrets-present conditionals, so
  forks and unconfigured repositories still produce an unsigned release.
- **Phase 6:** test coverage ≥ 80 % overall and 100 % on `core/`.
- **Phase 7:** no `QProgressDialog` in `src/`, and no `QMessageBox` outside `ui/feedback/`; the Law 1
  (no modal gate before Open, drop, Open Recent, quit) and Law 2 (overlay registry matches the
  drawn inventory) conformance tests pass; every extractable literal is wrapped for translation.
- **Phase 8:** acceptance tests match rate, ambiguity margin and plausible rate, not residuals
  alone; every rung of the alignment ladder is reachable from the running application.

**The lesson both Phase 7 and Phase 8 ended on:** an exit criterion not expressed as a failing test
is a preference, and a capability not exercised end to end from the running application is a
capability you do not have.

---

## Open items (outside the next phase)

| Item | State |
|---|---|
| Populated-workload certification (P3.5) | 4/32/128-channel latency, peak RSS, 1 GB / 180 M-sample import, second-open latency, decoder-settle-plus-rendered-frame numbers not yet recorded on a mid-spec machine. Record p50/p95/p99 and max UI heartbeat delay. |
| P4.6 slice 9 certification | The `TESTING.md` manual field-data checklist on all three platforms and the populated plot benchmarks (`archive/plans/PLOT_UX_PLAN.md` §14–§15). |
| `ui/main_window.py` size (D-148) | ~4 000 lines; target under 1 000 through composition only (D-051). |
| Physical props merge | Merge `feat/physical-props` and run its release gate (archived plan §4 slice 6). |
| Shipped translations | Machinery and 100 % wrapping exist; no `.qm` catalogue ships yet. Needs a translator, not code. |
| Native synchronization plugin API (D-026) | Native plugin event providers remain unfrozen. |

---

## Phase 9 — Interface design (NEXT)

**Goal:** make existing capability legible and dense enough for a 4-camera, 128-channel session on
a laptop, without removing any command, shortcut, evidence lane, or persisted state. Suggested
branch `feat/interface-design`. **The executable plan is `INTERFACE_DESIGN_PLAN.md`**; this section
is the summary.

The engine and the interaction layer are correct; the visual design has not kept pace. Five
full-width control strips sit under the plots, six inspector tabs are elided to "Sour…", guided
placement panels overflow sideways and explain themselves in paragraphs, nothing distinguishes a
primary action from a destructive one, traces are told apart by colour alone, and the window mixes
decimal separators.

The plan carries a findings register (F-01 … F-36, each traced to a file and line), target
wireframes, a dependency graph and schedule, a risk matrix, the existing tests each package must
amend, and the ten DECISIONS entries the phase needs. It builds on D-166 overlay label layout:
`PaintCanvas._label_area` finds the pane chrome by widget name, so DS-5 replaces that with an
explicit contract before any chrome moves.

| | Package | Delivers |
|---|---|---|
| DS-0 | Isolated baseline | screenshot harness isolated from real settings/recovery; amber-status and Light gutter defects triaged |
| DS-1 | Authority and strings | sidebar/header buttons action-backed (rule 15); Reset Session menu action; constructor literals gated for `tr()` |
| DS-2 | Tokens, roles, icons | spacing/type/density tokens, primary/secondary/tool/destructive roles without QSS, bundled SVG icons |
| DS-3 | Bottom chrome | five strips → three; loop and speed join the transport; status to the status bar; scrubber shows coverage |
| DS-4 | Data Streams density | lane height follows density; capped, scrollable |
| DS-5 | Video pane chrome | `chrome_rects()` contract for LabelLayout first; compact OSD, aspect-sized panes, action-backed tools |
| DS-6 | Inspector navigation | icon + label rail; Tasks to a status-bar popover |
| DS-7 | Source cards | compact cards, timing behind a disclosure, one Open button, Reset Session out of the Open group |
| DS-8 | Guided workflows | shared step panel for wheel, props, identity, alignment; empty states |
| DS-9 | Plot rows | legible gutters, hover row tools, lighter grid, redundant trace encoding |
| DS-10 | Numbers and time | one decimal-separator policy |
| DS-11 | Entry points | decide on a slim main toolbar |
| DS-12 | Painted-surface a11y | `QAccessibleInterface` for plots, lanes, video, 3D |
| DS-13 | Onboarding | First Session Tutorial in Help, contextual docs links |
| DS-14 | Docking | splitters → docks, workspaces (carried from Phase 7 WP-11) |

**Exit criteria, all enforced by tests:** every control the phase moves is the same `QAction`
before and after; no stylesheet added for colour or weight; 640×480 and the empty layout still
hold; no inspector page scrolls horizontally; every visible trace carries a non-colour
identifier; plot and cursor benchmarks within 20 %; golden sync untouched.

---

## Working method with AI agents (all phases)

- One phase = one milestone = a series of small PR-sized tasks. Agents work from `PROMPTS.md` kickoff prompts + `AGENTS.md` standing rules.
- Every task PR must include/extend tests; `core/` changes require benchmarks unaffected or improved.
- Human review checkpoints: end of each phase, run the manual smoke checklist in `TESTING.md` §6 on your own real field data (agents never see it; it stays your private regression reality-check).
- Keep `DECISIONS.md` (lightweight ADR log): every irreversible choice (formats, API shapes) gets 5 lines — context, decision, alternatives. Agents must read it and must not silently reverse decisions.
- When a phase completes, move its executable plan to `archive/plans/`, add a row to "Delivered
  phases" above, and carry anything left open into "Open items" — do not leave finished plans at
  the repository root.
