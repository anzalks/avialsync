# Alignment UX simplification

Authorized 2026-10-16 on the existing `feat/alignment-workflow` branch.

1. Reorganize sync form/review helpers into recording selection, suggested method,
   contextual setup, and a result card. Use Settings/Results tabs on narrow
   displays and the same controls side by side on wide displays. Keep one primary
   Preview/Apply action in the fixed footer; group verification and export.
2. Add plain-language result/recovery guidance, offset-first manual controls with
   an explicit existing-drift indication, session labels and duplicate-path
   disambiguation. Preserve explicit evidence declarations and acceptance.
3. Register remembered layout/expansion preferences in the settings schema;
   retain selections only within the current session generation. Never restore
   a proposal, paired observations, thresholds, or an exposure declaration.
4. Add Qt regressions for responsive layouts, fonts, keyboard use, naming,
   suggestions, stale previews, drift retention, and preference isolation.
   Update HANDOUT, DECISIONS, the guide, and native screenshots.

Files: `ui/sync_form.py`, `sync_fields.py`, `sync_review.py`, `sync_wizard.py`,
small presentation/selection/preference helpers; `core/settings_schema.py`;
`ui/controllers/session_state.py`; tests, guide screenshot tool, documentation.

Risks: resizing must reparent existing controls without losing fit state; hidden
drift must remain effective; remembered selection must not cross session resets;
source labels must not change identifiers; Return must never apply a fresh
asynchronous result automatically. No fitting, timeline, or source-data changes.

Validation: focused Qt and sync tests after each increment; full `pytest -x`,
Ruff, strict core/standard mypy, existing sync benchmarks, docs warnings-as-errors,
native normal/narrow captures and larger-font checks. Golden assertions untouched.
