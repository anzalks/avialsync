"""Process-level runtime helpers.

This module used to locate a media runtime — libmpv, then FFmpeg — that had to
exist on the machine beside the application. Nothing does that any more: video
decoding, probing, proxy generation, and clip export all run in-process against
the FFmpeg that PyAV carries inside its own wheel (D-075). There is no search
path, no ``AVIALSYNC_MEDIA_ROOT``, and no executable to require.

What is left is the one thing that is genuinely about the *process* rather than
about media.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TypedDict


class NoWindowKwargs(TypedDict, total=False):
    """Subprocess keyword arguments that suppress a console window.

    A ``TypedDict`` rather than ``dict[str, int]`` so mypy can still resolve the
    overloads of ``subprocess.run``/``Popen`` when this is splatted into them.
    ``total=False`` because the mapping is empty off Windows.
    """

    creationflags: int


def no_window_kwargs() -> NoWindowKwargs:
    """Return subprocess kwargs that keep a child process from opening a console.

    A windowed Windows build has no console of its own, so a child process is
    given a fresh one — which flashes on screen and steals focus.

    ``CREATE_NO_WINDOW`` exists only on Windows; every other platform gets an
    empty mapping, so call sites can unconditionally splat the result.
    """
    if sys.platform != "win32":
        return NoWindowKwargs()
    # subprocess.CREATE_NO_WINDOW is Windows-only, hence the guarded lookup.
    return NoWindowKwargs(creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
