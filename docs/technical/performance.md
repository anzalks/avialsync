# Performance verification

AvialView separates workload correctness from speed certification because the computer running a
test affects its result.

The engineering marks are the product requirements: 2.5 seconds to build the 180-million-sample
pyramid, 5 milliseconds to query it, 2 milliseconds for a cursor update, and 250 milliseconds for
the 10,000-event synchronization preview. The test suite checks all four.
The 3D current-pose sampler has its own 2 millisecond guard at 128 XYZ points. It reuses one
timestamp lookup for all coordinate channels in a source and never reads or projects a full
trajectory during playback.

## GitHub workload verification

Every change and release verifies the representative scientific workload across supported operating
systems: three cameras and four dense data streams can be opened, cached, queried, and synchronized.
This is a functional integration check, including exact decoded-frame fixtures and a build artifact
on each platform. It deliberately does not treat a shared GitHub machine as a speed authority, a
native-compositor test, or a release installer test.

## Engineering certification

Run timing certification locally on the intended engineering machine before a performance-sensitive
release. The published marks are enforced exactly:

```shell
QT_QPA_PLATFORM=offscreen conda run -n avialview pytest --benchmark-only
```

Do not tune an individual threshold to make a slow machine pass. A changed product requirement
needs a documented decision and a new ground-truth benchmark.

Pyramid sidecars keep their exact level-1 arrays and published envelope format. Their independent
array writes use a bounded three-worker pool so storage I/O overlaps without creating an
unbounded number of threads during large imports. A write failure is propagated to the import
worker; it must never leave the UI reporting a successful cache.
