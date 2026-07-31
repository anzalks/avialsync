## What and why

<!-- What changed, and the problem it solves. Link the issue if there is one. -->

## How it was verified

<!-- The actual commands and their results, not "tests pass". If you fixed a
     bug, say how you reproduced it first. -->

```
conda run -n avialview ruff check .
conda run -n avialview mypy src/avialview/core
conda run -n avialview mypy src/avialview
QT_QPA_PLATFORM=offscreen conda run -n avialview pytest -q --ignore=tests/benchmarks
```

## Checklist

- [ ] Tests ship with the code (`core/` logic → unit tests; UI behaviour →
      pytest-qt; performance-relevant → benchmark)
- [ ] All four gate commands pass locally
- [ ] No test was weakened, skipped, or `# type: ignore`d to make this land
- [ ] `tests/test_sync_golden.py` untouched and passing (required for any change
      to `core/timeline.py`, the playback loop, or seek logic)
- [ ] No performance budget regressed by more than 20 % on touched benchmarks
- [ ] `HANDOUT.md` updated if this changes a module's public API, adds a trap,
      or fixes a listed bug
- [ ] `DECISIONS.md` entry added if this makes a choice future contributors
      must not silently reverse
- [ ] New dependency? Licence named here, and it is not GPL/AGPL

## Anything reviewers should look at closely

<!-- Trade-offs you made, things you were unsure about, or areas where you would
     like a second opinion. Saying "I am not certain about X" is welcome. -->
