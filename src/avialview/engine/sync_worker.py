"""Background TTL/event evidence extraction and alignment fitting."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from avialview.core.pyramid import RAW_CHUNK_SAMPLES, PyramidReader
from avialview.core.sync import extract_ttl_edges, fit_exact_index_mapping, fit_sync_events


@dataclass(frozen=True)
class SignalEvidenceSpec:
    """A cached signal channel from which TTL transitions are extracted."""

    source_id: str
    cache_dir: Path
    channel_id: str
    threshold: float = 0.5
    use_all_times: bool = False


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

    def __init__(
        self,
        reference: EvidenceSpec,
        target: EvidenceSpec,
        mode: str = "affine",
        index_offset: int = 0,
    ) -> None:
        super().__init__()
        self._reference = reference
        self._target = target
        self._mode = mode
        self._index_offset = index_offset

    @Slot()
    def run(self) -> None:
        """Extract raw evidence and emit one deterministic fit proposal."""
        try:
            is_exact = self._mode == "exact_index"
            reference_times = self._event_times(self._reference, use_all_times=is_exact)
            target_times = self._event_times(self._target, use_all_times=is_exact)

            if is_exact:
                proposal = fit_exact_index_mapping(
                    reference_times,
                    target_times,
                    reference_id=self._reference.source_id,
                    target_id=self._target.source_id,
                    index_offset=self._index_offset,
                )
            else:
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
    def _event_times(spec: EvidenceSpec, use_all_times: bool = False) -> np.ndarray:
        if isinstance(spec, EventEvidenceSpec):
            return np.asarray(spec.times, dtype=np.float64)

        reader = PyramidReader(spec.cache_dir, spec.channel_id)
        if use_all_times or getattr(spec, "use_all_times", False):
            times, _, _ = reader.mapped_columns()
            return times

        chunks = reader.iter_raw_chunks(RAW_CHUNK_SAMPLES)
        events = extract_ttl_edges(chunks, source_id=spec.source_id, threshold=spec.threshold)
        return np.asarray([event.time for event in events], dtype=np.float64)
