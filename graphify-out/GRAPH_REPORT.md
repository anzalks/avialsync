# Graph Report - .  (2026-07-26)

## Corpus Check
- 127 files · ~69,510 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1932 nodes · 3155 edges · 40 communities (31 shown, 9 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 272 edges (avg confidence: 0.62)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 25
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32

## God Nodes (most connected - your core abstractions)
1. `MainWindow` - 135 edges
2. `Transport` - 58 edges
3. `SourceInspection` - 42 edges
4. `PlotPane` - 40 edges
5. `DECISIONS.md — lightweight ADR log` - 35 edges
6. `TimeMap` - 33 edges
7. `VideoPane` - 33 edges
8. `CSVLoader` - 31 edges
9. `VideoGrid` - 31 edges
10. `PyramidReader` - 29 edges

## Surprising Connections (you probably didn't know these)
- `plot_pane()` --calls--> `PlotPane`  [INFERRED]
  tests/test_ui_plot_measure.py → src/avialview/ui/plot_pane.py
- `panel()` --calls--> `ReadoutPanel`  [INFERRED]
  tests/test_ui_readout_delta.py → src/avialview/ui/readout_panel.py
- `test_frame_records_at_empty_grid()` --calls--> `VideoGrid`  [INFERRED]
  tests/test_annotation_frames.py → src/avialview/ui/video_grid.py
- `ToyBinarySource` --uses--> `ChannelInfo`  [INFERRED]
  examples/plugins/avialview-plugin-example/src/avialview_plugin_example/__init__.py → src/avialview/core/source.py
- `ToyBinarySource` --uses--> `TimeSeriesSource`  [INFERRED]
  examples/plugins/avialview-plugin-example/src/avialview_plugin_example/__init__.py → src/avialview/core/source.py

## Import Cycles
- None detected.

## Communities (40 total, 9 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.00
Nodes (1008): ABC, Edge, Enum, Any, ndarray, Path, A minimal external AvialView Plugin API v1 implementation., Read ``.toybin`` records encoded as little-endian ``(time, value)`` pairs. (+1000 more)

### Community 1 - "Community 1"
Cohesion: 0.03
Nodes (74): 1. Single authority — one QAction (or one transport signal) per action, 2026-07 · D-001 · Master time = float64 seconds, UTC epoch, 2026-07 · D-002 · Video playback = libmpv only, 2026-07 · D-003 · License Apache-2.0; no GPL deps, 2026-07 · D-004 · Sidecar cache format, 2026-07 · D-005 · Chunked ingest is the only ingest path, 2026-07 · D-006 · VideoSource conversion hook is first-class, 2026-07 · D-007 · Frame stepping uses actual frame timestamps (+66 more)

### Community 2 - "Community 2"
Cohesion: 0.04
Nodes (49): 10. `python-mpv` (PyPI) ≠ `mpv` (PyPI), 11. Annotation label edits via `markers` property are silently discarded, 12. ruff `line-length = 100` — IDE diagnostics at 79 chars are false positives, 13. `_load_level()` on PyramidReader is private — do not call outside ReadoutPanel, 14. Session v1 → v2 migration: SensorEntry / VideoEntry gain new optional fields, 15. Never cache time→pixel positions; map from current geometry at paint time, 16. `type: ignore` is never a shipping mechanism, 17. Annotation schema (v3) — per-video frame records (+41 more)

### Community 3 - "Community 3"
Cohesion: 0.05
Nodes (37): Formats, Lab formats, Sensor and tracking data, Video, Plugin guide, Synchronization and future plugins, Time-series plugins, Video plugins (+29 more)

### Community 4 - "Community 4"
Cohesion: 0.12
Nodes (14): 1. Repository layout (complete — the authoritative map of what lives where), 2. Runtime dataflow, 2a. Synchronization dataflow (D-026), 2b. Timeline Evidence overview (D-027), 3. Threading model, 4. Plugin contract (frozen at Phase 5 as API v1), 5. Session file (.avv, JSON, schema_version field), 5b. Cache invalidation key (updates D-004) (+6 more)

### Community 5 - "Community 5"
Cohesion: 0.12
Nodes (14): 1. Test layers, 2. Fixtures — `tools/make_fixtures.py` (ground truth for everything), 3. Golden sync tests (`tests/test_sync_golden.py`), 3a. TTL/event synchronization golden tests (D-026), 4. Performance benchmarks (`tests/benchmarks/`), 5. GUI test conventions, 6. Manual smoke checklist (human, end of each phase, on YOUR real field data), 7. Edge-case test matrix (each row = at least one automated test + a fixture variant) (+6 more)

### Community 6 - "Community 6"
Cohesion: 0.14
Nodes (13): AvialView — Project Blueprint (v1), Non-negotiable design principles (every phase, every agent, every PR), P5.4 — Evidence-based synchronization (TTL/events), Performance budgets (CI-enforced where marked ★), Phase 0 — Foundation (Week 0–1), Phase 1 — Core engine, headless (Week 1–2), Phase 2 — Playback MVP (Week 2–4), Phase 3 — Multi-source + performance (Week 4–7) (+5 more)

### Community 7 - "Community 7"
Cohesion: 0.23
Nodes (12): _deterministic_communities(), main(), Path, Build AvialView's committed, offline structural development graph.  This utility, Count source words for the report without processing non-source files., Write a no-dependency local inspector for the portable graph JSON., Remove Graphify's automatic Git stamp so repeated refreshes are identical., Group connected components without a stochastic community partitioner. (+4 more)

### Community 8 - "Community 8"
Cohesion: 0.18
Nodes (10): AGENTS.md — AvialView agent instructions (canonical), Architecture rules (violations = rejected PR), Coding standards, Definition of Done (every task), How to run things, Known traps (learned the hard way — do not rediscover), Naming & casing — BINDING (never invent variants), Task protocol for agents (+2 more)

### Community 9 - "Community 9"
Cohesion: 0.18
Nodes (10): Debugging prompt template (any phase), Phase 0 prompts, Phase 1 prompts, Phase 2 prompts, Phase 3 prompts, Phase 4 prompts (one per feature, same pattern), Phase 5 prompts, Phase 6 prompts (+2 more)

### Community 10 - "Community 10"
Cohesion: 0.36
Nodes (7): discover_media_files(), main(), Path, Stage locally installed LGPL media libraries for a release bundle.  Downloads ar, Find mpv/ffmpeg runtime files in the supplied package-manager directories., Copy discovered runtime media files into a clean bundle-local directory., stage_media_files()

### Community 11 - "Community 11"
Cohesion: 0.29
Nodes (6): Architecture, Loading and viewing a source, Main parts, Master timeline, Session and extension boundaries, Synchronization design

### Community 12 - "Community 12"
Cohesion: 0.33
Nodes (5): Data handling, Gaps and missing values, Sessions and provenance, Source files and caches, Time and precision

### Community 13 - "Community 13"
Cohesion: 0.40
Nodes (5): build_bundle(), main(), Path, Build a one-directory AvialView bundle for the current platform., Run PyInstaller with only staged, local media libraries included.

### Community 14 - "Community 14"
Cohesion: 0.33
Nodes (5): Regression checks for the token-free development graph automation., The committed updater must not grow API-backed graph features., The local hook refreshes only; it never changes Git history or staging., test_graph_updater_stays_structural_and_offline(), test_hook_leaves_graph_updates_for_manual_review()

### Community 15 - "Community 15"
Cohesion: 0.47
Nodes (5): _media_stager(), Path, Tests for release media staging without requiring platform media packages., The release bundle receives media runtimes, not arbitrary package-manager files., test_media_staging_copies_only_runtime_media_files()

### Community 16 - "Community 16"
Cohesion: 0.33
Nodes (5): Regression checks for the PyInstaller specification., An unset media path must not accidentally mean the working directory., SPECPATH is the packaging directory, not the spec-file path., test_spec_only_includes_explicitly_staged_media(), test_spec_resolves_the_project_root_from_packaging_directory()

### Community 17 - "Community 17"
Cohesion: 0.40
Nodes (4): Appearance and font size, Main areas of the window, Useful controls, User Guide

### Community 18 - "Community 18"
Cohesion: 0.50
Nodes (3): Engineering certification, GitHub workload verification, Performance verification

### Community 19 - "Community 19"
Cohesion: 0.50
Nodes (3): Regression checks for the Qt platform selection in CI., Displayless Windows CI must select VideoPane's null-video backend., test_windows_ci_uses_headless_video_backend()

### Community 20 - "Community 20"
Cohesion: 0.50
Nodes (3): Tests for published-package compatibility metadata., Published metadata supports exactly the tested Python range., test_package_caps_python_at_3_12()

### Community 21 - "Community 21"
Cohesion: 0.50
Nodes (3): main(), Enable the repository's versioned Git hooks for the current clone., Point this clone at the repository-managed hook directory.

## Knowledge Gaps
- **207 isolated node(s):** `What this project is`, `Naming & casing — BINDING (never invent variants)`, `Tech stack — FIXED`, `Architecture rules (violations = rejected PR)`, `Coding standards` (+202 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Are the 42 inferred relationships involving `MainWindow` (e.g. with `CacheManager` and `ImportReport`) actually correct?**
  _`MainWindow` has 42 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `Transport` (e.g. with `Player` and `MainWindow`) actually correct?**
  _`Transport` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `SourceInspection` (e.g. with `ImportWorker` and `ImportReportDialog`) actually correct?**
  _`SourceInspection` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `PlotPane` (e.g. with `Player` and `MainWindow`) actually correct?**
  _`PlotPane` has 8 INFERRED edges - model-reasoned connections that need verification._
- **What connects `What this project is`, `Naming & casing — BINDING (never invent variants)`, `Tech stack — FIXED` to the rest of the system?**
  _207 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.0022596463689325344 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.02666666666666667 - nodes in this community are weakly interconnected._
