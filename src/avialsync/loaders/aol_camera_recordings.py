"""AOL camera recordings dropped without their microscope trials.

The camera PC saves a fixed set of cameras once per trial, so several of its
recording folders are one experiment's cameras, not as many separate sessions.
When the controller's trials can be found -- beside the camera tree, mirroring
``<date>/<experiment>``, or under the microscope saved-data folder setting --
the drop is laid out as those trials with their cameras. When they
cannot, each camera's recordings are joined into one video, each recording at
its own first-frame stamp on the camera PC's clock, the time between
recordings a gap (D-217).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from avialsync.core.source import SessionItem, SessionLayout
from avialsync.core.trials import Part, Placement, place
from avialsync.loaders.aol_camera_join import (
    AOLJoinedCameraSource,
    CameraSegment,
    camera_files,
    joined_source_id,
    recording_length,
    trial_roots,
)
from avialsync.loaders.aol_microscope_trial import experiment_trials
from avialsync.loaders.aol_trial_matching import CameraRecording

#: What a camera PC recording folder holds besides its videos and their frame times.
_CAMERA_EXTRAS = frozenset({"camera_module_timing_report.mat"})


def _places(experiment: Path, roots: Sequence[Path]) -> list[Path]:
    """Where a camera experiment's microscope experiment may be.

    ``videos/<date>/<experiment>`` beside ``<date>/<experiment>``, or beside
    another mirror of it, and ``<date>/<experiment>`` under each saved-data root.
    """
    date = experiment.parent
    base = date.parent.parent
    places = [base / date.name / experiment.name]
    try:
        siblings = sorted(child for child in base.iterdir() if child.is_dir())
    except OSError:
        siblings = []
    places += [sibling / date.name / experiment.name for sibling in siblings]
    places += [root / date.name / experiment.name for root in roots]
    return [place for place in dict.fromkeys(places) if place != experiment]


def trials_for(
    recordings: Sequence[CameraRecording], roots: Sequence[Path] | None = None
) -> list[Path]:
    """The microscope trial folders that may hold these recordings' trials."""
    roots = trial_roots() if roots is None else roots
    found: dict[Path, None] = {}
    for experiment in dict.fromkeys(recording.folder.parent for recording in recordings):
        for where in _places(experiment, roots):
            found.update(dict.fromkeys(experiment_trials(where)))
    return list(found)


def is_plain(folder: Path) -> bool:
    """Whether *folder* holds only camera videos, their frame times and timing report.

    Anything else -- pose, extracted metrics, an encoder log -- is a camera
    session the AOL session scanner lays out, and is left to it.
    """
    owned = set(_CAMERA_EXTRAS)
    for video, timing in camera_files(folder).values():
        owned.update((video.name, timing.name))
    try:
        return all(child.name in owned or child.name.startswith(".") for child in folder.iterdir())
    except OSError:
        return False


def by_clock(recordings: Sequence[CameraRecording]) -> SessionLayout:
    """Each camera's recordings as one video, each recording where the camera clock puts it.

    Recordings without a first-frame stamp cannot be placed on that clock;
    when none has one, they play back to back and the layout says so.
    """
    ordered = sorted(
        recordings, key=lambda recording: (recording.local_epoch, recording.folder.name)
    )
    lengths = [recording_length(recording.folder) for recording in ordered]
    parts = [
        Part(recording.folder.name, length, recording.local_epoch)
        for recording, length in zip(ordered, lengths, strict=True)
    ]
    plan = place(parts)
    notes = list(plan.warnings)
    if not plan.kept:
        plan = place(parts, Placement.BACK_TO_BACK)
        notes = [
            "These recordings carry no frame stamps, so the time between them is not "
            "known: they play back to back."
        ]
    joined: dict[str, list[CameraSegment]] = {}
    for index, start, length in zip(plan.kept, plan.starts, plan.lengths, strict=True):
        for camera, (video, timing) in camera_files(ordered[index].folder).items():
            joined.setdefault(camera, []).append(CameraSegment(video, timing, start, length))
    epoch = plan.epoch
    items = [
        SessionItem(
            path=joined_source_id(pieces),
            loader=AOLJoinedCameraSource,
            config={"segments": [piece.to_config() for piece in pieces]},
            label=f"{camera} — camera, {len(pieces)} of {len(ordered)} recordings joined",
            source_epoch=epoch if epoch > 0 else None,
        )
        for camera, pieces in sorted(joined.items())
    ]
    return SessionLayout(
        items=items,
        session_epoch=epoch,
        anchor_epoch=epoch,
        segments=plan.segments(),
        warnings=[
            "No microscope trials were found for these recordings, so they are joined on "
            "the camera clock alone. Set Preferences → Lab Data → AOL microscope saved-data "
            "folder, or drop the trials with them, to pair them with their trials.",
            *notes,
        ],
    )
