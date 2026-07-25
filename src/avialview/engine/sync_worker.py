"""Background TTL/event evidence extraction and alignment fitting."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from avialview.core.pyramid import PyramidReader
from avialview.core.sync import extract_ttl_edges, fit_sync_events


@dataclass(frozen=True)
class SignalEvidenceSpec:
    """A cached signal channel from which TTL transitions are extracted."""

    source_id: str
    cache_dir: Path
    channel_id: str
    threshold: float = 0.5


@dataclass(frozen=True)
class EventEvidenceSpec:
    """Native timestamp evidence, such as camera-frame trigger timestamps."""

    source_id: str
    times: np.ndarray


EvidenceSpec: TypeAlias = SignalEvidenceSpec | EventEvidenceSpec


class SyncWorker(QObject):
    """Build an evidence-based proposal without blocking the UI thread."""

    finished = Signal(object)  # SyncProposal
    error = Signal(str)

    def __init__(self, reference: EvidenceSpec, target: EvidenceSpec) -> None:
        super().__init__()
        self._reference = reference
        self._target = target

    @Slot()
    def run(self) -> None:
        """Extract raw evidence and emit one deterministic fit proposal."""
        try:
            reference_times = self._event_times(self._reference)
            target_times = self._event_times(self._target)
            proposal = fit_sync_events(
                reference_times,
                target_times,
                reference_id=self._reference.source_id,
                target_id=self._target.source_id,
            )
            self.finished.emit(proposal)
        except Exception as error:
            self.error.emit(str(error))

    @staticmethod
    def _event_times(spec: EvidenceSpec) -> np.ndarray:
        if isinstance(spec, EventEvidenceSpec):
            return np.asarray(spec.times, dtype=np.float64)

        reader = PyramidReader(spec.cache_dir, spec.channel_id)
        times, values, _, _ = reader._load_level(1)
        chunk_size = 1_000_000
        chunks = (
            (times[index : index + chunk_size], values[index : index + chunk_size])
            for index in range(0, len(times), chunk_size)
        )
        events = extract_ttl_edges(chunks, source_id=spec.source_id, threshold=spec.threshold)
        return np.asarray([event.time for event in events], dtype=np.float64)
