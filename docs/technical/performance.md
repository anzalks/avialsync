# Performance verification

AvialSync separates workload correctness from speed certification because the computer running a
test affects its result.

The engineering marks are product requirements: 2.5 seconds to build the 180-million-sample
pyramid, 5 milliseconds to query it, 2 milliseconds for a fully populated cursor update,
2 milliseconds to sample a 128-point 3D pose, 16 milliseconds for a plot window refresh, and
250 milliseconds for the 10,000-event synchronization preview. No UI-thread callback may exceed
30 milliseconds; the target is 8 milliseconds or less so the event loop retains headroom.

## Audit status (2026-07-29)

The following paths already have the correct ownership model:

- `MasterClock` advances from monotonic time and never waits for a video decoder.
- Decode work runs on a worker thread per pane. Playback drops frames rather than allowing a stalled
  pane to stop time, and each pane keeps only the newest requested time.
- Scrub requests and video render/OSD callbacks retain only the latest pending value.
- Hidden video panes are paused and excluded from synchronization work.
- Video opening, data import, synchronization fitting, proxy generation, and diagnostics have
  background-worker entry points.
- Plot queries select bounded mmap-backed pyramid slices, coalesce resize/window storms, and skip
  hidden plot rows.
- Current-pose 3D sampling shares one timestamp lookup per source and never loads a trajectory into
  the paint path.

Those protections do not make the entire application freeze-free. The implemented hardening and
remaining work are:

| Severity | Path | Why it can stall or lose responsiveness | Required fix |
|---|---|---|---|
| P0 | Session save/load and two-minute autosave | Large exact mappings now use compressed, checksum-validated sidecars instead of JSON float lists. Session serialization and IO still run on the UI thread. | Snapshot state quickly; serialize/write/read in a worker; coalesce autosaves and commit atomically. |
| P0 | Region statistics and data export | Searchsorted range slices and worker-owned readers move reductions, CSV, and Parquet work out of the UI event loop. | Add cancellable/chunked writers, progress, and a Qt heartbeat integration test. |
| P0 | Video clip and snapshot export | Packet-copy trimming and PNG composition/encoding run in workers; widget grabbing stays on the UI thread by Qt requirement. | Add cancellable/progress-aware jobs and a Qt heartbeat integration test. |
| P0 | First import and session reopen | CSV/tracking use one bulk parser pass and a valid cache manifest reopens without parsing. Import still accumulates complete channels; Neo can materialize a full block. | Parse into bounded per-channel builders; stream plugin data; measure peak RSS and warm reopen. |
| P0 | Exact alignment acceptance | Exact fitting retains bounded display evidence; UI acceptance keeps NumPy arrays and session save writes large arrays to a compact sidecar. | Benchmark one-million-frame accept/save/load/seek memory and move session IO to workers. |
| P1 | 60 Hz observers | Every readout label is reformatted each tick; readout and 3D sampling continue when their panels are collapsed; tracking overlay performs a lookup per reader during paint. | Retain the latest master time, skip hidden consumers, sample once per source, batch label updates, and cap presentation rate without changing clock accuracy. |
| P1 | Evidence and plot overlays | Timeline paint/hover scans all TTL/gap/annotation evidence. Sweep boundaries remove and recreate every visible gap/annotation graphics item. | Index by timestamp, query only the visible range, deduplicate by pixel, and pool/reposition graphics items. |
| P1 | Source materialization | Plot, readout, sidebar, and tracking structures are built synchronously for every imported channel. Recursive drop classification and plugin discovery also run on the UI thread. | Prepare metadata off-thread, add/virtualize rows in event-loop-sized batches, and cancel obsolete work. |
| P1 | Multi-video open | Expensive video probes are serialized with the one-at-a-time native pane lifecycle. ffprobe frame output is captured as one large text string. | Probe with a bounded worker pool, stream timestamp output, and serialize only native render-pane construction. |
| P2 | Theme accent lookup | The first macOS custom paint may synchronously execute `defaults` with a one-second timeout. | Resolve once during startup diagnostics or use the palette immediately and apply the discovered accent later. |

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
array writes use a bounded three-worker pool so storage I/O overlaps without creating an
unbounded number of threads during large imports. A write failure is propagated to the import
worker; it must never leave the UI reporting a successful cache. This write pool does not make the
current importer streaming: source parsing, concatenation, pyramid construction, and sidecar commit
must also become bounded-memory operations before the import path is certified.
