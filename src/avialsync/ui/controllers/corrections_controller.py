"""Persisting hand corrections: sidecar first, session as the fallback (D-099).

A correction is a fact about the recording, so it is written beside the pose
file the moment it is made rather than waiting for the session to be saved.  Two
hundred careful drags are collected data now; leaving them in RAM until somebody
remembers Ctrl+S is the wrong default for work that cannot be regenerated.

The session then records only a count per source.  That keeps one authority for
the corrections themselves while still making a missing or emptied sidecar
*reportable* — "this session recorded 47 corrections and found 12" — instead of
silently showing fewer points than the user left behind.

When the pose file's directory cannot be written — an archived acquisition on
read-only media is the ordinary case — the corrections go into the session
instead and the user is told which storage they got.  Losing the work is not one
of the options.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from avialsync.core import point_edit_sidecar
from avialsync.core.point_edit_sidecar import Correction
from avialsync.ui.i18n import tr

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

#: Where a source's corrections are kept.  A source is "session" only because
#: writing beside it failed, never by preference.
SIDECAR = "sidecar"
SESSION = "session"


def frame_axis(window: MainWindow, source_id: str) -> tuple[np.ndarray, float] | None:
    """Return a pose source's own sample times and frame rate, if it has them.

    The store keys a correction by **sample index**, because that is what stays
    put when an offset or an accepted TimeMap changes *when* a sample is shown.
    Everything outside the application speaks **video frame numbers**: the
    sidecar a person reads, the corrected pose CSV, DLC's labeled data. For a
    pose file written contiguously from frame 0 the two are the same number,
    which is why the difference stays invisible until someone hands you a file
    covering only the frames they labelled.

    Returns ``None`` when the source is not a registered 2D pose source or
    declares no frame rate; callers then treat the index as the frame, which is
    the right answer for the contiguous case and the only one available.
    """
    for sources in window._overlay_sources.values():
        entry = sources.get(source_id)
        if entry is None:
            continue
        rate = float(entry.get("frame_rate", 0.0))
        points = entry.get("points") or {}
        if rate <= 0.0 or not points:
            return None
        reader = next(iter(points.values()))[0]
        times = reader.source_reader.mapped_columns()[0]
        if len(times) == 0:
            return None
        return times, rate
    return None


def frame_for(window: MainWindow, source_id: str, index: int) -> int:
    """Convert a sample index to the video frame number it names."""
    axis = frame_axis(window, source_id)
    if axis is None:
        return int(index)
    times, rate = axis
    if not 0 <= index < len(times):
        return int(index)
    return int(round(float(times[index]) * rate))


def index_for(window: MainWindow, source_id: str, frame: int) -> int | None:
    """Convert a video frame number back to this source's sample index.

    ``None`` when the file has no sample within half a frame of *frame* — a
    pose file re-exported over a different range, where landing the correction
    on the nearest row would silently move it to the wrong animal.
    """
    axis = frame_axis(window, source_id)
    if axis is None:
        return int(frame)
    times, rate = axis
    target = float(frame) / rate
    position = int(np.searchsorted(times, target, side="left"))
    candidates = [i for i in (position - 1, position) if 0 <= i < len(times)]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda i: abs(float(times[i]) - target))
    if abs(float(times[nearest]) - target) > 0.5 / rate:
        return None
    return nearest


def persist(window: MainWindow, source_id: str) -> None:
    """Write one source's corrections beside its pose file, now.

    Called from the single funnel every user correction passes through
    (``WindowMutationTarget.set_tracked_point``), so a drag, an undo, and a redo
    all reach disk by the same path.  Never called for the read path: adopting a
    sidecar must not echo it straight back.
    """
    if not source_id:
        return
    rows = [
        Correction(frame=frame_for(window, source_id, index), bodypart=point, x=x, y=y)
        for index, point, x, y in window.point_edits.for_source(source_id)
    ]
    try:
        written = point_edit_sidecar.write(Path(source_id), rows)
    except OSError as error:
        _fall_back_to_the_session(window, source_id, error)
        return

    window._point_edit_storage[source_id] = SIDECAR
    if source_id not in window._announced_correction_files:
        window._announced_correction_files.add(source_id)
        window.notifications.show_success(
            tr("Corrections for {source} are saved beside it, in {file}.").format(
                source=Path(source_id).name, file=written.name
            )
        )


def _fall_back_to_the_session(window: MainWindow, source_id: str, error: OSError) -> None:
    """Keep the work when the data directory will not take it.

    Reported once per source: a read-only acquisition volume fails on every
    subsequent drag too, and a strip that reappears on each one would train the
    user to dismiss it without reading.
    """
    window._point_edit_storage[source_id] = SESSION
    logger.warning("Could not write corrections beside %s", source_id, exc_info=error)
    if source_id in window._announced_correction_files:
        return
    window._announced_correction_files.add(source_id)
    window.notifications.show_warning(
        tr(
            "Corrections for {source} are kept in this session: its folder "
            "could not be written. Save the session to keep them."
        ).format(source=Path(source_id).name),
        details=str(error),
    )


def adopt(window: MainWindow, source_id: str) -> None:
    """Load the corrections that live beside a pose file as it is imported.

    This is what makes a correction outlive the session it was made in: open the
    same pose file anywhere and its corrections come with it.
    """
    if not source_id:
        return
    corrections = point_edit_sidecar.read(Path(source_id))
    expected = window._expected_correction_counts.pop(source_id, None)
    if corrections is None:
        if expected:
            _report_missing(window, source_id, expected)
        return

    rows: list[tuple[int, str, float, float]] = []
    unplaceable = 0
    for entry in corrections.entries:
        index = index_for(window, source_id, entry.frame)
        if index is None:
            unplaceable += 1
            continue
        rows.append((index, entry.bodypart, entry.x, entry.y))
    window.point_edits.load_source(source_id, rows)
    window._point_edit_storage[source_id] = SIDECAR

    name = Path(source_id).name
    if unplaceable:
        window.notifications.show_warning(
            tr(
                "{n} correction(s) name frames that are not in {source}. They "
                "have been left out rather than moved to the nearest row."
            ).format(n=unplaceable, source=name)
        )
    if corrections.skipped:
        window.notifications.show_warning(
            tr("{n} correction(s) in {file} could not be read and were skipped.").format(
                n=corrections.skipped, file=point_edit_sidecar.sidecar_path(source_id).name
            )
        )
    if expected is not None and expected != len(corrections.entries):
        window.notifications.show_warning(
            tr(
                "This session recorded {expected} correction(s) for {source} "
                "and its corrections file holds {found}."
            ).format(expected=expected, source=name, found=len(corrections.entries))
        )
    if corrections.source_bytes is not None:
        try:
            actual = Path(source_id).stat().st_size
        except OSError:
            actual = corrections.source_bytes
        if actual != corrections.source_bytes:
            # Evidence, not a gate (architecture rule 8). A re-exported pose file
            # can renumber frames, which would land old corrections on the wrong
            # ones -- but discarding a user's work on a size comparison would be
            # worse than telling them and letting them look.
            window.notifications.show_warning(
                tr(
                    "{source} has changed size since its corrections were made. "
                    "Check that they still sit on the right frames."
                ).format(source=name)
            )


def _report_missing(window: MainWindow, source_id: str, expected: int) -> None:
    window.notifications.show_warning(
        tr(
            "This session recorded {expected} correction(s) for {source}, "
            "and no corrections file was found beside it."
        ).format(expected=expected, source=Path(source_id).name)
    )


def build_manifest(window: MainWindow) -> list[dict[str, Any]]:
    """Describe each source's corrections for the ``.avv``.

    Coordinates are written only for a source that fell back to session storage.
    Everywhere else the count is the whole record, so the session cannot drift
    into being a second, stale copy of the corrections.
    """
    manifest: list[dict[str, Any]] = []
    for source_id in sorted(window.point_edits.source_ids()):
        storage = window._point_edit_storage.get(source_id, SIDECAR)
        record: dict[str, Any] = {
            "source": source_id,
            "count": window.point_edits.count_for(source_id),
            "storage": storage,
        }
        if storage == SESSION:
            record["edits"] = window.point_edits.to_list(source_id)
        manifest.append(record)
    return manifest


def restore_manifest(window: MainWindow, manifest: list[dict[str, Any]] | None) -> None:
    """Take up what a session says about corrections, before its sources load.

    Session-stored entries are adopted straight away; sidecar-stored ones are
    only *expected*, and each pose file confirms or contradicts its own count as
    it imports.
    """
    window._expected_correction_counts.clear()
    window._point_edit_storage.clear()
    window._announced_correction_files.clear()
    for record in manifest or []:
        try:
            source_id = str(record["source"])
            storage = str(record.get("storage", SIDECAR))
            count = int(record.get("count", 0))
        except (KeyError, TypeError, ValueError):
            continue
        if storage == SESSION:
            window.point_edits.adopt(record.get("edits") or [])
            window._point_edit_storage[source_id] = SESSION
        else:
            window._expected_correction_counts[source_id] = count


def remap(window: MainWindow, old_id: str, new_id: str) -> None:
    """Follow a relinked pose file, so its expectations move with it."""
    if old_id == new_id:
        return
    window.point_edits.remap_source(old_id, new_id)
    expected = window._expected_correction_counts.pop(old_id, None)
    if expected is not None:
        window._expected_correction_counts[new_id] = expected
    storage = window._point_edit_storage.pop(old_id, None)
    if storage is not None:
        window._point_edit_storage[new_id] = storage
