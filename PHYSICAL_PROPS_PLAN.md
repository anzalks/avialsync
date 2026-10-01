# Physical props — implementation plan

Branch: `feat/physical-props`. Decision: D-149. This plan extends the wheel
feature without changing what existing wheel files mean. Complete one slice at
a time; a model that exists only in `core/` is not an app feature.

## 1. Vocabulary and mathematical contract

A **physical prop** is apparatus visible with the animal. Its name and kind
describe the object, never the recording rig. Keep three facts separate:

1. **Structure:** fixed support geometry in the calibration's 3D frame, with
   declared units and the clicks or measurements that locate it.
2. **Material motion:** a state `q(t)` and an explicit map from a material point
   on the prop to a world point. This is not always a rigid transform of the
   whole apparatus: a belt's frame stays put while its surface moves.
3. **Evidence:** user clicks, source channel and live TimeMap, fitted parameters,
   residuals, ambiguities, and checks on later frames. A declaration is marked
   as such; it is never reported as measured motion.

The built-in kinds have different state spaces and observation requirements:

| Kind | Fixed structure | Material state | Evidence needed for motion |
|---|---|---|---|
| Wheel | Axle, radius, bars | Angle on S¹; keep the encoder's unwrapped angle for checks | Bar clicks on a reference frame; optional encoder and later bar checks |
| Belt | Contact plane, travel direction, visible boundary | Signed distance on R; surface position may wrap by a declared loop length | At least a measured direction and a displacement source or repeated visual landmarks |
| Ball | Centre and radius | Orientation on SO(3), represented by a unit quaternion | Tracked surface landmarks or a sensor that genuinely gives orientation; one scalar cannot determine 3D orientation |
| Horizontal ladder | Ordered, individually clicked footholds or rung ends; optional rails | Static singleton | Each clicked image point remains evidence; calibrated multi-view clicks can locate it in 3D |

Wheel bars, belt texture, and ball surface markings are **material** features.
The ladder and an unmarked sphere can still be drawn with no motion evidence.
The ladder never generates rungs from a pitch or forces them onto one level.
Regular, irregular, raised, missing, and staggered steps are all represented by
the actual clicked points or segments, with optional labels and ordering. A
single-view click remains at its original 2D location; a dashed projection in
another view is a guide, not another observation or an invented 3D point.
Motion may be absent or unavailable at some times. At those times show the
reference geometry and an explicit "motion unknown" state; never synthesize
displacement or the animal's locomotion from a prop label. An encoder's source
offset remains the source's own TimeMap, as for wheels (D-124, D-131).

Use frame presentation time for video overlays (D-113), master time for the 3D
view, and one sample path through the plotted source. All animation caches are
keyed by displayed frame index. Calibration changes, a changed source mapping,
or changed evidence invalidate derived geometry or motion, not raw clicks.

## 2. Visible workflow

`Edit → Add Physical Prop…` and an action-backed **Props** inspector expose
Wheel, Belt, Ball, and Ladder. Preserve the current wheel gesture and its
fields inside the Wheel editor. Each other kind asks for only its own geometry
and evidence; every click is immediately labelled as an observation or a
projection. For a ladder, Add Step records a point or the two ends of a rung;
the user can add, relabel, reorder, move, or remove individual steps without
refitting its neighbours. The inspector shows the fit and ambiguity before an
explicit acceptance, then holds per-prop edits, source binding, verification,
and Remove.

Each prop has registered View → Overlays layers with per-camera overrides. A
solid mark denotes accepted observed/fitted geometry, a dashed mark denotes a
preview or estimate, and text identifies missing motion evidence. The 3D pane
shows the same frame's state. Placement and fitting remain non-modal; any job
over the threshold goes through `MainWindow._run_job`. Actions that need
calibrated views declare preconditions through `_require`; an existing prop
still loads and reports partial evidence when calibration or a source is absent.

## 3. Persistence and compatibility

Existing `pose-3d/<name>.wheel.toml` files remain the authoritative wheel
format and must round-trip without semantic change. New prop records use
versioned, kind-tagged `pose-3d/<name>.prop.toml` sidecars, beside their data.
The sidecar stores declared geometry, raw clicks, source references, fit and
check reports, plus an explicit removed tombstone; it does not store generated
per-frame geometry. Discovery must reserve both suffixes from source loaders.
The `.avv` session stores presentation choices and references, not a second
copy of the prop's measurements. Names are unique across all prop kinds in a
recording. Unsupported future kinds remain visible as unreadable records with
a quality message rather than preventing the recording from opening.

## 4. Reviewable slices and acceptance evidence

1. **Plan and decision.** Add this plan, D-149, and links from BLUEPRINT,
   PROMPTS, and HANDOUT. Commit before code.
2. **Headless motion foundation.** Add typed states and material-point maps in
   `core/physical_props.py`; adapt wheel math only through a narrow adapter.
   Test static invariance, belt signed travel and wrapping, wheel periodicity,
   and ball quaternion normalization/composition against ground truth.
3. **Geometry and persistence.** Add kind-specific geometry, evidence and
   versioned sidecar IO, a shared store, and legacy wheel discovery. Test
   round-trips, malformed or future records, tombstones, and name collisions.
4. **Document and UI.** Add inverse commands and the mutation funnel; build
   the Props inspector, action, registered layers, and per-kind placement.
   Test with pytest-qt that a prop can be added, undone, reopened and drawn on
   every camera without breaking Add Wheel or marker placement.
5. **Motion and verification.** Bind sensors through the existing source reader
   and TimeMap, use the displayed frame's presentation time, and add later-frame
   checks. Prove no motion is drawn when evidence is absent or ambiguous. Add
   synthetic ground-truth fixtures and a benchmark for the frame path.
6. **Release gate.** Update user docs and HANDOUT's module map; run `pytest -x`,
   `ruff check .`, both mypy commands, affected benchmarks, and the untouched
   sync golden tests. Check translated strings, accessibility, and overlay
   registration. Do not call a headless-only slice an app feature.

The final acceptance examples are a static ladder with unequal step spacing and
height, preserving every clicked point; a belt whose
surface moves while its frame stays fixed, a ball with two-axis rotation, and
an old wheel sidecar that reopens and animates exactly as before. A scalar ball
encoder and a belt with no direction must remain explicitly underdetermined.
