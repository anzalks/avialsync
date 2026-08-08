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

To present one folder as *several* sources with different roles — separate
videos, pose data routed to the 3D view, a sensor trace, all sharing one anchor
time — implement `SessionSource` instead.

## Session plugins

A session is a directory that *is* a recording rather than one that merely
contains files. Subclass `SessionSource` and publish it under the
`avialsync.sessions` entry-point group, or drop the module into
`~/.avialsync/plugins/`:

```python
from avialsync.core.source import SessionItem, SessionLayout, SessionSource


class MyRigSession(SessionSource):
    @classmethod
    def can_open(cls, path: Path) -> float:
        return 1.0 if (path / "rig.marker").exists() else 0.0

    def scan(self, path: Path, registry) -> SessionLayout:
        items = [
            SessionItem(video, registry.find_best_loader(video), {"offset": -start})
            for video, start in cameras(path)
        ]
        items.append(SessionItem(path / "wheel.csv", MyEncoderLoader, {"role": ""}))
        return SessionLayout(items=items, anchor_epoch=..., camera_fps=...)
```

```toml
[project.entry-points."avialsync.sessions"]
myrig = "my_plugin:MyRigSession"
```

`can_open` is asked about every dropped directory before per-file scanning, so
keep it cheap — a marker file or a name pattern, not a directory walk. `scan`
runs off the UI thread and may read files.

Return session-wide settings as `SessionLayout` fields, not as extra items:
`anchor_epoch` (the UTC instant relative timestamps are measured from — it also
switches the display to wall-clock time), `camera_fps`, and `skeleton`. Set a
`SessionItem.loader` of `None` to let capability resolution pick one, which is
what you should do for ordinary video.

`config` reaches the loader as its import config. Two keys are interpreted by
the application: `role` routes a source away from the plot rows — `"pose3d"` to
the 3D view, `"overlay2d"` (with `overlay_video`) to that camera's overlay —
and `offset` shifts the source onto master time.

If your scanner raises, the folder falls back to per-file scanning and the
reason appears in **Help → Diagnostics**; a broken plugin never makes a folder
unopenable. `loaders/aol_session_loader.py` is a full worked example.

## Naming your format

The import dialog lists whatever the registry found, and each format supplies
its own label — override `display_name()` to control it, and
`display_aliases()` to be offered under several. Both have defaults, so this is
optional.

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
create a playable cached file and return it; AvialSync opens only
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
