"""Opening a recording for reading, including segments played back to back.

An AOL camera's trials are saved one file per trial. Rather than copy them into
one file, the cache holds a short FFmpeg concat list naming each file and the
frames it contributes (:mod:`avialsync.loaders.aol_camera_join`); FFmpeg plays
the list as one stream. The list names files by absolute path, which FFmpeg's
concat reader refuses unless told the list is trusted -- it is, being one this
application wrote into its own cache. Every reader of a recording opens it
here, so that permission is given in one place and nowhere else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import av

#: The suffix of a segment list written by the joined-camera source.
CONCAT_SUFFIX = ".ffconcat"


def open_input(path: Path | str) -> Any:
    """``av.open(path)`` for reading; a segment list is read as one stream."""
    if Path(path).suffix == CONCAT_SUFFIX:
        return av.open(str(path), options={"safe": "0"})
    return av.open(str(path))
