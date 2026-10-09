"""Background worker for scanning dropped files and classifying candidates.

Format-neutral by construction. A dropped directory is offered to the
registered :class:`~avialsync.core.source.SessionSource` plugins first; if one
claims it, that plugin decides what the folder contains. Nothing here knows any
lab's folder layout, and adding support for one must not require editing this
file.
"""

import logging
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.registry import LoaderRegistry, is_own_sidecar
from avialsync.core.source import SessionItem, SessionLayout, SessionSource, TimeSeriesSource

logger = logging.getLogger(__name__)


class DropScanWorker(QObject):
    """Scan dropped paths for importable sources off the UI thread."""

    #: candidates, session layout (empty when no plugin claimed a folder)
    finished = Signal(list, object)
    session_found = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        paths: list[Path],
        registry: LoaderRegistry,
        loaded: Sequence[SessionItem] = (),
    ) -> None:
        super().__init__()
        self._paths = paths
        self._registry = registry
        # What is already open, so a drop can be laid out against it.
        self._loaded = list(loaded)
        self._is_cancelled = False
        self._layout = SessionLayout()

    def cancel(self) -> None:
        self._is_cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            all_candidates, paths = self._scan_together(self._paths)

            for path in paths:
                if self._is_cancelled:
                    break
                all_candidates.extend(self._collect_drop_candidates(path))

            if not self._is_cancelled:
                self.finished.emit(all_candidates, self._layout)

        except Exception as e:
            logger.exception("Error scanning drop candidates")
            self.error.emit(str(e))

    def _collect_drop_candidates(self, path: Path) -> list[tuple[Path, type | None, dict | None]]:
        """Collect paths and their best-guess loaders recursively, avoiding session files."""
        if path.suffix.lower() == ".avv":
            self.session_found.emit(str(path))
            return []

        # A directory may *be* a recording rather than merely contain files, and
        # a file may be a whole session -- an NWB file holds a session's time
        # series, imaging and videos in one (D-188). Ask the session plugins
        # before falling back to per-file scanning.
        session_candidates = self._scan_session(path)
        if session_candidates is not None:
            return session_candidates

        loader_class = self._registry.find_best_loader(path)

        if loader_class is not None:
            # Pre-compute is_frame_indexed for time series off-thread
            config = None
            if issubclass(loader_class, TimeSeriesSource):
                try:
                    if getattr(loader_class, "is_frame_indexed", lambda s: False)(loader_class()):
                        config = {"_is_frame_indexed": True}
                except Exception as e:
                    # Ignore instantiation errors during probing, but log them
                    logger.debug("Failed to probe %s: %s", loader_class, e)
            return [(path, loader_class, config)]

        candidates = []
        if path.is_dir():
            session_files = list(path.glob("*.avv"))
            if session_files:
                return self._collect_drop_candidates(session_files[0])
            for child in path.iterdir():
                if child.name.startswith("."):
                    continue
                if is_own_sidecar(child):
                    # Also ours: a corrections file is a CSV, so without this a
                    # folder the user has corrected offers to import the
                    # corrections back as a data source beside the pose file
                    # they belong to (D-099).
                    continue
                candidates.extend(self._collect_drop_candidates(child))
        else:
            candidates.append((path, None, None))

        return candidates

    def _scan_together(
        self, paths: list[Path]
    ) -> tuple[list[tuple[Path, type | None, dict | None]], list[Path]]:
        """Let session plugins lay out several dropped paths as one recording.

        Returns the candidates of every layout claimed this way and the paths
        left for scanning one at a time. A plugin that fails here is reported
        and the paths fall through, exactly as for :meth:`_scan_session`.
        """
        candidates: list[tuple[Path, type | None, dict | None]] = []
        for session_cls in self._registry.sessions():
            if self._is_cancelled or not paths:
                break
            try:
                claimed = session_cls().scan_together(paths, self._loaded, self._registry)
            except Exception as error:  # noqa: BLE001 - plugin boundary
                logger.exception("Session plugin %s failed on a drop", session_cls.__name__)
                self._registry.plugin_errors.append(
                    (session_cls.display_name(), f"scan failed: {type(error).__name__}: {error}")
                )
                continue
            if claimed is None:
                continue
            layout, used = claimed
            self._adopt(session_cls, layout, ", ".join(path.name for path in used))
            candidates += [(item.path, item.loader, dict(item.config)) for item in layout.items]
            paths = [path for path in paths if path not in used]
        return candidates, paths

    def _adopt(self, session_cls: type[SessionSource], layout: SessionLayout, name: str) -> None:
        """Keep the first claiming session's settings; later ones only add items."""
        # Session-wide settings — the wall-clock anchor above all — describe one
        # recording, and the drop reports exactly one set of them. The first
        # session to claim keeps them: dropping two folders at once used to leave
        # whichever happened to be scanned last owning the timeline's anchor,
        # which is arbitrary, and silent. Their *items* all still load.
        if self._layout.items or self._layout.anchor_epoch:
            logger.info(
                "%s also laid out %s; its items load, but the timeline keeps the first "
                "session's settings (anchor_epoch=%.3f). Drop one session at a time to "
                "read wall clock from this one.",
                session_cls.display_name(),
                name,
                self._layout.anchor_epoch,
            )
        else:
            self._layout = layout

    def _scan_session(self, path: Path) -> list[tuple[Path, type | None, dict | None]] | None:
        """Lay out *path* with the session plugin that claims it, if any.

        Returns ``None`` when no plugin claims the directory, so the caller
        falls back to scanning its files individually. A plugin that claims the
        folder but then fails is reported and also falls back: a broken session
        scanner must not make the folder unopenable.
        """
        session_cls = self._registry.find_best_session(path)
        if session_cls is None:
            return None
        try:
            layout = session_cls().scan(path, self._registry)
        except Exception as error:  # noqa: BLE001 - plugin boundary
            logger.exception("Session plugin %s failed on %s", session_cls.__name__, path)
            # Named as the user knows it: Diagnostics is read by whoever
            # installed the plugin, not by whoever wrote its class.
            self._registry.plugin_errors.append(
                (session_cls.display_name(), f"scan failed: {type(error).__name__}: {error}")
            )
            return None

        self._adopt(session_cls, layout, path.name)
        return [(item.path, item.loader, dict(item.config)) for item in layout.items]
