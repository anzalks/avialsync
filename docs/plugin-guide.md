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
            SessionItem(
                video,
                registry.find_best_loader(video),
                source_epoch=start,  # when this camera's first frame was exposed
            )
            for video, start in cameras(path)
        ]
        items.append(
            SessionItem(
                path / "wheel.csv",
                MyEncoderLoader,
                {"role": ""},
                source_epoch=midnight,  # its timestamps count from midnight
            )
        )
        return SessionLayout(
            items=items,
            session_epoch=min(start for _video, start in cameras(path)),
            anchor_epoch=...,
            camera_fps=...,
        )
```

```toml
[project.entry-points."avialsync.sessions"]
myrig = "my_plugin:MyRigSession"
```

`can_open` is asked about every dropped directory before per-file scanning, so
keep it cheap — a marker file or a name pattern, not a directory walk. `scan`
runs off the UI thread and may read files.

Return session-wide settings as `SessionLayout` fields, not as extra items:
`session_epoch` (the UTC instant you want master-clock zero to be — usually when
the recording started), `anchor_epoch` (the UTC instant relative timestamps are
measured from — it also switches the display to wall-clock time), `camera_fps`,
`skeleton` (body-part pairs; declaring them takes precedence over the
skeleton the 3D view otherwise detects from pairwise rigidity, D-082), and
`rotary` (a `RotaryHint` naming the channel that carries a running wheel's
cumulative angle in degrees, and the wheel's bar count and radius when your rig
records them, D-113 — it pre-fills Add Wheel and is never applied on its own). Set a
`SessionItem.loader` of `None` to let capability resolution pick one, which is
what you should do for ordinary video.

`session_epoch` and `anchor_epoch` are commonly different, and both are useful:
a rig whose logs are written as seconds since midnight has an `anchor_epoch` of
that midnight, while its master zero is the instant the cameras started, hours
later. Declare `session_epoch` rather than letting it be derived — sources load
concurrently, so a derived zero would depend on which file happened to finish
first.

### Say where your timestamps start, never where the source should go

`SessionItem.source_epoch` is the **UTC instant your file's `t=0` is**, and it is
the only timing question a session has to answer. The application derives the
placement from it (`session_zero - source_epoch`), so you never compute an
offset:

| Your file's timestamps are… | Declare |
|---|---|
| seconds from its own first frame (a video container) | that frame's UTC instant |
| seconds since midnight | that midnight |
| Unix epoch seconds already | `0.0`, or nothing — they are recognised |
| something with no knowable instant | nothing; it keeps its own zero |

**Always declare an absolute instant.** A session-relative number declares
nothing: 34526 is equally 09:35:26 and a nine-hour elapsed time, and the
application cannot tell which you meant.

**Never put a placement in `config`.** `config` is hashed into the sidecar cache
key, so an offset there lets a re-placement invalidate the samples underneath it
— and it lands in the offset control the user nudges by hand, which is how an
AOL session came to open with -34526 s already typed into every camera (D-110).
`source_epoch` is a `SessionItem` field for exactly that reason, as `label` and
`coverage_group` are.

**If your scan leaves something out, say so in `warnings`.** A folder holding one
unreadable recording beside three good ones should still yield the three — do not
fail the whole scan — but returning fewer items and nothing else leaves a session
that looks complete while missing data. Each string is shown to the user; the log
is not (D-085).

```python
return SessionLayout(items=items, warnings=[f"{name} could not be read — {why}"])
```

`config` reaches the loader as its import config, and is hashed into the sidecar
cache key — so put what the loader needs to *read* the file there, and nothing
about where the file belongs in time. One key is interpreted by the application:
`role` routes a source away from the plot rows — `"pose3d"` to the 3D view,
`"overlay2d"` (with `overlay_video`) to that camera's overlay.

A bare `offset` in `config` still works, and means the whole source-to-master
mapping rather than a correction on top of a placement. Prefer `source_epoch`:
it composes with the session zero, survives a source being re-placed, and leaves
the offset control free for what the user actually uses it for.

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

### Optional: messages the recording carries

Many formats store prose the experimenter wrote — an acquisition system's
annotation stream, a commented file header, a note appended when the session
stopped. If yours does, return it from `messages()`:

```python
from avialsync.core.messages import Message


def messages(self) -> list[Message]:
    """Return free-text records, in this source's own timeline."""
    return [Message(text="stimulus on", time=61.4, channel="MessageCenter")]
```

It is called once after `open()`, on the import thread, and has a default that
returns nothing, so a plugin that never defines it is fully supported. Times are
in your source's timeline — the same one `read_chunks` yields — so the session's
alignment moves a note and the samples it describes together.

**Leave `time` as `None` for anything the file did not timestamp.** A header or a
closing comment has no place on the clock, and AvialSync shows those as untimed
notes rather than pinning them to the start of the recording. Do not substitute
`0.0`: that asserts a moment the file never recorded.

Messages are displayed read-only, in their own Inspector tab and timeline lane.
They are not annotations — the user's own markers are separate, editable, and
exported as their work (see D-078).

**Do not return a note the file wrote about itself.** A sync preamble — the line
declaring the recording's start sample or its software clock — places the clock
rather than saying anything a person wrote, and listing it puts the same two rows
at the head of every recording a user opens. Parse it for the times you need and
withhold it, as both Open Ephys readers do with `sync_messages.txt` and with
`messages.events`' `Software time:` and `start time:` lines (D-085).

If your format stores a message as a sample number, divide by the rate onto the
**same axis your `read_chunks` timestamps use**. Rebasing onto the first recorded
sample when your samples are not rebased offsets every note from the trace it
describes by the recording's own start.

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

## Trigger plugins

A trigger plugin is the third source kind, beside time-series and video, and it
answers a different question from either: not *what* was recorded but *when
things happened*, and what those instants are evidence **of**.

That second half is the reason the kind exists. A pulse train is not
self-describing. The same column of edges means something different depending
on which way the wire ran, and the difference decides what may be done with it:

- `frame_strobe` — the camera emitted a pulse per exposure it **took**. Pulse
  count is frame count, so pulse *i* may be paired with frame *i*.
- `frame_trigger` — a generator **asked** for each exposure. A frame the camera
  dropped looks exactly like one it kept, so index pairing would shift
  everything after the loss. Counts agreeing does not rescue it — a drop plus a
  duplicate agree too.
- `sync_train` — a shared square wave, far sparser than the frame rate. Enough
  to follow two clocks wherever they wander; not enough to identify a frame.
- `sparse_events` — a handful of landmarks. Enough to place a recording, rarely
  enough to check the placing.

Your plugin declares the kind; `core.alignment.choose_method` derives the model
from it. This is deliberately not a user-facing dropdown: asking someone to
pick "exact index mapping" asks them to certify something only the recording
knows.

Register under the `avialsync.triggers` entry-point group:

```toml
[project.entry-points."avialsync.triggers"]
my_rig_ttl = "my_package.triggers:MyRigTriggerSource"
```

Implement `core.source.TriggerSource`:

| Method | Returns |
|---|---|
| `can_open(path)` | Confidence in `[0, 1]`, without expensive I/O |
| `open(path, config)` | Nothing; reads what is needed to enumerate trains |
| `trains()` | The id of every train this file offers |
| `kind_of(train_id)` | One of the four kinds above, as a string |
| `read_train(train_id)` | `(times, durations)` in the file's own clock |

Two optional hooks. `suggest_trains(path)` proposes a starting configuration
for the user to correct — **never suggest `frame_strobe`**, because that is a
claim about wiring your file cannot make, and it is the one decision that must
not be made on the user's behalf. `target_hint(train_id)` names the source a
train is evidence about, when the file records it.

`durations` is the exposure length per event where both edges were recorded,
and `None` where only one was. Return `None` rather than zeros: a provider with
only rising edges does not know the width, and saying so is not the same as
measuring it as nothing. Where durations exist, a strobe is timestamped at its
exposure **midpoint**, which is the instant a frame represents for a subject
moving through the exposure.

`times` must be strictly increasing, in the file's own clock. Do not rebase it
onto anything — AvialSync places sources through their own time map and never
rewrites a timestamp.

Keep laboratory-specific parsing and semantics in the plugin. AvialSync
preserves raw timestamps, performs the alignment, shows the matched evidence
and fit quality, and requires user acceptance before changing a source mapping.
It does not provide acquisition drivers or built-in scientific analysis.
