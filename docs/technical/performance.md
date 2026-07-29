# Performance verification

AvialView separates workload correctness from speed certification because the computer running a
test affects its result.

The engineering marks are product requirements: 2.5 seconds to build the 180-million-sample
pyramid, 5 milliseconds to query it, 2 milliseconds for a fully populated cursor update,
2 milliseconds to sample a 128-point 3D pose, 16 milliseconds for a plot window refresh, and
250 milliseconds for the 10,000-event synchronization preview. No UI-thread callback may exceed
30 milliseconds; the target is 8 milliseconds or less so the event loop retains headroom.

## Audit status (2026-07-29)

The following paths already have the correct ownership model:

- `MasterClock` advances from monotonic time and never waits for a video decoder.
- libmpv owns decode work. Playback drops frames rather than allowing a stalled pane to stop time.
- Scrub requests and video render/OSD callbacks retain only the latest pending value.
- Hidden video panes are paused and excluded from synchronization work.
- Video opening, data import, synchronization fitting, proxy generation, and diagnostics have
  background-worker entry points.
- Plot queries select bounded mmap-backed pyramid slices, coalesce resize/window storms, and skip
  hidden plot rows.
- Current-pose 3D sampling shares one timestamp lookup per source and never loads a trajectory into
  the paint path.

Those protections do not make the entire application freeze-free. The audited remaining work is:

| Severity | Path | Why it can stall or lose responsiveness | Required fix |
|---|---|---|---|
| P0 | Session save/load and two-minute autosave | JSON conversion and file replacement run on the UI thread. Exact mappings can contain one entry per frame. | Snapshot state quickly; serialize/write/read in a worker; compact exact mappings into a binary sidecar; coalesce autosaves and commit atomically. |
| P0 | Region statistics and data export | Full-resolution boolean masks, reductions, Python CSV row loops, and Parquet writes run synchronously. | Use searchsorted bounds, chunked reductions/writes, progress/cancel, and a worker. |
| P0 | Video clip and snapshot export | ffmpeg is awaited on the UI thread; PNG composition/encoding and disk IO are synchronous. | Keep only the Qt widget grab on the UI thread; move image encoding, IO, and subprocess lifetime to workers. |
| P0 | First import and session reopen | CSV/tracking data is reread once per channel, all chunks are retained before concatenate, and valid time-series caches are not reused. Neo can materialize a full block. | Parse a source once into bounded per-channel builders; stream plugin data; take the cache fast path; measure peak RSS and warm reopen. |
| P0 | Exact alignment acceptance | Exact fitting builds one Python object per frame, then the UI builds more Python lists for provenance/session JSON. | Keep NumPy arrays through the worker boundary; store bounded evidence samples plus compact sidecar arrays. |
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
| Video mapping/callbacks | Exact-map command fan-out and a fake callback coalescer are cheap. | Actual libmpv seek settle, decoded-frame paint proof, VFR/long-GOP/proxy variants, callback delivery/OSD paint, and three/four simultaneous panes. |
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
QT_QPA_PLATFORM=offscreen conda run -n avialview pytest --benchmark-only
```

Do not tune an individual threshold to make a slow machine pass. A changed product requirement
needs a documented decision and a new ground-truth benchmark.

Pyramid sidecars keep their exact level-1 arrays and published envelope format. Their independent
array writes use a bounded three-worker pool so storage I/O overlaps without creating an
unbounded number of threads during large imports. A write failure is propagated to the import
worker; it must never leave the UI reporting a successful cache. This write pool does not make the
current importer streaming: source parsing, concatenation, pyramid construction, and sidecar commit
must also become bounded-memory operations before the import path is certified.
