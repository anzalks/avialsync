"""Frame selection from presentation timestamps — the single authority.

The frame displayed for a source time ``t`` is the frame whose presentation
interval contains ``t``: the last frame with ``pts <= t``.  A reader that
returns the *first* frame with ``pts >= t`` is wrong at every scrub position
between two frames — measured at 179 of 179 mid-interval probes, which at
30 fps misattributes an event by 33 ms.

This module is headless and dependency-light on purpose.  Both the decoder
(``engine/pyav_reader.py``, which selects the frame) and the readout
(``ui/video_timing.py``, which names it) resolve time through the same call, so
the two cannot disagree.  Under libmpv they were separate authorities and did
disagree; keeping them fused is the point (D-075, AGENTS.md rule 6).  ``engine``
may not import ``ui`` at module scope (ARCHITECTURE §1), so the shared
primitive lives here rather than beside the readout that used to own it.
"""

from __future__ import annotations

import numpy as np

#: Slack on every comparison between a decoder timestamp and the frame table.
#:
#: The table historically came from ``ffprobe``, which prints ``pts_time``
#: rounded to six decimals, while a decoder reports the unrounded value: frame 2
#: of 30 fps footage is ``0.066667`` in the table and ``0.06666666666666667``
#: from the decoder.  A frame's own timestamp can therefore land *below* its own
#: table entry, which a strict search reads as the frame before it — so the
#: readout named the wrong frame and a forward step returned the frame already
#: on screen, i.e. did nothing.  One rounding quantum absorbs that.  It is
#: thousands of times shorter than any real inter-frame interval (4.3 ms even at
#: 230 fps), so it can never reach past a neighbouring frame.
PTS_EPSILON_S = 1e-6


def frame_index_at(frame_times: np.ndarray, source_time: float) -> int:
    """Return the index of the presentation frame active at ``source_time``.

    Args:
        frame_times: Presentation timestamps in source seconds, display order.
        source_time: The instant to resolve, in the same source timebase.

    Returns:
        The index of the last frame with ``pts <= source_time``, clamped to the
        table.  Times before the first frame resolve to frame 0.
    """
    index = int(np.searchsorted(frame_times, source_time + PTS_EPSILON_S, side="right")) - 1
    return max(0, min(index, len(frame_times) - 1))


def adjacent_frame_time(
    frame_times: np.ndarray,
    source_time: float,
    direction: int,
) -> float:
    """Return the neighbouring real presentation timestamp.

    Anchored on the frame *containing* ``source_time`` — the one on screen — so
    a step always lands on a different frame.

    Args:
        frame_times: Presentation timestamps in source seconds, display order.
        source_time: The instant to step from.
        direction: Positive to step forward, negative to step back.

    Returns:
        The neighbour's presentation timestamp, clamped at either end.
    """
    if direction > 0:
        index = int(np.searchsorted(frame_times, source_time + PTS_EPSILON_S, side="right"))
        index = min(index, len(frame_times) - 1)
    else:
        index = int(np.searchsorted(frame_times, source_time - PTS_EPSILON_S, side="left")) - 1
        index = max(index, 0)
    return float(frame_times[index])
