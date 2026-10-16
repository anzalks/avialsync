"""Immutable evidence specifications and explicit visual-correspondence preparation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import numpy as np

from avialsync.core.errors import SyncEvidenceError
from avialsync.core.pyramid import PyramidReader
from avialsync.core.sync import SyncProposal
from avialsync.core.timeline import TimeMap
from avialsync.core.triggers import TriggerKind


@dataclass(frozen=True)
class SignalEvidenceSpec:
    """A cached signal channel from which TTL transitions are extracted."""

    source_id: str
    cache_dir: Path
    channel_id: str
    #: Logical-high level. None means halfway between the channel's lowest and
    #: highest samples, which is what a sensor target with levels of its own needs.
    threshold: float | None = 0.5
    use_all_times: bool = False
    #: What this train is evidence *of*, which is what lets the ladder choose a
    #: model. Defaults to the weakest kind: an unlabelled channel is a handful
    #: of landmarks until someone says otherwise.
    kind: TriggerKind = TriggerKind.SPARSE_EVENTS
    clock_id: str = ""
    accepted_mapping: TimeMap | None = None
    strobe_for: str = ""
    display_name: str = ""


@dataclass(frozen=True)
class EventEvidenceSpec:
    """Native timestamp evidence, such as camera-frame trigger timestamps."""

    source_id: str
    times: np.ndarray
    #: As above. Carried on the spec rather than asked for separately, because
    #: it travels with the evidence and every other route loses it -- which is
    #: what left `EXACT` and `PIECEWISE` unreachable even though both worked.
    kind: TriggerKind = TriggerKind.SPARSE_EVENTS
    clock_id: str = ""
    accepted_mapping: TimeMap | None = None
    is_video_time_axis: bool = False
    strobe_for: str = ""
    display_name: str = ""
    #: Pulses in :attr:`times` whose fall was never seen, so whose exposure
    #: midpoint is unknown. Left out of the fit and counted, as for a channel.
    incomplete_indices: tuple[int, ...] = ()
    is_imaging_time_axis: bool = False
    measurement_resolution: float = 0.0
    excluded_incomplete_count: int = 0

    @property
    def is_frame_time_axis(self) -> bool:
        """Whether these instants describe stored images rather than shared events."""
        return self.is_video_time_axis or self.is_imaging_time_axis


EvidenceSpec: TypeAlias = SignalEvidenceSpec | EventEvidenceSpec


def _midpoint(reader: PyramidReader, spec: SignalEvidenceSpec) -> float:
    """Halfway between a line's lowest and highest samples.

    Read from the coarsest pyramid level that still holds the extremes, so it
    costs a bounded read whatever the recording's length.
    """
    coverage = reader.coverage()
    if coverage is None:
        raise SyncEvidenceError(f"{spec.source_id} has no samples to find pulses in.")
    _, lows, highs, _ = reader.query(coverage[0], coverage[1], max_points=256)
    lows = lows[np.isfinite(lows)]
    highs = highs[np.isfinite(highs)]
    if not len(lows) or not len(highs) or float(highs.max()) <= float(lows.min()):
        raise SyncEvidenceError(
            f"{spec.source_id} never changes level, so it carries no pulses to align. "
            "Type a threshold, or choose the channel that carries the sync line."
        )
    return (float(lows.min()) + float(highs.max())) / 2.0


def fit_landmark_evidence(
    reference: EvidenceSpec,
    target: EvidenceSpec,
    pairs: tuple[tuple[float, float], ...] | None,
    precision: float,
    resolution: float,
    span: tuple[float, float] | None,
) -> SyncProposal:
    """Convert explicitly paired raw times through the reference's accepted clock."""
    from avialsync.core.landmark_alignment import fit_landmarks

    values = np.asarray(pairs if pairs is not None else (), dtype=np.float64).reshape((-1, 2))
    mapping = reference.accepted_mapping
    master = mapping.to_master_array(values[:, 0]) if mapping else values[:, 0]
    return fit_landmarks(
        master,
        values[:, 1],
        reference_id=reference.source_id,
        target_id=target.source_id,
        precision_requirement=precision,
        observation_resolution=resolution,
        target_span=span,
    )
