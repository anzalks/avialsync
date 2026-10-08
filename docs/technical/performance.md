# Performance verification

AvialSync separates workload correctness from speed certification because the computer running a
test affects its result.

The engineering marks are product requirements: 2.5 seconds to build the 180-million-sample
pyramid, 5 milliseconds to query it, 2 milliseconds for a fully populated cursor update,
2 milliseconds to sample a 128-point 3D pose, 16 milliseconds for a plot window refresh, and
250 milliseconds for the 10,000-event synchronization preview. No UI-thread callback may exceed
30 milliseconds; the target is 8 milliseconds or less so the event loop retains headroom.

## Audit status (2026-07-30)

The following paths already have the correct ownership model:

- `MasterClock` advances from monotonic time and never waits for a video decoder.
- Decode work runs on a worker thread per pane. Playback drops frames rather than allowing a stalled
  pane to stop time, and each pane keeps only the newest requested time.
- Scrub requests and video render/OSD callbacks retain only the latest pending value.
- Hidden video panes are paused and excluded from synchronization work.
- Video opening, data import, synchronization fitting, proxy generation, and diagnostics have
  background-worker entry points.
- Text import previews, stimulus-grid overviews, retraining-label assembly, and launch-time
  recovery reads run in registered workers; their UI callbacks hand off bounded data or render
  the resulting overview.
- 3D pose setup opens XYZ cache arrays and derives orientation-specific skeletons in a registered
  worker. Axis changes reuse those estimates, and a newer channel selection supersedes old results.
- Plot queries select bounded mmap-backed pyramid slices, coalesce resize/window storms, and skip
  hidden plot rows.
- Current-pose 3D sampling shares one timestamp lookup per source and never loads a trajectory into
  the paint path.

The implementation gaps recorded in the 2026-07-29 audit were closed by 2026-07-30. Session
save/load/autosave and annotation export run on workers; import staging is chunked; cache replacement
is recoverable; evidence and plot hot paths are indexed; and video metadata probes run in a bounded
pool. The former P0/P1 table described work that has since shipped and is intentionally removed.

The remaining release gate is measurement, not another implementation claim:

- Record populated 4/32/128-channel latency, peak RSS and warm reopen for the 1 GB import workload.
- Measure decoder settle through the frame actually painted, including p50/p95/p99 and maximum UI
  heartbeat delay.
- Retain the representative operating-system and mid-spec-machine checks described in the
  project `HANDOUT.md`; existing microbenchmarks are baselines, not certification.

**Known responsiveness caveat:** On macOS, the first system-accent lookup can synchronously run
`defaults` with a one-second timeout. The result is cached, so this does not repeat on each paint.

Correctness and throughput are co-equal. The companion data-path findings and required fixtures are
documented in [Data handling](data-handling.md).

## Benchmark coverage audit

The current tests give useful component baselines, but several names/claims are broader than the
measured work:

| Existing check | What it proves | Missing before certification |
|---|---|---|
| Pyramid build/query | One in-memory 180 M-sample build and bounded mmap query meet local mean budgets. | Cold/warm storage, peak RSS, chunked ingest, cancel/failure recovery, and p95/p99. |
| Cursor path | Plot/transport dispatch with an empty readout is fast. | Install 4/32/128 readers, include camera/overlay state, deliver queued paints, test collapsed panels, and measure maximum heartbeat delay. |
| Four-channel window refresh | Four bounded pyramid queries and curve updates average under the current test's 30 ms threshold. | Enforce the Blueprint's 16 ms mark, render min/max envelopes, include gaps/annotations and actual paints, and scale visible rows. |
| 3D cursor | Sampling 128 XYZ points is below 2 ms. | Paint cost, skeleton edges, multiple sources, hidden-pane behavior, and p99. |
| Video scrub | Three-camera long-GOP jump, drag, and re-scrub are measured end to end against their budgets in `tests/benchmarks/test_seek_backends.py`. | Proxy variants, callback delivery/OSD paint, and four simultaneous panes. |
| Sync fit | A deterministic 10,000-event affine fit averages below 250 ms. | Exact one-million-frame mapping memory/accept/save/load, cancellation, ambiguity/outlier fixtures, and p99. |

Add a Qt heartbeat probe to every long-job integration test. While the job runs, post a lightweight
event at a fixed cadence and record the largest delivery delay. A worker finishing quickly does not
excuse a 100 ms UI-thread setup or completion slot.

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
QT_QPA_PLATFORM=offscreen conda run -n avialsync pytest --benchmark-only
```

Do not tune an individual threshold to make a slow machine pass. A changed product requirement
needs a documented decision and a new ground-truth benchmark.

Pyramid sidecars keep their exact level-1 arrays and published envelope format. Their independent
array writes use a bounded three-worker pool, and failures propagate to the import worker. The
importer now stages parser chunks through `ChannelStage` rather than retaining the full parsed input
before cache construction. That implementation is complete; representative peak-memory and latency
measurements remain open before the path can be called certified.
