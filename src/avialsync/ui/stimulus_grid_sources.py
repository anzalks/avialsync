"""What a stimulus grid can carry, read from the open session on the UI thread.

Snapshots, not live objects: each camera's mapping and levels, each imaging
stack's loader, timing and exactly how the viewer shows it, and each sensor
channel's worker-safe reader reference, grouped by the data source it came
from. Nothing here reads a file.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.pyramid import PyramidReader
from avialsync.engine.export_worker import ReaderReference
from avialsync.engine.stimulus_grid_imaging import GridImaging
from avialsync.engine.stimulus_grid_layout import GridLabels, GridVideo
from avialsync.ui.cvd import palette_for_surface
from avialsync.ui.i18n import tr
from avialsync.ui.stimulus_grid_dialog import (
    StimulusChannelOption,
    StimulusEventSourceOption,
    StimulusGridDialog,
)
from avialsync.ui.stimulus_grid_rows import (
    GridRowsPanel,
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
    media = grid.media_path_for  # a proxy is what decodes
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


def _sorted_unique_times(values: Iterable[float]) -> tuple[float, ...]:
    """Return finite strictly increasing timestamps (collapsed within 1 us)."""
    finite = sorted(float(v) for v in values if np.isfinite(v))
    deduped: list[float] = []
    for t in finite:
        if not deduped or t - deduped[-1] > 1e-6:
            deduped.append(t)
    return tuple(deduped)


def sensor_groups(
    window: MainWindow,
) -> tuple[list[SensorGroupOption], list[StimulusChannelOption]]:
    """Plot channels (including queued rows) grouped by data source, and as triggers."""
    grouped: dict[str, list[StreamOption]] = {}
    triggers: list[StimulusChannelOption] = []
    seen: set[tuple[Path, str]] = set()
    for channel in window.plot_pane.channels:
        seen.add((channel.reader.cache_dir, channel.reader.channel_id))
        reference = ReaderReference.from_reader(channel.reader)
        source = channel.reader.source_id or channel.name
        streams = grouped.setdefault(source, [])
        colour = _PALETTE[len(streams) % len(_PALETTE)]
        streams.append(StreamOption(channel.name, reference, colour, channel.unit))
        triggers.append(
            StimulusChannelOption(channel.name, reference, channel.reader, f"sensor:{source}")
        )
    for cache_dir, name, time_map, source_id, _vis in window.plot_pane._pending_rows:
        if (cache_dir, name) in seen:
            continue
        seen.add((cache_dir, name))
        mapped = MappedChannelReader(PyramidReader(cache_dir, name), time_map, source_id)
        reference = ReaderReference.from_reader(mapped)
        source = source_id or name
        unit = window.plot_pane._units.get(mapped.key, "")
        streams = grouped.setdefault(source, [])
        colour = _PALETTE[len(streams) % len(_PALETTE)]
        streams.append(StreamOption(name, reference, colour, unit))
        triggers.append(StimulusChannelOption(name, reference, mapped, f"sensor:{source}"))
    groups = [
        SensorGroupOption(f"sensor:{source}", _source_label(window, source), tuple(streams))
        for source, streams in grouped.items()
    ]
    return groups, triggers


def event_sources(window: MainWindow) -> list[StimulusEventSourceOption]:
    """Discrete session event streams on the master clock (TTL, trials, messages, flags)."""
    found: list[StimulusEventSourceOption] = []
    overview = window.transport.overview
    ttl_times = _sorted_unique_times(ev[0] for ev in overview._ttl_events)
    if ttl_times:
        found.append(
            StimulusEventSourceOption(
                tr("Accepted TTL / Sync Events ({count})").format(count=len(ttl_times)),
                ttl_times,
            )
        )
    seg_times = _sorted_unique_times(seg[0] for seg in overview._segments)
    if seg_times:
        found.append(
            StimulusEventSourceOption(
                tr("Trials / Stimulus Segments ({count})").format(count=len(seg_times)),
                seg_times,
            )
        )
    timed_msgs = [m for m in window.message_store.messages() if m.time is not None]
    msg_times = _sorted_unique_times(float(m.time) for m in timed_msgs if m.time is not None)
    if msg_times:
        found.append(
            StimulusEventSourceOption(
                tr("Recorded Messages ({count})").format(count=len(msg_times)),
                msg_times,
            )
        )
        by_channel: dict[str, list[float]] = {}
        for msg in timed_msgs:
            if msg.channel and msg.time is not None:
                by_channel.setdefault(msg.channel, []).append(float(msg.time))
        if len(by_channel) > 1:
            for ch_name, raw_times in sorted(by_channel.items()):
                ch_times = _sorted_unique_times(raw_times)
                if ch_times:
                    found.append(
                        StimulusEventSourceOption(
                            tr("Messages — {channel} ({count})").format(
                                channel=ch_name, count=len(ch_times)
                            ),
                            ch_times,
                        )
                    )
    marker_times = _sorted_unique_times(m.t_start for m in window.annotation_store.markers)
    if marker_times:
        found.append(
            StimulusEventSourceOption(
                tr("Annotations / Flags ({count})").format(count=len(marker_times)),
                marker_times,
            )
        )
    return found


def has_stimulus_inputs(window: MainWindow) -> bool:
    """Whether the workspace has picture media plus at least one sensor or event trigger."""
    has_media = bool(window.video_grid._paths or window.imaging_pane.source_paths())
    if not has_media:
        return False
    return bool(
        window.plot_pane.channels or window.plot_pane._pending_rows or event_sources(window)
    )


def event_clips(
    window: MainWindow,
    camera_paths: Sequence[str],
    events: Sequence[float],
    before: float,
    after: float,
    out_dir: Path,
) -> list[tuple[str, float, float, Path]]:
    """Build per-event ``(media_path, src_start, src_end, output_path)`` trim specs."""
    chosen = list(camera_paths) or list(window.video_grid._paths)
    clips: list[tuple[str, float, float, Path]] = []
    for orig_path in chosen:
        media_path = window.video_grid.media_path_for(orig_path)
        mapping = window.video_grid.time_map_for(orig_path)
        suffix = Path(media_path).suffix or ".mp4"
        stem = Path(orig_path).stem
        for idx, event_t in enumerate(events, start=1):
            t0, t1 = float(event_t - before), float(event_t + after)
            if mapping is not None:
                s0, s1 = mapping.to_source(t0), mapping.to_source(t1)
            else:
                s0, s1 = t0, t1
            if s0 > s1:
                s0, s1 = s1, s0
            stamp = f"{event_t:.3f}".replace("-", "neg").replace(".", "_")
            dest = out_dir / f"{stem}_event_{idx:03d}_{stamp}s{suffix}"
            clips.append((media_path, s0, s1, dest))
    return clips


def build_stimulus_dialog(window: MainWindow) -> tuple[StimulusGridDialog, GridRowsPanel]:
    """Build the configured stimulus export dialog and its row selector."""
    groups, channels = sensor_groups(window)
    rows = GridRowsPanel(camera_rows(window) + imaging_rows(window), groups, remembered(window))
    dialog = StimulusGridDialog(channels, window, rows, event_sources=event_sources(window))
    return dialog, rows


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
