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
from typing import Any

from avialsync.core.source import SessionItem, SessionLayout, SessionSource

logger = logging.getLogger(__name__)

#: Anatomical order of the AOL rig: up one forelimb, across the head bar, and
#: down the other. Consecutive members are bones; the chain is walked in order,
#: so a rig missing a joint links straight across it — a session without
#: ``left_elbow`` joins ``left_paw`` to ``left_shoulder`` rather than losing
#: that side of the animal to two dropped edges.
#:
#: This is the AOL pipeline's own rig, not a guess about anatomy in general:
#: it applies only to a folder ``AOLSessionSource`` claimed, only when
#: ``trial_config.yml`` declares no skeleton of its own, and only to the parts
#: the EKS export actually contains. A rig it does not recognise produces
#: nothing and leaves the 3D view to detect its own (D-082).
#: One Data Streams lane for everything the pipeline derived from the cameras:
#: 3D pose, per-camera 2D pose, and the extracted ROI metrics. They are read
#: from the same videos frame for frame, so their coverage spans are the same
#: span, and one recording drew seven identical lanes above the encoder trace
#: whose span is the only one that differs. The videos keep their own lanes:
#: that a camera is present is not the same statement as that it was tracked.
VIDEO_DERIVED_COVERAGE_GROUP = "Video tracking"

DEFAULT_SKELETON_CHAIN: tuple[str, ...] = (
    "left_toe",
    "left_paw",
    "left_elbow",
    "left_shoulder",
    "head_bar",
    "right_shoulder",
    "right_elbow",
    "right_paw",
    "right_toe",
)


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


@dataclass(frozen=True)
class AOLMetricFile:
    """One (ROI, metric) extraction result under a `data_root`-style export.

    Layout is fixed by the optical-flow/MI toolbox's own contract
    (``avialsync_data_schema.md`` §2): ``<video_type>/<roi_id>__<metric>.mat``,
    with ``video_type`` the same camera name AOL's own videos and timing files
    use, sanitized. ``camera`` here is already resolved back to AOL's own
    camera label where possible -- see ``_collect_extracted_metrics``.
    """

    path: Path
    camera: str
    roi_id: str
    metric: str


@dataclass(frozen=True)
class AOLVideoExtraction:
    """One camera's exported ROI metrics from the video-extraction toolbox.

    The export is ``video-extraction/<variant>/<Camera>.mat`` (MATLAB v7.3 /
    HDF5) beside its ``<Camera>.metadata.json`` sidecar. Preferred over the
    upstream per-``(ROI, metric)`` v6 store, which holds the same numbers but
    no time axis, no ROI labels and no ROI geometry.
    """

    path: Path
    camera: str
    variant: str
    metrics: tuple[str, ...]


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
    # Extracted per-frame metrics (optical flow / motion index / etc.) found
    # anywhere under the session, keyed to the same cameras as the videos.
    metric_files: list[AOLMetricFile] = field(default_factory=list)
    # One exported ROI-metric file per camera from the video-extraction toolbox.
    video_extraction_files: list[AOLVideoExtraction] = field(default_factory=list)
    # Encoder log file
    encoder_file: Path | None = None
    # Per-camera relative timing files
    timing_files: dict[str, Path] = field(default_factory=dict)
    # Parsed video start epochs (float UTC epoch), mapping video str(Path) to epoch
    video_start_epochs: dict[str, float] = field(default_factory=dict)
    # Parsed video start epochs, keyed by camera label instead of video path --
    # metric files have no video of their own to match against.
    camera_start_epochs: dict[str, float] = field(default_factory=dict)
    # Parsed anchor date for encoder (YYYY-MM-DD)
    anchor_date: str | None = None
    # Camera fps from trial_config.yml
    camera_fps: float = 30.0
    # Trial config metadata
    trial_config: dict[str, object] = field(default_factory=dict)
    # Skeleton mapping from trial config
    skeleton: list[tuple[str, str]] = field(default_factory=list)


def _eks_bodyparts(path: Path) -> list[str]:
    """Body-part names in an EKS export, from its header line alone.

    One ``readline``: this runs for every claimed folder on the scan thread,
    and the file is the session's full 3D trajectory.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            header = handle.readline().strip()
    except (OSError, UnicodeError) as exc:
        logger.warning("Could not read EKS header %s: %s", path, exc)
        return []

    bodyparts: list[str] = []
    for column in (c.strip() for c in header.split(",")):
        if column.endswith(("_x", "_y", "_z")):
            name = column[:-2]
            if name and name not in bodyparts:
                bodyparts.append(name)
    return bodyparts


def default_skeleton(bodyparts: list[str]) -> list[tuple[str, str]]:
    """Bones between consecutive :data:`DEFAULT_SKELETON_CHAIN` parts that exist.

    Matching is by suffix, because a column may still carry the model prefix
    the EKS loader strips later (``ensemble_head_bar`` is ``head_bar``). The
    chain name is what comes back, which is what the loader names the channel
    and therefore what the 3D view sees.

    Returns nothing when fewer than two chain members are present: one bone
    drawn across an unrecognised rig is worse than none, and none is what hands
    the view over to its own detection.
    """
    present = [name for name in DEFAULT_SKELETON_CHAIN if _has_bodypart(name, bodyparts)]
    if len(present) < 2:
        return []
    return list(zip(present, present[1:], strict=False))


def _has_bodypart(name: str, bodyparts: list[str]) -> bool:
    """Whether *name* is one of *bodyparts*, prefixed or not."""
    return any(part == name or part.endswith(f"_{name}") for part in bodyparts)


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

    # The rig's own skeleton, for a session that declared none of its own.
    if not manifest.skeleton and manifest.eks_files:
        manifest.skeleton = default_skeleton(_eks_bodyparts(manifest.eks_files[0]))
        if manifest.skeleton:
            logger.info(
                "No skeleton in trial_config.yml; using the AOL rig's %d default bones.",
                len(manifest.skeleton),
            )

    # ── Discover 2D per-camera pose predictions ──────────────────────
    manifest.pose_2d_tracks = _collect_2d_tracks(session_dir, manifest.camera_labels)

    # ── Discover extracted per-frame metrics (optical flow / MI / etc.) ──
    (
        manifest.video_extraction_files,
        manifest.metric_files,
    ) = _collect_extracted_metrics(session_dir, manifest.camera_labels)

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
                        manifest.camera_start_epochs[cam_name] = epoch

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


def _collect_extracted_metrics(
    session_dir: Path, camera_labels: list[str]
) -> tuple[list[AOLVideoExtraction], list[AOLMetricFile]]:
    """Find both extracted-metric stores in one walk of the session folder.

    Two formats, one traversal. The toolbox's per-camera *export* is
    ``video-extraction/<variant>/<Camera>.mat`` beside a JSON sidecar, and its
    upstream store is one ``<roi_id>__<metric>.mat`` per (ROI, metric) under a
    ``data_root``. Neither lives at a fixed path -- the export tree can be
    emitted under a separate root, and ``data_root``'s own name follows the
    lab's ``export_filename`` -- so both are recognised by what the file *is*
    rather than where it sits (D-080, D-081).

    They are collected together because a session that carries the upstream
    store carries thousands of those small files, and walking the tree twice to
    ask two questions about the same paths doubles that cost for nothing.

    An export supersedes the upstream store for its camera: the two hold the
    same numbers, and importing both would plot every ROI twice, once on the
    export's real timestamps and once on timestamps synthesised from
    ``index / fps``.

    A MATLAB file that is neither -- another tool's output in the same tree --
    matches nothing and is ignored. ``thumbnail.mat`` is a static reference
    image with no ``roi_id`` prefix, so it never matches either.
    """
    from avialsync.loaders.aol_metric_loader import ROI_METRIC_FILENAME_RE
    from avialsync.loaders.aol_video_extraction_loader import read_sidecar

    exports: list[AOLVideoExtraction] = []
    from_store: list[AOLMetricFile] = []

    for mat_file in sorted(session_dir.rglob("*.mat")):
        meta = read_sidecar(mat_file)
        if meta is not None:
            metrics = meta.get("metrics")
            exports.append(
                AOLVideoExtraction(
                    path=mat_file,
                    camera=str(meta.get("camera") or mat_file.stem),
                    variant=str(meta.get("variant") or mat_file.parent.name),
                    metrics=tuple(str(m) for m in metrics) if isinstance(metrics, list) else (),
                )
            )
            continue

        match = ROI_METRIC_FILENAME_RE.match(mat_file.name)
        if match is None:
            continue
        # The parent folder is the toolbox's `video_type`. Resolve it back to
        # one of AOL's own camera labels with the same longest-match rule 2D
        # pose files use, since the toolbox sanitises punctuation to `_`. A
        # folder matching no known camera keeps its raw name, so a store
        # dropped without its sibling videos still loads -- just unaligned.
        raw_camera = mat_file.parent.name
        camera = _match_camera(raw_camera, camera_labels) or raw_camera
        from_store.append(
            AOLMetricFile(
                path=mat_file, camera=camera, roi_id=match.group(1), metric=match.group(2)
            )
        )

    superseded = {export.camera for export in exports}
    metric_files = [metric for metric in from_store if metric.camera not in superseded]

    if exports:
        logger.info(
            "AOL manifest: %d video-extraction export(s) for camera(s) %s",
            len(exports),
            ", ".join(sorted(superseded)),
        )
    if metric_files:
        logger.info(
            "AOL manifest: %d per-ROI metric file(s) across %d camera folder(s)",
            len(metric_files),
            len({metric.camera for metric in metric_files}),
        )
    if len(from_store) != len(metric_files):
        logger.info(
            "Ignoring %d per-ROI metric file(s) superseded by a video-extraction export.",
            len(from_store) - len(metric_files),
        )
    return exports, metric_files


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
    of AOL trial_config.yml files. A section written as a YAML *sequence*
    becomes a list, not a mapping: a skeleton branches, so ``head_bar`` is the
    first name of two edges at once, and folding those lines into one dict
    kept only the last of them — a rig lost its shoulders and one leg to a
    parser detail, with no error anywhere to say so.
    """
    config: dict[str, object] = {}
    current_key: str | None = None
    current_section: dict[str, object] | list[object] | None = None

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                stripped = line.rstrip()
                if not stripped or stripped.lstrip().startswith("#"):
                    continue

                indent = len(line) - len(line.lstrip())
                if indent == 0:
                    key, _, value = stripped.partition(":")
                    if not _:
                        continue
                    current_key, current_section = key.strip(), None
                    if value.strip():
                        config[current_key] = _yaml_value(value.strip())
                        current_key = None
                elif current_key is not None:
                    current_section = _append_config_entry(
                        config, current_key, current_section, stripped.strip()
                    )
    except (OSError, UnicodeError) as exc:
        logger.warning("Could not read trial config %s: %s", path, exc)

    return config


def _append_config_entry(
    config: dict[str, object],
    section_key: str,
    section: dict[str, object] | list[object] | None,
    entry: str,
) -> dict[str, object] | list[object] | None:
    """Add one indented line to its section, creating it as list or mapping."""
    is_item = entry.startswith("-")
    if is_item:
        entry = entry[1:].strip()
    if section is None:
        section = [] if is_item else {}
        config[section_key] = section

    key, separator, value = entry.partition(":")
    if isinstance(section, list):
        if separator:
            section.append({key.strip(): _yaml_value(value.strip())})
        elif entry:
            section.append(_yaml_value(entry))
    elif separator:
        section[key.strip()] = _yaml_value(value.strip())
    return section


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


class AOLSessionSource(SessionSource):
    """Lay out an AOL multi-camera experiment folder as a session.

    This is the reference implementation of :class:`SessionSource`, and the
    reason that ABC exists: the layout below used to live inside
    ``engine/drop_worker.py``, which meant the application's own drop path
    imported one lab's format by name. Another rig with a comparable folder had
    no way in short of editing that file. Everything AOL-specific now lives
    here, and the drop path knows only "some plugin claims this directory".

    All timing is expressed on one axis. The encoder log is written as
    seconds-since-midnight UTC, so video and pose start epochs are rebased onto
    the same axis by subtracting the session's anchor epoch (D-045); do not
    "fix" that by adding the anchor to encoder timestamps instead, which shifts
    it by roughly 20 days.
    """

    @classmethod
    def display_name(cls) -> str:
        return "AOL Session"

    @classmethod
    def can_open(cls, path: Path) -> float:
        return 1.0 if is_aol_session(path) else 0.0

    def scan(self, path: Path, registry: Any) -> SessionLayout:
        manifest = build_manifest(path)
        anchor_epoch = _anchor_epoch(manifest)

        items: list[SessionItem] = []
        items.extend(_video_items(manifest, anchor_epoch, registry))
        items.extend(_eks_items(manifest, anchor_epoch))
        items.extend(_pose_2d_items(manifest, anchor_epoch, registry))
        items.extend(_video_extraction_items(manifest, anchor_epoch))
        items.extend(_metric_items(manifest, anchor_epoch))
        items.extend(_encoder_items(manifest))

        logger.info(
            "AOL session detected: %d items from %s (fps=%.1f)",
            len(items),
            path.name,
            manifest.camera_fps,
        )
        return SessionLayout(
            items=items,
            anchor_epoch=anchor_epoch,
            camera_fps=manifest.camera_fps,
            skeleton=manifest.skeleton,
        )


def _anchor_epoch(manifest: AOLManifest) -> float:
    """Return the session's UTC midnight anchor, or 0.0 when it declares none."""
    if not manifest.anchor_date:
        return 0.0
    try:
        anchor = datetime.datetime.strptime(manifest.anchor_date, "%Y-%m-%d")
    except ValueError:
        return 0.0
    return anchor.replace(tzinfo=datetime.UTC).timestamp()


def _rebased(start_epoch: float, anchor_epoch: float) -> float:
    """Move an absolute start epoch onto the session's seconds-since-midnight axis."""
    if anchor_epoch > 0.0 and start_epoch > 0.0:
        return start_epoch - anchor_epoch
    return start_epoch


def _start_epoch_for(manifest: AOLManifest, video: Path) -> float:
    for vid_path, epoch in manifest.video_start_epochs.items():
        if Path(vid_path).name.lower() == video.name.lower():
            return float(epoch)
    return 0.0


def _video_items(manifest: AOLManifest, anchor_epoch: float, registry: Any) -> list[SessionItem]:
    """Cameras, deferred to whatever loader can read the container."""
    items: list[SessionItem] = []
    for video in manifest.videos:
        loader_cls = registry.find_best_loader(video)
        if loader_cls is None:
            logger.warning("No loader found for AOL video %s", video.name)
            continue
        start_epoch = _rebased(_start_epoch_for(manifest, video), anchor_epoch)
        config: dict[str, Any] = {"offset": -start_epoch}
        if manifest.camera_fps > 0:
            config["fps"] = manifest.camera_fps
        items.append(SessionItem(video, loader_cls, config, label=f"{video.name} — camera"))
    return items


def _eks_items(manifest: AOLManifest, anchor_epoch: float) -> list[SessionItem]:
    """3D triangulated pose, which drives the 3D view rather than a plot row (D-046)."""
    from avialsync.loaders.aol_eks_loader import AOLEksLoader

    items: list[SessionItem] = []
    for eks_file in manifest.eks_files:
        start_epoch = _rebased(resolve_eks_start_epoch(eks_file, manifest), anchor_epoch)
        items.append(
            SessionItem(
                eks_file,
                AOLEksLoader,
                {
                    "fps": manifest.camera_fps,
                    "start_epoch": start_epoch,
                    "skeleton": manifest.skeleton,
                    "auto_resolved": True,
                    "_is_frame_indexed": True,
                    "role": "pose3d",
                },
                # Named by where it goes, not by what reads it. A session emits
                # one 3D file and one 2D file per camera, all ending "_eks.csv"
                # and all detected as "Tracking Data (2D/3D)" — and none of them
                # becomes a plot row (D-046), so the filename alone left no way
                # to tell which drives the 3D view and which paint a video.
                label=f"{eks_file.name} — 3D pose",
                coverage_group=VIDEO_DERIVED_COVERAGE_GROUP,
            )
        )
    return items


def _pose_2d_items(manifest: AOLManifest, anchor_epoch: float, registry: Any) -> list[SessionItem]:
    """Per-camera 2D pose, drawn over its own video and never plotted."""
    items: list[SessionItem] = []
    video_by_camera = {
        label: video for label, video in zip(manifest.camera_labels, manifest.videos, strict=False)
    }
    for track in manifest.pose_2d_tracks:
        overlay_video = video_by_camera.get(track.camera)
        if overlay_video is None:
            logger.warning(
                "Skipping 2D track %s: no video for camera %s", track.path.name, track.camera
            )
            continue
        loader_cls = registry.find_best_loader(track.path)
        if loader_cls is None:
            logger.warning("No loader found for 2D pose file %s", track.path.name)
            continue
        start_epoch = _rebased(_start_epoch_for(manifest, overlay_video), anchor_epoch)
        items.append(
            SessionItem(
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
                label=f"{track.path.name} — 2D pose over {track.camera}",
                coverage_group=VIDEO_DERIVED_COVERAGE_GROUP,
            )
        )
    return items


def _video_extraction_items(manifest: AOLManifest, anchor_epoch: float) -> list[SessionItem]:
    """Exported ROI metrics, plotted like any other recorded signal.

    No ``role`` is set: unlike the pose exports sitting in the same recording
    folder (D-046), these are ordinary sensor traces and belong on plot rows.

    Both timing reference points are handed over rather than one resolved
    offset, because only the loader discovers which axis its file actually
    carries -- an absolute POSIX one needs the anchor subtracted, while a
    recording-relative one needs the camera's rebased start added, and telling
    them apart at scan time would mean opening every HDF5 file.

    Where the camera's own start is known, ``time_base`` asks for it to be the
    anchor. The export's ``absolute_times`` is true POSIX, converted from the
    camera's *local* wall clock at export time, while this session's axis is
    that wall clock read as seconds since midnight (D-045). On the reference
    session the two differ by exactly the site's UTC offset, which placed every
    ROI metric one hour before the video it came from. The camera start carries
    no time zone, so it is the one reference both sides already agree on.
    """
    from avialsync.loaders.aol_video_extraction_loader import (
        TIME_BASE_CAMERA_START,
        AOLVideoExtractionLoader,
    )

    items: list[SessionItem] = []
    for export in manifest.video_extraction_files:
        camera_epoch = _start_epoch_for_camera(manifest, export.camera)
        start_epoch = _rebased(camera_epoch, anchor_epoch)
        config: dict[str, Any] = {
            "anchor_epoch": anchor_epoch,
            "start_epoch": start_epoch,
            "auto_resolved": True,
        }
        if camera_epoch > 0.0:
            # Tested on the camera's own epoch, not on the rebased start: a
            # camera that began exactly at the anchor rebases to 0.0, which is
            # a real start rather than a missing one.
            config["time_base"] = TIME_BASE_CAMERA_START
        metrics = ", ".join(export.metrics) if export.metrics else "ROI metrics"
        items.append(
            SessionItem(
                export.path,
                AOLVideoExtractionLoader,
                config,
                label=f"{export.path.name} - {export.camera} {metrics}",
                coverage_group=VIDEO_DERIVED_COVERAGE_GROUP,
            )
        )
    return items


def _start_epoch_for_camera(manifest: AOLManifest, camera: str) -> float:
    return manifest.camera_start_epochs.get(camera, 0.0)


def _metric_items(manifest: AOLManifest, anchor_epoch: float) -> list[SessionItem]:
    """Extracted per-frame metrics (optical flow / motion index / etc.).

    No ``role`` is set: unlike pose data (D-046) these are ordinary recorded
    signals, so they become plot rows just like the encoder trace.
    """
    from avialsync.loaders.aol_metric_loader import AOLMetricLoader

    items: list[SessionItem] = []
    for metric_file in manifest.metric_files:
        start_epoch = _rebased(_start_epoch_for_camera(manifest, metric_file.camera), anchor_epoch)
        items.append(
            SessionItem(
                metric_file.path,
                AOLMetricLoader,
                {
                    "fps": manifest.camera_fps,
                    "start_epoch": start_epoch,
                    "metric": metric_file.metric,
                    "auto_resolved": True,
                    "_is_frame_indexed": True,
                },
                label=(
                    f"{metric_file.path.name} — {metric_file.camera} "
                    f"{metric_file.metric.replace('_', ' ')}"
                ),
                coverage_group=VIDEO_DERIVED_COVERAGE_GROUP,
            )
        )
    return items


def _encoder_items(manifest: AOLManifest) -> list[SessionItem]:
    """The rotary encoder trace, already on the session's own time axis."""
    from avialsync.loaders.aol_encoder_loader import AOLEncoderLoader

    if manifest.encoder_file is None:
        return []
    config: dict[str, Any] = {"auto_resolved": True}
    if manifest.anchor_date:
        config["anchor_date"] = manifest.anchor_date
    return [
        SessionItem(
            manifest.encoder_file,
            AOLEncoderLoader,
            config,
            label=f"{manifest.encoder_file.name} — rotary encoder",
        )
    ]


def resolve_eks_start_epoch(eks_file: Path, manifest: AOLManifest) -> float:
    """Pick the camera start epoch a 3D EKS file should be timed against.

    The session-level file is literally named ``_eks.csv``, so its leading name
    token is empty -- and an empty token is a substring of every video name.
    Matching on it silently bound the file to whichever video came first. Blank
    tokens are ignored here, and a file that identifies no camera falls back to
    the earliest camera start with a log line rather than an arbitrary one.
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
