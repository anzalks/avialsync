"""The edited tracker, materialised beside the original in the sidecar cache.

The recording is never written.  Its imported pyramid is never written either.
An edit produces a **generation** -- ``<file>.avialcache/edited/<fingerprint>/``
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
and the two sidecars beside it.  Deleting ``.avialcache/`` costs a rebuild and
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
import json
import logging
import os
import shutil
import uuid
from collections.abc import Iterable
from pathlib import Path

import numpy as np

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

#: Where generations live inside a source's own sidecar cache directory.
EDITED_DIR = "edited"

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


def load(cache_dir: Path, fingerprint: str) -> EditedCache | None:
    """Return an already-materialised generation, or None when there is none."""
    directory = _generation_dir(cache_dir, fingerprint)
    manifest = _read_manifest(directory)
    if manifest is None:
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

        _write_manifest(staging, program.fingerprint, written)
        directory.parent.mkdir(parents=True, exist_ok=True)
        if directory.exists():
            _remove_generation(directory)
        os.replace(staging, directory)
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


def _write_manifest(directory: Path, fingerprint: str, channels: list[str]) -> None:
    written = _datetime.datetime.now(_datetime.UTC).isoformat(timespec="seconds")
    (directory / _MANIFEST).write_text(
        json.dumps(
            {
                "marker": _MARKER,
                "fingerprint": fingerprint,
                "channels": sorted(channels),
                "written": written,
            },
            indent=1,
        ),
        encoding="utf-8",
    )


def prune(cache_dir: Path, keep: Iterable[str]) -> list[str]:
    """Remove *committed* generations this module wrote, except those in *keep*.

    Returns the fingerprints removed.  Two directories are never touched: one
    without our manifest, because this walks a folder inside the user's data
    directory and the only safe rule is to delete solely what we can prove we
    wrote; and a staging directory, because a rebuild in flight is not rubbish
    left by an old one.  Every edit starts a job and a person dragging points
    starts several, so a sweep that could reach another job's staging killed it
    half-written and lost the edit it was applying.

    A staging directory therefore outlives only a hard crash -- :func:`materialise`
    removes its own on the way out, whether it committed or raised.
    """
    root = cache_dir / EDITED_DIR
    if not root.is_dir():
        return []
    kept = set(keep)
    removed: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name in kept:
            continue
        if entry.name.startswith(_TEMP_PREFIX):
            continue
        if _read_manifest(entry) is not None:
            _remove_generation(entry)
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
