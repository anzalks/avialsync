# PROMPTS.md — kickoff prompts per phase

Model-agnostic: written for frontier coding agents (Claude Sonnet/Opus-class, GPT-5-class,
Gemini 3-class). Paste the Universal Preamble + the phase prompt into a fresh session.
Break each phase into the numbered tasks; run ONE task per agent session for clean context.

> **Completed phases.** Prompts for Phases 0–9, identity repair, and physical props were removed
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

## Phase prompts

No phase is open. Phase 9's prompts were removed when it shipped; they are in git history, and its
plan is `archive/plans/INTERFACE_DESIGN_PLAN.md`.

## Debugging prompt template (any phase)

```
Bug: <symptom>. Repro: <steps/fixture>. Expected vs actual: <...>.
First write a failing test that reproduces it, then fix, then show the test passing.
Do not touch golden sync assertions. If the fix changes behavior, update docs and DECISIONS.md.
For CI failures, also identify the boundary that failed (dependency/runtime, headless compositor,
decode evidence, lifecycle, or packaging); do not paper over it with retries outside the known
transient raw-capture case.
```
