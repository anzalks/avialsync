# Changelog

Notable changes to AvialSync, newest first. Each entry summarises the commits between two release
tags; the reasoning behind each change is in `DECISIONS.md` under the decision numbers given, and the
full history is in git. Versions follow the tags in the repository.

## Unreleased

### Added
- Alignment setup starts from the recording, with narrow Settings and Results pages, one
  Preview/Apply footer, a concise result card, and grouped checks and export (D-241, D-242).
- Alignment results are judged over the overlap of the recordings and say why a match was
  rejected (D-243).

### Changed
- Imports state the timebase they read and show the parsed times; epochs are read at the right
  scale (D-244).
- File → Cache no longer deletes anything in one click, and proxies are written where you choose
  (D-244).
- Keyboard lanes, honest labels, bulk relink, and readable Preferences (D-244).
- A saved prop's TOML carries its own projection and recording references, so its geometry
  reloads without the session that made it (D-245).
- Internal: the main window is composed of focused modules; behaviour is unchanged (D-248).

### Fixed
- Left/Right frame steps work again after alignment, keep the chosen timestamp, and act on the
  camera you clicked (D-246).
- A translation catalogue built with `lupdate` now applies; none ships yet (D-247).
- Custom timeline lanes draw in the real accent colour, and overlay labels are outlined.
- At the Extra large font size the Sources sidebar widens to fit its own controls instead of
  showing a permanent horizontal scrollbar.
- Quitting no longer prints a cache-lock traceback.

## 0.1.13 — 2026-10-15

### Fixed
- Prop evidence stays visible across camera frames.

## 0.1.12 — 2026-10-15

### Added
- Ladder spacing supports first and last anchors and neighbouring rungs (D-239); belt and ball
  motion aligns to video.
- Physical bone thickness for tracked skeletons.
- 3D view tools match the video controls, with a separate body-part label switch (D-237).

### Changed
- Saved prop controls and persistence are unified (D-238).
- Exports keep complete clock mappings and source provenance (D-229).
- Cache generations are preserved across application processes (D-230).
- Validated cache reopens are faster.

### Fixed
- 3D reprojection draws even with the tracking points hidden.
- The AOL rig wheel's bar 0 is re-anchored as the analysis loads it.
- Session reset no longer logs disconnect warnings.

## 0.1.11 — 2026-10-11

### Added
- Streams recorded in parts load as one source, joined in place, with the gaps kept (D-217,
  D-219); streams stop where they have no data, and gaps can be collapsed for viewing (D-218).
- The status bar shows the cache size (D-215).
- Every interactive control either acts or says why it cannot (D-214).

### Changed
- The cache stores only what carries information and reads binary sources in place (D-216).
- Joined AOL camera trials play from their own files rather than a copy (D-216).

### Fixed
- Vicon subjects draw their own bones from the `.vsk` file (D-219).
- Plot Export opens, and Delete is offered only with a selection.

## 0.1.10 — 2026-10-07

### Added
- NWB files open as sessions — series, imaging and trials — including Zarr, legacy and streamed
  DANDI assets (D-188, D-193).
- A two-photon stack viewer with channel overlay, levels and centred averaging (D-186, D-192,
  D-194, D-195).
- Physical props: wheel, belt, ball and ladder in one Props inspector with versioned sidecars.
- Identity repair: declared identity groups, the braid view, accepted flips rebuilt into the
  cache, and a corrected export.
- Stimulus-aligned grid video export; DeepLabCut and Lightning Pose retraining bundles (D-198);
  one publication path for exports and an Exports inspector (D-197).
- Vicon C3D markers as native 3D points with a calibrated video overlay.
- Plots can be detached to a second display; sources and channels can be filtered.

### Changed
- The interface redesign (Phase 9): an inspector dock and rail, Tasks in the status bar, compact
  video headers and source cards, guided step panels, every number shown with a full stop, and a
  First Session Tutorial (D-167 – D-182).
- All derived data lives in one per-user cache folder; File → Cache deletes one trial's cache or
  all of it (D-160).

## 0.1.9 — 2026-09-14

### Added
- Alignment on evidence (Phase 8): trigger evidence from file to fit, the model ladder chosen by
  the evidence, a camera as a reference, and a non-modal evidence review (D-108).

### Changed
- A loader declares its zero instead of its placement; moving a source shifts it in time rather
  than stretching the session.
- Repaints no longer fork a process, and line fits no longer use SVD.

### Fixed
- Background-job completion handlers run on the interface thread.

## 0.1.8 — 2026-09-10

### Fixed
- Theme changes reach every surface; returning to the System theme works and pane boundaries are
  marked end to end.
- Every caller uses the shared feedback surfaces (D-107).

## 0.1.7 — 2026-09-08

### Added
- UX foundations (Phase 7): command bus with undo and hot exit, the Edit menu, overlay registry
  with View → Overlays, non-modal long work, presented errors, a settings schema with
  Preferences, rebindable shortcuts and a command palette, named window layouts, a
  colour-vision-safe palette, screen-reader names, and high-bit-depth display levels
  (D-087 – D-107).
- Fix Tracker: correct a predicted point by hand; corrections are kept beside the pose file and
  exported.
- Unsaved work is offered back at launch and never deleted.
- Snapshots compose a figure instead of grabbing the window.

## 0.1.6 — 2026-08-27

### Added
- Reset Session; independent zoom and pan per video; `CITATION.cff`.

## 0.1.5 — 2026-08-27

### Added
- Seek by clicking a plot.

### Fixed
- Workspace panes stay visible on small displays.

## 0.1.4 — 2026-08-26

### Fixed
- Held shortcuts no longer repeat toggling actions; sub-second budgets are timed with
  `perf_counter`.

## 0.1.3 — 2026-08-25

### Added
- Open Ephys messages from the original `.continuous` format.
- AOL extracted per-ROI optical-flow and motion-index metrics, and the video-extraction toolbox's
  per-camera exports (see the format contracts in the documentation).
- A skeleton is detected from pose geometry when none is declared.

### Fixed
- A seek is answered with its own frame.
- A malformed Open Ephys comment no longer costs the whole recording.

## 0.1.2 — 2026-08-10

### Fixed
- The 2D pose overlay paints on every camera, not only the first.

## 0.1.1 — 2026-08-09

First release after the 0.1.0 betas (`v0.1.0b1` – `v0.1.0b10`, August 2026). For earlier history,
see the git log.
