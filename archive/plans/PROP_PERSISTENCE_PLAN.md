# Physical prop persistence and reload

Branch: `fix/prop-persistence`

Delivered 2026-10-16 (D-245). Archived as implementation record, not an open phase.

## Scope

Make newly saved physical props portable and reliably reloadable. Only the new current
`*_prop.toml` schema is supported. Do not import, convert, rewrite or recover earlier formats.
User recordings and existing prop files remain untouched during development and testing.

Self-contained means that the record owns its geometry, observations, units, camera projection
context (including image corrections), reference-camera identity and motion-model parameters.
Raw videos and dense sensor samples remain recordings, referenced portably; missing motion
evidence must be stated rather than replaced by an invented rotation.

## Problems to address

- Current records store a calibration filename, but camera overlays require the separately
  discovered live calibration; even a valid current record is not self-contained.
- Quiet calibration loading requires two open cameras, although displaying an accepted model
  in one known camera does not need two-camera fitting.
- Encoder references are absolute paths, and relinking does not repair prop bindings.
- The reference camera is chosen again from pane order rather than recorded with the prop.
- Discovery and saving derive the destination anew from the currently loaded sources.
- Per-folder queued saves advance through UI callbacks; pending revisions are not themselves
  registered work at shutdown. Stale completion callbacks can reach a different session.
- Failed per-file discovery is treated as completed folder discovery, without an explicit
  rescan route. Error text hides useful version/filename information.
- A loaded wheel with unavailable motion can disappear without a clear dependency explanation.

## Implementation steps

1. Add a headless, immutable prop context and a single current codec. Embed complete camera
   projection snapshots, reference identity/time and relative source references. Keep one schema
   version authority, strict validation and atomic ownership-preserving publication. Extend the
   existing four prop models without adding another accepted prop store.
2. Capture context on acceptance and preserve it through edits and undo/redo. Render saved props
   through their own saved camera context; support reopening only one matching camera, a moved
   recording, and changed pane order. Keep unavailable motion unknown, but allow the known
   placement frame and explain unavailable dependencies in the existing inspector.
3. Give discovery/persistence explicit recording ownership and a worker-drained revision queue.
   Suppress stale session notifications, retain latest accepted revisions, allow retries/rescans,
   and show Saved only for completed current revisions. Keep all work registered and shutdown
   bounded; no blocking modal or UI-thread file IO.
4. Add synthetic current-format integration tests, update HANDOUT/DECISIONS and the user guide,
   run correctness, types, lint, documentation and prop/wheel performance gates, then commit.

## Main files

- `core/prop_context.py` (new), `core/prop_file.py`, `core/wheel_file.py`,
  `core/wheel.py`, `core/physical_props.py`.
- `engine/prop_file_worker.py` and a focused queue module if needed.
- `ui/props_app.py`, a focused prop-context adapter, wheel display/acceptance and record feedback,
  plus recording/discovery hooks only where necessary.
- Prop codec, worker and Qt integration tests; existing wheel/prop benchmarks.

## Validation and risks

- Fresh save -> actual background completion -> new window -> reopen: wheel, ladder, belt, ball.
- Remove external calibration; preserve effective camera projection and corrections.
- Relocate the whole recording; match camera/encoder identities without guessed ambiguous links.
- Open cameras singly/in different orders; keep the saved reference frame and source timing.
- Missing/gapped encoder, nonzero placement frame and overlay-off state remain explicit.
- Burst edits, failures/retry, delayed callbacks, reset/reopen and immediate close preserve the
  latest completed revision and never report an old session's save as the current one's.
- Unsupported versions, malformed contexts, duplicate names and tombstones remain safe and
  reported. Old formats remain unsupported, with no compatibility reader.
- No raw timestamp changes or invented evidence. Rendering performs no file IO or repeated
  camera reconstruction. Document any necessary amendments to D-113/D-156/D-239 explicitly.

## Delivered behavior and limits

- New records use current version 3. All four prop types carry their accepted projection context;
  camera snapshots retain nonlinear image corrections. No earlier records were migrated.
- Saved camera/reference identities survive pane order changes and whole-recording moves. A single
  saved reference camera can display the wheel without external calibration. A different file with
  the same basename is not substituted. Arbitrary external-file renames are not guessed.
- Wheel refits/verification and belt/ball motion checks use saved cameras. A first calibrated ladder
  step records context with its inverse step edit; undo/redo needs no live calibration.
- One registered worker drains/coalesces accepted writes. Discovery waits off-thread for pending
  saves, owner folders stay stable, stale session completions stay silent, and per-file Retry rescans.
- Wheel controls explain required reference/encoder data and the placement-frame fallback. Missing
  motion remains unknown. Dense sensor samples and videos remain separate recordings.
- Python 3.11's installed SciPy exposed a read-only rotvec incompatibility: the projection adapter
  now copies only the three rotation coefficients while retaining immutable saved camera arrays.

## Verification

- Fresh-window tests cover actual background saves and camera projection for all four prop kinds;
  wheel reload also checks its 3D scene.
- Regressions cover moved recordings, nested camera folders, changed pane order, unknown encoder
  motion, context validation, image corrections, latest-write draining, immediate close, reset/reopen,
  destination ownership, stale completions, and deterministic undo.
- Full correctness: 4,576 passed, 2 skipped; post-conversion focused checks: 180 passed.
- Both mypy gates, ruff and formatting pass; Sphinx builds with warnings as errors.
- Fourteen prop/wheel benchmarks pass. Saved-camera projection of 64 ladder steps averages 1.55 ms
  against the 2 ms frame budget; the existing live-camera comparison averages 1.59 ms.
- Persistence regressions also pass on Python 3.11 (53 tests).
