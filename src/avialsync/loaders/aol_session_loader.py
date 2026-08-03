"""AOL Session Folder Loader.

Detects an AOL multi-camera experiment folder by its signature files and
returns a structured manifest of files to load: labeled videos, EKS 3D
tracking data, and encoder log, with per-camera timing metadata.

This module provides folder-level detection and manifest building. The
actual file loading is routed through the normal AvialSync import pipeline
via the individual AOL loaders (AOLEncoderLoader, AOLEksLoader) and the
standard video loader.
"""

import datetime
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AOL2DTrack:
    """The fused 2D pose prediction bound to the camera it was tracked on.

    Exactly one per camera: the ensemble-fused ``*_eks`` result.  The individual
    contributing-model predictions it was built from are deliberately not
    loaded — they are intermediate pipeline output, and overlaying five nearly
    identical point clouds per camera obscures the very thing the fused result
    exists to show.  Tracks are overlaid on their camera's video, never plotted.
    """

    path: Path
    camera: str
    # "eks" for the fused result, otherwise the model directory name.
    model: str

    @property
    def is_ensemble(self) -> bool:
        """Whether this is the fused ensemble result rather than a single model."""
        return self.model == "eks"


@dataclass
class AOLManifest:
    """Structured manifest of files in an AOL session folder."""

    session_dir: Path
    # Labeled videos (preferred) or raw camera videos
    videos: list[Path] = field(default_factory=list)
    # Camera labels derived from video filenames
    camera_labels: list[str] = field(default_factory=list)
    # EKS 3D tracking CSV (usually one per session)
    eks_files: list[Path] = field(default_factory=list)
    # One fused 2D pose prediction per camera (the ensemble *_eks result)
    pose_2d_tracks: list[AOL2DTrack] = field(default_factory=list)
    # Encoder log file
    encoder_file: Path | None = None
    # Per-camera relative timing files
    timing_files: dict[str, Path] = field(default_factory=dict)
    # Parsed video start epochs (float UTC epoch), mapping video str(Path) to epoch
    video_start_epochs: dict[str, float] = field(default_factory=dict)
    # Parsed anchor date for encoder (YYYY-MM-DD)
    anchor_date: str | None = None
    # Camera fps from trial_config.yml
    camera_fps: float = 30.0
    # Trial config metadata
    trial_config: dict[str, object] = field(default_factory=dict)
    # Skeleton mapping from trial config
    skeleton: list[tuple[str, str]] = field(default_factory=list)


def is_aol_session(path: Path) -> bool:
    """Return True if the directory has AOL session signature files.

    An AOL session folder is identified by having at least:
    - One or more camera .mp4 files (or a labeled_videos/ subdir)
    - At least one *-relative times.txt file
    """
    if not path.is_dir():
        return False

    has_timing = any(path.glob("*-relative times.txt"))
    has_video = any(path.glob("*.mp4")) or (path / "labeled_videos").is_dir()

    return has_timing and has_video


def build_manifest(session_dir: Path) -> AOLManifest:
    """Scan an AOL session folder and build a loading manifest.

    Priority for videos:
    1. Root *.mp4 (raw camera recordings)
    2. labeled_videos/*.mp4, only when no raw recording exists

    Raw footage wins because AvialSync draws the pose itself, live, from the
    prediction CSVs. A ``labeled_videos`` render has the same points burned into
    the pixels, so loading it would show every marker twice and make the overlay
    impossible to toggle, recolour, or read a value from.

    The manifest includes camera fps from trial_config.yml when available.
    """
    manifest = AOLManifest(session_dir=session_dir)

    # ── Read trial_config.yml if present ─────────────────────────────
    config_path = session_dir / "trial_config.yml"
    if config_path.is_file():
        manifest.trial_config = _read_trial_config(config_path)
        hw = manifest.trial_config.get("hardware", {})
        if isinstance(hw, dict) and "camera_fps" in hw:
            try:
                manifest.camera_fps = float(hw["camera_fps"])  # type: ignore[arg-type]
            except (ValueError, TypeError):
                pass

        skeleton = manifest.trial_config.get("skeleton")
        if isinstance(skeleton, dict):
            # The custom YAML parser might leave "- " list markers on keys/values
            manifest.skeleton = [
                (str(k).lstrip("- "), str(v).lstrip("- ")) for k, v in skeleton.items()
            ]
        elif isinstance(skeleton, list):
            edges = []
            for item in skeleton:
                if isinstance(item, dict):
                    for k, v in item.items():
                        edges.append((str(k), str(v)))
                elif isinstance(item, list) and len(item) == 2:
                    edges.append((str(item[0]), str(item[1])))
            manifest.skeleton = edges

    # ── Discover videos ──────────────────────────────────────────────
    # Raw footage first: the overlay is drawn live, so a pre-rendered
    # labeled_videos copy would double every marker.
    _add_root_videos(session_dir, manifest)
    if not manifest.videos:
        labeled_dir = session_dir / "labeled_videos"
        if labeled_dir.is_dir():
            labeled_videos = sorted(labeled_dir.glob("*.mp4"))
            if labeled_videos:
                logger.info(
                    "No raw camera MP4s in %s; falling back to %d labeled video(s).",
                    session_dir.name,
                    len(labeled_videos),
                )
                manifest.videos = labeled_videos
                manifest.camera_labels = [_camera_label_from_labeled(v) for v in labeled_videos]

    # ── Discover EKS tracking files ──────────────────────────────────
    # Search in pose-3d/*/ subdirectories
    pose_3d = session_dir / "pose-3d"
    if pose_3d.is_dir():
        for sub in pose_3d.iterdir():
            if sub.is_dir():
                for csv_file in sub.glob("*_eks*.csv"):
                    manifest.eks_files.append(csv_file)

    # Also check directly in session dir
    for csv_file in session_dir.glob("*_eks*.csv"):
        manifest.eks_files.append(csv_file)

    manifest.eks_files.sort()

    # ── Discover 2D per-camera pose predictions ──────────────────────
    manifest.pose_2d_tracks = _collect_2d_tracks(session_dir, manifest.camera_labels)

    # ── Discover encoder log ─────────────────────────────────────────
    encoder = session_dir / "encoder_log.txt"
    if encoder.is_file():
        manifest.encoder_file = encoder

    # ── Discover per-camera timing files ─────────────────────────────
    for timing_file in sorted(session_dir.glob("*-relative times.txt")):
        # Extract camera name: "FaceCam-relative times.txt" → "FaceCam"
        cam_name = timing_file.name.replace("-relative times.txt", "")
        manifest.timing_files[cam_name] = timing_file

        # Parse first line to extract absolute UTC epoch start time
        try:
            with open(timing_file, encoding="utf-8") as f:
                first_line = f.readline().strip()
                if first_line:
                    parts = first_line.split()
                    if len(parts) >= 3:
                        # Format: "1 0.000 08-05-2026;09:35:26.3120"
                        ts = parts[2]
                        dt = datetime.datetime.strptime(ts, "%d-%m-%Y;%H:%M:%S.%f").replace(
                            tzinfo=datetime.UTC
                        )
                        epoch = dt.timestamp()

                        # Match video file to this camera
                        for video in manifest.videos:
                            if _camera_label_from_labeled(video) == cam_name:
                                manifest.video_start_epochs[str(video)] = epoch

                        # Use the first parsed date as the global encoder anchor date
                        if manifest.anchor_date is None:
                            manifest.anchor_date = dt.strftime("%Y-%m-%d")
        except Exception as e:
            logger.warning("Failed to parse timing file %s: %s", timing_file.name, e)

    logger.info(
        "AOL manifest: %d videos, %d EKS files, encoder=%s, %d timing files, fps=%.1f",
        len(manifest.videos),
        len(manifest.eks_files),
        "yes" if manifest.encoder_file else "no",
        len(manifest.timing_files),
        manifest.camera_fps,
    )

    return manifest


def _collect_2d_tracks(session_dir: Path, camera_labels: list[str]) -> list[AOL2DTrack]:
    """Find the fused per-camera 2D pose CSV under ``predictions/``.

    Layout produced by the Lightning Pose / EKS pipeline::

        predictions/<model_tag>/<Camera>_eks.csv     <- ensemble result  (loaded)
        predictions/<model_tag>/model_N/<Camera>.csv <- contributing model (skipped)

    Only the ensemble result is loaded: one track per camera.  The contributing
    per-model predictions are intermediate output, and drawing all of them puts
    several nearly-coincident point clouds on one frame.
    ``*_eks_input.csv`` is pipeline input, not a prediction, and is ignored.

    Files whose camera cannot be identified are skipped with a warning rather
    than guessed at, so a mislabelled export never lands on the wrong video.
    """
    predictions = session_dir / "predictions"
    if not predictions.is_dir():
        return []

    by_camera: dict[str, AOL2DTrack] = {}
    for model_dir in sorted(predictions.iterdir()):
        if not model_dir.is_dir():
            continue
        for csv_file in sorted(model_dir.glob("*.csv")):
            stem = csv_file.stem.lower()
            if not stem.endswith("_eks") or stem.endswith("_eks_input"):
                continue
            camera = _match_camera(csv_file.stem, camera_labels)
            if camera is None:
                logger.warning("Skipping 2D pose file with unknown camera: %s", csv_file.name)
                continue
            if camera in by_camera:
                logger.warning(
                    "Camera %s already has a fused 2D track (%s); ignoring %s.",
                    camera,
                    by_camera[camera].path.name,
                    csv_file.name,
                )
                continue
            by_camera[camera] = AOL2DTrack(path=csv_file, camera=camera, model="eks")

    tracks = [by_camera[camera] for camera in sorted(by_camera)]
    logger.info("AOL 2D tracks: one fused overlay for each of %d camera(s)", len(tracks))
    return tracks


def _match_camera(stem: str, camera_labels: list[str]) -> str | None:
    """Resolve a file stem to one of the session's cameras.

    Longest label first so ``SideCam`` cannot be shadowed by a shorter prefix,
    and empty labels are never used as a match (an empty token would otherwise
    match every filename).
    """
    lowered = stem.lower()
    for label in sorted((c for c in camera_labels if c), key=len, reverse=True):
        if lowered.startswith(label.lower()):
            return label
    return None


def _add_root_videos(session_dir: Path, manifest: AOLManifest) -> None:
    """Add root-level camera MP4s to the manifest."""
    root_videos = sorted(v for v in session_dir.glob("*.mp4") if not v.name.startswith("."))
    manifest.videos = root_videos
    manifest.camera_labels = [v.stem for v in root_videos]


def _camera_label_from_labeled(video_path: Path) -> str:
    """Extract camera label from a labeled video filename.

    Example: "FaceCam_eks_raw_models_labeled_default_sv_singleview_ens3.mp4"
    → "FaceCam"
    """
    stem = video_path.stem
    # The camera name is the first part before the first underscore
    # that matches a known camera naming pattern
    parts = stem.split("_")
    if parts:
        return parts[0]
    return stem


def _read_trial_config(path: Path) -> dict[str, object]:
    """Parse a simple YAML trial config without requiring PyYAML.

    Handles the flat key:value and one-level nested structure typical
    of AOL trial_config.yml files.
    """
    config: dict[str, object] = {}
    current_section: dict[str, object] | None = None

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                stripped = line.rstrip()
                if not stripped or stripped.startswith("#"):
                    continue

                indent = len(line) - len(line.lstrip())

                if indent == 0:
                    # Top-level key
                    if ":" in stripped:
                        key, _, value = stripped.partition(":")
                        key = key.strip()
                        value = value.strip()
                        if value:
                            config[key] = _yaml_value(value)
                            current_section = None
                        else:
                            # Start of a nested section
                            current_section = {}
                            config[key] = current_section

                elif current_section is not None and indent > 0:
                    # Nested key
                    if ":" in stripped:
                        key, _, value = stripped.partition(":")
                        key = key.strip()
                        value = value.strip()
                        current_section[key] = _yaml_value(value)
    except (OSError, UnicodeError) as exc:
        logger.warning("Could not read trial config %s: %s", path, exc)

    return config


def _yaml_value(value: str) -> object:
    """Convert a simple YAML scalar to a Python value."""
    if value.lower() in ("true", "yes"):
        return True
    if value.lower() in ("false", "no"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value
