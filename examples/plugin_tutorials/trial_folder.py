"""Tutorial plugin: a recording folder made of trials (docs/plugins/folder-of-trials.md).

The rig this reads, which you replace with yours::

    my_recording/
        rig.json                 marks the folder as this rig's recording
        trial_001/
            trial.json           {"start_unix": 1700000000.0, "duration_s": 10.0}
            daq.csv              time (s from the trial's start), cam_strobe, wheel
            camera.mp4           optional; one per trial
        trial_002/ ...

Copy this file into ~/.avialsync/plugins/ (File → Plugins → Open Plugins
Folder), pick File → Plugins → Reload Plugins, and drop ``my_recording`` on the
window. ``avialsync plugin-check my_recording`` checks it without a window.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from avialsync.core.settings_schema import Setting
from avialsync.core.source import ChannelInfo, SessionItem, SessionLayout, SessionSource
from avialsync.core.trials import Part, place
from avialsync.loaders.csv_loader import CSVLoader
from avialsync.loaders.joined_parts import (
    JOINED_PARTS,
    JoinedTimeSeriesSource,
    JoinedVideoSource,
    loader_name,
)


class RigDaqLoader(CSVLoader):
    """The rig's DAQ file: a CSV whose ``cam_strobe`` column is the camera's strobe."""

    @classmethod
    def display_name(cls) -> str:
        return "DAQ Channels"

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 0.0  # only ever declared by the session below

    def channels(self) -> list[ChannelInfo]:
        # One pulse per exposure the camera took, so the sync wizard may pair
        # pulse i with frame i. Say so only when it is how your rig is wired.
        return [
            replace(channel, trigger="frame_strobe", trigger_for="camera.mp4")
            if channel.name == "cam_strobe"
            else channel
            for channel in super().channels()
        ]


class TrialFolderSession(SessionSource):
    """Lay out a folder of trials: every trial at its recorded start, gaps kept."""

    #: Which folders are trials, chosen in Preferences → Trial Folder Rig.
    _trial_pattern = "trial_*"

    @classmethod
    def display_name(cls) -> str:
        return "Trial Folder Rig"

    @classmethod
    def plugin_id(cls) -> str:
        return "trial_folder_rig"

    @classmethod
    def settings(cls) -> tuple[Setting, ...]:
        return (
            Setting(
                key="trial_pattern",
                label="Trial folder pattern",
                group="",  # empty: the plugin's own tab
                default="trial_*",
                kind=str,
                help_text="Folders matching this pattern are the recording's trials.",
            ),
        )

    @classmethod
    def configure(cls, values: dict[str, Any]) -> None:
        cls._trial_pattern = str(values.get("trial_pattern") or "trial_*")

    @classmethod
    def can_open(cls, path: Path) -> float:
        # Cheap: asked about every dropped path before anything is read.
        return 1.0 if (path / "rig.json").is_file() else 0.0

    def scan(self, path: Path, registry: Any) -> SessionLayout:
        trials = sorted(p for p in path.glob(self._trial_pattern) if p.is_dir())
        parts, notes = [], []
        for trial in trials:
            try:
                info = json.loads((trial / "trial.json").read_text(encoding="utf-8"))
                parts.append(Part(trial.name, float(info["duration_s"]), info.get("start_unix")))
            except (OSError, ValueError, KeyError) as error:
                notes.append(f"{trial.name} could not be read — {error}")
        # Each trial at its recorded start; a trial without one, or overlapping
        # the one before, is left out and named in plan.warnings.
        plan = place(parts)
        kept = [trials[index] for index in plan.kept]
        epoch = plan.epoch  # the first kept trial's start, as Unix time
        items = []
        daq = [
            {"path": str(trial / "daq.csv"), "start": start}
            for trial, start in zip(kept, plan.starts, strict=True)
            if (trial / "daq.csv").is_file()
        ]
        if daq:
            items.append(
                SessionItem(
                    Path(daq[0]["path"]),
                    JoinedTimeSeriesSource,
                    {"parts": daq, "part_loader": loader_name(RigDaqLoader)},
                    label=f"DAQ, {len(daq)} trials joined",
                    source_epoch=epoch,
                )
            )
        videos = [
            {"path": str(trial / "camera.mp4"), "start": start}
            for trial, start in zip(kept, plan.starts, strict=True)
            if (trial / "camera.mp4").is_file()
        ]
        if videos:
            items.append(
                SessionItem(
                    Path(videos[0]["path"]) / JOINED_PARTS,
                    JoinedVideoSource,
                    {"parts": videos},
                    label=f"Camera, {len(videos)} trials joined",
                    kind="Video",
                    source_epoch=epoch,
                )
            )
        return SessionLayout(
            items=items,
            session_epoch=epoch,
            anchor_epoch=epoch,
            segments=plan.segments(),
            warnings=[*notes, *plan.warnings],
        )
