"""Read and write physical-prop sidecars away from the GUI thread."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.errors import PropModelError
from avialsync.core.physical_props import PhysicalProp
from avialsync.core.prop_file import (
    PropFileIssue,
    PropKind,
    PropRecord,
    read_props,
    write_prop,
    write_removed,
)
from avialsync.core.prop_write_queue import PropWriteQueue, PropWriteRequest
from avialsync.core.wheel import Wheel


@dataclass(frozen=True)
class PropWriteResult:
    """A finished revision; UI delivery may arrive after further edits or a reset."""

    request: PropWriteRequest
    path: Path | None = None
    error: str = ""


class PropFileReadWorker(QObject):
    """Discover independent prop records in a recording folder."""

    finished = Signal(object, object)
    error = Signal(str)

    def __init__(
        self,
        folder: Path,
        sources: tuple[str, ...] = (),
        *,
        queues: Mapping[Path, PropWriteQueue] | None = None,
    ) -> None:
        super().__init__()
        self._folder = folder
        self._sources = sources
        self._queues = queues or {}
        self.locations: dict[str, Path] = {}

    @Slot()
    def run(self) -> None:
        try:
            props, issues = self._read_recording()
        except OSError as error:
            self.error.emit(str(error))
        else:
            self.finished.emit(props, issues)

    def _read_recording(self) -> tuple[list[PropRecord], list[PropFileIssue]]:
        """Find a shared recording folder even when only one nested camera is open."""
        self._wait_for_saves(self._folder)
        props, issues = read_props(self._folder)
        self.locations = {prop.name: self._folder for prop in props}
        candidates = {
            parent / "pose-3d"
            for source in self._sources
            for parent in Path(source).parents
            if parent != parent.parent and parent != Path.home()
        }
        sources = {Path(source) for source in self._sources}
        for folder in sorted(candidates - {self._folder}):
            try:
                self._wait_for_saves(folder)
                if not folder.is_dir():
                    continue
                found, _issues = read_props(folder)
            except OSError:
                # An unrelated ancestor must not discard readable local records.
                continue
            for prop in found:
                # Ancestor folders must prove ownership, never win by filename alone.
                if prop.name not in self.locations and any(
                    Path(camera.source) in sources for camera in prop.context.cameras
                ):
                    props.append(prop)
                    self.locations[prop.name] = folder
        return props, issues

    def _wait_for_saves(self, folder: Path) -> None:
        queue = self._queues.get(folder)
        if queue is not None and not queue.wait_until_idle():
            raise OSError("Physical-prop saves are still pending; retry after the task finishes.")


class PropFileWriteWorker(QObject):
    """Write one immutable accepted revision atomically."""

    finished = Signal(object)
    error = Signal(str)
    revision_finished = Signal(object)

    def __init__(
        self,
        folder: Path,
        name: str,
        prop: PhysicalProp | Wheel | None,
        *,
        kind: PropKind = "ladder",
        overwrite_existing: bool = True,
        queue: PropWriteQueue | None = None,
    ) -> None:
        super().__init__()
        self._folder = folder
        self._name = name
        self._prop = prop
        self._kind = kind
        self._overwrite_existing = overwrite_existing
        self._queue = queue

    @Slot()
    def run(self) -> None:
        if self._queue is not None:
            self._drain()
            return
        try:
            path = (
                write_prop(self._folder, self._prop, overwrite_existing=self._overwrite_existing)
                if self._prop is not None
                else write_removed(
                    self._folder,
                    self._name,
                    kind=self._kind,
                    overwrite_existing=self._overwrite_existing,
                )
            )
        except (OSError, ValueError, PropModelError) as error:
            self.error.emit(str(error))
        else:
            self.finished.emit(path)

    def _drain(self) -> None:
        """Publish all accepted pending records even while the UI is closing."""
        assert self._queue is not None
        last_path: Path | None = None
        while (request := self._queue.take()) is not None:
            overwrite = self._queue.may_overwrite(request)
            try:
                path = (
                    write_prop(request.folder, request.prop, overwrite_existing=overwrite)
                    if request.prop is not None
                    else write_removed(
                        request.folder,
                        request.name,
                        kind=request.kind,
                        overwrite_existing=overwrite,
                    )
                )
            except (OSError, ValueError, PropModelError) as error:
                result = PropWriteResult(request, error=str(error))
            else:
                self._queue.published(request)
                last_path = path
                result = PropWriteResult(request, path)
            self.revision_finished.emit(result)
        self.finished.emit(last_path)
