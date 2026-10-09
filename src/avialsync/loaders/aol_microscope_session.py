"""Session scanner for AOL microscope trials and experiment folders.

A trial folder is one session: its ribbon scan tiled as the reconstructed tree,
and the trial's cameras -- each camera's frame 0 on the trial's trigger.

An experiment folder, or several trial folders dropped together, is one long
session joined back to back the way the controller's own analysis joins
trials (:func:`~avialsync.loaders.aol_microscope_trial.joined_starts`): one
ribbon source across every trial that shares the first trial's scan, and each
camera's per-trial recordings as one video
(:mod:`~avialsync.loaders.aol_camera_join`). The trials themselves are declared
as :attr:`~avialsync.core.source.SessionLayout.segments`, so where one ends and
the next begins stays visible on the joined timeline. A trial scanned
differently cannot be joined and is reported, not dropped silently (D-085).

The camera PC names its folders by its own clock, never by the controller's
trial, so cameras are associated by when they recorded
(:func:`~avialsync.loaders.aol_trial_matching.match_cameras`), whether they
were found beside the trials, dropped with them, or loaded before them
(D-208).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from avialsync.core.source import SessionItem, SessionLayout, SessionSource
from avialsync.loaders.aol_camera_join import (
    AOLJoinedCameraSource,
    camera_files,
    camera_folders_in,
    camera_roots,
    camera_segments,
    find_recordings,
    is_camera_folder,
    joined_source_id,
    match_tolerance,
    recording,
)
from avialsync.loaders.aol_camera_recordings import back_to_back, is_plain, trials_for
from avialsync.loaders.aol_microscope_trial import (
    MicroscopeTrial,
    experiment_trials,
    is_microscope_trial,
    joined_starts,
    read_trial,
)
from avialsync.loaders.aol_ribbon_scan import AOLRibbonScanSource
from avialsync.loaders.aol_trial_encoder import (
    ENCODER_LOG,
    AOLTrialEncoderSource,
    has_wheel_speed,
)
from avialsync.loaders.aol_trial_matching import (
    ZONE_NOTE,
    CameraMatch,
    CameraPairing,
    CameraRecording,
    match_cameras,
    pairing_note,
    unmatched_note,
)
from avialsync.loaders.aol_trial_stimulus import read_stimulus
from avialsync.loaders.video_standard import VideoStandardLoader


def _at(epoch: float, offset: float = 0.0) -> float | None:
    """A source epoch, or no claim when the trial has no ``STARTTIME``."""
    return epoch + offset if epoch > 0 else None


def _scan_signature(trial: MicroscopeTrial) -> tuple[Any, ...]:
    return (trial.roi_numbers, trial.channels, trial.lines, trial.width)


def _trial_lengths(trials: Sequence[MicroscopeTrial], starts: Sequence[float]) -> list[float]:
    """Each trial's slot on the joined timeline: up to the next trial's start."""
    return [
        (starts[index + 1] if index + 1 < len(starts) else starts[index] + trial.duration)
        - starts[index]
        for index, trial in enumerate(trials)
    ]


def _segments(trials: Sequence[MicroscopeTrial]) -> list[tuple[float, float, str]]:
    """The trials as named stretches of the joined timeline, in Unix-epoch seconds."""
    epoch = trials[0].start_epoch
    if epoch <= 0:
        return []
    starts = joined_starts(list(trials))
    lengths = _trial_lengths(trials, starts)
    return [
        (epoch + start, epoch + start + length, trial.folder.name)
        for trial, start, length in zip(trials, starts, lengths, strict=True)
    ]


def _ribbon_item(
    trials: list[MicroscopeTrial], path: Path, config: dict[str, object], name: str
) -> SessionItem:
    """The ribbon scan, every ROI tiled as the reconstructed tree."""
    first = trials[0]
    return SessionItem(
        path=path,
        loader=AOLRibbonScanSource,
        config=config,
        label=f"{name} — {len(first.roi_files)} ribbon ROIs, tiled",
        source_epoch=_at(first.start_epoch),
    )


def _context(trials: Sequence[MicroscopeTrial]) -> list[MicroscopeTrial]:
    """These trials and the rest of their experiments': the camera clock is agreed on all.

    One trial and its one camera agree with themselves whatever their clocks
    say; the experiment's other trials and recordings are what show a camera
    started early.
    """
    known = {trial.folder: trial for trial in trials}
    for experiment in dict.fromkeys(trial.folder.parent for trial in trials):
        for folder in experiment_trials(experiment):
            if folder not in known:
                known[folder] = read_trial(folder, verify=False)
    return list(known.values())


def _unmatched_during(
    match: CameraMatch, trials: Sequence[MicroscopeTrial], tolerance: float
) -> list[CameraRecording]:
    """Unmatched recordings that started while these trials were being recorded."""
    clock = match.clock_offset
    starts = [trial.start_epoch for trial in trials if trial.start_epoch > 0]
    if clock is None or not starts:
        return []
    first = min(starts) - tolerance
    last = max(t.start_epoch + t.duration for t in trials if t.start_epoch > 0) + tolerance
    return [c for c in match.unmatched if first <= c.local_epoch - clock <= last]


def match_for(
    trials: Sequence[MicroscopeTrial],
    dropped: Sequence[CameraRecording] | None = None,
    also: Sequence[CameraRecording] = (),
    roots: Sequence[Path] | None = None,
) -> tuple[list[CameraPairing], list[str]]:
    """The camera recordings that belong to *trials*, and what the user should be told.

    *dropped* are recordings the user chose; without them, recordings are looked
    for beside the trials (:func:`find_recordings`). *also* are recordings
    already on the timeline, matched so they are recognised rather than loaded
    twice. Recordings saved inside a trial folder always count.
    """
    roots = camera_roots() if roots is None else roots
    folders = [trial.folder for trial in trials]
    if dropped is None:
        found = find_recordings(folders, roots)
    else:
        found = list(dropped) + [r for f in folders if (r := recording(f)) is not None]
    seen = {r.folder for r in found}
    found += [r for r in also if r.folder not in seen]
    tolerance = match_tolerance()
    match = match_cameras(_context(trials), found, tolerance)
    wanted = set(folders)
    pairs = [pair for pair in match.pairs if pair.trial.folder in wanted]
    notes = [note for pair in pairs if (note := pairing_note(pair))]
    if dropped is not None:
        mine = {r.folder for r in dropped}
        left = [c for c in match.unmatched if c.folder in mine]
    else:
        left = _unmatched_during(match, trials, tolerance)
    if left and not match.zone_known and any(t.start_epoch > 0 for t in trials):
        notes.append(ZONE_NOTE)
    notes += [unmatched_note(camera) for camera in left]
    return pairs, notes


def _placement(trial: MicroscopeTrial, pair: CameraPairing) -> str:
    """Where a single trial's camera sits, in the words of its label."""
    if pair.offset:
        return f"{pair.offset:+.1f} s from {trial.folder.name} trigger, by its clock"
    return f"{trial.folder.name} trigger"


def camera_items(
    trials: Sequence[MicroscopeTrial],
    pairs: Sequence[CameraPairing],
    epoch: float | None,
    starts: Sequence[float] | None = None,
) -> tuple[list[SessionItem], list[str]]:
    """Each paired camera, placed on its trial's trigger -- or where its clock says.

    One trial: its recordings directly, frame 0 on the trial's ``STARTTIME``
    plus the pairing's offset. Several: one joined video per camera on the
    back-to-back timeline (*starts*, the joined starts, are derived when not
    given). *epoch* is the Unix time of the timeline's zero.
    """
    if not trials:
        return [], []
    if len(trials) == 1:
        items: list[SessionItem] = []
        for pair in pairs:
            for _camera, (video, timing) in sorted(camera_files(pair.camera.folder).items()):
                items.append(
                    SessionItem(
                        path=video,
                        loader=VideoStandardLoader,
                        config={
                            "frame_timestamps": str(timing),
                            "frame_timestamps_format": "aol_relative_ms",
                            "start_time": 0.0,
                        },
                        label=f"{video.name} — camera, {_placement(trials[0], pair)}",
                        source_epoch=None if epoch is None else epoch + pair.offset,
                    )
                )
        return items, []
    starts = list(starts) if starts is not None else joined_starts(list(trials))
    folders = [trial.folder for trial in trials]
    found, notes = camera_segments(
        pairs,
        dict(zip(folders, starts, strict=True)),
        dict(zip(folders, _trial_lengths(trials, starts), strict=True)),
    )
    joined = [
        SessionItem(
            path=joined_source_id(segments),
            loader=AOLJoinedCameraSource,
            config={"segments": [segment.to_config() for segment in segments]},
            label=f"{camera} — camera, {len(segments)} of {len(trials)} trials joined",
            source_epoch=epoch,
        )
        for camera, segments in sorted(found.items())
    ]
    return joined, notes


def _joinable(trials: list[MicroscopeTrial]) -> tuple[list[MicroscopeTrial], list[str]]:
    """The trials that share the first trial's scan, and a note for each that does not."""
    joined = [t for t in trials if _scan_signature(t) == _scan_signature(trials[0])]
    notes = [
        f"{trial.folder.name} was scanned differently and is not joined; "
        "open its folder on its own."
        for trial in trials
        if trial not in joined
    ]
    return joined, notes


def lay_out(
    trials: Sequence[MicroscopeTrial],
    path: Path,
    name: str,
    dropped: Sequence[CameraRecording] | None = None,
    loaded: Sequence[CameraRecording] = (),
    wheel: bool = True,
) -> tuple[SessionLayout, list[CameraPairing]]:
    """One trial, or several joined back to back, with their cameras and wheel speed.

    Cameras already *loaded* are matched but not laid out again. *wheel* off
    leaves out the controller's wheel speed, when an encoder log already gives
    it. Returns the pairings as well, so a caller can place the layout against
    those cameras.
    """
    ordered = sorted(trials, key=lambda trial: (trial.start_epoch, trial.folder.name))
    warnings = [f"{t.folder.name}: {w}" for t in ordered for w in t.warnings]
    if len(ordered) == 1:
        joined = ordered
        config: dict[str, object] = {"trial_folder": str(ordered[0].folder)}
        label = name
    else:
        joined, skipped = _joinable(ordered)
        warnings += skipped
        # Stored so placing the experiment later costs no file reads on the UI thread.
        config = {
            "trial_folders": [str(t.folder) for t in joined],
            "trial_starts": joined_starts(joined),
        }
        label = f"{name} — {len(joined)} trials"
    pairs, notes = match_for(joined, dropped, loaded)
    shown = {camera.folder for camera in loaded}
    epoch = _at(joined[0].start_epoch)
    cameras, more = camera_items(
        joined, [pair for pair in pairs if pair.camera.folder not in shown], epoch
    )
    layout = SessionLayout(
        items=[
            _ribbon_item(joined, path, config, label),
            *_wheel_item(joined, config, label, wheel),
            *cameras,
        ],
        session_epoch=epoch or 0.0,
        anchor_epoch=epoch or 0.0,
        segments=_segments(joined),
        warnings=warnings + notes + more,
    )
    return layout, pairs


def _trial_folders(config: dict[str, Any]) -> list[Path]:
    """The trial folders an AOL ribbon source was opened with, joined or single."""
    folders = config.get("trial_folders") or (
        [config["trial_folder"]] if config.get("trial_folder") else []
    )
    return [Path(str(folder)) for folder in folders]


def _wheel_item(
    trials: Sequence[MicroscopeTrial], config: dict[str, object], label: str, wheel: bool = True
) -> list[SessionItem]:
    """The signals the controller saved with these trials: wheel speed, stimulus TTL.

    One source, named by the first trial's ``params.mat`` which holds both; the
    config, the same as the ribbon scan's, says which trials it spans and where
    each starts. Wheel speed is left out when an encoder log already gives it.
    """
    speed = wheel and any(has_wheel_speed(trial.folder) for trial in trials)
    stimulus = any(read_stimulus(trial.folder) is not None for trial in trials)
    if not (speed or stimulus):
        return []
    parts = [name for name, has in (("wheel speed", speed), ("stimulus TTL", stimulus)) if has]
    return [
        SessionItem(
            path=trials[0].folder / "params.mat",
            loader=AOLTrialEncoderSource,
            config={**config, "wheel_speed": speed},
            label=f"{label} — {' and '.join(parts)}",
            source_epoch=_at(trials[0].start_epoch),
        )
    ]


def _loaded(
    loaded: Sequence[SessionItem],
) -> tuple[list[SessionItem], dict[Path, tuple[CameraRecording, float]]]:
    """What is already on the timeline: AOL imaging, and camera recordings with their epochs."""
    imaging = [
        item
        for item in loaded
        if item.source_epoch
        and (item.config.get("trial_folders") or item.config.get("trial_folder"))
    ]
    cameras: dict[Path, tuple[CameraRecording, float]] = {}
    for item in loaded:
        folder = item.path.parent
        if not item.source_epoch or folder in cameras or not is_camera_folder(folder):
            continue
        found = recording(folder)
        if found is not None:
            cameras[folder] = (found, float(item.source_epoch))
    return imaging, cameras


def _shifted(layout: SessionLayout, shift: float, note: str) -> SessionLayout:
    """The same layout with every wall-clock claim moved by *shift* seconds."""
    return replace(
        layout,
        items=[
            item
            if item.source_epoch is None
            else replace(item, source_epoch=item.source_epoch + shift)
            for item in layout.items
        ],
        session_epoch=layout.session_epoch + shift if layout.session_epoch else 0.0,
        anchor_epoch=layout.anchor_epoch + shift if layout.anchor_epoch else 0.0,
        segments=[(start + shift, end + shift, name) for start, end, name in layout.segments],
        warnings=[*layout.warnings, note],
    )


def _onto_cameras(
    layout: SessionLayout,
    pairs: Sequence[CameraPairing],
    cameras: dict[Path, tuple[CameraRecording, float]],
) -> SessionLayout:
    """Place trials dropped after their cameras where those cameras already are.

    The camera session is on the camera PC's clock and the trials on the
    controller's; the first loaded camera that matched a trial says how far
    apart the two are, so the trials land on its trigger rather than the zone
    and clock skew away from it.
    """
    loaded = [pair for pair in pairs if pair.camera.folder in cameras]
    if not loaded or not layout.session_epoch:
        return layout
    config = layout.items[0].config  # the ribbon scan: what was joined, and where
    folders = _trial_folders(config)
    starts = [float(start) for start in config.get("trial_starts") or [0.0]]
    pair = loaded[0]
    if pair.trial.folder not in folders:
        return layout
    trigger = layout.session_epoch + starts[folders.index(pair.trial.folder)]
    shift = cameras[pair.camera.folder][1] - (trigger + pair.offset)
    note = (
        f"Placed on the loaded cameras: {pair.camera.folder.name} matched trial "
        f"{pair.trial.folder.name}."
    )
    return _shifted(layout, shift, note)


def _cameras_onto(
    imaging: Sequence[SessionItem], dropped: Sequence[CameraRecording]
) -> SessionLayout:
    """Dropped cameras laid out against the AOL trials already on the timeline."""
    items: list[SessionItem] = []
    notes: list[str] = []
    joined = [item for item in imaging if item.config.get("trial_folders")]
    groups = joined[:1] or list(imaging)
    paired: set[Path] = set()
    for item in groups:
        folders = [
            Path(f) for f in item.config.get("trial_folders") or [item.config["trial_folder"]]
        ]
        trials = [read_trial(folder, verify=False) for folder in folders]
        starts = item.config.get("trial_starts")
        mine = {camera.folder for camera in dropped}
        # Recordings saved inside a loaded trial folder are on screen already.
        pairs = [pair for pair in match_for(trials, dropped)[0] if pair.camera.folder in mine]
        paired.update(pair.camera.folder for pair in pairs)
        notes += [note for pair in pairs if (note := pairing_note(pair))]
        found, more = camera_items(trials, pairs, item.source_epoch, starts)
        items += found
        notes += more
    notes += [unmatched_note(camera) for camera in dropped if camera.folder not in paired]
    return SessionLayout(items=items, warnings=notes)


def _dropped(paths: Sequence[Path]) -> tuple[list[Path], list[Path], list[Path], int]:
    """``(trial folders, camera folders, paths used, how many of them held trials)``."""
    trials: list[Path] = []
    cameras: list[Path] = []
    used: list[Path] = []
    holders = 0
    for path in paths:
        if is_microscope_trial(path):
            found = [path]
        elif found := experiment_trials(path):
            pass
        elif is_camera_folder(path):
            cameras.append(path)
            used.append(path)
            continue
        elif inside := camera_folders_in(path):
            cameras += inside
            used.append(path)
            continue
        else:
            continue
        trials += found
        used.append(path)
        holders += 1
    return list(dict.fromkeys(trials)), list(dict.fromkeys(cameras)), used, holders


class AOLMicroscopeTrialSource(SessionSource):
    """Load one controller trial, or a whole experiment back to back."""

    @classmethod
    def display_name(cls) -> str:
        return "AOL Microscope Trial"

    @classmethod
    def can_open(cls, path: Path) -> float:
        if is_microscope_trial(path):
            return 1.0
        return 0.8 if experiment_trials(path) else 0.0

    def scan(self, path: Path, registry: Any) -> SessionLayout:
        """Lay out one trial, or join an experiment's trials into one session."""
        if is_microscope_trial(path):
            # Names and timing only: pixels are verified by the source that reads them.
            return lay_out([read_trial(path, verify=False)], path, path.name)[0]
        folders = experiment_trials(path)
        if not folders:
            return SessionLayout()
        trials = [read_trial(folder, verify=False) for folder in folders]
        return lay_out(trials, path, path.name)[0]

    def scan_together(
        self, paths: Sequence[Path], loaded: Sequence[SessionItem], registry: Any
    ) -> tuple[SessionLayout, list[Path]] | None:
        """Trials and cameras dropped together, or onto each other, as one session.

        Several trials (folders or experiments) join back to back; cameras
        dropped with them are matched to them by clock rather than looked for.
        Cameras dropped onto loaded trials join those trials, and trials
        dropped onto loaded cameras are placed on them. A lone trial or
        experiment with nothing loaded is left to :meth:`scan`.
        """
        trial_folders, camera_folders, used, holders = _dropped(paths)
        imaging, cameras = _loaded(loaded)
        dropped = [r for f in camera_folders if (r := recording(f)) is not None]
        if trial_folders:
            if not (holders > 1 or camera_folders or (cameras and not imaging)):
                return None
            trials = [read_trial(folder, verify=False) for folder in trial_folders]
            path, name = _group_path(trial_folders, used)
            known = [found for found, _epoch in cameras.values()]
            # An open camera session's encoder log already plots the wheel speed.
            logged = any((folder / ENCODER_LOG).is_file() for folder in cameras)
            layout, pairs = lay_out(trials, path, name, dropped or None, known, not logged)
            if cameras and not imaging:
                layout = _onto_cameras(layout, pairs, cameras)
            return layout, used
        if dropped and imaging:
            return _cameras_onto(imaging, dropped), used
        if len(dropped) > 1 and not cameras:
            alone = _cameras_alone(dropped)
            return (alone, used) if alone is not None else None
        return None


def _cameras_alone(dropped: Sequence[CameraRecording]) -> SessionLayout | None:
    """Several camera recordings dropped with nothing open: their trials, or back to back.

    The camera PC records the same cameras for every trial, so these are one
    experiment's cameras. With its trials found they load as that experiment
    (the imaging is offered in the review, to keep or skip); without, each
    camera's recordings join one after another.
    """
    folders = trials_for(dropped)
    if folders:
        trials = [read_trial(folder, verify=False) for folder in folders]
        pairs, _notes = match_for(trials, dropped)
        paired = [pair.trial for pair in pairs if pair.camera in dropped]
        if paired:
            chosen = [trial.folder for trial in paired]
            path, name = _group_path(chosen, chosen)
            layout = lay_out(paired, path, name, dropped)[0]
            note = (
                f"Found {len(paired)} microscope trials for these cameras in "
                f"{chosen[0].parent}; skip the imaging in the review to load the cameras alone."
            )
            return replace(layout, warnings=[*layout.warnings, note])
    if all(is_plain(recording.folder) for recording in dropped):
        return back_to_back(dropped)
    return None


def _group_path(trial_folders: Sequence[Path], used: Sequence[Path]) -> tuple[Path, str]:
    """The source id and name of dropped trials: their experiment when they are all of it."""
    experiment = trial_folders[0].parent
    if len(trial_folders) == 1:
        return trial_folders[0], trial_folders[0].name
    if set(experiment_trials(experiment)) == set(trial_folders):
        return experiment, experiment.name
    return trial_folders[0], f"{experiment.name} (chosen trials)"
