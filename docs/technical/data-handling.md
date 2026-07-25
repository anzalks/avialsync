# Data handling

## Source files and caches

Text and plugin data are read once and converted into a sidecar cache beside the source. The cache is
used for later viewing so large files are not repeatedly parsed. The cache key includes source content
information, including a content-hash tail, to avoid treating a changed file as unchanged. The cache
directory is named `<file>.avialcache/`; deleting it is safe because AvialView can build it again from
the source file.

Importers process data in chunks. A time-series plugin yields time/value chunks in chronological order;
the importer validates them, records import statistics, and builds the cache away from the interface
thread. Video loaders provide an mpv-playable media path and frame timing metadata when available.

## Time and precision

Master and source time are floating-point seconds. Timestamp arrays retain high precision. Plotting
uses a downsampled pyramid for display only; values at the cursor and exported data come from the
underlying cached source representation. Frame stepping uses the video's actual frame timestamps when
they are available, rather than assuming a fixed frame rate.

## Gaps and missing values

Missing values remain missing. Gaps are detected after import from timestamp spacing and recorded for
plotting and inspection, so a line is not drawn across a known discontinuity. NaNs and importer-defined
sentinel values are counted in the import report; the original input stays untouched.

## Sessions and provenance

A `.avv` session stores references to sources, visual layout, offsets/drift, annotations, and accepted
synchronization provenance. It does not copy or alter the original recordings. Local window geometry
and presentation preferences remain local to each user. When a source has moved, the session can ask
the user to relink it instead of guessing a replacement.
