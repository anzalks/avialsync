"""Prepare bounded pyramid pages without querying data on the UI thread."""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.channel_reader import MappedChannelReader
from avialsync.core.pyramid import PyramidReader
from avialsync.core.timeline import TimeMap


@dataclass(frozen=True)
class PlotRowRequest:
    """A row's own pyramid reader and its clock mapping frozen at request time.

    The reader is the row's, not a fresh one: its levels are already mapped,
    which made a warm 48-row page seven times cheaper than reopening them, and
    it adds no memory maps of its own to keep a cache folder busy on Windows.
    `PyramidReader` keeps its level cache consistent across threads.
    """

    index: int
    reader: PyramidReader
    source_id: str
    time_map: TimeMap


@dataclass(frozen=True)
class PlotPage:
    """One viewport of ready-to-draw bounded row curves."""

    generation: int
    t0: float
    rows: tuple[tuple[int, np.ndarray, np.ndarray], ...]


class PlotPageWorker(QObject):
    """Read and shape one page, stopping when a newer request supersedes it."""

    finished = Signal(object)
    cancelled = Signal()
    error = Signal(str)
    progress = Signal(int)

    def __init__(
        self,
        generation: int,
        t0: float,
        t1: float,
        budget: int,
        rows: tuple[PlotRowRequest, ...],
    ) -> None:
        super().__init__()
        self.generation = generation
        self.t0 = t0
        self.t1 = t1
        self.budget = budget
        self.rows = rows
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        """Discard this page at the next row boundary."""
        self._cancelled.set()

    def can_cancel(self) -> bool:
        return not self._cancelled.is_set()

    @Slot()
    def run(self) -> None:
        """Prepare bounded interleaved min/max curves for the requested viewport."""
        prepared: list[tuple[int, np.ndarray, np.ndarray]] = []
        try:
            for number, spec in enumerate(self.rows):
                if self._cancelled.is_set():
                    self.cancelled.emit()
                    return
                reader = MappedChannelReader(spec.reader, spec.time_map, spec.source_id)
                t, lower, upper, gaps = reader.query(self.t0, self.t1, max_points=self.budget)
                x = np.repeat(t - self.t0, 2)
                y = np.empty(len(x), dtype=np.float64)
                y[0::2] = lower
                y[1::2] = upper
                y[np.repeat(np.asarray(gaps, dtype=bool), 2)] = np.nan
                prepared.append((spec.index, x, y))
                self.progress.emit(int(100 * (number + 1) / max(len(self.rows), 1)))
            if self._cancelled.is_set():
                self.cancelled.emit()
            else:
                self.finished.emit(PlotPage(self.generation, self.t0, tuple(prepared)))
        except Exception as error:
            self.error.emit(str(error))
