"""Background worker for scanning dropped files and classifying candidates."""

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from avialview.core.registry import LoaderRegistry
from avialview.core.source import TimeSeriesSource

logger = logging.getLogger(__name__)


class DropScanWorker(QObject):
    """Scan dropped paths for importable sources off the UI thread."""

    # candidates, is_aol_session
    finished = Signal(list, bool)
    session_found = Signal(str)
    error = Signal(str)

    def __init__(self, paths: list[Path], registry: LoaderRegistry) -> None:
        super().__init__()
        self._paths = paths
        self._registry = registry
        self._is_cancelled = False
        self._is_aol_session_found = False

    def cancel(self) -> None:
        self._is_cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            all_candidates = []

            for path in self._paths:
                if self._is_cancelled:
                    break

                # If the user dropped an AOL folder, we want to bypass the popup
                # and load everything quietly under the hood.
                if path.is_dir():
                    from avialview.loaders.aol_session_loader import is_aol_session

                    if is_aol_session(path):
                        self._is_aol_session_found = True

                candidates = self._collect_drop_candidates(path)
                all_candidates.extend(candidates)

            if not self._is_cancelled:
                self.finished.emit(all_candidates, self._is_aol_session_found)

        except Exception as e:
            logger.exception("Error scanning drop candidates")
            self.error.emit(str(e))

    def _collect_drop_candidates(self, path: Path) -> list[tuple[Path, type | None, dict | None]]:
        """Collect paths and their best-guess loaders recursively, avoiding session files."""
        if path.suffix.lower() == ".avv":
            self.session_found.emit(str(path))
            return []

        # ── AOL session folder detection ─────────────────────────────
        if path.is_dir():
            from avialview.loaders.aol_session_loader import is_aol_session

            if is_aol_session(path):
                return self._collect_aol_candidates(path)

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
                if not child.name.startswith("."):
                    candidates.extend(self._collect_drop_candidates(child))
        else:
            candidates.append((path, None, None))

        return candidates

    def _collect_aol_candidates(self, path: Path) -> list[tuple[Path, type | None, dict | None]]:
        """Build import candidates from an AOL session folder."""
        from avialview.loaders.aol_eks_loader import AOLEksLoader
        from avialview.loaders.aol_encoder_loader import AOLEncoderLoader
        from avialview.loaders.aol_session_loader import build_manifest

        manifest = build_manifest(path)

        # We need to pass the manifest anchor state back via config dicts since we
        # are no longer in MainWindow.
        anchor_epoch = 0.0
        if manifest.anchor_date:
            import datetime

            try:
                anchor = datetime.datetime.strptime(manifest.anchor_date, "%Y-%m-%d")
                anchor_epoch = anchor.replace(tzinfo=datetime.UTC).timestamp()
            except ValueError:
                pass

        candidates: list[tuple[Path, type | None, dict | None]] = []

        # We also need a way to tell the UI about the AOL session state.
        # We will inject a special "virtual" candidate that configures the session.
        candidates.append(
            (
                Path("virtual://aol_session_setup"),
                None,
                {
                    "camera_fps": manifest.camera_fps,
                    "anchor_epoch": anchor_epoch,
                    "skeleton": manifest.skeleton,
                },
            )
        )

        # 1. Videos (labeled preferred, raw fallback)
        for video in manifest.videos:
            loader_cls = self._registry.find_best_loader(video)
            if loader_cls is not None:
                start_epoch = 0.0
                for vid_path, epoch in manifest.video_start_epochs.items():
                    if Path(vid_path).name.lower() == video.name.lower():
                        start_epoch = epoch
                        break

                if anchor_epoch > 0.0 and start_epoch > 0.0:
                    start_epoch -= anchor_epoch

                config = {"offset": -start_epoch}
                if manifest.camera_fps > 0:
                    config["fps"] = manifest.camera_fps

                candidates.append((video, loader_cls, config))

        # 2. EKS 3D tracking files
        for eks_file in manifest.eks_files:
            start_epoch = 0.0
            cam_name_from_file = eks_file.name.split("_")[0]
            cam_name_from_dir = eks_file.parent.name.split("_")[0]

            for vid_path, epoch in manifest.video_start_epochs.items():
                vid_name = Path(vid_path).name
                if cam_name_from_file in vid_name or cam_name_from_dir in vid_name:
                    start_epoch = epoch
                    break

            if anchor_epoch > 0.0 and start_epoch > 0.0:
                start_epoch -= anchor_epoch

            eks_config: dict[str, Any] = {
                "fps": manifest.camera_fps,
                "start_epoch": start_epoch,
                "skeleton": manifest.skeleton,
                "auto_resolved": True,
                "_is_frame_indexed": True,  # Pre-computed
            }
            candidates.append((eks_file, AOLEksLoader, eks_config))

        # 3. Encoder log
        if manifest.encoder_file is not None:
            encoder_config: dict[str, Any] = (
                {"anchor_date": manifest.anchor_date, "auto_resolved": True}
                if manifest.anchor_date
                else {"auto_resolved": True}
            )
            candidates.append((manifest.encoder_file, AOLEncoderLoader, encoder_config))

        logger.info(
            "AOL session detected: %d candidates from %s (fps=%.1f)",
            len(candidates) - 1,  # -1 for virtual candidate
            path.name,
            manifest.camera_fps,
        )

        return candidates
