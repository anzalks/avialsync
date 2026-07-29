"""Tests for libmpv seek command dispatch."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from avialview.core.timeline import TimeMap
from avialview.engine.seeker import SeekGroup


@dataclass
class _Pane:
    """Minimal VideoPane stand-in for SeekGroup tests."""

    time_map: TimeMap = field(default_factory=TimeMap)
    mpv: object | None = field(default_factory=object)
    is_seeking: bool = False
    calls: list[tuple[float, bool]] = field(default_factory=list)

    def seek(self, target_t: float, *, exact: bool) -> None:
        """Record a queued libmpv seek command."""
        self.calls.append((target_t, exact))


def test_seek_group_fans_out_commands_without_marking_panes_stuck() -> None:
    """Seek completion remains owned by libmpv's seeking property observer."""
    first = _Pane()
    second = _Pane()
    second.time_map.set_mapping(offset=1.25, drift_ppm=0.0)

    group = SeekGroup([first, second])
    group.seek(4.0, exact=True)

    assert first.calls == [(4.0, True)]
    assert second.calls == [(5.25, True)]
    assert group.is_settled()


def test_seek_group_maps_one_master_trigger_to_each_video_frame() -> None:
    """Accepted per-video evidence must fan out one shared trigger without drift."""
    trigger_times = np.array([100.0, 100.1, 100.2])
    first = _Pane()
    first.time_map.set_exact_mapping(trigger_times, np.array([0.0, 0.033, 0.066]))
    second = _Pane()
    second.time_map.set_exact_mapping(trigger_times, np.array([2.0, 2.050, 2.100]))

    SeekGroup([first, second]).seek(100.1, exact=True)

    assert first.calls == [(0.033, True)]
    assert second.calls == [(2.050, True)]
