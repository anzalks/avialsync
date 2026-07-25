# Plugin guide

KinoChronix discovers plugins from the `kinochronix.loaders` entry-point group
and from Python files in `~/.kinochronix/plugins/`. The highest non-zero
`can_open(path)` score wins. A plugin must be importable without importing Qt.

## Time-series plugins

Subclass `TimeSeriesSource`, implement `can_open`, `open`, `channels`, and
`read_chunks`, then register the class in your package metadata:

```toml
[project.entry-points."kinochronix.loaders"]
my_format = "my_plugin:MySource"
```

`open()` and `read_chunks()` execute in an importer worker thread. Each yielded
pair contains one-dimensional, globally chronological NumPy arrays. Preserve
NaNs; KinoChronix owns cache construction, decimation, and gap detection.
Duplicate timestamps keep the final value. Sort non-monotonic input or raise
`NonMonotonicTimeError`; never emit decreasing timestamps.

See `examples/plugins/kinochronix-plugin-example` for an installable toy binary
loader.

## Video plugins

Subclass `VideoSource` and implement every abstract method. `open()` runs in a
background worker. If `needs_conversion()` is true, `prepare(progress_cb)` must
create an mpv-playable cached file and return it; KinoChronix opens only
`media_path()` after preparation succeeds. `time_bounds()` returns
`(metadata_start, metadata_start + duration)` when a UTC start is available,
otherwise `(0.0, duration)`. `start_time()` is only a metadata guess: the user
offset always takes precedence.

## Synchronization and future plugins

KinoChronix currently extracts rising TTL edges from cached time-series channels
and aligns them to video frame-event timestamps through the Sync Wizard. Its plugin
event-provider API is intentionally not frozen yet. The future extension will let a
loader expose raw event timestamps and metadata for native digital events, TTL edges,
or camera-frame triggers.

Keep laboratory-specific parsing and semantics in the plugin. KinoChronix will
preserve raw timestamps, perform visual alignment, show matched evidence and fit
quality, and require user acceptance before changing a source mapping. It will not
provide acquisition drivers or built-in scientific analysis.
