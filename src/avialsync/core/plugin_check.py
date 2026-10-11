"""Check plugins against the plugin API without opening a window.

``avialsync plugin-check`` lists every plugin discovery found, and what kept
any from loading. Given a recording it does what a drop does -- asks the
session scanners, else the loaders -- and checks what comes back against the
rules in the plugin guide: an absolute ``source_epoch``, trials that do not
overlap, timestamps that never go backwards, trigger kinds that exist. It reads
at most a few chunks per channel, so it is quick on a large recording.

Headless, like the rest of ``core/``: the same check runs in a terminal, in a
plugin's own test suite, and against an installed application.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.registry import LoaderRegistry
from avialsync.core.source import (
    PLUGIN_API_VERSION,
    ImagingSource,
    SessionItem,
    SessionLayout,
    TimeSeriesSource,
    VideoSource,
)
from avialsync.core.triggers import TriggerKind

__all__ = ["PluginReport", "check_path", "list_plugins"]

#: Anything earlier is not a Unix time: 1973-03-03. A ``source_epoch`` below it
#: is a session-relative number, which the guide forbids (it declares nothing).
_EARLIEST_EPOCH = 1e8
#: Chunks read per channel; enough to see ordering, cheap on 50 GB.
_CHUNKS_PER_CHANNEL = 3


@dataclass
class PluginReport:
    """What a check found: lines to show, and problems that fail it."""

    lines: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def text(self) -> str:
        if self.ok:
            return "\n".join([*self.lines, "OK"])
        verdict = f"{len(self.problems)} problem(s):\n  " + "\n  ".join(self.problems)
        return "\n".join([*self.lines, verdict])


def list_plugins(registry: LoaderRegistry) -> PluginReport:
    """Every discovered plugin with where it came from, and every load failure."""
    report = PluginReport([f"AvialSync plugin API {PLUGIN_API_VERSION}"])
    for kind, cls, origin in registry.plugins():
        state = "" if registry.is_enabled(cls) else " [switched off]"
        report.lines.append(f"{kind}: {cls.display_name()} ({origin}){state}")  # type: ignore[attr-defined]
    for name, reason in registry.plugin_errors:
        report.problems.append(f"{name}: {reason}")
    return report


def check_path(registry: LoaderRegistry, path: Path) -> PluginReport:
    """Lay out *path* as a drop would, and check what the plugins return."""
    report = PluginReport()
    session_cls = registry.find_best_session(path)
    if session_cls is not None:
        tied = registry.tied_sessions(path)
        if tied:
            names = ", ".join(cls.display_name() for cls in tied)
            report.problems.append(f"{names} all claim {path.name} with the same score")
        report.lines.append(f"{path.name}: laid out by {session_cls.display_name()}")
        try:
            layout = session_cls().scan(path, registry)
        except Exception as error:  # noqa: BLE001 - plugin boundary
            report.problems.append(f"scan raised {type(error).__name__}: {error}")
            return report
        _check_layout(layout, report)
        for item in layout.items:
            loader = item.loader or registry.find_best_loader(item.path)
            _check_source(item.path, loader, dict(item.config), report)
        return report
    loader = registry.find_best_loader(path)
    if loader is None:
        report.problems.append(f"nothing installed claims {path}")
        return report
    tied_loaders = registry.tied_loaders(path)
    if tied_loaders:
        names = ", ".join(cls.display_name() for cls in tied_loaders)
        report.problems.append(f"{names} all claim {path.name} with the same score")
    _check_source(path, loader, {}, report)
    return report


def _check_layout(layout: SessionLayout, report: PluginReport) -> None:
    report.lines.append(f"  {len(layout.items)} item(s), {len(layout.segments)} trial(s)")
    for warning in layout.warnings:
        report.lines.append(f"  warning: {warning}")
    for epoch_name in ("session_epoch", "anchor_epoch"):
        value = float(getattr(layout, epoch_name))
        if 0.0 < value < _EARLIEST_EPOCH:
            report.problems.append(f"{epoch_name} {value} is not a Unix time")
    for item in layout.items:
        _check_item(item, report)
    previous_end = -np.inf
    for start, end, name in layout.segments:
        if not end > start:
            report.problems.append(f"trial {name!r} ends at or before it starts")
        if start < previous_end:
            report.problems.append(f"trial {name!r} starts inside the trial before it")
        if 0.0 < start < _EARLIEST_EPOCH:
            report.problems.append(f"trial {name!r} start {start} is not a Unix time")
        previous_end = max(previous_end, end)


def _check_item(item: SessionItem, report: PluginReport) -> None:
    epoch = item.source_epoch
    if epoch is not None and 0.0 < epoch < _EARLIEST_EPOCH:
        report.problems.append(
            f"{item.path.name}: source_epoch {epoch} is not an absolute instant; declare the "
            "UTC instant this file's t=0 is"
        )
    if "offset" in item.config and item.source_epoch is not None:
        report.problems.append(f"{item.path.name}: both an offset in config and a source_epoch")


def _check_source(
    path: Path, loader: type | None, config: dict[str, Any], report: PluginReport
) -> None:
    if loader is None:
        report.lines.append(f"  {path.name}: no loader; left for the user to choose")
        return
    report.lines.append(f"  {path.name}: {loader.display_name()}")  # type: ignore[attr-defined]
    try:
        if issubclass(loader, TimeSeriesSource):
            _check_time_series(loader(), path, config, report)
        elif issubclass(loader, ImagingSource):
            metadata = loader().open(path, config)
            if np.any(np.diff(np.asarray(metadata.frame_times)) <= 0):
                report.problems.append(f"{path.name}: frame_times are not strictly increasing")
        elif issubclass(loader, VideoSource):
            source = loader()
            source.open(path, config)
            times = source.frame_times()
            if times is not None and np.any(np.diff(np.asarray(times)) < 0):
                report.problems.append(f"{path.name}: frame_times go backwards")
    except Exception as error:  # noqa: BLE001 - plugin boundary
        report.problems.append(f"{path.name}: {type(error).__name__}: {error}")


def _check_time_series(
    source: TimeSeriesSource, path: Path, config: dict[str, Any], report: PluginReport
) -> None:
    source.open(path, config)
    channels = source.channels()
    if not channels:
        report.problems.append(f"{path.name}: declares no channels")
    kinds = {kind.value for kind in TriggerKind}
    for channel in channels:
        trigger = getattr(channel, "trigger", "")
        if trigger and trigger not in kinds:
            report.problems.append(
                f"{path.name}:{channel.name}: trigger {trigger!r} is not one of {sorted(kinds)}"
            )
        last = -np.inf
        chunks: Iterator[tuple[np.ndarray, np.ndarray]] = iter(source.read_chunks(channel.name))
        for times, values in islice(chunks, _CHUNKS_PER_CHANNEL):
            t = np.asarray(times)
            v = np.asarray(values)
            if t.ndim != 1 or v.ndim != 1 or len(t) != len(v):
                report.problems.append(
                    f"{path.name}:{channel.name}: chunks must be two 1-D arrays of one length"
                )
                break
            if len(t) and (t[0] < last or np.any(np.diff(t) < 0)):
                report.problems.append(f"{path.name}:{channel.name}: timestamps go backwards")
                break
            if len(t):
                last = float(t[-1])
