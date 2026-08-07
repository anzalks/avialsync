"""Wall-clock and layout evidence an Open Ephys recording carries outside neo.

Sample reading is neo's job and stays there — this module never opens
``continuous.dat`` and never names a channel.  What it covers is the part neo
does not model: where a recording sits inside a record-node tree, and how the
acquisition clock relates to wall-clock time.

``timestamps.npy`` is a free-running acquisition clock, not a UTC epoch, and neo
reports ``t_start`` on that same clock.  The only absolute instant an Open Ephys
recording contains is the first line of ``sync_messages.txt``.  Pairing that with
the GUI's local-time session directory name is also the only in-band evidence of
which timezone the rig was in — which is what keeps every other clock in the
folder from having to be guessed at.

Reference: Open Ephys "Binary Format" (GUI v0.6+).
"""

from __future__ import annotations

import datetime
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

#: The file whose presence *defines* an Open Ephys recording directory.
MANIFEST_NAME = "structure.oebin"

#: Directory depth searched below a dropped path for :data:`MANIFEST_NAME`.
#: A record node nests ``<session>/Record Node N/experimentN/recordingN``, so a
#: folder holding both the node tree and its camera media sits four levels above
#: the manifest.  Five allows one enclosing folder above that.
MAX_SEARCH_DEPTH = 5

#: Upper bound on directories visited by :func:`find_recordings`.  This runs from
#: ``can_open`` for every dropped folder, and an unbounded walk of somebody's
#: home directory is a hang, not a scan.
MAX_SEARCH_DIRS = 4096

#: Open Ephys names its session directory in *local* time with this layout.
_RECORD_DIR_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")

#: ``Software Time (milliseconds since midnight Jan 1st 1970 UTC): 1782053697004``
_SOFTWARE_TIME_PATTERN = re.compile(r"Software Time[^:]*:\s*(\d+)")

#: Real UTC offsets are whole quarter-hours.  Snapping to that grid turns a
#: second-resolution directory name into an exact zone offset.
_UTC_OFFSET_GRID_SECONDS = 900

#: How far the derived offset may sit from the quarter-hour grid before the
#: evidence is rejected as coincidence rather than a timezone.
_UTC_OFFSET_TOLERANCE_SECONDS = 120.0


def is_recording_dir(path: Path) -> bool:
    """Return whether *path* is itself a recording directory."""
    return path.is_dir() and (path / MANIFEST_NAME).is_file()


def find_recordings(
    root: Path,
    max_depth: int = MAX_SEARCH_DEPTH,
    max_dirs: int = MAX_SEARCH_DIRS,
) -> list[Path]:
    """Return every recording directory at or below *root*, in a stable order.

    A breadth-first walk bounded twice over: in depth, because a record-node tree
    has a known shape, and in directory count, because this runs on every dropped
    folder and somebody will eventually drop their home directory.

    Sidecar caches and dotted directories are skipped outright.  An
    ``.avialcache`` holds thousands of ``.npy`` files, so walking one costs more
    than the entire search it is part of.
    """
    if not root.is_dir():
        return []

    found: list[Path] = []
    queue: list[tuple[Path, int]] = [(root, 0)]
    visited = 0

    while queue and visited < max_dirs:
        current, depth = queue.pop(0)
        visited += 1

        if (current / MANIFEST_NAME).is_file():
            # A recording never contains another recording, so stop descending.
            found.append(current)
            continue
        if depth >= max_depth:
            continue

        try:
            children = sorted(child for child in current.iterdir() if child.is_dir())
        except OSError as error:
            logger.debug("Skipping unreadable directory %s: %s", current, error)
            continue
        for child in children:
            if child.name.startswith(".") or child.name.endswith(".avialcache"):
                continue
            queue.append((child, depth + 1))

    if visited >= max_dirs:
        logger.info(
            "Open Ephys search under %s stopped after %d directories; "
            "deeper recordings are not listed.",
            root,
            max_dirs,
        )
    return found


def stream_folder_names(recording: Path) -> list[str]:
    """Return the continuous-stream directory names the manifest declares.

    Each stream owns a directory, and pointing a source at its *own* directory is
    what lets one recording contribute several independently cached sources: a
    sidecar cache is named after its source path, so three sources sharing the
    recording directory would overwrite one another's cache in turn.

    The names come from the manifest rather than from neo's stream names, which
    are decorated with the record node they came through.
    """
    manifest = recording / MANIFEST_NAME
    try:
        declared = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Cannot read Open Ephys manifest %s", manifest, exc_info=True)
        return []
    if not isinstance(declared, dict):
        return []

    names: list[str] = []
    for entry in declared.get("continuous", []) or []:
        if not isinstance(entry, dict):
            continue
        folder = str(entry.get("folder_name", "")).rstrip("/")
        if folder:
            names.append(folder)
    return names


def parse_software_epoch(recording: Path) -> float | None:
    """Return the UTC epoch the GUI wrote at record start, or ``None``.

    The first line of ``sync_messages.txt`` is milliseconds since the epoch, and
    it is the only absolute instant in the format.  A recording without it is not
    broken — it simply declares no wall clock, and the session then stays on
    relative time rather than inventing one.
    """
    sync_messages = recording / "sync_messages.txt"
    try:
        text = sync_messages.read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.debug("No Open Ephys sync messages at %s", sync_messages)
        return None
    match = _SOFTWARE_TIME_PATTERN.search(text)
    if match is None:
        logger.info("Open Ephys sync messages at %s declare no software time.", sync_messages)
        return None
    return int(match.group(1)) / 1000.0


def anchor_epoch(software_epoch: float | None, first_sample_time: float | None) -> float:
    """Return the UTC epoch that acquisition-clock zero corresponds to.

    Master time stays the recording's own clock, untouched, so raw source
    timestamps survive into the session exactly as recorded.  This anchor is what
    turns them into readable wall clock: the GUI's software time is the instant
    the first sample was taken, so clock zero is that epoch minus that sample's
    timestamp.

    Returns ``0.0`` when the recording declares no absolute instant, which
    ``SessionLayout`` reads as "these times stay relative".
    """
    if software_epoch is None or first_sample_time is None:
        return 0.0
    return float(software_epoch - first_sample_time)


def parse_record_dir_time(name: str) -> datetime.datetime | None:
    """Parse Open Ephys's ``YYYY-MM-DD_HH-MM-SS`` session directory name.

    The result is deliberately timezone-*naive*: the GUI writes local time here
    and records nothing about which zone that was.  Attaching a zone anywhere but
    :func:`utc_offset_seconds`, which has a second instant to check it against, is
    the silent-UTC assumption behind one- and two-hour "corruption" reports.
    """
    if _RECORD_DIR_PATTERN.match(name) is None:
        return None
    try:
        return datetime.datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")
    except ValueError:  # pragma: no cover - the pattern already rejects these
        return None


def find_record_dir(recording: Path) -> Path | None:
    """Return the ancestor of *recording* named as a session directory."""
    for parent in recording.parents:
        if parse_record_dir_time(parent.name) is not None:
            return parent
    return None


def utc_offset_seconds(local_naive: datetime.datetime, utc_epoch: float) -> float | None:
    """Return the rig's UTC offset implied by one instant named two ways.

    Open Ephys writes the same recording start twice: as a local-time directory
    name, and as a UTC epoch in ``sync_messages.txt``.  Their difference *is* the
    acquisition machine's UTC offset, so the session carries its own timezone
    evidence and nothing has to be assumed about the machine reading it later.

    The difference is snapped to the quarter-hour grid every real zone lies on,
    and rejected when it does not land near one — a near-miss is a coincidence,
    and accepting it would silently shift every camera by an hour.
    """
    as_if_utc = local_naive.replace(tzinfo=datetime.UTC).timestamp()
    raw_offset = as_if_utc - utc_epoch
    snapped = round(raw_offset / _UTC_OFFSET_GRID_SECONDS) * _UTC_OFFSET_GRID_SECONDS
    if abs(raw_offset - snapped) > _UTC_OFFSET_TOLERANCE_SECONDS:
        logger.info(
            "Open Ephys local/UTC evidence differs by %.1f s, which is not a timezone offset; "
            "sources timed only by filename are left for the user to place.",
            raw_offset,
        )
        return None
    return float(snapped)


def recording_utc_offset(recording: Path) -> float | None:
    """Return the acquisition machine's UTC offset from the recording's own evidence."""
    software_epoch = parse_software_epoch(recording)
    if software_epoch is None:
        return None
    record_dir = find_record_dir(recording)
    if record_dir is None:
        return None
    local_naive = parse_record_dir_time(record_dir.name)
    if local_naive is None:
        return None
    return utc_offset_seconds(local_naive, software_epoch)
