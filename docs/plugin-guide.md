# Plugin guide

AvialSync discovers plugins from the `avialsync.loaders` entry-point group
and from Python files in `~/.avialsync/plugins/`. The highest non-zero
`can_open(path)` score wins. A plugin must be importable without importing Qt.

## Time-series plugins

Subclass `TimeSeriesSource`, implement `can_open`, `open`, `channels`, and
`read_chunks`, then register the class in your package metadata:

```toml
[project.entry-points."avialsync.loaders"]
my_format = "my_plugin:MySource"
```

`open()` and `read_chunks()` execute in an importer worker thread. Each yielded
pair contains one-dimensional, globally chronological NumPy arrays. Preserve
NaNs; AvialSync owns cache construction, decimation, and gap detection.
Duplicate timestamps keep the final value. Sort non-monotonic input or raise
`NonMonotonicTimeError`; never emit decreasing timestamps.

See `examples/plugins/avialsync-plugin-example` for an installable toy binary
loader.

### Claiming a whole recording folder

`can_open(path)` is offered directories as well as files, so a rig with its own
folder layout can be supported without changing AvialSync:

```python
@classmethod
def can_open(cls, path: Path) -> float:
    return 1.0 if path.is_dir() and (path / "myrig.marker").exists() else 0.0
```

When a plugin claims a directory, the drop scan stops there and hands the whole
folder to it instead of recursing into the loose files inside. Your `open()`
receives the directory, and the folder becomes **one** source with as many
channels as you declare.

What this cannot yet do is present one folder as *several* sources with
different roles — separate videos, pose data routed to the 3D view, and a
sensor trace, all sharing one anchor time. That fan-out exists for the built-in
AOL session format but is not reachable from a plugin; see "Pending" in
`HANDOUT.md`. If your folder needs it today, the workaround is to let users drop
the individual files (or the subfolders) rather than the session root.

### Optional: single-pass bulk ingest

`read_chunks` is called once per channel, so a format parsed in one pass is
re-parsed for every channel it declares — an 80-channel file, 80 times. If your
format is like that, you may also define `read_all_chunks`:

```python
def read_all_chunks(self) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
    """Yield {channel_name: (t, v)} per chunk, every declared channel aligned."""
```

AvialSync uses it in place of the per-channel calls when it is present, and
falls back to `read_chunks` when it is not. This is an optional extension, not
part of the frozen v1 contract: it is absent from `TimeSeriesSource`, and a
plugin that never defines it is fully supported. If you do define it, every
chunk must carry every channel you declared, on the same rows, under the same
ordering, duplicate, and NaN rules as `read_chunks` — both paths must build the
same cache from the same file.

## Video plugins

Subclass `VideoSource` and implement every abstract method. `open()` runs in a
background worker. If `needs_conversion()` is true, `prepare(progress_cb)` must
create an mpv-playable cached file and return it; AvialSync opens only
`media_path()` after preparation succeeds. `time_bounds()` returns
`(metadata_start, metadata_start + duration)` when a UTC start is available,
otherwise `(0.0, duration)`. `start_time()` is only a metadata guess: the user
offset always takes precedence.

`video_metadata()` is an optional, source-compatible extension with a default implementation.
Override it to return `VideoMetadata` when the format exposes codec, byte size, and
timestamp-derived CFR/VFR evidence.

## Synchronization and future plugins

AvialSync currently extracts rising TTL edges from cached time-series channels
and aligns them to video frame-event timestamps through the Sync Wizard. Its plugin
event-provider API is intentionally not frozen yet. The future extension will let a
loader expose raw event timestamps and metadata for native digital events, TTL edges,
or camera-frame triggers.

Keep laboratory-specific parsing and semantics in the plugin. AvialSync will
preserve raw timestamps, perform visual alignment, show matched evidence and fit
quality, and require user acceptance before changing a source mapping. It will not
provide acquisition drivers or built-in scientific analysis.
