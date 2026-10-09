# Completed plans (archive)

These were executable plans for work that has shipped. They are kept as the record of how the
work was reasoned and sequenced; **do not work from them**. The settled outcomes are in
DECISIONS.md, and the current module map and traps in HANDOUT.md. No phase plan is open.

| Plan | Outcome | Decisions |
|---|---|---|
| `MIGRATION_PYAV.md` | libmpv replaced by PyAV; `pip install` needs no OS media install. Complete 2026-08-07. | D-075, D-086 |
| `UX_FOUNDATIONS_PLAN.md` | Phase 7: command bus, undo, settings, overlay registry, feedback surface, error presenter, display levels, a11y/i18n machinery. WP-11 docking and shipped translations were left open and carried into the interface design plan (DS-14) and BLUEPRINT open items. | D-087 – D-107 |
| `PLOT_UX_PLAN.md` | P4.6 Review/Sweep/Scope plots, time span, navigator, gutters, Y modes (slices 2–8). Slice 9 certification is carried into BLUEPRINT open items. §2 remains the compatibility ledger cited by TESTING.md. | D-042, D-044 |
| `PHYSICAL_PROPS_PLAN.md` | Wheel, belt, ball, and ladder props in one inspector and `_prop.toml` sidecar, on `feat/physical-props`. Merge and its release-gate check are a BLUEPRINT open item. | D-149, D-154 – D-157, D-162 – D-166 |
| `INTERFACE_DESIGN_PLAN.md` | Phase 9: inspector rail and dock, compact bottom chrome and source cards, step panels and empty states, compact video chrome, plot-row identity, one number policy, painted-surface accessibility, onboarding links, scrolling workspace. The TESTING.md §6 manual check on field data is a BLUEPRINT open item. | D-167 – D-182 |
| `AOL_MICROSCOPE_PLAN.md` | AOL AVI timing, microscope ribbon mosaics and cell ROI views, trial-scoped imports, and explicit camera-to-trial placement. Read-only real-data smoke check completed 2026-10-09; real same-session pairing remains open. | D-202 |

Source and test comments that cite these files by name refer to the copies here.
