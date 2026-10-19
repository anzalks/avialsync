# Translations plan

Branch: `feat/translations-window-composition`, based on `fix/prop-persistence` at `c144a78`
(unmerged; rebase onto `main` once that branch lands). Shared with `WINDOW_COMPOSITION_PLAN.md`;
the order of the two is in §Sequencing.

Status: proposed, 2026-10-19. No code has changed. The decisions marked *proposed* below need the
user's agreement before the slice that depends on them starts.

## Goal

Make a translation catalogue actually change what the interface says, prove it end to end with
a generated pseudo-locale, close the gaps the current gate cannot see, let the user choose a
language, and ship catalogues in the wheel and the installers. Translating into a real language
is human work and is the last step, not a prerequisite for the rest.

Out of scope: translating the Sphinx documentation; right-to-left layout mirroring; strings that
third-party plugins supply; exception detail text behind "Show details" and log messages, which
stay English for bug reports; anything written to a file.

## Findings (measured 2026-10-19 on `c144a78`)

1. **A catalogue built the documented way would never apply.** `ui/i18n.tr()` looks strings up
   under the context `"avialsync"`. `pyside6-lupdate` (PySide6 6.11.2) extracts all 1,873 source
   texts under the empty context `""`. Reproduced in a scratch directory: one message translated,
   compiled with `lrelease`, and installed. `translate("avialsync", text)` returned the English
   source, and `translate("", text)` returned the translation. The only test,
   `test_accessibility_i18n.py:273`, covers the no-catalogue case, so nothing catches this.
2. **The 100 % gate measures one shape of string.** `translatable_ratio` counts literals passed
   directly to known setters, constructors, dialogs and notification calls. It does not see:
   - **Text built elsewhere and passed in later.** An unrefined AST scan of strings that contain
     a space, sit outside `tr()` and are not log calls finds:

     | Package | Plain literals | f-strings | Exception arguments |
     |---|---|---|---|
     | `ui/` | 288 | 88 | 22 |
     | `core/` | 128 | 94 | 267 |
     | `loaders/` | 119 | 90 | 160 |

     These are upper bounds: many are keys, file filters or format strings, so triage comes
     first. Two confirmed examples are `ui/quality_badge.py:59`
     (`f"{n} gap{'s' if …}"`) and `core/settings_schema.py:120` (`f"Last {kind} export folder"`).
   - **Indirect keys.** There are 19 `tr(variable)` sites, such as the column tuples,
     `tr(setting.label)`, `tr(setting.help_text)` and `tr(group)`. They look up text that
     `lupdate` never extracted, because the source literal sits in a constant or in `core/`.
3. **No plurals.** 47 sites build plurals by hand (`'s' if n != 1`, `(s)`). `tr()` takes no
   count, so `lupdate` cannot emit numerus forms.
4. **Shortcut remaps are keyed by the translated label.** `ui/shortcut_overrides.action_id()`
   slugs `action.text()` to `[a-z0-9_]`. Changing the language would orphan every remapped
   shortcut. In a non-Latin script, every action in a category would also collapse to the same
   id.
5. **No language choice.** The locale comes only from `QLocale.system()`, and
   `core/settings_schema.py` has no language setting.
6. **Catalogues would not ship in the installers.** `packaging/avialsync.spec` lists only
   `avialsync.png` and `CITATION.cff` as resources. Whether the wheel carries `*.qm` is unverified.

## Constraints

- D-173 still holds: numbers use a full stop whatever the language. Translation never changes
  `apply_number_locale()`.
- `core/` stays headless (rule 2). Core-defined labels are marked with a pure-Python no-op named
  `QT_TRANSLATE_NOOP(context, text)`. Verified: `lupdate` extracts such a call by name without
  PySide6 being imported.
- Files are language-neutral. Session JSON, sidecars, CSV/NWB export column names, cache keys,
  action/overlay/setting ids and plugin entry points are never translated.
- Rule 15: one authority per concept. The catalogue is generated from the source and never
  hand-edited into a second string table.
- Rule 17: the ratio gate stays at 100 % throughout. New gates are added beside it, never
  instead of it.

## Proposed decisions (record in DECISIONS.md before the dependent slice)

- **D-next-a · Translation context.** `tr()` uses the context that `lupdate` writes for its calls.
  This is preferred to post-processing the `.ts` file or rewriting 2,009 call sites. A round-trip
  test pins the context, so a PySide6 upgrade that changes it fails loudly.
- **D-next-b · Action ids are language-independent.** `action_id()` derives from the untranslated
  source text (stored on the action as `av_source_text` when it is created), or from `av_id`.
  Existing ids are unchanged because they were derived from English.
- **D-next-c · Catalogue layout.** `.ts` sources live in `translations/`, and compiled `.qm`
  files in `src/avialsync/resources/i18n/` are committed. A test recompiles into a temporary
  directory and compares the result, so a stale `.qm` fails CI. This adds no build-time
  dependency on Qt tools for `pip install`.
- **D-next-d · Language changes apply on restart.** Live retranslation would need every widget
  to handle `LanguageChange`, which this plan does not take on.

## Slices

Each slice is one reviewable commit series with its tests. Run the full suite after each one.

**T1 · Make a catalogue apply (D-next-a).** Change only the lookup context. Add a round-trip
test: run `lupdate` on a small module into `tmp_path`, fill one translation, compile with
`lrelease`, `install_translator`, and assert that a real `MainWindow` menu action shows the
translated text. The tools ship with PySide6, so this runs on all three CI platforms. Update
the `resources/i18n/README.md` instructions to the working form.

**T2 · Tooling and pseudo-locale (D-next-c).** Add `tools/update_translations.py`, which runs
`lupdate` over the tracked sources plus `lrelease`, and is deterministic and idempotent. Add a
generated pseudo-locale `en_XA` that brackets and accents every string and pads it by about 35 %.
It needs no translator and shows two things at a glance: unbracketed text is untranslated, and
clipped text is a layout fault. `AVIALSYNC_LANGUAGE=en_XA` forces it at launch. The
stale-catalogue test from D-next-c goes here.

**T3 · Gates the ratio cannot provide.**
- A recording translator, installed during the existing UI tests, logs every lookup that misses
  the extracted catalogue. The gate is: every string the running interface asked for exists in
  the catalogue. This catches indirect keys and runtime-built text that a source scan cannot.
- The scanner also flags a `tr()` whose argument is neither a literal nor a value marked with
  `QT_TRANSLATE_NOOP`.
- Seed both gates with today's counts as a baseline that only shrinks, the same pattern as
  `controller_private_access_baseline.json`.

**T4 · Language-independent action ids (D-next-b).** Run this before any catalogue ships. Test:
under `en_XA`, every action keeps the id it has in English, no two actions share an id, and a
remapped shortcut survives a language switch.

**T5 · Coverage sweep.** Run this after the window composition, so moved code is converted once.
- Triage the scan counts in finding 2 into user-facing and internal.
- Convert f-strings to `tr("… {name}").format(name=…)`.
- Add a count argument to `tr()` and convert the 47 plural sites to `%n` numerus forms.
- Mark tuple and `core/` labels with `QT_TRANSLATE_NOOP`.
- Map core error titles and causes through `ui/feedback/error_presenter.py`, which already wraps
  them. Details stay raw.
- Order: menus and actions, dialogs, inspector and source cards, feedback and quality badges,
  Preferences, import wizard and reports.
- Lower the T3 baselines in each commit. The goal is a zero-miss run of the UI suite under
  `en_XA`.

**T6 · Language preference (D-next-d).** Add a `Language` setting in `core/settings_schema.py`
with "System default" plus the shipped catalogues. Show it in Preferences, persisted and applied
at the next launch, and say so beside the control. The order of precedence is
`AVIALSYNC_LANGUAGE`, then the setting, then the system locale.

**T7 · Ship and document.**
- Include `resources/i18n/*.qm` in the wheel and in `packaging/avialsync.spec` data.
- The installed-wheel smoke test and the frozen-app smoke test launch under `en_XA` and check
  one translated label.
- Write a translator guide (how to add a language with Qt Linguist and run the tool), plus a
  user-guide note on the setting.
- Update HANDOUT for the changed contracts.

**T8 · First real language (human).** This needs a fluent speaker who knows the field.
Machine-translated catalogues are not shipped unreviewed. Agents prepare the `.ts` file and
review layout under it; the translation itself is not agent work.

## Validation

- Round-trip, stale-catalogue, missed-lookup and action-id tests, run on Python 3.11 and 3.12.
- Under `en_XA`, take guide screenshots with `tools/generate_guide_screenshots.py` (not
  offscreen) and review them for clipping. Existing layout policy tests must pass under `en_XA`
  without their assertions being loosened.
- Also run the full suite, strict core and package mypy, Ruff, warnings-as-errors docs, the
  wheel and sdist checks, and the macOS frozen-app smoke test. Windows and Linux frozen builds
  are verified by CI after the user pushes.
- No performance budget is touched. `tr()` lookups happen at construction, never per tick.
  Confirm this with the cursor-update benchmark after T5.

## Risks

- Hidden English remains through paths nobody exercises in tests. Mitigation: the T3 runtime
  gate and the pseudo-locale screenshots.
- German-length text clips compact chrome (D-174 headers, source cards). Mitigation: fix the
  layout policy, not the text, per the "assert the policy, not pixels" trap.
- A PySide6 upgrade changes `lupdate` context behaviour. Mitigation: the T1 round-trip test.
- Translated text reaching a file. Mitigation: a test that saves and exports under `en_XA` and
  asserts the session, sidecar and export bytes equal the English run's.
