"""Annotation markers: point and range, and the one definition of their CSV.

The list of markers is presented by :mod:`avialsync.ui.changes_panel`, together
with hand corrections to tracked points -- both are human judgements laid over a
recording, and a reviewer wants them in one place (D-099).
"""

from __future__ import annotations

import csv
import dataclasses
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication,
)

from avialsync.ui.theme import marker_color


def _resolved_marker_color(index: int) -> str:
    """Return the *index*-th marker colour against the application palette."""
    # `instance()` is typed as the QCoreApplication base, which has no palette;
    # a headless run legitimately has none, so both cases fall back to a default
    # palette rather than assuming a GUI application exists.
    app = QApplication.instance()
    palette = app.palette() if isinstance(app, QApplication) else QPalette()
    return marker_color(palette, index).name()


@dataclasses.dataclass
class VideoFrame:
    """Per-video frame snapshot stored with an annotation marker."""

    path: str
    frame_index: int
    media_timestamp: float


@dataclasses.dataclass
class Marker:
    """A single annotation marker on the timeline.

    If ``t_end`` is None this is a point marker; otherwise it is a range.
    ``video_frames`` holds one record per loaded video at the moment of marking.
    """

    t_start: float
    t_end: float | None
    label: str
    #: Position in the categorical marker sequence, not a colour. The colour it
    #: resolves to depends on the live palette, so a marker stays legible when
    #: the user switches appearance instead of keeping a hex tuned for the
    #: theme that happened to be active when it was created.
    color_index: int = 0
    video_frames: list[VideoFrame] = dataclasses.field(default_factory=list)

    @property
    def color(self) -> str:
        """Resolve this marker's colour against the current application palette."""
        return _resolved_marker_color(self.color_index)


class AnnotationStore(QObject):
    """In-memory store for timeline markers.

    Emits ``changed`` whenever markers are added or removed so that
    connected UI components (plot, annotation panel) can redraw.
    """

    changed = Signal()
    #: Emitted with the index of a newly inserted marker.
    marker_added = Signal(int)
    #: Emitted with the index it held and the marker itself, so a deletion can
    #: be reversed without the observer having kept its own copy.
    marker_removed = Signal(int, object)
    #: index, previous label, new label.
    marker_relabelled = Signal(int, str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._markers: list[Marker] = []
        self._color_idx = 0

    @property
    def markers(self) -> list[Marker]:
        return list(self._markers)

    def add_point(
        self, t: float, label: str = "", video_frames: list[VideoFrame] | None = None
    ) -> Marker:
        """Add a point marker at time *t*."""
        index = self._color_idx
        self._color_idx += 1
        m = Marker(
            t_start=t, t_end=None, label=label, color_index=index, video_frames=video_frames or []
        )
        self._markers.append(m)
        self.marker_added.emit(len(self._markers) - 1)
        self.changed.emit()
        return m

    def add_range(
        self,
        t_start: float,
        t_end: float,
        label: str = "",
        video_frames: list[VideoFrame] | None = None,
    ) -> Marker:
        """Add a range marker from *t_start* to *t_end*."""
        if t_start > t_end:
            t_start, t_end = t_end, t_start
        index = self._color_idx
        self._color_idx += 1
        m = Marker(
            t_start=t_start,
            t_end=t_end,
            label=label,
            color_index=index,
            video_frames=video_frames or [],
        )
        self._markers.append(m)
        self.marker_added.emit(len(self._markers) - 1)
        self.changed.emit()
        return m

    def remove(self, index: int) -> None:
        """Remove a marker by index."""
        if 0 <= index < len(self._markers):
            removed = self._markers.pop(index)
            self.marker_removed.emit(index, removed)
            self.changed.emit()

    def insert(self, index: int, marker: Marker) -> None:
        """Put *marker* back at *index*.

        Undo of a deletion restores position, not just existence: markers are
        listed and exported in order, and a restored marker appearing at the
        end of the table would read as a different annotation.
        """
        index = max(0, min(index, len(self._markers)))
        self._markers.insert(index, marker)
        self.marker_added.emit(index)
        self.changed.emit()

    def set_label(self, index: int, label: str) -> None:
        """Rename the marker at *index*.

        The annotation panel used to assign straight into ``_markers`` from
        outside the store, which meant a rename emitted nothing and no observer
        could see it.
        """
        if not 0 <= index < len(self._markers):
            return
        before = self._markers[index].label
        if before == label:
            return
        self._markers[index].label = label
        self.marker_relabelled.emit(index, before, label)
        self.changed.emit()

    def clear(self) -> None:
        self._markers.clear()
        self.changed.emit()

    def export_csv(self, path: Path) -> None:
        """Write this store's markers to *path*.

        Synchronous; the application exports through
        :class:`~avialsync.engine.changes_export_worker.ChangesExportWorker` so
        the UI thread never writes this file itself.
        """
        write_marker_rows(path, marker_rows(self._markers))


#: Columns of the annotation export. One authority: the store's own
#: ``export_csv`` and the off-thread worker both build rows through
#: :func:`marker_rows`, so the layout cannot drift between them. It used to be
#: written out in both places and in the panel's export button besides.
MARKER_COLUMNS = ("label", "comment", "t_master", "video_path", "frame_index", "media_timestamp")


def marker_rows(markers: list[Marker]) -> list[list[Any]]:
    """Return one row per ``(marker, video)``, in export order.

    A marker with no video frames produces a single row with the video columns
    empty, rather than being dropped: a flag placed on the timeline before any
    footage loaded is still something the user made.
    """
    rows: list[list[Any]] = []
    for marker in markers:
        if marker.video_frames:
            for frame in marker.video_frames:
                rows.append(
                    [
                        marker.label,
                        "",
                        marker.t_start,
                        frame.path,
                        frame.frame_index,
                        frame.media_timestamp,
                    ]
                )
        else:
            rows.append([marker.label, "", marker.t_start, "", "", ""])
    return rows


def write_marker_rows(path: Path, rows: list[list[Any]]) -> None:
    """Write annotation *rows* to *path* with the standard header."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(MARKER_COLUMNS))
        writer.writerows(rows)
