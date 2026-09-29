"""Which labels a tracker can confuse, derived from the file's own schema.

Two kinds of confusion happen to pose data, and they are the same arithmetic:

* **individuals** -- ``testMouse`` and ``conSpecific`` cross, and the estimator
  carries on with the labels exchanged;
* **sides** -- a left and a right wrist swap behind an occlusion, inside one
  animal, where no individual is involved at all.

Both are :class:`~avialsync.core.identity_swaps.SwapGroup` -- lanes that own a
point each per part -- so the model, the plot, the cache and the export handle
one case and get the other free (D-141).

**A group's ``name`` is a persisted identifier, not a label.**  It is written
into the swap sidecar beside the pose file and referenced by every event, so it
is a stable ascii id here and the UI translates it for display.  Renaming one
is a migration, exactly as :func:`avialsync.core.pose.canonical_name` is.
"""

from __future__ import annotations

from avialsync.core.identity_swaps import SwapGroup
from avialsync.core.pose import PoseSchema

__all__ = [
    "ANIMALS",
    "SIDES",
    "CUSTOM",
    "LEFT",
    "RIGHT",
    "group_id",
    "split_group_id",
    "is_custom",
    "groups_for_schema",
    "side_of",
]

#: Group id for the individuals of a multi-animal export.
ANIMALS = "animals"
#: Group id prefix for left-against-right within one animal.  A multi-animal
#: file gets one per individual: ``sides:testMouse``.
SIDES = "sides"
#: Group id prefix for a pair of lanes the *user* declared, which no schema can
#: derive: ``custom:front paws``.
CUSTOM = "custom"

#: Separates a group's kind from what qualifies it.  One character, defined
#: once: a group id is written into the swap sidecar beside the pose file, so
#: four places testing for a prefix with a string literal is four places that
#: can disagree about what a persisted identifier means (rule 15, and the same
#: defect D-140 exists to prevent).
_QUALIFIER = ":"

LEFT = "left"
RIGHT = "right"

#: Tokens that name a side when they stand alone between separators. Single
#: letters are accepted only as whole tokens: glued, ``r`` would claim the
#: ``ear`` of ``rear`` and invent a side that is not in the data.
_SIDE_TOKENS = {
    "left": LEFT,
    "l": LEFT,
    "right": RIGHT,
    "r": RIGHT,
}

#: Tokens that name a side glued straight onto a stem (``leftwrist``).
_GLUED_TOKENS = {"left": LEFT, "right": RIGHT}

_SEPARATORS = ("_", "-", ".")


def group_id(kind: str, qualifier: str = "") -> str:
    """The persisted id of a group of *kind*, qualified when it needs to be."""
    return f"{kind}{_QUALIFIER}{qualifier}" if qualifier else kind


def split_group_id(identifier: str) -> tuple[str, str]:
    """Split a group id into ``(kind, qualifier)``; the qualifier may be empty."""
    kind, separator, qualifier = identifier.partition(_QUALIFIER)
    return (kind, qualifier) if separator else (identifier, "")


def is_custom(identifier: str) -> bool:
    """Whether this group was declared by the user rather than derived."""
    return split_group_id(identifier)[0] == CUSTOM


def side_of(bodypart: str) -> tuple[str, str] | None:
    """Split *bodypart* into ``(side, stem)``, or ``None`` when it names no side.

    The stem is lower-cased because it becomes a persisted part id and because
    ``LeftWrist`` and ``rightwrist`` have to pair; the side is one of
    :data:`LEFT` or :data:`RIGHT`.
    """
    name = bodypart.strip()
    if not name:
        return None

    normalised = name
    for separator in _SEPARATORS[1:]:
        normalised = normalised.replace(separator, _SEPARATORS[0])
    tokens = [token for token in normalised.split(_SEPARATORS[0]) if token]
    if len(tokens) >= 2:
        first, last = tokens[0].lower(), tokens[-1].lower()
        if first in _SIDE_TOKENS:
            return _SIDE_TOKENS[first], "_".join(tokens[1:]).lower()
        if last in _SIDE_TOKENS:
            return _SIDE_TOKENS[last], "_".join(tokens[:-1]).lower()

    lowered = name.lower()
    for token, side in _GLUED_TOKENS.items():
        if lowered.startswith(token) and len(lowered) > len(token):
            return side, lowered[len(token) :]
        if lowered.endswith(token) and len(lowered) > len(token):
            return side, lowered[: -len(token)]
    return None


def groups_for_schema(schema: PoseSchema) -> tuple[SwapGroup, ...]:
    """Every group *schema* supports, in the order the UI offers them.

    Animals first, because an individual flip moves everything and is what a
    reviewer looks for first.  A group with fewer than two lanes, or with no
    part both lanes carry, is dropped rather than offered: a selector listing a
    comparison that cannot be made is worse than one that does not list it.
    """
    groups = [_animals(schema)]
    groups.extend(_sides(schema))
    return tuple(group for group in groups if group is not None and group)


def _animals(schema: PoseSchema) -> SwapGroup | None:
    """Individuals as lanes, body parts as parts."""
    individuals = schema.individuals
    if len(individuals) < 2:
        return None

    owners: dict[str, list[str]] = {}
    for point in schema.points:
        if point.individual:
            owners.setdefault(point.bodypart, []).append(point.individual)

    # A part only one animal carries cannot be exchanged with anything, so it
    # is not a part of this group -- and must not be, or the centroid of "all
    # parts" would be computed over a different set per lane.
    parts = tuple(part for part, lanes in owners.items() if len(set(lanes)) >= 2)
    members = tuple(
        (point.individual, point.bodypart, point.name)
        for point in schema.points
        if point.individual and point.bodypart in parts
    )
    return SwapGroup(name=ANIMALS, lanes=individuals, parts=parts, members=members)


def _sides(schema: PoseSchema) -> list[SwapGroup]:
    """Left against right, once per individual that has both."""
    found: dict[str, dict[tuple[str, str], str]] = {}
    for point in schema.points:
        split = side_of(point.bodypart)
        if split is None:
            continue
        side, stem = split
        found.setdefault(point.individual, {})[(side, stem)] = point.name

    groups: list[SwapGroup] = []
    for individual, members in found.items():
        stems = sorted(
            {stem for _, stem in members if (LEFT, stem) in members and (RIGHT, stem) in members}
        )
        if not stems:
            continue
        name = group_id(SIDES, individual)
        groups.append(
            SwapGroup(
                name=name,
                lanes=(LEFT, RIGHT),
                parts=tuple(stems),
                members=tuple(
                    (side, stem, point)
                    for (side, stem), point in sorted(members.items())
                    if stem in stems
                ),
            )
        )
    return groups
