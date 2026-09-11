"""One declared zero for the session, after NWB's timing model.

NWB gives every file a ``session_start_time`` and states every timestamp in
seconds relative to it.  Nothing in this application did, and two things
followed from that.

A CSV imported as ``epoch_ms`` lands near 1.7e9 while a video's frame times are
``pts * time_base`` from a container start of zero.  Bounds are a union, so the
master timeline became fifty-four years long with two short islands at its
ends, and the correction could not even be typed: the offset control clamps at
a day, silently, because Qt spin boxes do.

The second is quieter.  ``format_time`` has always taken the Unix epoch of
master-clock zero and falls back to elapsed time when it is zero -- and no
caller ever passed one, so two of the three time display modes could not work
and never said why.

The rule here is NWB's.  One instant is the session's zero; sources that carry
absolute timestamps are placed against it through their own time map, which
means nothing is rewritten -- the mapping is what moves, exactly as it does for
every other alignment in this application.
"""

from __future__ import annotations

__all__ = [
    "ABSOLUTE_EPOCH_FLOOR",
    "is_absolute",
    "reference_epoch",
    "rebase_offset",
]

#: At or above this, a timestamp is Unix epoch seconds rather than elapsed
#: time.  1e8 is 1973-03-03: no recording runs for the 3.2 years it would take
#: to reach it by elapsed time, and no epoch timestamp from a working clock
#: falls below it.  The gap between the two populations is four decades wide,
#: which is why a threshold is safe here and would not be for a tighter guess
#: such as separating seconds-since-midnight from elapsed seconds.
ABSOLUTE_EPOCH_FLOOR = 1e8


def is_absolute(t: float) -> bool:
    """Whether *t* is wall-clock time rather than time since a recording began."""
    return float(t) >= ABSOLUTE_EPOCH_FLOOR


def reference_epoch(current: float, source_start: float) -> float:
    """The session's zero, given what it already is and a newly loaded source.

    Declared once and then kept, which is the half of NWB's convention that
    makes it useful: a reference that moved whenever an earlier source arrived
    would renumber every timestamp the user had already written down.  The
    first source carrying wall-clock time sets it; later ones are placed
    against it, before it if that is where they truly are.

    Returns 0.0 for a session of purely container-relative sources, which is
    the honest answer -- their zero is a recording start nobody wrote down.
    """
    if current:
        return float(current)
    if is_absolute(source_start):
        return float(source_start)
    return 0.0


def rebase_offset(source_start: float, reference: float) -> float:
    """The time-map offset placing an absolute source against the session zero.

    ``TimeMap`` maps master time to source time as ``t + offset``, so a source
    whose own clock reads 1.7e9 at the session's zero needs exactly that as its
    offset, and then runs from master zero like everything else.

    A container-relative source gets nothing.  Its timestamps already begin at
    its own start, and moving it onto a wall clock it never recorded would be
    inventing a time -- the user aligns it, from evidence or by hand.
    """
    if not reference or not is_absolute(source_start):
        return 0.0
    return float(reference)
