"""The edited tracker, materialised beside the original in its cache entry.

The recording is never written.  Its imported pyramid is never written either.
An edit produces a **generation** -- ``<cache entry>/edited/<fingerprint>/``
-- holding the pyramid of exactly the channels the edits changed, and every
consumer then reads those channels from there and the rest from the original
cache.  Plot rows, the video overlay, the 3D view, the readout and every export
therefore show the edited tracker without any of them knowing what a flip is
(D-142).

**Per channel, not per source.**  A generation holds only what changed: a flip
of one body part between two animals is four channels out of sixty, and a
directory holding all sixty would cost a full re-import for every drag.
:meth:`EditedCache.dir_for` is what routes a reader, and the channels it does
not name are read from the original -- the same arrays, not a copy of them.

**Derived, and safe to lose.**  A generation is a pure function of the pose file
and the two sidecars beside it.  Deleting the cache costs a rebuild and
nothing else, which is exactly what makes it the right place for this and the
sidecar the wrong one.

**Nothing outside ``edited/`` is ever removed.**  :func:`prune` deletes only
directories it can prove this module wrote: inside ``edited/``, named for a
fingerprint, carrying a manifest with this module's own marker.  Anything else
is left where it is, whatever it looks like.
"""

from __future__ import annotations

import dataclasses
import datetime as _datetime
import hashlib
import json
import logging
import os
import shutil
import threading
import uuid
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from avialsync.core.cache import EDITED_SUBDIR
from avialsync.core.edit_program import EditProgram
from avialsync.core.pose import PosePoint, PoseSchema
from avialsync.core.pyramid import PyramidBuilder, PyramidReader

logger = logging.getLogger(__name__)

__all__ = [
    "EDITED_DIR",
    "EditedCache",
    "materialise",
    "load",
    "prune",
]

#: Where generations live inside a source's own cache entry. Owned
#: by :mod:`avialsync.core.cache`, which carries it across a rebuild.
EDITED_DIR = EDITED_SUBDIR

#: The base cache's own key file, written by :class:`~avialsync.core.cache.CacheManager`.
_BASE_KEY_FILE = "meta.json"

#: Written into every manifest.  :func:`prune` refuses to remove a directory
#: that does not carry it, so a fingerprint-shaped directory somebody else left
#: in there survives us.
_MARKER = "avialsync-edited-tracker"

_MANIFEST = "manifest.json"
_TEMP_PREFIX = ".tmp_"

#: Written into a corrected coordinate's likelihood, for the same reason
#: :mod:`avialsync.core.pose_export` writes it: the first thing most analyses do
#: is drop rows below a likelihood threshold, and a corrected point usually
#: carries a low one -- so leaving it would filter out the correction it was
#: made for.
CORRECTED_LIKELIHOOD = 1.0


@dataclasses.dataclass(frozen=True)
class EditedCache:
    """One materialised generation, and how to read through it."""

    fingerprint: str
    directory: Path
    #: The channels this generation holds.  Everything else reads the original.
    channels: frozenset[str] = frozenset()

    def __bool__(self) -> bool:
        return bool(self.channels)

    def dir_for(self, cache_dir: Path, channel: str) -> Path:
        """Where *channel* should be read from: the generation, or the original."""
        return self.directory if channel in self.channels else cache_dir


def _generation_dir(cache_dir: Path, fingerprint: str) -> Path:
    return cache_dir / EDITED_DIR / fingerprint


def _base_key(cache_dir: Path) -> str | None:
    """Identify the import a generation was built from, or None for a bare cache.

    A generation is a function of the edits *and* the arrays they edit. The
    fingerprint names only the edits, so after a re-import -- a frame rate
    learned from the camera re-dates every sample -- the same edits would have
    found the old generation and kept showing the old timing.
    """
    try:
        key = (cache_dir / _BASE_KEY_FILE).read_bytes()
    except OSError:
        return None
    return hashlib.sha1(key, usedforsecurity=False).hexdigest()[:16]


def load(cache_dir: Path, fingerprint: str) -> EditedCache | None:
    """Return an already-materialised generation, or None when there is none.

    One built from a different import of the same source is none: it is stale,
    and the caller rebuilds it.
    """
    directory = _generation_dir(cache_dir, fingerprint)
    manifest = _read_manifest(directory)
    if manifest is None or manifest.get("base") != _base_key(cache_dir):
        return None
    held = manifest.get("channels")
    names = held if isinstance(held, list) else []
    return EditedCache(
        fingerprint=fingerprint,
        directory=directory,
        channels=frozenset(str(name) for name in names),
    )


def materialise(
    cache_dir: Path,
    program: EditProgram,
    schema: PoseSchema,
    *,
    rebuild: bool = False,
) -> EditedCache:
    """Write the channels *program* changes, and return how to read them.

    Skips the work when the generation this program names is already complete,
    which is what makes reopening a session with edits free.  An empty program
    materialises nothing and reads straight through to the original cache.
    """
    affected = program.affected(point.name for point in schema.points)
    if not program or not affected:
        return EditedCache(fingerprint=program.fingerprint, directory=cache_dir)

    existing = load(cache_dir, program.fingerprint)
    if existing is not None and not rebuild:
        return existing

    directory = _generation_dir(cache_dir, program.fingerprint)
    # One staging directory per *job*, not per fingerprint. A person editing
    # points starts a rebuild per edit, and two of them naming the same
    # directory means the second writes into what the first is committing.
    staging = directory.with_name(f"{_TEMP_PREFIX}{program.fingerprint}_{uuid.uuid4().hex[:8]}")
    staging.mkdir(parents=True, exist_ok=True)

    try:
        written: list[str] = []
        for name in affected:
            point = schema.point(name)
            if point is None:
                continue
            written.extend(_write_point(cache_dir, staging, program, point))

        _write_manifest(staging, program.fingerprint, written, _base_key(cache_dir))
        directory.parent.mkdir(parents=True, exist_ok=True)
        if not rebuild:
            # Another job for the same edits may have committed while this one
            # ran -- several are in flight while a person works, and undoing
            # back to an edit still being built starts a second. Its readers
            # are already painting from it. Same fingerprint, same content, so
            # it is kept as it is and this job's copy is discarded below.
            committed = load(cache_dir, program.fingerprint)
            if committed is not None:
                return committed
        _commit(staging, directory)
    finally:
        # Whatever went wrong, this job's own half-written directory goes with
        # it rather than being left for a later sweep to find and puzzle over.
        if staging.exists():
            _remove_generation(staging)
    return EditedCache(
        fingerprint=program.fingerprint,
        directory=directory,
        channels=frozenset(written),
    )


def _commit(staging: Path, directory: Path) -> None:
    """Make *staging* the generation at *directory* without a reader seeing a gap.

    A new generation is one atomic rename. Replacing a committed one used to
    ``rmtree`` it first, and readers load their arrays lazily on first paint:
    measured, a reader that had loaded ``_t.npy`` then found ``_v.npy`` gone,
    the overlay's ``paintEvent`` raised, and Qt crashed natively. Each file is
    instead renamed over its predecessor, which is atomic per file and leaves
    an open memory map on the old one, and the manifest goes last so a
    directory never claims channels it does not yet hold.
    """
    if not directory.exists():
        os.replace(staging, directory)
        return
    manifest = staging / _MANIFEST
    for entry in staging.iterdir():
        if entry != manifest:
            os.replace(entry, directory / entry.name)
    os.replace(manifest, directory / _MANIFEST)


def _write_point(
    cache_dir: Path,
    staging: Path,
    program: EditProgram,
    point: PosePoint,
) -> list[str]:
    """Write every channel of one point, edited, into *staging*."""
    channels: list[str] = []
    axes = tuple(point.axes)
    corrected_indices: set[int] = set()

    for position, axis in enumerate(axes):
        channel = point.channel(axis)
        try:
            times, values = _edited_values(cache_dir, program, point.name, channel, position)
        except (FileNotFoundError, ValueError):
            logger.warning("No cached channel %s to edit; leaving the original.", channel)
            continue
        if position < 2:
            corrected_indices |= _corrected_indices(program, point.name, len(values))
        PyramidBuilder(staging, channel).build_and_save(times, values)
        channels.append(channel)

    likelihood = point.likelihood_channel
    if likelihood is not None:
        try:
            times, values = _edited_values(cache_dir, program, point.name, likelihood, None)
        except (FileNotFoundError, ValueError):
            return channels
        for index in corrected_indices:
            values[index] = CORRECTED_LIKELIHOOD
        PyramidBuilder(staging, likelihood).build_and_save(times, values)
        channels.append(likelihood)
    return channels


def _edited_values(
    cache_dir: Path,
    program: EditProgram,
    name: str,
    channel: str,
    axis_position: int | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(t, v)`` for one channel with routing and corrections applied.

    *axis_position* is 0 for x and 1 for y -- the two a hand correction can
    move; anything else takes routing alone.
    """
    reader = PyramidReader(cache_dir, channel)
    times, values, _ = reader.mapped_columns()
    times = np.asarray(times)
    out = np.array(values, dtype=np.float64, copy=True)
    count = len(out)

    suffix = channel[len(name) :]
    for segment in program.segments_for(name):
        start, stop = segment.bounded(count)
        if stop <= start:
            continue
        donor = PyramidReader(cache_dir, f"{segment.source}{suffix}")
        _, donor_values, _ = donor.mapped_columns()
        end = min(stop, len(donor_values))
        if end > start:
            out[start:end] = donor_values[start:end]

    if axis_position is not None and axis_position < 2:
        for (point, index), position in program.corrections.items():
            if 0 <= index < count and program.source_of(name, index) == point:
                out[index] = position[axis_position]
    return times, out


def _corrected_indices(program: EditProgram, name: str, count: int) -> set[int]:
    """Which samples of *name* show a hand-corrected coordinate."""
    return {
        index
        for (point, index) in program.corrections
        if 0 <= index < count and program.source_of(name, index) == point
    }


def _read_manifest(directory: Path) -> dict[str, object] | None:
    try:
        payload = json.loads((directory / _MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("marker") != _MARKER:
        return None
    return payload


def _write_manifest(
    directory: Path, fingerprint: str, channels: list[str], base: str | None
) -> None:
    written = _datetime.datetime.now(_datetime.UTC).isoformat(timespec="seconds")
    (directory / _MANIFEST).write_text(
        json.dumps(
            {
                "marker": _MARKER,
                "fingerprint": fingerprint,
                "base": base,
                "channels": sorted(channels),
                "written": written,
            },
            indent=1,
        ),
        encoding="utf-8",
    )


#: How many committed generations survive a sweep, the current one included.
#: A reader holds a *path*, not a subscription: the braid is built in a job from
#: a snapshot of where each channel lives, and the person keeps editing while it
#: runs. Keeping only the newest deleted the directory a running job was reading.
#: Three bounds the disk at a few edited channels per edit while leaving a job
#: two edits behind something to read.
KEEP_GENERATIONS = 3
_PIN_LOCK = threading.Lock()
_PINNED: dict[Path, int] = {}


class GenerationPin:
    """Keep a reader's cache directory available while a job holds it."""

    def __init__(self, directory: Path) -> None:
        pinned = directory.absolute()
        self.directory: Path | None = None
        with _PIN_LOCK:
            if not pinned.is_dir():
                raise FileNotFoundError(pinned)
            _PINNED[pinned] = _PINNED.get(pinned, 0) + 1
            self.directory = pinned

    def close(self) -> None:
        """Release this generation once its reader reference is discarded."""
        directory = getattr(self, "directory", None)
        if directory is None:
            return
        with _PIN_LOCK:
            remaining = _PINNED[directory] - 1
            if remaining:
                _PINNED[directory] = remaining
            else:
                del _PINNED[directory]
        self.directory = None

    def __del__(self) -> None:
        self.close()


def pin_reader_directory(directory: Path) -> GenerationPin | None:
    """Pin a base or edited reader directory while a worker may open it."""
    try:
        return GenerationPin(directory)
    except FileNotFoundError:
        return None


def pinned_cache_entries() -> frozenset[Path]:
    """Return base entry paths held by worker snapshots."""
    with _PIN_LOCK:
        return frozenset(
            path.parent.parent if path.parent.name == EDITED_DIR else path for path in _PINNED
        )


def prune(cache_dir: Path, keep: Iterable[str], generations: int = KEEP_GENERATIONS) -> list[str]:
    """Remove *committed* generations this module wrote, except those in *keep*.

    Returns the fingerprints removed.  The *generations* most recent survive,
    the ones named in *keep* among them, because a reader holds a path rather
    than a subscription and a job started an edit ago is still reading one.

    Two directories are never touched at all: one without our manifest, because
    this walks a folder inside the user's data directory and the only safe rule
    is to delete solely what we can prove we wrote; and a staging directory,
    because a rebuild in flight is not rubbish left by an old one.  Every edit
    starts a job and a person dragging points starts several, so a sweep that
    could reach another job's staging killed it half-written and lost the edit
    it was applying.

    A staging directory therefore outlives only a hard crash -- :func:`materialise`
    removes its own on the way out, whether it committed or raised.
    """
    root = cache_dir / EDITED_DIR
    if not root.is_dir():
        return []
    kept = set(keep)
    with _PIN_LOCK:
        kept.update(path.name for path in _PINNED if path.parent == root.absolute())
    others = [
        entry
        for entry in root.iterdir()
        if entry.is_dir()
        and entry.name not in kept
        and not entry.name.startswith(_TEMP_PREFIX)
        and _read_manifest(entry) is not None
    ]
    # Newest first, so what a job started moments ago outlives what nothing has
    # looked at since two edits back.
    others.sort(key=lambda entry: entry.stat().st_mtime_ns, reverse=True)
    removed: list[str] = []
    for entry in others[max(0, generations - len(kept)) :]:
        with _PIN_LOCK:
            if entry.absolute() in _PINNED:
                continue
            renamed = root / f"{_TEMP_PREFIX}prune-{uuid.uuid4().hex}"
            try:
                os.rename(entry, renamed)
            except OSError:
                logger.warning("Could not retire edited generation %s", entry, exc_info=True)
                continue
        _remove_generation(renamed)
        removed.append(entry.name)
    return removed


def _remove_generation(directory: Path) -> None:
    """Delete one generation directory, and report rather than raise.

    Guarded by its position and its manifest, both checked by the callers: this
    function is never handed a path that was not produced by this module.
    """
    try:
        shutil.rmtree(directory)
    except OSError:
        logger.warning("Could not remove edited generation %s", directory, exc_info=True)
