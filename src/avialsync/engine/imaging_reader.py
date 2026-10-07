"""The imaging pane's reader: one lazy source, coalesced requests, bounded memory.

One worker per selected stack lives on its own thread for as long as the stack
is shown (D-190). The pane hands it the newest wanted frame index and display
view; anything older that has not started yet is dropped, so a reader slower
than the 60 Hz tick skips frames instead of building a backlog nobody will see.

Raw planes are cached by ``(frame, channel)`` in their own dtype, downsampled
once, under a byte budget rather than a count. That is what lets a moving
average slide by one read per frame during playback, and lets a brightness
drag re-render the current picture without touching the file at all.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.errors import LoaderContractError
from avialsync.core.imaging_display import (
    ImagingView,
    auto_window,
    average_range,
    compose,
)
from avialsync.core.source import ImagingSource

logger = logging.getLogger(__name__)

#: Longest side of a displayed plane. Larger acquisitions are strided down once,
#: on read, so neither the cache nor the composite ever holds the full raster.
MAX_PREVIEW_SIDE = 1024

#: Raw-plane cache budget. A 31-frame average of a two-channel 512x512 uint16
#: stack needs 31 MiB; this leaves room for scrubbing back and forth over it.
CACHE_BYTES = 128 * 1024 * 1024


class ImagingReadWorker(QObject):
    """Own one lazy reader and render the newest requested frame.

    Signals carry the source path so a pane that has since switched stacks can
    ignore a late result rather than show the wrong one.
    """

    opened = Signal(str)
    frame_ready = Signal(str, int, object)
    frame_failed = Signal(str, int, str)
    failed = Signal(str, str)
    #: ``(path, channel, low, high)`` -- a reference window measured from data.
    window_measured = Signal(str, int, float, float)

    def __init__(
        self,
        path: Path,
        loader_cls: type[ImagingSource],
        config: dict[str, Any],
        frame_count: int,
    ) -> None:
        super().__init__()
        self._path = path
        self._loader_cls = loader_cls
        self._config = config
        self._frame_count = frame_count
        self._reader: ImagingSource | None = None
        self._pending: tuple[int, ImagingView] | None = None
        self._lock = threading.Lock()
        self._planes: OrderedDict[tuple[int, int], np.ndarray] = OrderedDict()
        self._cached_bytes = 0

    @Slot()
    def open(self) -> None:
        """Open the source on its owning thread."""
        try:
            self._reader = self._loader_cls()
            self._reader.open(self._path, self._config)
        except Exception as error:  # noqa: BLE001 - source plugin boundary
            self.failed.emit(str(self._path), str(error))
            return
        self.opened.emit(str(self._path))

    def request(self, index: int, view: ImagingView) -> None:
        """Replace any outstanding request; safe to call from any thread."""
        with self._lock:
            self._pending = (index, view)

    @Slot()
    def decode_pending(self) -> None:
        """Render the newest request, if one is still waiting."""
        with self._lock:
            pending, self._pending = self._pending, None
        if pending is None or self._reader is None:
            return
        index, view = pending
        try:
            image = self.render(index, view)
        except Exception as error:  # noqa: BLE001 - a damaged page is one frame's failure
            logger.warning(
                "Could not read imaging frame %s from %s", index, self._path, exc_info=error
            )
            self.frame_failed.emit(str(self._path), index, str(error))
            return
        self.frame_ready.emit(str(self._path), index, image)

    def render(self, index: int, view: ImagingView) -> np.ndarray | None:
        """Average, window and overlay the visible channels at *index*.

        Returns ``None`` when no channel is visible. A channel without a
        measured reference window has one measured here, from the averaged plane
        the user is looking at, and reported through ``window_measured``.
        """
        frames = average_range(index, self._frame_count, view.average)
        planes = []
        for channel, shown in enumerate(view.channels):
            if not shown.visible:
                continue
            mean = self._mean(frames, channel)
            if not shown.measured:
                low, high = auto_window(mean)
                shown = dataclasses.replace(shown, auto_low=low, auto_high=high)
                self.window_measured.emit(str(self._path), channel, low, high)
            planes.append((mean, shown))
        return compose(planes) if planes else None

    def _mean(self, frames: range, channel: int) -> np.ndarray:
        total: np.ndarray | None = None
        for frame in frames:
            plane = self._plane(frame, channel)
            if total is None:
                total = plane.astype(np.float32)
            else:
                total += plane
        assert total is not None  # average_range always holds the index itself
        if len(frames) > 1:
            total *= np.float32(1.0 / len(frames))
        return total

    def _plane(self, frame: int, channel: int) -> np.ndarray:
        key = (frame, channel)
        cached = self._planes.get(key)
        if cached is not None:
            self._planes.move_to_end(key)
            return cached
        assert self._reader is not None
        plane = self._reader.read_frame(frame, channel)
        if plane.ndim != 2:
            raise LoaderContractError(
                f"{self._loader_cls.__name__}.read_frame returned {plane.ndim} dimensions, not 2"
            )
        step = max(1, -(-max(plane.shape) // MAX_PREVIEW_SIDE))
        if step > 1:
            plane = np.ascontiguousarray(plane[::step, ::step])
        self._planes[key] = plane
        self._cached_bytes += plane.nbytes
        while self._cached_bytes > CACHE_BYTES and len(self._planes) > 1:
            _key, dropped = self._planes.popitem(last=False)
            self._cached_bytes -= dropped.nbytes
        return plane

    @Slot()
    def close(self) -> None:
        """Release file handles and cached planes on the reader's thread."""
        if self._reader is not None:
            self._reader.close()
        self._reader = None
        self._planes.clear()
        self._cached_bytes = 0
