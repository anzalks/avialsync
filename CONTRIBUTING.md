# Contributing to AvialSync

Thanks for considering a contribution. AvialSync is a scientific tool: the thing
people trust it for is that what they see on screen is *when* it actually
happened. That shapes most of the rules below.

## Before you start

Read **[AGENTS.md](AGENTS.md)** first. It is the single source of truth for
architecture rules, coding standards, and the definition of done — for humans
and for AI coding assistants alike. Then read the relevant phase in
[BLUEPRINT.md](BLUEPRINT.md) and skim [DECISIONS.md](DECISIONS.md).

`DECISIONS.md` records choices that must not be silently reversed. If your
change needs to reverse one, that is fine — propose it as a new entry in the
pull request rather than quietly diverging.

## Setting up

Every command is prefixed with the conda environment. The system Python may
differ from the environment Python, and that difference has caused real
confusion.

```bash
conda create -n avialsync python=3.12
conda run -n avialsync pip install -e .[dev]
conda run -n avialsync python tools/make_fixtures.py   # needs ffmpeg in PATH
```

Run the app:

```bash
conda run -n avialsync avialsync
conda run -n avialsync avialsync demo      # generates and opens a sample session
```

## The gate

All four must pass before a pull request is ready. Run them after each
increment, not only at the end.

```bash
conda run -n avialsync ruff check . && conda run -n avialsync ruff format .
conda run -n avialsync mypy src/avialsync/core     # strict, enforced
conda run -n avialsync mypy src/avialsync          # standard
QT_QPA_PLATFORM=offscreen conda run -n avialsync pytest -q --ignore=tests/benchmarks
```

Coverage targets (TESTING.md §1) are checked with:

```bash
QT_QPA_PLATFORM=offscreen conda run -n avialsync pytest --cov=avialsync --cov-report=term
```

## Rules that get a pull request rejected

These are not style preferences. Each one exists because breaking it produced a
real bug in this codebase.

1. **One master clock.** UI and sources never keep independent time state. They
   subscribe to `MasterClock` and map through `TimeMap`.
2. **`core/` never imports PySide6.** Enforced by `tests/test_headless_core.py`,
   which imports every core module individually — the package-level check missed
   a violation for several phases.
3. **The UI thread never blocks.** Anything that can take more than ~30 ms gets
   a worker and a progress signal. Widgets are only ever created on the UI
   thread; `tests/test_ui_main.py::test_drop_real_video_completes_async_open`
   asserts that thread identity and has caught a real regression.
4. **Plot only through the decimation pyramid.** Never hand raw arrays over
   100 k samples to pyqtgraph.
5. **No GPL/AGPL dependencies.** Name the licence in the pull request.
6. **Never weaken a failing test to make it pass.** If a test looks wrong,
   explain why and propose the fix explicitly. Never add `# type: ignore` or a
   mypy `ignore_errors` override to ship code you know is broken.
7. **Tests ship with the code.** New `core/` logic gets unit tests; UI behaviour
   gets a pytest-qt test; performance-relevant code gets a benchmark.

`tests/test_sync_golden.py` is sacred. It proves decoded frames land at the
right time. Do not touch its assertions.

## Known traps

`HANDOUT.md` has a "Known Traps" section — around two dozen things that look
reasonable and are wrong (a bare `QWidget {}` QSS selector blanks video panes;
`setParent(None)` turns a widget into a popup window; `LC_NUMERIC` must be `C`
before libmpv loads). Reading it will save you an afternoon.

## Commits and pull requests

Conventional commits: `feat(scope): …`, `fix:`, `perf:`, `test:`, `docs:`,
`chore:`. One logical change per commit.

In the pull request, say what you changed, why, and how you verified it. If you
added a dependency, name its licence. If you changed a module's public API,
added a trap, or fixed a listed bug, update `HANDOUT.md` in the same commit.

## Where help is most useful

- **Format plugins.** The `TimeSeriesSource` / `VideoSource` contracts are
  frozen; see `docs/plugin-guide.md`. Lab-specific formats belong in plugins,
  not in core.
- **Platform verification.** Video rendering is intentionally platform-specific
  at one boundary (Qt OpenGL on Windows/macOS, native `wid` on Linux). Reports
  from real hardware are valuable — CI is headless everywhere.
- **The open items under "Pending" in `HANDOUT.md`**, which lists known gaps
  with the evidence behind each.

## Licensing your contribution

AvialSync is dual-licensed: AGPL-3.0-or-later for everyone, plus a commercial
licence for organisations that cannot accept the AGPL's reciprocity. That only
remains possible while one party can license the whole work under both, so
contributions are accepted under [CLA.md](CLA.md).

You keep the copyright in your work. Add this to your first pull request:

```
I have read CLA.md and I accept its terms for this and my future contributions.
```

## Reporting bugs

Include: what you did, what you expected, what happened, your OS and Python
version, and the output of **Help → Diagnostics → Copy diagnostics**. If it is a
timing or synchronisation problem, say which sources were loaded and what their
offsets were — that is usually the whole answer.

Please do not attach private research data. If a bug only reproduces on your own
recordings, describe their shape (rate, duration, channel count, container) and
we will try to build a fixture that matches.
