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
- [ ] Cross-process cache ownership.
- [ ] Composition.
- [ ] Enforced quality gates and core coverage.
- [ ] Reproducible dependencies.
- [ ] Representative local certification.
- [ ] Documentation and final gate.
