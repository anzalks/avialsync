# Engineering hardening plan

Branch: `fix/engineering-hardening`, based on `bf5f0f2`.

Scope: the nine engineering improvements from the project evaluation. No new
session-report UI, sharing bundle, translations, or installer-signing work.

## Implementation sequence

1. **Version reporting and benchmark validity.** Use the running code's version
   for diagnostics, documentation, and artifact provenance. Exercise visible
   plot panes, actual prepared rows, and delivered resize/paint events. Add
   regression tests proving the benchmarks execute their named work.
2. **Portable export provenance.** Record source fingerprints and complete
   affine/exact mappings, including reference times, without changing timestamps.
   Cover nonlinear mappings, identical source names, and export round trips.
3. **Cross-process cache ownership.** Add nonblocking OS-backed reader/writer
   leases, retaining the existing in-process reservation rules. Test concurrent
   readers, replacement, eviction, and automatic release after process exit.
4. **Composition.** Move cohesive window responsibilities into bounded modules
   with real QObject slot owners or existing controller functions. Reduce the
   MainWindow shell toward the documented 1,000-line target while preserving
   command, action, thread, undo, and shutdown behavior.
5. **Quality gates and coverage.** Enable strict core typing explicitly. Add
   meaningful tests for uncovered core behavior and enforce 80% overall and
   100% core coverage without weakening tests or excluding reachable code.
6. **Reproducible CI and release dependencies.** Record tested dependency sets
   for supported interpreters/platforms and apply them to workflow installs.
   Preserve ordinary pip installation and the existing PySide6 upper bound.
7. **Representative certification.** Add fixture-backed measurements of cold
   import, warm reopening, populated interactions, rendered frames, heartbeat
   delays, and peak RSS; record local distributions and hardware explicitly.
8. **Documentation and final validation.** Correct current architecture, CI,
   performance, cache, and provenance contracts. Enforce --no-install-recommends
   in every workflow package-install step. Update HANDOUT and DECISIONS with
   each changed contract and run the full gate.

## Validation

- Targeted regression tests first, followed by the full correctness suite after
  each reviewable increment; golden sync assertions remain unchanged.
- Ruff lint/format, strict core mypy, standard package mypy, and Sphinx with
  warnings as errors.
- Core coverage measured with branches; no new suppression of real defects.
- Relevant benchmarks measured on the local machine with real work assertions.
- Python 3.11 checks where the verified development environment is available.
- Wheel/packaging smoke checks supported by this host.
- Inspect the starting branch's failed workflow, reproduce its failure locally,
  and complete all checks before exactly one push. Monitor the pushed SHA's CI;
  do not open a PR or trigger extra workflow runs.

## Risks and external validation

Timing and provenance must describe the mapping actually used. Cache locking
must be nonblocking and work on Windows and POSIX. QObject composition must
preserve queued delivery and explicit lifetime. New dependency pins must resolve
on all three operating systems and both supported Python versions.

Windows/Linux execution and private field-data certification require those
environments. Local measurements and prepared cross-platform tests must never
be reported as completed external certification.

## Progress

- [x] Baseline evaluation and clean branch created.
- [x] Version reporting and benchmark validity: 3,910 correctness tests and
  12 plot benchmarks passed; strict core and standard package mypy passed.
- [x] Complete export provenance: 3,929 correctness tests passed; the shared
  million-frame mapping conversion averaged 22.35 ms on its export worker.
- [x] Cross-process cache ownership: 3,951 correctness tests passed; the
  Python 3.11 cache/import/identity/responsiveness checks passed. Six cache
  benchmarks passed (warm manifest validation 4.43 ms, within the 20% limit).
- [x] Bounded composition: keyboard/focus policy, feedback, and workspace
  geometry extracted; MainWindow 3,893 → 3,440 lines, with tighter ceilings.
  3,961 correctness tests and 101 Python 3.11 UI checks passed. The documented
  under-1,000-line end target remains architectural debt.
- [x] Core typing and coverage policy: 4,308 full-suite tests plus the final
  retry regression passed. All 9,003 core lines and 2,500 branches covered;
  89.2% overall. Strict core (including Windows) and package mypy passed;
  15 affected local benchmarks passed. CI enforcement is in the next increment.
- [x] Reproducible dependencies and enforced CI coverage: all six resolution
  preflights, 40 workflow/packaging contract tests and 4,314 full-suite tests
  passed. Coverage gate passed; strict core/package typing and warnings-as-errors
  docs passed on both verified Python environments. Full 3.11 execution is
  included in the final supported-interpreter preflight.
- [x] Representative local certification: five isolated scenarios passed with
  a 1.014 GB/30.5 M-row CSV, warm three-camera reopening, painted-frame identity,
  populated 4/32/128-row distributions, heartbeat and peak RSS. The report in
  `docs/technical/engineering-certification.md` records remaining tails and the
  32 GB/offscreen scope. Thirteen affected plot benchmarks passed; final cursor
  and resize checks passed after lifetime/block preservation. A 180 M-sample
  pyramid build averaged 1.984 s, with a 0.127 ms query; long-GOP seek checks passed.
- [x] Documentation and local final gate: 4,327 Python 3.12 tests passed;
  the full Python 3.11 suite passed 4,325 tests, followed by all 46 latest
  geometry/props/page/golden regressions. Core remains 9,003/9,003 lines and
  2,500/2,500 branches; overall coverage is 89.2%. Both interpreters pass
  strict core typing (including Windows), standard package typing, dependency
  checks and warnings-as-errors documentation. Ruff and workflow actionlint pass.
  Wheel/sdist validation, a clean installed-wheel demo/GUI smoke, the macOS
  PyInstaller build and frozen plugin smoke for both layouts passed. No installer
  was published. The pushed SHA's native workflow result is reported separately.

## Native CI result

The one authorized push published `17255e7`. CI run `38621380837` passed
lint/types and documentation but failed macOS/Python 3.11 during Props-test
teardown; matrix fail-fast cancelled the other five test jobs. That run was red.
A queued resize refreshed a test-only `SimpleNamespace` row missing `page_t0`.
The correction uses the real `ChannelPlot` dataclass with inert graphics and
adds a deterministic queued-refresh regression; existing assertions remain.
The user published correction `8f0411c`. Run `38634163208` is green: all six
OS/interpreter test combinations, lint/types, documentation, and the Linux
complete-core coverage gate passed. No extra workflow rerun was needed.

The follow-up passes the full suites locally: 4,327 tests on Python 3.11 and
4,328 on Python 3.12, plus the unchanged complete-core coverage gate. This is
local validation; the separate native run above confirms the pushed result.

## Requested UI follow-up: compact 3D controls and label visibility

After CI passed, the user requested a compact, readable 3D adjustment area,
video-style icon controls below the scene with no top band, appropriate
reprojection/fit symbols, and an independent 3D body-part label switch.
Files: the 3D pane and its new bounded controls component, shared glyph catalog, overlay registry,
View action binding/application, UI/overlay regression tests, HANDOUT, this
plan, DECISIONS, and the user guide. No dependencies or workflow changes.

Validation: actual mouse/keyboard popup interaction at narrow widths and larger
fonts, shared video glyph/style assertions, unchanged pane-resize policies,
numeric diameter and line/tube consistency, rendering with labels hidden,
independent undo/redo and session persistence, full supported-interpreter suites,
strict core/package typing, lint/format, warnings-as-errors docs, and the existing
3D workload benchmarks. Risks are clipped controls, changed navigation,
native popup lifecycle, and divergence between menu, saved state, and pixels.
Local verification passed: 4,343 Python 3.12 tests and 4,342 Python 3.11 tests;
all 9,003 core lines and 2,500 branches remain covered (89.23% overall).
Both interpreters pass strict core/package typing and warnings-as-errors docs;
Ruff lint/format and 171 focused UI/architecture checks pass. Ten native popup
checks and the native label/action check pass. The three existing 3D benchmarks
pass: cursor 0.237 ms, prepared installation 0.295 ms, skeleton detection
4.768 ms means. Native previews show all tools below the scene and complete
popup text. No performance budget or existing assertion was weakened.

The UI follow-up remains unpublished under the original one-push limit;
the green hosted result above covers `8f0411c`, not this new local change.
