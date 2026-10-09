"""An imaging row in a stimulus grid: the stack as the image viewer shows it (D-210).

Each event column shows the frame whose presentation interval contains the
column's instant -- the same choice the viewer makes (``frame_index_at``, the
last frame held for its tail interval) -- composed by the viewer's own reader
(:class:`~avialsync.engine.imaging_reader.ImagingReadWorker`): its channels,
colours, windows and centred averaging, and cropped to the viewer's zoom and
pan. A cell whose instant has no imaging says so rather than holding a frame.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtGui import QImage

from avialsync.core.errors import ExportError
from avialsync.core.imaging_display import ImagingView
from avialsync.core.source import ImagingSource
from avialsync.core.timeline import TimeMap
from avialsync.core.video_timing import frame_index_at
from avialsync.engine.imaging_reader import ImagingReadWorker


@dataclass(frozen=True)
class GridImaging:
    """An imaging stack and detached snapshots of how and when the viewer shows it.

    *crop* is the visible part of the composed picture as fractions
    ``(x, y, width, height)``, or ``None`` for the whole of it.
    """

    path: Path
    label: str
    loader: type[ImagingSource]
    config: dict[str, Any]
    frame_times: np.ndarray
    tail: float
    view: ImagingView
    width: int
    height: int
    time_map: TimeMap = field(default_factory=TimeMap)
    crop: tuple[float, float, float, float] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "time_map", self.time_map.copy())
        object.__setattr__(self, "config", dict(self.config))
        object.__setattr__(
            self, "frame_times", np.asarray(self.frame_times, dtype=np.float64).copy()
        )

    @property
    def aspect_ratio(self) -> float:
        """Width over height of what is shown, crop included."""
        crop_width, crop_height = (1.0, 1.0) if self.crop is None else self.crop[2:]
        width, height = self.width * crop_width, self.height * crop_height
        return width / height if width > 0 and height > 0 else 16 / 9


class ImagingRow:
    """Opens one stack on the export worker and renders its frames on demand."""

    def __init__(self, imaging: GridImaging) -> None:
        self.imaging = imaging
        times = imaging.frame_times
        if len(times) == 0:
            raise ExportError(f"{imaging.label} has no frames to export.")
        self._reader = ImagingReadWorker(imaging.path, imaging.loader, imaging.config, len(times))
        failures: list[str] = []
        self._reader.failed.connect(lambda _path, message: failures.append(message))
        self._reader.open()
        if failures:
            raise ExportError(f"{imaging.label} could not be opened: {failures[0]}")
        mapping = imaging.time_map
        self.bounds = (
            float(mapping.to_master(float(times[0]))),
            float(mapping.to_master(float(times[-1]) + imaging.tail)),
        )
        self._shown: tuple[int, QImage | None] | None = None

    def index_at(self, master_time: float) -> int | None:
        """The frame shown at *master_time*, or ``None`` where there is no imaging."""
        if not self.bounds[0] <= master_time < self.bounds[1]:
            return None
        source = float(self.imaging.time_map.to_source(master_time))
        return frame_index_at(self.imaging.frame_times, source)

    def image_at(self, master_time: float) -> QImage | None:
        """The picture at *master_time*, rendered once per frame and reused while held."""
        index = self.index_at(master_time)
        if index is None:
            return None
        if self._shown is not None and self._shown[0] == index:
            return self._shown[1]
        pixels = self._reader.render(index, self.imaging.view)
        image = None if pixels is None else _cropped(_to_image(pixels), self.imaging.crop)
        self._shown = (index, image)
        return image

    def ticks(
        self,
        event: float,
        before: float,
        after: float,
        playback_speed: float,
        ticks_per_second: int,
    ) -> Iterator[int]:
        """Output ticks, in order, where this row's picture changes in *event*'s window."""
        mapping = self.imaging.time_map
        times = self.imaging.frame_times
        start = float(mapping.to_source(event - before))
        end = float(mapping.to_source(event + after))
        first = int(np.searchsorted(times, start, side="left"))
        stop = int(np.searchsorted(times, end, side="left"))
        for source_time in times[first:stop]:
            elapsed = float(mapping.to_master(float(source_time))) - event + before
            # The rendered instant must never precede this frame's own time.
            yield int(np.ceil(elapsed / playback_speed * ticks_per_second - 1e-9))
        coverage_end = (self.bounds[1] - event + before) / playback_speed
        yield int(np.ceil(coverage_end * ticks_per_second - 1e-9))

    def close(self) -> None:
        self._reader.close()


def _to_image(pixels: np.ndarray) -> QImage:
    pixels = np.ascontiguousarray(pixels)
    height, width = pixels.shape[:2]
    image_format = (
        QImage.Format.Format_Grayscale8 if pixels.ndim == 2 else QImage.Format.Format_RGB888
    )
    # copy(): the QImage borrows the array, which does not outlive this call.
    return QImage(pixels.data, width, height, pixels.strides[0], image_format).copy()


def _cropped(image: QImage, crop: tuple[float, float, float, float] | None) -> QImage:
    if crop is None:
        return image
    x, y, width, height = crop
    return image.copy(
        round(x * image.width()),
        round(y * image.height()),
        max(1, round(width * image.width())),
        max(1, round(height * image.height())),
    )
