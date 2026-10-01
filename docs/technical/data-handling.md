# Data handling

## Source files and caches

The product contract is that text and plugin data are read once and converted into a sidecar cache
beside the source. A valid cache must be used on later viewing so a large source is not repeatedly
parsed. The cache key includes source content information, including a content-hash tail, to avoid
treating a changed file as unchanged. The cache directory is named `<file>.avialcache/`; deleting it
is safe because AvialSync can build it again from the source file.

Importers process data in chunks. A time-series plugin yields time/value chunks in chronological order;
the importer validates them, records import statistics, and builds the cache away from the interface
thread. Video loaders provide a playable media path and frame timing metadata when available.

The P3.5 implementation audit closed on 2026-07-30. `ChannelStage` stages parser chunks to disk
before materializing a channel, `NeoLoader` reads blocks lazily, and a content/config-validated
manifest enables the cache fast path. These changes address the former full-channel and full-block
materialization gaps. Representative peak-memory and warm-reopen measurements remain open; see
[Performance verification](performance.md).

Cache replacement uses a recoverable swap and a file-level fallback when the cache directory cannot
be renamed. The previous valid sidecar is retained or restored on replacement failure; fault-
injection coverage exercises recovery. Cache durability is implemented, while target-scale import
performance remains to be measured.

## Time and precision

Master and source time are floating-point seconds. Timestamp arrays retain high precision. Plotting
uses a downsampled pyramid for display only; cursor values, statistics, and exported data must come
from the exact cached source representation. Every source needs its own `TimeMap`; UI consumers
receive master time and convert to source time through that mapping. Frame stepping uses actual video
presentation timestamps when they are available, rather than assuming a fixed frame rate.

The P0 accuracy audit closed on 2026-07-30. Plot rows render pyramid minima and maxima, gap evidence
is propagated into coarser buckets, CSV timestamps use an explicit schema with chronology checks
across chunks and the selected timezone, and time-series sources map through their own `TimeMap`.
These are implemented behaviors; the representative workloads that certify their scale remain open
in [Performance verification](performance.md).

The numbered audit details below preserve the 2026-07-29 diagnosis; all four implementation issues
were resolved by 2026-07-30 and are not current blockers.

1. Plot rows render both extrema of each pyramid bucket. Spike fixtures verify the envelope across
   the tested display scales.
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

Sampling uses one shared rule: `sample_at` returns the last sample at or before the requested source
time. `MappedChannelReader` converts master time through the source's `TimeMap` before delegating,
so readouts, plots, exports, and tracking consumers do not independently choose a nearest-sample or
interpolation policy.

## Gaps and missing values

Missing values remain missing. Gaps are detected after import from timestamp spacing and recorded for
plotting and inspection, so a line is not drawn across a known discontinuity. NaNs and importer-defined
sentinel values are counted in the import report; the original input stays untouched.

## Sessions and provenance

A `.avv` session stores references to sources, visual layout, offsets/drift, annotations, and accepted
synchronization provenance. It does not copy or alter the original recordings. Local window geometry
and presentation preferences remain local to each user — named workspace layouts likewise, because a
layout belongs to the person and their screen rather than to the recording. When a source has moved,
the session can ask the user to relink it instead of guessing a replacement.

Hand corrections to pose data are the one edit kept *outside* the session, in a `.avialfix.csv`
sidecar beside the pose file, so they travel with the recording rather than with the session. The
session records only how many corrections each source had; if that count and the sidecar disagree, or
the sidecar has gone, the discrepancy is reported rather than absorbed.

Exact per-frame mappings can contain millions of timestamp pairs. Large accepted mappings live
in a compact, checksum-validated compressed session sidecar while session JSON retains its summary
and bounded evidence sample. Serialization and IO run on a worker (`engine/session_worker.py`); only
the close-time autosave is synchronous, deliberately, because the window is being destroyed.
Converting the full arrays to Python lists and indented JSON is prohibited because it causes
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

For a pose source, accepted identity swaps and point corrections form one edit program (D-142).
Corrections address raw file columns and retain the label shown when they were made (D-143).
Only affected channels are materialised into fingerprinted generations under
`<file>.avialcache/edited/`; the imported arrays and original recording remain unchanged.
The corrected pose CSV streams each row, substitutes raw-column corrections, then permutes all
fields of routed points. A swap-only source also produces this single edited copy; the export
path must differ from the recording path (D-145).
View → Play original switches the readers back to the imported arrays without altering the
edit program or the corrected export, and the choice is persisted in the session.

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
