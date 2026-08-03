"""Background worker for scanning dropped files and classifying candidates."""

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from avialsync.core.registry import LoaderRegistry
from avialsync.core.source import TimeSeriesSource

logger = logging.getLogger(__name__)

# Marker row used to carry session-wide AOL settings (camera fps, anchor epoch,
# skeleton) back to the UI alongside the real files. Compare against this object
# with ``==``; never re-derive it from a string. Path("virtual://x") normalises to
# "virtual:\\x" on Windows, so a string round-trip silently stops matching and the
# marker leaks into the import list.
AOL_SESSION_SETUP = Path("virtual://aol_session_setup")


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
                    from avialsync.loaders.aol_session_loader import is_aol_session

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
            from avialsync.loaders.aol_session_loader import is_aol_session

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

    @staticmethod
    def _resolve_eks_start_epoch(eks_file: Path, manifest: Any) -> float:
        """Pick the camera start epoch a 3D EKS file should be timed against.

        The session-level file is literally named ``_eks.csv``, so its leading
        name token is empty -- and an empty token is a substring of every video
        name. Matching on it silently bound the file to whichever video came
        first. Blank tokens are ignored here, and a file that identifies no
        camera falls back to the earliest camera start with a log line rather
        than an arbitrary one.
        """
        epochs = manifest.video_start_epochs
        if not epochs:
            return 0.0

        tokens = [
            token
            for token in (eks_file.name.split("_")[0], eks_file.parent.name.split("_")[0])
            if token
        ]
        for token in tokens:
            for vid_path, epoch in epochs.items():
                if token.lower() in Path(vid_path).name.lower():
                    return float(epoch)

        earliest = min(epochs.values())
        logger.info(
            "3D EKS file %s names no camera; timing it from the earliest camera start (%.3f).",
            eks_file.name,
            earliest,
        )
        return float(earliest)

    def _collect_aol_candidates(self, path: Path) -> list[tuple[Path, type | None, dict | None]]:
        """Build import candidates from an AOL session folder."""
        from avialsync.loaders.aol_eks_loader import AOLEksLoader
        from avialsync.loaders.aol_encoder_loader import AOLEncoderLoader
        from avialsync.loaders.aol_session_loader import build_manifest

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
                AOL_SESSION_SETUP,
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
            start_epoch = self._resolve_eks_start_epoch(eks_file, manifest)

            if anchor_epoch > 0.0 and start_epoch > 0.0:
                start_epoch -= anchor_epoch

            eks_config: dict[str, Any] = {
                "fps": manifest.camera_fps,
                "start_epoch": start_epoch,
                "skeleton": manifest.skeleton,
                "auto_resolved": True,
                "_is_frame_indexed": True,  # Pre-computed
                # 3D pose drives the 3D view, not a plot row (D-046).
                "role": "pose3d",
            }
            candidates.append((eks_file, AOLEksLoader, eks_config))

        # 2b. Per-camera 2D pose predictions (ensemble + contributing models).
        # These overlay their own camera's video and are never plotted.
        video_by_camera = {
            label: video
            for label, video in zip(manifest.camera_labels, manifest.videos, strict=False)
        }
        for track in manifest.pose_2d_tracks:
            overlay_video = video_by_camera.get(track.camera)
            if overlay_video is None:
                logger.warning(
                    "Skipping 2D track %s: no video for camera %s", track.path.name, track.camera
                )
                continue
            loader_cls = self._registry.find_best_loader(track.path)
            if loader_cls is None:
                logger.warning("No loader found for 2D pose file %s", track.path.name)
                continue
            start_epoch = 0.0
            if overlay_video is not None:
                for vid_path, epoch in manifest.video_start_epochs.items():
                    if Path(vid_path).name.lower() == overlay_video.name.lower():
                        start_epoch = epoch
                        break

            if anchor_epoch > 0.0 and start_epoch > 0.0:
                start_epoch -= anchor_epoch

            candidates.append(
                (
                    track.path,
                    loader_cls,
                    {
                        "fps": manifest.camera_fps,
                        "offset": -start_epoch,
                        "auto_resolved": True,
                        "_is_frame_indexed": True,
                        # The overlay draws points only. Pose exports carry ~9
                        # columns per body part (likelihood, ensemble medians and
                        # variances); importing all of them built a pyramid per
                        # derived column and froze the UI on a real session.
                        "coords": ["x", "y"],
                        "role": "overlay2d",
                        "overlay_video": str(overlay_video),
                        "overlay_camera": track.camera,
                        "overlay_label": track.model,
                        "overlay_is_ensemble": track.is_ensemble,
                    },
                )
            )

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
