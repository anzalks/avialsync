"""Collision-free, non-overwriting file naming for multi-camera clip exports."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from avialsync.core.sidecar_names import on_disk
from avialsync.engine.transcode import clip_container_suffix

__all__ = [
    "clip_container_suffix",
    "non_overwriting_path",
    "planned_trim_clips",
    "unique_camera_stems",
]

_UNSAFE_FILE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def _safe_stem(text: str) -> str:
    cleaned = _UNSAFE_FILE_CHARS.sub("_", text).strip(" ._")
    return cleaned or "camera"


def unique_camera_stems(paths: Sequence[str]) -> dict[str, str]:
    """Return a distinct, portable filename stem for each camera source path.

    Joined multi-trial cameras share ``.../FaceCam.avi/joined_trials`` suffixes,
    and multi-folder rigs often name every file ``video.mp4``. Using ``on_disk``
    preserves ``FaceCam_avi_joined_trials``, and remaining duplicates add their
    parent folder name (or a numeric suffix) so one camera never overwrites
    another camera's exported clip.
    """
    disk_paths = {orig: on_disk(orig) for orig in paths}
    base_stems = {orig: _safe_stem(disk.stem) for orig, disk in disk_paths.items()}
    counts: dict[str, int] = {}
    for stem in base_stems.values():
        counts[stem] = counts.get(stem, 0) + 1

    resolved: dict[str, str] = {}
    used: set[str] = set()
    for orig in paths:
        stem = base_stems[orig]
        if counts[stem] > 1:
            parent_name = _safe_stem(disk_paths[orig].parent.name)
            if parent_name and parent_name.lower() != stem.lower():
                stem = f"{parent_name}_{stem}"
        candidate = stem
        suffix_idx = 2
        while candidate.lower() in used:
            candidate = f"{stem}_{suffix_idx}"
            suffix_idx += 1
        used.add(candidate.lower())
        resolved[orig] = candidate
    return resolved


def non_overwriting_path(
    candidate: Path,
    reserved: set[Path],
    forbidden: Iterable[Path | str] = (),
) -> Path:
    """Return *candidate* or ``<stem>_2<suffix>`` so folder exports never overwrite files."""
    blocked = {Path(item).resolve() for item in forbidden}
    chosen = candidate
    index = 2
    while True:
        resolved = chosen.resolve()
        if resolved not in reserved and resolved not in blocked and not chosen.exists():
            reserved.add(resolved)
            return chosen
        chosen = candidate.with_name(f"{candidate.stem}_{index}{candidate.suffix}")
        index += 1


def planned_trim_clips(
    paths: Sequence[str],
    media_for: Callable[[str], str],
    range_for: Callable[[str], tuple[float, float]],
    out_dir: Path,
    forbidden: Iterable[Path | str] = (),
) -> list[tuple[str, float, float, Path]]:
    """Build collision-free, non-overwriting multi-camera trim clip specs."""
    stems = unique_camera_stems(paths)
    reserved: set[Path] = set()
    clips: list[tuple[str, float, float, Path]] = []
    for orig_path in paths:
        media = media_for(orig_path)
        start_s, end_s = range_for(orig_path)
        dest = non_overwriting_path(
            out_dir / f"{stems[orig_path]}_trim{clip_container_suffix(media)}",
            reserved,
            forbidden,
        )
        clips.append((media, start_s, end_s, dest))
    return clips
