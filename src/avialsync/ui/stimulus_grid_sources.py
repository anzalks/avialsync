"""What a stimulus grid can carry, read from the open session on the UI thread (D-210).

Snapshots, not live objects: each camera's mapping and levels, each imaging
stack's loader, timing and exactly how the viewer shows it, and each sensor
channel's worker-safe reader reference, grouped by the data source it came
from. Nothing here reads a file.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.stimulus_grid_imaging import GridImaging
from avialsync.engine.stimulus_grid_layout import GridLabels, GridVideo
from avialsync.ui.cvd import palette_for_surface
from avialsync.ui.i18n import tr
from avialsync.ui.stimulus_grid_dialog import StimulusChannelOption
from avialsync.ui.stimulus_grid_rows import (
    PictureRowOption,
    RowChoices,
    SensorGroupOption,
    StreamOption,
)

if TYPE_CHECKING:
    from avialsync.ui.main_window import MainWindow

#: The grid movie is drawn on a dark surface, so the palette is lifted for it.
_PALETTE = palette_for_surface(dark_surface=True)


def _source_label(window: MainWindow, source_id: str) -> str:
    """A data source as the session named it, else by its file."""
    return window.session_runtime.item_labels.get(source_id) or Path(source_id).name


def camera_rows(window: MainWindow) -> list[PictureRowOption]:
    """Every camera; the ones on screen ticked."""
    grid = window.video_grid
    shown = set(map(id, grid.visible_panes()))
    media = grid.media_path_for  # a proxy is what decodes (D-188)
    rows = []
    for path, pane in zip(grid.pane_paths(), grid.panes, strict=False):
        size = pane.video_size
        aspect = size[0] / size[1] if size and size[1] else 16 / 9
        video = GridVideo(Path(media(path)), Path(path).name, pane.time_map, pane.display_levels())
        rows.append(PictureRowOption(path, video.label, video, aspect, id(pane) in shown))
    return rows


def imaging_rows(window: MainWindow) -> list[PictureRowOption]:
    """Every imaging stack as the viewer shows it; the one in the viewer ticked."""
    pane = window.imaging_pane
    shown = pane.source_choice.currentData()
    rows = []
    for index in range(pane.source_choice.count()):
        source_id = str(pane.source_choice.itemData(index))
        loader, config, mapping = pane.source_config(source_id)
        info = pane.metadata_for(source_id)
        crop = pane.frame_label.visible_fraction() if source_id == shown else None
        imaging = GridImaging(
            Path(source_id),
            pane.source_choice.itemText(index) or Path(source_id).name,
            loader,
            config,
            info.frame_times,
            info.tail_duration,
            pane.view_for(source_id),
            info.width,
            info.height,
            mapping,
            crop,
        )
        rows.append(
            PictureRowOption(
                f"imaging:{source_id}",
                imaging.label,
                imaging,
                imaging.aspect_ratio,
                source_id == shown,
                "imaging",
            )
        )
    return rows


def sensor_groups(
    window: MainWindow,
) -> tuple[list[SensorGroupOption], list[StimulusChannelOption]]:
    """Plot channels grouped by their data source, and the same channels as triggers."""
    grouped: dict[str, list[StreamOption]] = {}
    triggers: list[StimulusChannelOption] = []
    for channel in window.plot_pane.channels:
        reference = ReaderReference.from_reader(channel.reader)
        source = channel.reader.source_id or channel.name
        streams = grouped.setdefault(source, [])
        colour = _PALETTE[len(streams) % len(_PALETTE)]
        streams.append(StreamOption(channel.name, reference, colour))
        triggers.append(
            StimulusChannelOption(channel.name, reference, channel.reader, f"sensor:{source}")
        )
    groups = [
        SensorGroupOption(f"sensor:{source}", _source_label(window, source), tuple(streams))
        for source, streams in grouped.items()
    ]
    return groups, triggers


def remembered(window: MainWindow) -> RowChoices | None:
    """The rows chosen last in this session, or nothing after a reset."""
    stored = window.session_runtime.stimulus_grid_rows
    if stored is None or stored[0] != window.session_runtime.generation:
        return None
    choices = stored[1]
    return choices if isinstance(choices, RowChoices) else None


def remember(window: MainWindow, choices: RowChoices) -> None:
    window.session_runtime.stimulus_grid_rows = (window.session_runtime.generation, choices)


def grid_labels() -> GridLabels:
    """Capture translated burn-in templates before the worker starts."""
    return GridLabels(
        title=tr("Stimulus-aligned comparison"),
        event=tr("Event {index}"),
        no_footage=tr("No footage"),
        ruler=tr("{before:.2f} s    Stimulus    +{after:.2f} s"),
        current=tr("Relative time: {time:+.3f} s"),
        no_signal=tr("No signal samples in the selected windows"),
        frame=tr("Frame {index}"),
        no_imaging=tr("No imaging data"),
        band=tr("{label} · mean of {count} events"),
    )
