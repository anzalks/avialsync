"""Deriving clean signal groups and concise labels from channel lists.

A multi-channel source arrives as flat channel identifiers: ``Jaw_MI`` /
``Jaw_MeanFlow``, ``Acc-X`` / ``Acc-Y`` / ``Acc-Z``, ``CH1``..``CH32`` beside
``ADC1``..``ADC8``, or deep NWB paths such as
``ophys.DfOverF.RoiResponseSeries.roi0``. This module derives hierarchical
signal groups and concise per-channel labels from the channel set itself so the
``Sources`` tree, ``Plots`` stack/grouped views, and ``Values`` inspector share
one consistent grouping model without imposing single-child wrappers on flat
files.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

__all__ = [
    "MIN_GROUP_SIZE",
    "channel_tree_paths",
    "compact_channel_label",
    "group_prefixes",
    "matches_filter",
    "split_channel",
]

#: How many channels must share a prefix before it earns a group. Two catches
#: stereo/XY pairs while leaving lone names like ``t_sec`` flat.
MIN_GROUP_SIZE = 2

#: Delimiters commonly used by acquisition rigs between a group stem and channel.
_DELIMITERS: tuple[str, ...] = ("_", "-", ":")

#: Generic NWB / acquisition container type names that add no information when
#: they are the sole child beneath an already-named group (e.g. ``DfOverF``).
_REDUNDANT_SERIES_WRAPPERS: frozenset[str] = frozenset(
    {
        "RoiResponseSeries",
        "SpatialSeries",
        "TimeSeries",
        "BehavioralTimeSeries",
        "BehavioralEvents",
        "BehavioralEpochs",
        "CompassDirection",
        "PupilTracking",
        "EyeTracking",
    }
)

_NUMBERED_BANK_RE = re.compile(r"^([A-Za-z]{2,})\s*#?(\d+)$")


def _explicit_parts(channel: str) -> list[str]:
    """Split on separators (``/`` and ``.``) that always express hierarchy."""
    return [part for part in channel.replace(".", "/").split("/") if part] or [channel]


def _candidate_delimiter_prefixes(leaf: str) -> list[tuple[str, str]]:
    """Return ``(delimiter, prefix)`` candidates for *leaf* from shortest to longest."""
    for delim in _DELIMITERS:
        if delim not in leaf:
            continue
        tokens = leaf.split(delim)
        if len(tokens) < 2 or not tokens[0].strip() or not tokens[-1].strip():
            continue
        built: list[tuple[str, str]] = []
        for end in range(1, len(tokens)):
            prefix = delim.join(tokens[:end]).strip()
            remainder = delim.join(tokens[end:]).strip()
            if prefix and remainder:
                built.append((delim, prefix))
        if built:
            return built
    return []


def _delimiter_prefixes(channels: Sequence[str]) -> set[str]:
    """Prefixes worth grouping across ``_``, ``-``, and ``:``.

    When every channel starting with ``tail_`` actually starts with ``tail_base_``
    (equal counts), only ``tail_base`` is kept so ``tail_base_x`` groups as
    ``["tail_base", "x"]`` rather than ``["tail", "base_x"]``. When a broader
    group contains multiple subgroups (``mouse1_snout_x``, ``mouse1_ear_x``),
    both ``mouse1`` and ``mouse1_snout`` remain active for nested grouping.
    """
    counts: Counter[tuple[str, str]] = Counter()
    by_leaf: list[list[tuple[str, str]]] = []
    for channel in channels:
        leaf = _explicit_parts(channel)[-1]
        cands = _candidate_delimiter_prefixes(leaf)
        by_leaf.append(cands)
        for item in cands:
            counts[item] += 1

    active: set[str] = set()
    for cands in by_leaf:
        for idx, (delim, prefix) in enumerate(cands):
            count = counts[(delim, prefix)]
            if count < MIN_GROUP_SIZE:
                continue
            # Suppress a shorter prefix if a longer prefix on the same leaf
            # accounts for every single member of the shorter one.
            shadowed = any(counts[longer] == count for longer in cands[idx + 1 :])
            if not shadowed:
                active.add(prefix)
    return active


def split_channel(channel: str, groupable_prefixes: set[str]) -> list[str]:
    """Return the hierarchical path for *channel* given *groupable_prefixes*.

    ``/`` and ``.`` always nest. Leading delimiter prefixes nest when present in
    *groupable_prefixes*, supporting multi-level prefixes such as
    ``mouse1_snout_x`` -> ``["mouse1", "snout", "x"]``.
    """
    parts = _explicit_parts(channel)
    leaf = parts[-1]
    cands = _candidate_delimiter_prefixes(leaf)
    matched = [(delim, prefix) for delim, prefix in cands if prefix in groupable_prefixes]
    if not matched:
        return parts

    nested: list[str] = []
    consumed = ""
    last_delim = "_"
    for delim, prefix in matched:
        last_delim = delim
        if not consumed:
            nested.append(prefix)
        elif prefix.startswith(consumed + delim):
            nested.append(prefix[len(consumed) + len(delim) :])
        else:
            continue
        consumed = prefix

    remainder = leaf[len(consumed) + len(last_delim) :].strip()
    if not remainder:
        return parts
    return parts[:-1] + nested + [remainder]


def group_prefixes(channels: list[str]) -> set[str]:
    """Prefixes that earn a group for this set of channels."""
    return _delimiter_prefixes(channels)


def _collapse_redundant_wrappers(raw_paths: dict[str, list[str]]) -> dict[str, list[str]]:
    """Drop redundant schema-type segments like ``RoiResponseSeries`` under ``DfOverF``."""
    children_by_parent: dict[tuple[str, ...], set[str]] = {}
    for parts in raw_paths.values():
        for depth in range(1, len(parts) - 1):
            parent = tuple(parts[:depth])
            children_by_parent.setdefault(parent, set()).add(parts[depth])

    cleaned: dict[str, list[str]] = {}
    for ch, parts in raw_paths.items():
        if len(parts) < 3:
            cleaned[ch] = parts
            continue
        out = [parts[0]]
        raw_prefix = [parts[0]]
        for seg in parts[1:-1]:
            siblings = children_by_parent.get(tuple(raw_prefix), set())
            raw_prefix.append(seg)
            if seg in _REDUNDANT_SERIES_WRAPPERS and len(siblings) == 1:
                continue
            out.append(seg)
        out.append(parts[-1])
        cleaned[ch] = out
    return cleaned


def channel_tree_paths(channels: Sequence[str]) -> dict[str, list[str]]:
    """Compute canonical ``[*groups, leaf]`` paths across *channels*.

    Combines explicit ``/`` and ``.`` hierarchy, multi-delimiter prefix grouping,
    redundant NWB wrapper elision, and multi-bank numbered hardware prefixes
    (such as ``CH1..CH32`` alongside ``ADC1..ADC8``) without wrapping single-bank
    sources in a pointless extra folder.
    """
    channel_list = list(channels)
    prefixes = _delimiter_prefixes(channel_list)
    initial = {ch: split_channel(ch, prefixes) for ch in channel_list}
    collapsed = _collapse_redundant_wrappers(initial)

    bank_counts: Counter[str] = Counter()
    bank_by_channel: dict[str, str] = {}
    for ch, parts in collapsed.items():
        if len(parts) == 1:
            match = _NUMBERED_BANK_RE.match(parts[0].strip())
            if match is not None:
                stem = match.group(1)
                bank_counts[stem] += 1
                bank_by_channel[ch] = stem

    total = len(channel_list)
    valid_banks = {
        stem for stem, count in bank_counts.items() if count >= MIN_GROUP_SIZE and count < total
    }
    if valid_banks:
        for ch, stem in bank_by_channel.items():
            if stem in valid_banks:
                collapsed[ch] = [stem, collapsed[ch][0]]
    return collapsed


def compact_channel_label(channel: str, path: Sequence[str] | None = None) -> str:
    """Return a concise ``group · leaf`` label for plot gutters and dense tables.

    Short flat names (``Electrode_1``, ``Jaw_MeanFlow``) keep their exact text;
    long dotted/slashed paths (``ophys.DfOverF.RoiResponseSeries.roi12``) become
    ``DfOverF · roi12`` so narrow gutters show the informative group and leaf.
    """
    parts = list(path) if path is not None else _explicit_parts(channel)
    if len(parts) < 2:
        return channel
    has_explicit_sep = "." in channel or "/" in channel
    if not has_explicit_sep and len(channel) <= 18:
        return channel
    group = parts[-2]
    leaf = parts[-1]
    if group in _REDUNDANT_SERIES_WRAPPERS and len(parts) >= 3:
        group = parts[-3]
    return f"{group} · {leaf}"


def matches_filter(channel: str, needle: str) -> bool:
    """Whether *channel* should show for the typed *needle*."""
    if not needle:
        return True
    return needle.strip().lower() in channel.lower()
