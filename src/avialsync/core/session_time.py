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
    "source_epoch_for",
    "unix_start",
    "reference_epoch",
    "placement_offset",
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


def source_epoch_for(source_start: float, declared: float | None = None) -> float | None:
    """The Unix epoch of a source's own zero, or ``None`` when it has no claim.

    Every timestamp is seconds since *some* instant.  This says which, and it
    is the only question a loader has to answer for its data to land in the
    right place -- the placement, the session zero and the wall-clock display
    all derive from it.

    A *declared* epoch always wins, because the loader read it out of the file
    and this function can only guess.  The guess, for a loader that declares
    nothing, is the four-decade magnitude gap in
    :func:`is_absolute`: timestamps that large are Unix time already, so their
    own zero is the Unix epoch itself.

    Everything else returns ``None`` -- an honest "no claim" rather than a
    guess.  Those sources keep their own zero, which is what a container
    counting from its first frame actually means, and the user aligns them from
    evidence or by hand.

    A time-of-day base is exactly why *declared* exists: 34526 s is 09:35:26
    and also a plausible nine-hour elapsed time, so no threshold can tell them
    apart.  A loader that knows the date does not have to -- it declares the
    midnight its timestamps count from and the ambiguity never arises.
    """
    if declared is not None:
        return float(declared)
    if is_absolute(source_start):
        return 0.0
    return None


def unix_start(source_start: float, source_epoch: float | None) -> float | None:
    """When a source's first sample happened, in Unix time, if that is knowable."""
    if source_epoch is None:
        return None
    return float(source_epoch) + float(source_start)


def placement_offset(source_epoch: float | None, session_zero: float) -> float:
    """The ``TimeMap`` offset putting a source on the session's master clock.

    ``TimeMap`` maps master to source time as ``t_source = t_master + offset``,
    and a source's samples are Unix time ``t_source + source_epoch``.  Master
    time is Unix time measured from the session zero, so::

        t_master = (t_source + source_epoch) - session_zero
                 = t_source - (session_zero - source_epoch)

    which names the offset outright.  Nothing is rewritten; the mapping is what
    moves, as it does for every alignment in this application.

    Zero when either side has no claim.  A source that does not know its own
    epoch keeps its own zero, and a session that has not declared one has no
    clock to place anything against.
    """
    if source_epoch is None or not session_zero:
        return 0.0
    return float(session_zero) - float(source_epoch)


def rebase_offset(source_start: float, reference: float) -> float:
    """Placement for a source whose timestamps are already Unix seconds.

    The ``source_epoch is 0.0`` case of :func:`placement_offset`, kept because
    it reads better at the call sites that only ever see that case: a source
    whose own clock reads 1.7e9 at the session's zero needs exactly that as its
    offset, and then runs from master zero like everything else.

    A container-relative source gets nothing.  Its timestamps already begin at
    its own start, and moving it onto a wall clock it never recorded would be
    inventing a time.
    """
    return placement_offset(source_epoch_for(source_start), reference)
