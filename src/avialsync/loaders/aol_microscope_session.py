"""Session scanner for AOL microscope trials and experiment folders.

A trial folder is one session: its ribbon scan tiled as the reconstructed tree,
and the trial's cameras when they were saved with it -- each camera's frame 0
on the trial's trigger.

An experiment folder is one long session, joined back to back the way the
controller's own analysis joins trials
(:func:`~avialsync.loaders.aol_microscope_trial.joined_starts`): one ribbon
source across every trial that shares the first trial's scan, and each
camera's per-trial recordings as one video
(:mod:`~avialsync.loaders.aol_camera_join`). The trials themselves are declared
as :attr:`~avialsync.core.source.SessionLayout.segments`, so where one ends and
the next begins stays visible on the joined timeline. A trial scanned
differently cannot be joined and is reported, not dropped silently (D-085).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from avialsync.core.source import SessionItem, SessionLayout, SessionSource
from avialsync.loaders.aol_camera_join import (
    AOLJoinedCameraSource,
    camera_roots,
    camera_segments,
    joined_source_id,
)
from avialsync.loaders.aol_microscope_trial import (
    MicroscopeTrial,
    experiment_trials,
    is_microscope_trial,
    joined_starts,
    read_trial,
)
from avialsync.loaders.aol_ribbon_scan import AOLRibbonScanSource
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


def camera_items(
    trials: Sequence[MicroscopeTrial], roots: Sequence[Path] | None = None
) -> list[SessionItem]:
    """Each camera found for these trials, placed on the trials' trigger.

    One trial: its recordings directly, frame 0 on the trial's ``STARTTIME``.
    Several: one joined video per camera on the back-to-back timeline. Cameras
    are looked for in the trial folders and under the configured camera data
    folders (:func:`~avialsync.loaders.aol_camera_join.camera_roots`).
    """
    roots = camera_roots() if roots is None else roots
    if not trials:
        return []
    starts = joined_starts(list(trials))
    found = camera_segments(
        [t.folder for t in trials], starts, _trial_lengths(trials, starts), roots
    )
    epoch = _at(trials[0].start_epoch)
    items: list[SessionItem] = []
    for camera, segments in sorted(found.items()):
        if len(trials) == 1:
            segment = segments[0]
            items.append(
                SessionItem(
                    path=segment.video,
                    loader=VideoStandardLoader,
                    config={
                        "frame_timestamps": str(segment.timing),
                        "frame_timestamps_format": "aol_relative_ms",
                        "start_time": 0.0,
                    },
                    label=f"{segment.video.name} — camera, {trials[0].folder.name} trigger",
                    source_epoch=epoch,
                )
            )
            continue
        items.append(
            SessionItem(
                path=joined_source_id(segments),
                loader=AOLJoinedCameraSource,
                config={"segments": [segment.to_config() for segment in segments]},
                label=f"{camera} — camera, {len(segments)} of {len(trials)} trials joined",
                source_epoch=epoch,
            )
        )
    return items


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
            trial = read_trial(path, verify=False)
            items = [_ribbon_item([trial], path, {"trial_folder": str(path)}, path.name)]
            items += camera_items([trial])
            epoch = trial.start_epoch if trial.start_epoch > 0 else 0.0
            return SessionLayout(
                items=items,
                session_epoch=epoch,
                anchor_epoch=epoch,
                segments=_segments([trial]),
                warnings=[f"{path.name}: {warning}" for warning in trial.warnings],
            )
        folders = experiment_trials(path)
        if not folders:
            return SessionLayout()
        trials = sorted(
            (read_trial(folder, verify=False) for folder in folders),
            key=lambda trial: (trial.start_epoch, trial.folder.name),
        )
        warnings = [f"{t.folder.name}: {w}" for t in trials for w in t.warnings]
        joined = [t for t in trials if _scan_signature(t) == _scan_signature(trials[0])]
        for trial in trials:
            if trial not in joined:
                warnings.append(
                    f"{trial.folder.name} was scanned differently and is not joined; "
                    "open its folder on its own."
                )
        # Stored so placing the experiment later costs no file reads on the UI thread.
        config: dict[str, object] = {
            "trial_folders": [str(t.folder) for t in joined],
            "trial_starts": joined_starts(joined),
        }
        items = [_ribbon_item(joined, path, config, f"{path.name} — {len(joined)} trials")]
        items += camera_items(joined)
        epoch = joined[0].start_epoch if joined[0].start_epoch > 0 else 0.0
        return SessionLayout(
            items=items,
            session_epoch=epoch,
            anchor_epoch=epoch,
            segments=_segments(joined),
            warnings=warnings,
        )
