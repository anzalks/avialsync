# Performance verification

AvialView has two kinds of automated performance check because the computer running a test affects
its result.

The engineering marks are the product requirements: 2.5 seconds to build the 180-million-sample
pyramid, 5 milliseconds to query it, 2 milliseconds for a cursor update, and 250 milliseconds for
the 10,000-event synchronization preview. The test suite checks all four.

## Hosted measurement

Every change and release runs the reusable **Performance** GitHub workflow once on Ubuntu with
Python 3.12. It records every timing path and uploads `benchmark.json` as a workflow artifact.
GitHub-hosted computers share CPU time and have variable temporary-disk performance, so this tier
uses one explicit 8× safety cap. It detects severe regressions without pretending that a shared
runner is the reference laboratory computer.

## Engineering certification

Run the same workflow manually with the **reference** tier before a performance-sensitive release.
It requires a GitHub self-hosted runner with the `avialview-performance` label and applies no
multiplier: the published marks are enforced exactly. The runner should be the documented
mid-spec, SSD-equipped reference machine and should not be carrying unrelated workload.

The command is also available locally:

```shell
QT_QPA_PLATFORM=offscreen conda run -n avialview pytest --benchmark-only
```

Do not tune an individual test threshold to make a runner pass. A slow hosted runner is reported
through its artifact; a changed product requirement needs a documented decision and a new
ground-truth benchmark.
