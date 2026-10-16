# Alignment workflow task

Authorized on 2026-10-16; branch `feat/alignment-workflow`, in this working tree.
This is new feature work, not a continuation of an archived phase plan.

## Scope and increments

1. Screen-bounded non-modal popup, scrolling setup, fixed status/accept footer,
   responsive layout, contextual inputs, separate manual and event modes,
   compact correspondence/residual/coverage tabs, keyboard accessibility.
2. Preview revision and live-clock checks; correct nudge directions and local
   frame intervals; retain nonlinear mappings during manual edits; inverse
   operations restore evidence status; invalidate dependent reference mappings.
3. Explicit visual event pairs (capture on the master clock), honest sparse
   results, imaging targets using the existing mapping/worker/command paths.
4. Timestamp-only trigger CSV, explicit units/mode/threshold/debounce;
   timestamp-resolution assessment; short source status; verification jumps;
   atomic proposed and accepted JSON reports on registered workers.
5. Update DECISIONS, HANDOUT, architecture and user guide; regressions, full
   correctness suite, strict core and standard mypy, ruff, relevant benchmarks,
   small/large-font visual inspection and documentation build.

## Validation and risks

- No golden sync assertions are edited. No raw data or private recordings used.
- New behavior gets unit/Qt integration tests, including save/reopen and undo.
- Arrays stay immutable/shared; undo keeps inverse operations, not session snapshots.
- Existing explicit replacement APIs retain their meaning; manual adjustment is additive.
- Never infer exposure wiring or apply a proposal without acceptance.
- Precision statements describe evidence, sampling and coverage, never certify
  unmeasured physical hardware latency.
- No new dependencies, QSS, unmanaged threads, modal jobs, or format-specific UI.

## Progress

- Initial popup and preview regression: 26 focused tests passed; first full
  correctness run: 4,396 passed, 2 existing skips.
- Nonlinear correction and mapping consumers: 48 focused tests passed.
- Dependency/undo and popup regressions: 83 focused tests passed.
- Visual landmarks, imaging, trigger inputs and report integration completed.

## Final validation

- Full correctness suite: 4,427 passed, 2 existing skips (276.86 s).
- Final integration/architecture/shutdown checks: 48 passed, including report
  action availability through undo/redo and the original exact-sync UI flow.
- Five relevant benchmarks passed: 10,000-event fit 196.5 ms; 1,000 explicit
  visual pairs 0.94 ms; adjusted million-frame scalar lookup 1.94 microseconds;
  four-video exact dispatch 9.88 microseconds; callback bursts 171.7 microseconds.
- Ordinary exact lookup compared against the starting commit in memory:
  1.55 vs 1.36 microseconds, +14.3%, within the 20% regression limit.
- Ruff lint and formatting, strict core mypy (66 files), standard mypy (341
  files), and Sphinx warnings-as-errors build passed. Golden sync tests unchanged.
- Native screenshots reviewed at normal and 760x560 sizes; 150% text and
  expanded settings covered by Qt tests. Seven alignment guide images updated.
- Regression coverage includes sparse/explicit pairs, sampled TTL precision,
  missing targets, dependent clocks, corrected exact save/reopen and replacement
  undo/redo, imaging acceptance, atomic reports and bounded evidence sampling.

All five increments are complete. No dependencies or licensing changes.
