"""Making a long channel list findable (WP-11).

A 70-channel source arrives as a flat scrolling column: ``Jaw_MI``,
``Jaw_MeanFlow``, ``Jaw_TopFlow``, ``Jaw_DirCoh``, ``Jaw_Brightness``,
``Jaw_Axial``, ``Jaw_Lateral``, ``Jaw_Speed``, ``Jaw_PeakSpeed``, ``Jaw_Drift``,
``Whisker_MI``…  The spec targets 128 channels at 50 kHz, so this is not the
worst case, it is the ordinary one.

The tree already grouped on ``/`` and ``.``.  Real rigs also separate with
``_``, which is why those names came through flat — every one of them is a
group and a measurement, and neither was visible.

Grouping on ``_`` unconditionally would be worse than not grouping: a source
with ``t_sec`` and ``force_n`` would gain two one-child groups and an extra
level of indentation for nothing.  So a prefix becomes a group only when at
least :data:`MIN_GROUP_SIZE` channels share it — the structure is derived from
the data rather than imposed on it.
"""

from __future__ import annotations

from collections import Counter

__all__ = ["MIN_GROUP_SIZE", "split_channel", "matches_filter"]

#: How many channels must share a prefix before it earns a group.  Two is
#: enough to be a pattern and low enough to catch a pair of axes; one would
#: turn every underscore into indentation.
MIN_GROUP_SIZE = 2


def _explicit_parts(channel: str) -> list[str]:
    """Split on the separators that always mean hierarchy."""
    return channel.replace(".", "/").split("/")


def _underscore_prefixes(channels: list[str]) -> set[str]:
    """Prefixes worth grouping, from the leaf names alone.

    Counted across the whole source rather than decided per channel: whether
    ``Jaw`` is a group depends on how many other channels start with it, which
    a single name cannot say.
    """
    counts: Counter[str] = Counter()
    for channel in channels:
        leaf = _explicit_parts(channel)[-1]
        prefix, separator, remainder = leaf.partition("_")
        if separator and remainder:
            counts[prefix] += 1
    return {prefix for prefix, count in counts.items() if count >= MIN_GROUP_SIZE}


def split_channel(channel: str, groupable_prefixes: set[str]) -> list[str]:
    """Return the tree path for *channel*.

    ``/`` and ``.`` always nest.  A leading ``prefix_`` nests only when
    *groupable_prefixes* says that prefix is shared, so ``Jaw_MeanFlow`` becomes
    ``["Jaw", "MeanFlow"]`` in a source full of ``Jaw_*`` and stays
    ``["t_sec"]`` in one where it is alone.
    """
    parts = _explicit_parts(channel)
    leaf = parts[-1]
    prefix, separator, remainder = leaf.partition("_")
    if separator and remainder and prefix in groupable_prefixes:
        return parts[:-1] + [prefix, remainder]
    return parts


def group_prefixes(channels: list[str]) -> set[str]:
    """Prefixes that earn a group for this set of channels."""
    return _underscore_prefixes(channels)


def matches_filter(channel: str, needle: str) -> bool:
    """Whether *channel* should show for the typed *needle*.

    Case-insensitive substring against the whole channel id, not just the leaf:
    someone typing "jaw" wants the group, and someone typing "flow" wants
    ``Jaw_MeanFlow`` and ``Jaw_TopFlow`` from the middle of their names.
    """
    if not needle:
        return True
    return needle.strip().lower() in channel.lower()
