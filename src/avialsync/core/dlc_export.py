"""Writing corrected frames as DeepLabCut labeled data, for a retraining loop.

The other export (:mod:`avialsync.core.pose_export`) answers "what should the
analysis use".  This one answers "what should the network learn from": the
frames a person corrected, in the layout DeepLabCut's ``labeled-data`` folders
use, so they can be merged into a training set and the model retrained on its
own mistakes.

Two things follow from that purpose and neither is optional.

**Every body part on a corrected frame is written, not only the corrected one.**
A training label is a whole pose.  Emitting the one coordinate a person moved
and leaving the rest blank would teach the network that the other body parts are
absent from the frame — the opposite of what the correction meant.  So the
caller supplies the model's own prediction for the frame and this writes it with
the corrections substituted in.

**A body part with no coordinate is written empty, never as zero.**  ``0,0`` is a
position in the image, and the top-left corner is where an unlabelled part would
end up teaching the network to look.  DLC reads an empty cell as "not labelled
in this frame", which is what an untracked part actually is.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from avialsync.core.artifact_io import publish
from avialsync.core.artifact_provenance import record, write_companion

logger = logging.getLogger(__name__)

__all__ = [
    "LabeledFrame",
    "LabeledDataReport",
    "collected_data_path",
    "training_csv_path",
    "write_labeled_data",
]

#: DLC keys each labelled image by its path relative to the project root.
_IMAGE_ROOT = "labeled-data"


@dataclass(frozen=True)
class LabeledFrame:
    """One frame's full pose, as it will be written.

    ``positions`` maps a body-part name to its ``(x, y)``; a part that has no
    coordinate on this frame is simply absent from the mapping.
    """

    frame: int
    positions: dict[str, tuple[float, float]]


@dataclass(frozen=True)
class LabeledDataReport:
    """What a labeled-data export turned out to contain."""

    frames: int = 0
    labelled_points: int = 0
    #: Body parts with no coordinate on a written frame. Reported because a
    #: training set that is half empty is worth knowing about before it is used.
    missing_points: int = 0


def image_name(frame: int) -> str:
    """Return DLC's image file name for a frame number."""
    return f"img{frame:05d}.png"


def image_relative_path(video_stem: str, frame: int) -> str:
    """Return the project-relative image path DLC keys a labelled frame by."""
    return f"{_IMAGE_ROOT}/{video_stem}/{image_name(frame)}"


def collected_data_path(root: Path | str, video_stem: str, scorer: str) -> Path:
    """Return the ``CollectedData_<scorer>.csv`` for one video's labelled frames."""
    return Path(root) / _IMAGE_ROOT / video_stem / f"CollectedData_{scorer}.csv"


def training_csv_path(root: Path | str, video_stem: str, scorer: str, profile: str) -> Path:
    """Locate a label CSV inside a bundle ready to copy into a project root."""
    if not scorer or any(char in scorer for char in '<>:"/\\|?*'):
        raise ValueError("Enter a portable scorer name from the target project.")
    if profile == "dlc":
        return collected_data_path(root, video_stem, scorer)
    if profile == "lightning_pose":
        return Path(root) / "CollectedData.csv"
    raise ValueError(f"Unknown training format: {profile}")


def write_labeled_data(
    target: Path | str,
    video_stem: str,
    scorer: str,
    bodyparts: list[str],
    frames: list[LabeledFrame],
    *,
    sources: tuple[Path | str, ...] = (),
    point_labels: Mapping[str, tuple[str, str]] | None = None,
    kind: str = "dlc-retraining",
) -> LabeledDataReport:
    """Write *frames* as a DLC ``CollectedData`` CSV at *target*.

    ``bodyparts`` fixes the column order, so every frame is written against the
    same layout whether or not it has a coordinate for each part.
    """
    target_path = Path(target)
    # The one export that creates directories, because ``labeled-data/<video>/``
    # is part of the format rather than part of the path the user chose: DLC
    # will not read a labelled set that is not nested this way.
    target_path.parent.mkdir(parents=True, exist_ok=True)

    scorer_row = ["scorer"]
    individual_row = ["individuals"] if point_labels else None
    bodypart_row = ["bodyparts"]
    coord_row = ["coords"]
    for part in bodyparts:
        individual, bodypart = point_labels[part] if point_labels else ("", part)
        scorer_row += [scorer, scorer]
        if individual_row is not None:
            individual_row += [individual, individual]
        bodypart_row += [bodypart, bodypart]
        coord_row += ["x", "y"]

    labelled = 0
    missing = 0

    def write(temporary: Path) -> None:
        nonlocal labelled, missing
        with open(temporary, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(scorer_row)
            if individual_row is not None:
                writer.writerow(individual_row)
            writer.writerow(bodypart_row)
            writer.writerow(coord_row)
            for item in sorted(frames, key=lambda frame: frame.frame):
                row: list[str] = [image_relative_path(video_stem, item.frame)]
                for part in bodyparts:
                    position = item.positions.get(part)
                    if position is None:
                        # Empty, never 0,0 -- see the module docstring.
                        row += ["", ""]
                        missing += 1
                        continue
                    row += [repr(float(position[0])), repr(float(position[1]))]
                    labelled += 1
                writer.writerow(row)

    publish(target_path, write, kind=kind, sources=sources)
    provenance = record(kind, sources, edit_counts={"labelled_frames": len(frames)})
    provenance.update(
        {
            "scorer": scorer,
            "video": video_stem,
            "frames": sorted(item.frame for item in frames),
            "bodyparts": bodyparts,
            "labelled_points": labelled,
            "missing_points": missing,
        }
    )
    write_companion(target_path, provenance, sources=sources)

    return LabeledDataReport(frames=len(frames), labelled_points=labelled, missing_points=missing)
