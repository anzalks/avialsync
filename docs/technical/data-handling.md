# Data handling

## Source files and caches

The product contract is that text and plugin data are read once and converted into a sidecar cache
beside the source. A valid cache must be used on later viewing so a large source is not repeatedly
parsed. The cache key includes source content information, including a content-hash tail, to avoid
treating a changed file as unchanged. The cache directory is named `<file>.avialcache/`; deleting it
is safe because AvialSync can build it again from the source file.

Importers process data in chunks. A time-series plugin yields time/value chunks in chronological order;
the importer validates them, records import statistics, and builds the cache away from the interface
thread. Video loaders provide an mpv-playable media path and frame timing metadata when available.

The 2026-07-29 hardening now gives CSV and tracking loaders a single bulk parser pass and gives
ImportWorker a content/config-validated manifest cache fast path. The worker still retains complete
channels before constructing their pyramids, and Neo's default reader can materialize a complete
recording block. These are worker-thread operations, so they usually do not stop Qt directly, but
they create memory/storage pressure and prevent target-scale certification. The remaining design is
bounded per-channel cache builders with backpressure, cancellation, recoverable partial output, and
peak memory independent of recording duration apart from fixed buffers.

Replacing a cache must preserve the last valid sidecar until the new sidecar is durable. The current
remove-then-rename sequence has a failure window and must be replaced by a cross-platform
swap/rollback protocol before cache writes are called atomic.

## Time and precision

Master and source time are floating-point seconds. Timestamp arrays retain high precision. Plotting
uses a downsampled pyramid for display only; cursor values, statistics, and exported data must come
from the exact cached source representation. Every source needs its own `TimeMap`; UI consumers
receive master time and convert to source time through that mapping. Frame stepping uses actual video
presentation timestamps when they are available, rather than assuming a fixed frame rate.

The audit identified four accuracy blockers:

1. Plot rows currently draw the midpoint of each min/max pyramid bucket. This can erase a short real
   excursion. The display must render the full bounded envelope, with a golden spike fixture proving
   that both extrema remain visible at 1×, 16×, 256×, and 4096×.
2. Coarse-level gap masks are recalculated from coarse timestamps. A real gap only slightly above the
   raw threshold can disappear after decimation. Raw gap evidence must be OR-reduced into its parent
   buckets, never inferred again at a different sampling interval.
3. CSV monotonicity and duplicate checks reset at each parser batch; the timestamp dtype is inferred
   per batch; and the import wizard's timezone selection is not applied by the loader. The loader
   must carry the previous accepted timestamp across chunks, use an explicit timestamp schema, and
   apply an explicit user-selected timezone with DST/pathology fixtures.
4. Time-series plots/readouts currently use cached timestamps directly and do not expose the
   per-source offset/drift mapping already used for video. Multiple sensor clocks therefore cannot
   all be treated as master time. Raw timestamps stay unchanged; accepted mappings belong beside the
   source and must be applied consistently by plots, readouts, overlays, exports, and sessions.

Sampling semantics must also be explicit and shared. The current readout uses the sample at or before
the cursor, while tracking views use the nearest sample. A source/channel declares nearest,
sample-and-hold, or interpolation behavior; one core query API applies that policy everywhere and
returns a no-data result outside a rate-derived tolerance. A fixed 100 ms tolerance is not valid for
both 1 Hz and 50 kHz data.

## Gaps and missing values

Missing values remain missing. Gaps are detected after import from timestamp spacing and recorded for
plotting and inspection, so a line is not drawn across a known discontinuity. NaNs and importer-defined
sentinel values are counted in the import report; the original input stays untouched.

## Sessions and provenance

A `.avv` session stores references to sources, visual layout, offsets/drift, annotations, and accepted
synchronization provenance. It does not copy or alter the original recordings. Local window geometry
and presentation preferences remain local to each user. When a source has moved, the session can ask
the user to relink it instead of guessing a replacement.

Exact per-frame mappings can contain millions of timestamp pairs. Large accepted mappings now live
in a compact, checksum-validated compressed session sidecar while session JSON retains its summary
and bounded evidence sample. The remaining work is to move session serialization and IO itself to
workers. Converting the full arrays to Python lists and indented JSON is prohibited because it causes
avoidable pauses, memory amplification, and very large autosaves.

## Identity and export correctness

A channel is identified by `(source_id, channel_id)`, not by its display name alone. This identity
must key plot rows, units, readouts, visibility, annotations, synchronization evidence, and export
columns. Two sources commonly both contain channels named `x`, `y`, `TTL`, or `ch0`; neither may
overwrite or hide the other.

Wide Parquet output is valid only after proving that every selected channel has the identical
timestamp axis. Otherwise export uses a long representation containing source ID, channel ID,
timestamp, value, and validity/gap information. CSV export may retain separated channel sections,
but both formats must use searchsorted slice bounds and chunked writers instead of allocating a
full-recording boolean mask.

## Required ground-truth workloads

Accurate streaming is not certified until all of these pass:

- duplicate and backward timestamps exactly across a 50,000-row parser boundary;
- an explicit-schema file whose later batch would otherwise infer a different timestamp type;
- naive timestamps across a DST transition for every supported timezone choice;
- two sources with the same channel names and different offsets, rates, gaps, and timestamp axes;
- impulses and gaps positioned at every pyramid bucket boundary and inside every bucket level;
- 1 GB/4-channel import with cancellation, bounded peak RSS, valid-cache reopen, and injected
  write/rename failure;
- exact export/statistics comparisons against raw NumPy results for irregular and NaN-bearing data;
- decoded presentation-frame timestamps versus cached video timing for CFR, VFR, B-frame,
  dropped-frame, missing-PTS, and long-GOP fixtures.
