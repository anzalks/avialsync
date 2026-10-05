# Physical props — implementation plan

Branch: `feat/physical-props`. Decisions: D-149, D-154–D-157. All kinds use one
versioned `_prop.toml` sidecar and one Props inspector; no legacy wheel-file
reader or migration path is supported. Existing old files are left untouched.
Complete one slice at a time; a model that
exists only in `core/` is not an app feature.

Current branch status: the Props inspector contains wheel placement and review,
clicked horizontal ladders, and belt and ball geometry and motion binding. All
four kinds save to `_prop.toml`; old `.wheel.toml` files are ignored and left
untouched. One accepted `PropStore` and one background sidecar read/write path
serve all four kinds (D-156). Belt displacement needs an explicit path direction,
mark distance, and displacement channel. Ball orientation needs an identified
surface mark and four synchronized quaternion channels from one source. Both
sample the displayed and reference frames' presentation times through the live source mapping,
and later-frame camera clicks record source readings and pixel residuals. The
support geometry stays fixed; absent, gapped, or out-of-coverage readings leave material
motion unknown. Visual-only motion is also available: a belt mark can be clicked
in two calibrated cameras on each observed frame, and a ball needs three named
surface marks in two cameras at both reference and later frames. Fits are
recomputed from raw clicks using current calibration. Missing frames remain
unknown; closed belts need explicit lap counts before signed travel is known.
Editing the declared belt path or ball dimensions retains visual clicks; the
Props inspector names a geometry mismatch or ambiguous observation instead of
discarding those clicks (D-162).
A two-roller belt now records both roller centres, equal radius, measured width, and the top
direction (D-163). Its flat upper and return runs join exact semicircular wraps. The closed
material loop uses analytic distance, while sampled faces are only for display. Existing point
paths remain available as a legacy geometry mode; their old sidecars still load.
A scalar ball encoder remains underdetermined.
Ladders declare how rungs are held (none, side rails at rung ends, or a centre beam); the bars
are drawn through the clicked rungs and never add or move one. Individual steps may be tagged
missing, raised, lowered, shifted, or irregular (D-164). A regular run may be extrapolated from
two clicked neighbouring rungs and a total rung count: per camera through the homography their four
ends fix, so one uncalibrated view suffices, and in 3D by their spacing. Extrapolated rungs are
dashed estimates; a clicked rung replaces one. A belt is placed from four clicks: top-run corners
in two calibrated cameras for 3D, or both roller hubs and the top above each in one camera for a
side-view model. Measured centre distance and radius set its size either way (D-165).

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
| Belt | Two level roller centres, radius, width and top direction; legacy paths remain readable | Signed distance on an exact closed loop; displayed surface wraps the rollers | Measured geometry and direction, plus a displacement source or repeated visual landmarks for motion |
| Ball | Centre and radius | Orientation on SO(3), represented by a unit quaternion | Tracked surface landmarks or a sensor that genuinely gives orientation; one scalar cannot determine 3D orientation |
| Horizontal ladder | Ordered, individually clicked footholds or rung ends; optional rails | Static singleton | Each clicked image point remains evidence; calibrated multi-view clicks can locate it in 3D |

Wheel bars, belt texture, and ball surface markings are **material** features.
The ladder and an unmarked sphere can still be drawn with no motion evidence.
The ladder never forces rungs onto one level, and generates rungs only when the user
declares a regular run from two clicked neighbours (D-165); those stay labelled estimates.
Its normal walkway is horizontal; individual clicks still allow measured irregular heights.
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

`Edit → Add Physical Prop…` and one action-backed **Props** inspector expose
Wheel, Belt, Ball, and Ladder. Its kind-sensitive Add control is the only way
to start wheel placement; no separate Add Wheel menu or toolbar action remains.
The existing wheel gesture and review fields are the Wheel page inside that
inspector, not a separate top-level tab. Each kind asks for only its own geometry and evidence; every click is immediately labelled
as an observation or a projection. New belt edits declare two roller centres,
radius, width, top direction, units and optional travel direction. Old belt edits retain
support-path vertices and loop state. Ball edits declare centre,
radius, units, and optional surface marks. Both show unknown motion until actual
motion evidence is bound. For a ladder, Add Step records a point or the two ends of a rung;
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

Every kind uses the versioned, kind-tagged `pose-3d/<name>_prop.toml` sidecar,
beside its data. It stores declared geometry, raw clicks, source references, fit
and check reports, plus an explicit removed tombstone; it does not store
generated per-frame geometry. Discovery reads only `_prop.toml` records. The old
`pose-3d/<name>.wheel.toml` format is unsupported: the app does not read,
convert, rewrite, or delete those files. New wheel mutations write only
`_prop.toml`.
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
   versioned sidecar IO, and a shared store. Test
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
an existing wheel saved as a `_prop.toml` sidecar that reopens and animates exactly as before. A scalar ball
encoder and a belt with no direction must remain explicitly underdetermined.
