"""Which camera a file is named after.

Recordings name their files after the camera that produced them --
``FrontCam.mp4``, ``FrontCam_eks.csv``, ``FrontCam-relative times.txt`` -- and
two places need to read that: a session loader matching a track to a camera,
and the import dialog working out which video a dropped pose file belongs on.

One rule, stated once (rule 15).  Longest label first, so ``SideCam`` cannot be
shadowed by a shorter label that happens to be a prefix of it, and an empty
label never matches -- an empty token would otherwise claim every filename.
"""

from __future__ import annotations

from collections.abc import Iterable

__all__ = ["match_label"]


def match_label(stem: str, labels: Iterable[str]) -> str | None:
    """Return the label *stem* is named after, or ``None`` when none is.

    A match is a prefix: ``FrontCam_eks`` is named after ``FrontCam``. It is
    deliberately not a substring test -- ``head_FrontCam_raw`` would match, and
    a file that merely mentions a camera is not that camera's file.
    """
    lowered = stem.lower()
    for label in sorted((label for label in labels if label), key=len, reverse=True):
        if lowered.startswith(label.lower()):
            return label
    return None
