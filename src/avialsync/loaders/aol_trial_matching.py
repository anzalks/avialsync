"""Clock evidence and unambiguous camera-to-trial matching for AOL recordings."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from avialsync.loaders.aol_microscope_trial import MicroscopeTrial


@dataclass(frozen=True)
class TrialMatch:
    """A trial selected by camera wall-clock proximity, with its evidence."""

    trial: MicroscopeTrial
    camera_local_epoch: float
    controller_utc_offset_s: int
    residual_s: float


def derive_utc_offset(trials: list[MicroscopeTrial], day: dt.date) -> int | None:
    """Infer a shared 15-minute-zone offset from folder times and UTC STARTTIME."""
    offsets: set[int] = set()
    for trial in trials:
        if trial.start_epoch <= 0:
            continue
        try:
            hour, minute, second = (int(part) for part in trial.folder.name.split("-"))
            local_clock = dt.datetime.combine(day, dt.time(hour, minute, second), tzinfo=dt.UTC)
        except (ValueError, OverflowError):
            continue
        delta = local_clock.timestamp() - trial.start_epoch
        offsets.add(round(delta / 900.0) * 900)
    return next(iter(offsets)) if len(offsets) == 1 else None


def match_trial(
    trials: list[MicroscopeTrial],
    camera_local_epoch: float,
    utc_offset_s: int,
    tolerance_s: float = 10.0,
) -> TrialMatch | None:
    """Match containment first, else one nearest STARTTIME inside the tolerance."""
    camera_utc = camera_local_epoch - utc_offset_s
    containing = [
        trial
        for trial in trials
        if trial.start_epoch <= camera_utc <= trial.start_epoch + trial.duration
    ]
    if len(containing) == 1:
        trial = containing[0]
        return TrialMatch(trial, camera_local_epoch, utc_offset_s, camera_utc - trial.start_epoch)
    if len(containing) > 1:
        return None
    candidates = sorted(
        ((abs(camera_utc - trial.start_epoch), trial) for trial in trials),
        key=lambda item: item[0],
    )
    if not candidates or candidates[0][0] > tolerance_s:
        return None
    if len(candidates) > 1 and candidates[1][0] <= tolerance_s:
        return None
    trial = candidates[0][1]
    return TrialMatch(trial, camera_local_epoch, utc_offset_s, camera_utc - trial.start_epoch)


def day_directory(saved_root: Path, camera_local_epoch: float) -> Path:
    """The one dated acquisition folder represented by a camera stamp."""
    day = dt.datetime.fromtimestamp(camera_local_epoch, tz=dt.UTC).date()
    return saved_root / day.isoformat()


# ── Many camera recordings against many trials ──────────────────────────────

#: How far a camera's first-frame stamp may sit from the session's agreed
#: camera clock and still count as starting on its trial's trigger. The stamps
#: are written by software on the camera PC: across one real experiment the
#: cameras that did start on their trial's trigger read 0.50 to 0.78 s after it,
#: so a whole second is jitter, not evidence of a different start.
TRIGGER_JITTER_S = 1.0

_STAMP_FORMAT = "%d-%m-%Y;%H:%M:%S.%f"


def first_frame_stamp(timing: Path) -> float | None:
    """The first frame's wall-clock stamp in a ``*-relative times.txt`` file.

    The camera PC writes its local clock without a zone; like the camera
    session (D-202) it is read as if it were UTC, and the controller's zone is
    derived separately from its folder names.
    """
    try:
        with timing.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                fields = line.split()
                if len(fields) < 3:
                    continue
                stamp = dt.datetime.strptime(fields[2], _STAMP_FORMAT)
                return stamp.replace(tzinfo=dt.UTC).timestamp()
    except (OSError, ValueError):
        return None
    return None


@dataclass(frozen=True)
class CameraRecording:
    """One trial's worth of camera files, as the camera PC saved them."""

    folder: Path
    local_epoch: float  # the cameras' shared first frame, local clock read as UTC


@dataclass(frozen=True)
class CameraPairing:
    """A camera recording associated with a trial, and the evidence for it."""

    camera: CameraRecording
    trial: MicroscopeTrial
    #: Seconds from the trial's trigger to the cameras' first frame. ``0.0``
    #: when they started on the trigger, as an externally triggered camera does.
    offset: float
    #: ``"folder"`` (saved in the trial folder), ``"name"`` (named after the
    #: trial), ``"clock"`` (started within the tolerance of the trial on the
    #: session's camera clock) or ``"order"`` (the only recording left between
    #: two clock matches, for the only trial left between them).
    evidence: str
    #: Camera start minus trial start once the session's clock offset is removed.
    residual: float = 0.0


@dataclass(frozen=True)
class CameraMatch:
    """Every pairing for a set of trials, and what could not be paired."""

    pairs: tuple[CameraPairing, ...]
    unmatched: tuple[CameraRecording, ...]
    #: Camera clock minus controller UTC, zone included; ``None`` when unknown.
    clock_offset: float | None
    #: Whether the trials' folder names gave the controller's zone at all.
    zone_known: bool


def pairing_note(pair: CameraPairing) -> str | None:
    """What the user should know about a pairing, or nothing for an ordinary one."""
    camera, trial = pair.camera.folder.name, pair.trial.folder.name
    if pair.evidence == "order":
        placed = "; placed by their own clock" if pair.offset else ""
        return (
            f"{camera} matched trial {trial} by order only: its cameras started "
            f"{pair.residual:+.1f} s from the trigger{placed}."
        )
    if pair.offset:
        return (
            f"{camera} did not start on trial {trial}'s trigger ({pair.offset:+.1f} s); "
            "placed by its own clock."
        )
    return None


def unmatched_note(camera: CameraRecording) -> str:
    """Why a camera recording was left out."""
    return (
        f"{camera.folder.name}: no trial was recording when these cameras started; "
        "not joined. Open the folder on its own to view it."
    )


ZONE_NOTE = (
    "The trial folder names and their STARTTIME disagree on the time zone, "
    "so cameras could not be matched by their clock."
)


def _consensus(residuals: list[tuple[int, float]]) -> float | None:
    """The residual most cameras agree on, to within the trigger jitter.

    Each camera counts once per cluster. A tie goes to the cluster nearest
    zero: with one camera and one trial, that pair is the evidence there is.
    """
    best: tuple[int, float, list[float]] | None = None
    for _camera, centre in residuals:
        near = [r for _c, r in residuals if abs(r - centre) <= TRIGGER_JITTER_S]
        cameras = len({c for c, r in residuals if abs(r - centre) <= TRIGGER_JITTER_S})
        key = (cameras, -abs(centre), near)
        if best is None or key[:2] > best[:2]:
            best = key
    if best is None:
        return None
    near = sorted(best[2])
    return float(near[len(near) // 2])


def _clock_offset(trials: list[MicroscopeTrial], cameras: list[CameraRecording]) -> float | None:
    """Camera-clock minus controller-UTC, to the zone: from the trials' folder names."""
    if not trials or not cameras:
        return None
    stamps = [c.local_epoch for c in cameras if c.local_epoch > 0]
    if not stamps:
        return None
    day = dt.datetime.fromtimestamp(min(stamps), tz=dt.UTC).date()
    return derive_utc_offset(trials, day)


def _in_order(pairs: list[CameraPairing], camera: CameraRecording, trial: MicroscopeTrial) -> bool:
    """Whether pairing these keeps cameras and trials in the same time order."""
    return all(
        (camera.local_epoch < p.camera.local_epoch) == (trial.start_epoch < p.trial.start_epoch)
        for p in _clocked(pairs)
    )


def _clocked(pairs: list[CameraPairing]) -> list[CameraPairing]:
    """The pairs whose camera and trial both carry a wall-clock start."""
    return [p for p in pairs if p.camera.local_epoch > 0 and p.trial.start_epoch > 0]


def match_cameras(
    trials: list[MicroscopeTrial],
    cameras: list[CameraRecording],
    tolerance_s: float = 10.0,
) -> CameraMatch:
    """Associate camera recordings with trials: folder, then name, then clock, then order.

    Folder names never have to agree. The camera and controller PCs clocks are
    compared once for the whole set -- the zone from the trials' folder names,
    the remaining offset as the value most recordings agree on -- so one camera
    that started early cannot drag the others. Pairs are one to one and keep
    both sides in time order. A recording whose clock puts it more than
    :data:`TRIGGER_JITTER_S` from its trial's trigger is placed where its clock
    says, and said so; nothing is moved onto a trigger it did not record.
    """
    pairs: list[CameraPairing] = []
    by_folder = {trial.folder: trial for trial in trials}
    by_name = {trial.folder.name: trial for trial in trials}
    for camera in cameras:
        trial = by_folder.get(camera.folder)
        evidence = "folder"
        if trial is None:
            trial, evidence = by_name.get(camera.folder.name), "name"
        if trial is not None and all(p.trial is not trial for p in pairs):
            pairs.append(CameraPairing(camera, trial, 0.0, evidence))

    zone = _clock_offset([t for t in trials if t.start_epoch > 0], cameras)
    skew: float | None = None
    residual: dict[tuple[int, int], float] = {}
    left = [c for c in cameras if c.local_epoch > 0 and all(p.camera is not c for p in pairs)]
    open_trials = [t for t in trials if t.start_epoch > 0 and all(p.trial is not t for p in pairs)]
    if zone is not None and left and open_trials:
        residual = {
            (i, j): camera.local_epoch - zone - trial.start_epoch
            for i, camera in enumerate(left)
            for j, trial in enumerate(open_trials)
        }
        skew = _consensus([(i, r) for (i, _j), r in residual.items() if abs(r) <= tolerance_s])
    if zone is not None and skew is not None:
        candidates = sorted(
            (abs(r - skew), i, j) for (i, j), r in residual.items() if abs(r - skew) <= tolerance_s
        )
        for _distance, i, j in candidates:
            camera, trial = left[i], open_trials[j]
            taken = any(p.camera is camera or p.trial is trial for p in pairs)
            if not taken and _in_order(pairs, camera, trial):
                pairs.append(_placed(camera, trial, residual[(i, j)] - skew, "clock"))
        pairs += _by_order(pairs, left, open_trials, zone, skew)

    unmatched = tuple(c for c in cameras if all(p.camera is not c for p in pairs))
    pairs.sort(key=lambda p: (p.trial.start_epoch, p.trial.folder.name))
    clock = None if zone is None or skew is None else zone + skew
    return CameraMatch(tuple(pairs), unmatched, clock, zone is not None)


def _placed(
    camera: CameraRecording, trial: MicroscopeTrial, deviation: float, evidence: str
) -> CameraPairing:
    """Within the jitter the camera started on the trigger; beyond it, where its clock says."""
    offset = deviation if abs(deviation) > TRIGGER_JITTER_S else 0.0
    return CameraPairing(camera, trial, offset, evidence, deviation)


def _by_order(
    pairs: list[CameraPairing],
    cameras: list[CameraRecording],
    trials: list[MicroscopeTrial],
    zone: float,
    skew: float,
) -> list[CameraPairing]:
    """Pair the one recording left between two matches with the one trial left there."""
    anchors = sorted(_clocked(pairs), key=lambda p: p.trial.start_epoch)
    found: list[CameraPairing] = []
    for before, after in zip(anchors, anchors[1:], strict=False):
        between_cameras = [
            c
            for c in cameras
            if before.camera.local_epoch < c.local_epoch < after.camera.local_epoch
            and all(p.camera is not c for p in pairs)
        ]
        between_trials = [
            t
            for t in trials
            if before.trial.start_epoch < t.start_epoch < after.trial.start_epoch
            and all(p.trial is not t for p in pairs)
        ]
        if len(between_cameras) == 1 and len(between_trials) == 1:
            camera, trial = between_cameras[0], between_trials[0]
            deviation = camera.local_epoch - zone - skew - trial.start_epoch
            found.append(_placed(camera, trial, deviation, "order"))
    return found
