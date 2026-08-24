"""Wall-clock and layout evidence an Open Ephys recording carries outside neo.

Sample reading is neo's job and stays there — this module never opens
``continuous.dat`` and never names a channel.  What it covers is the part neo
does not model: where a recording sits inside a record-node tree, and how the
acquisition clock relates to wall-clock time.

It also reads the recording's *event prose*, which neo does model — badly enough
that we do not use its answer.  neo picks one seconds-or-sample-numbers rule for
the whole recording and lets the last event stream read set it, and it raises
mid-header on shapes the format permits, which loses the entire recording rather
than one annotation.  :func:`read_messages` and :func:`event_stream_defects`
exist for those two reasons and no others (D-085).

``timestamps.npy`` is a free-running acquisition clock, not a UTC epoch, and neo
reports ``t_start`` on that same clock.  The only absolute instant an Open Ephys
recording contains is the first line of ``sync_messages.txt``.  Pairing that with
the GUI's local-time session directory name is also the only in-band evidence of
which timezone the rig was in — which is what keeps every other clock in the
folder from having to be guessed at.

Reference: Open Ephys "Binary Format" (GUI v0.6+).
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.messages import MAX_MESSAGES, Message, clean

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
    return [
        str(entry["folder_name"]).rstrip("/")
        for entry in _declared_entries(recording, "continuous")
    ]


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


# ── Event streams ───────────────────────────────────────────────────────

#: Files an Open Ephys event folder may carry its labels in, in the order neo
#: prefers them.  A folder with none of these has nothing to say, and neo raises
#: on it rather than skipping it.
_LABEL_FILE_NAMES = ("text.npy", "metadata.npy", "channels.npy", "states.npy")

#: The file whose presence means ``timestamps.npy`` is already in seconds.  Open
#: Ephys v0.6 moved sample numbers into their own file and rebased timestamps
#: onto seconds; before that, ``timestamps.npy`` held the sample numbers.
_SAMPLE_NUMBERS_NAME = "sample_numbers.npy"

_TIMESTAMPS_NAME = "timestamps.npy"
_TEXT_NAME = "text.npy"


@dataclasses.dataclass(frozen=True)
class EventStreamDefect:
    """A declared event stream that neo cannot read past.

    neo validates every event stream while parsing the *whole* recording's
    header, so one malformed annotation folder raises before any continuous
    stream is reached and the entire recording becomes unopenable.  Worse, the
    exception escapes neo's format sniffing, which then hands back a reader for
    some unrelated format entirely — so what reaches the user names neither this
    folder nor this problem.

    Naming both is what turns that into something a user can fix (D-085).
    """

    folder: str
    problem: str

    def __str__(self) -> str:
        return f"events/{self.folder}: {self.problem}"


def _read_manifest(recording: Path) -> dict[str, Any]:
    """Return the recording's parsed ``structure.oebin``, or an empty mapping."""
    manifest = recording / MANIFEST_NAME
    try:
        declared = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Cannot read Open Ephys manifest %s", manifest, exc_info=True)
        return {}
    return declared if isinstance(declared, dict) else {}


def _declared_entries(recording: Path, kind: str) -> list[dict[str, Any]]:
    """Return the manifest's ``continuous`` or ``events`` entries that name a folder."""
    entries: list[dict[str, Any]] = []
    for entry in _read_manifest(recording).get(kind, []) or []:
        if isinstance(entry, dict) and str(entry.get("folder_name", "")).strip():
            entries.append(entry)
    return entries


def _load_array(path: Path) -> Any | None:
    """Return the array at *path*, or ``None`` if it cannot be read as one.

    Memory-mapped, so checking a header costs no read.  ``allow_pickle`` stays
    off: an object-dtype array is not something an acquisition system writes,
    and honouring one would mean executing whatever sits in the data directory.
    """
    try:
        return np.load(path, mmap_mode="r")
    except Exception:  # noqa: BLE001 - an unreadable array is a defect to report, not a crash
        logger.debug("Open Ephys event array %s is unreadable.", path, exc_info=True)
        return None


def event_stream_defects(recording: Path) -> list[EventStreamDefect]:
    """Return every declared event stream neo would raise on, in manifest order.

    Empty for a healthy recording, and empty for a folder neo merely warns about
    and skips.  Only what is *fatal to the whole recording* is reported, because
    that is the difference between a note the user loses and a recording they
    cannot open at all.
    """
    defects: list[EventStreamDefect] = []
    for entry in _declared_entries(recording, "events"):
        folder = str(entry["folder_name"]).rstrip("/")
        directory = recording / "events" / folder
        if not directory.is_dir():
            # neo warns and skips a declared-but-absent folder; the recording
            # still opens, so this is not the fatal class being reported.
            continue
        if not (directory / _TIMESTAMPS_NAME).is_file():
            defects.append(EventStreamDefect(folder, f"no {_TIMESTAMPS_NAME}"))
            continue
        labels = [name for name in _LABEL_FILE_NAMES if (directory / name).is_file()]
        if not labels:
            expected = ", ".join(_LABEL_FILE_NAMES)
            defects.append(EventStreamDefect(folder, f"no labels — expected one of {expected}"))
            continue
        array = _load_array(directory / labels[0])
        if array is None:
            defects.append(EventStreamDefect(folder, f"{labels[0]} is not a readable .npy array"))
        elif array.dtype.kind == "U":
            # neo calls .decode() on every label whenever the dtype is textual,
            # but a "U" array already holds str.  The GUI writes "S"; a file
            # rewritten in Python is what produces this.
            defects.append(
                EventStreamDefect(
                    folder,
                    f"{labels[0]} holds unicode text; neo can only decode the byte "
                    "strings the Open Ephys GUI writes",
                )
            )
    return defects


def read_messages(recording: Path) -> list[Message]:
    """Return the recording's free-text annotations, read without neo.

    Read here rather than taken from neo's event channels because neo decides
    once, for the whole recording, whether event timestamps are seconds or
    sample numbers: the flag is overwritten by each stream in turn and the last
    one wins.  A recording whose annotation folder and TTL folder disagree gets
    *both* rescaled by whichever was read last, silently moving every message —
    and every TTL edge — by a factor of the sample rate.  Deciding per stream,
    from the file actually present in that folder, is why this exists (D-085).

    Times are on the recording's own acquisition clock, exactly like the samples.
    """
    found: list[Message] = []
    for entry in _declared_entries(recording, "events"):
        if len(found) >= MAX_MESSAGES:
            break
        folder = str(entry["folder_name"]).rstrip("/")
        directory = recording / "events" / folder
        text = _load_array(directory / _TEXT_NAME)
        times = _load_array(directory / _TIMESTAMPS_NAME)
        # Only a stream carrying prose is a message stream.  A TTL folder has
        # states and channels, which are already a plotted square wave.
        if text is None or times is None or len(text) == 0 or len(text) != len(times):
            continue
        seconds = _event_seconds(times, directory, entry)
        channel = str(entry.get("channel_name") or folder)
        for time, value in zip(seconds[:MAX_MESSAGES], text[:MAX_MESSAGES], strict=False):
            body = clean(_decode(value))
            if body:
                found.append(Message(text=body, time=float(time), channel=channel))
    return found


def _event_seconds(times: Any, directory: Path, entry: dict[str, Any]) -> Any:
    """Return *times* in seconds on the acquisition clock.

    Decided per stream, from the file present in *this* folder — see
    :func:`read_messages` for why that is deliberately not neo's answer.
    """
    values = np.asarray(times, dtype=np.float64)
    if (directory / _SAMPLE_NUMBERS_NAME).is_file():
        return values
    try:
        rate = float(entry.get("sample_rate") or 0.0)
    except (TypeError, ValueError):
        rate = 0.0
    if rate <= 0.0:
        logger.info(
            "Open Ephys event stream %s declares no usable sample rate; "
            "reading its timestamps as seconds.",
            directory.name,
        )
        return values
    return values / rate


def _decode(value: Any) -> str:
    """Return one label as text, whichever way the file spelled it."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
