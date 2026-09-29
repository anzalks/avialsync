"""What a tracked point is, stated once.

A pose file is not a bag of named traces.  It has individuals, body parts, axes,
confidences and derived columns, and every one of those is a question a consumer
has to answer.  :class:`~avialsync.core.source.TimeSeriesSource` speaks flat
``ChannelInfo`` channels -- the right contract for a voltage trace and the wrong
one for a tracked point -- so before this module each consumer recovered the
structure by splitting ``_x`` off a channel name.  Nine sites across seven files
did that, and three shipped defects came out of it: multi-animal support had to
change three files because each keyed a point by body part alone and each
collapsed two animals that share ``snout``; the EKS loader decided 2D-versus-3D
by testing a column count against ``% 3``; and a whole module existed to map
declared body-part names back onto the names a cache happened to hold (D-140).

The loader declares a :class:`PoseSchema`; everything downstream reads it.  A
new format is then one loader emitting the same schema, and no consumer changes.

**The canonical name is a persisted identifier.**  :class:`PointKey.point` is
written into the ``.avialfix.csv`` corrections sidecar beside each pose file and
into the session (D-099), so :func:`canonical_name` is the single place that
decides it and renaming is a migration, not an edit.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "PosePoint",
    "PoseSchema",
    "canonical_name",
    "split_channel",
]

#: Separates a point's name from its axis in a flat channel name, and an
#: individual from its body part inside that name. One character, used for both,
#: because a pose export offers nothing else that survives every reader.
_SEPARATOR = "_"

#: The axes a point may carry, in the order a schema reports them.
_AXIS_ORDER = ("x", "y", "z")


def canonical_name(individual: str, bodypart: str) -> str:
    """Return the one name a tracked point is known by.

    ``individual`` is empty for a format that has no notion of one, which is
    every single-animal export; the name is then the body part alone and a
    DeepLabCut or Lightning Pose file keeps the names it always had. A
    multi-animal file carries the individual, because its body parts repeat:
    ``snout`` belongs to two mice and is two points, as it is in the recording.
    """
    individual = individual.strip()
    bodypart = bodypart.strip()
    return f"{individual}{_SEPARATOR}{bodypart}" if individual else bodypart


def split_channel(channel: str) -> tuple[str, str] | None:
    """Split a flat channel name into ``(point, axis)``, or ``None``.

    For the consumers that genuinely hold only a channel name -- a loose reader
    reaching the overlay, a CSV field in a hand-made marker file -- and never a
    schema. It is deliberately the *same* rule :meth:`PoseSchema.channel` writes
    with, so the two cannot drift; a consumer that can reach a schema should use
    the schema, which knows what is a coordinate and what is a derived column.
    """
    point, separator, axis = channel.rpartition(_SEPARATOR)
    if not separator or axis not in _AXIS_ORDER or not point:
        return None
    return point, axis


@dataclass(frozen=True)
class PosePoint:
    """One tracked point: who it belongs to, what it is, and what it carries."""

    #: The animal, or ``""`` for a format with no individuals. DeepLabCut's
    #: reserved ``single`` group is an individual like any other.
    individual: str
    bodypart: str
    #: ``("x", "y")`` or ``("x", "y", "z")``, always in that order.
    axes: tuple[str, ...]
    has_likelihood: bool = False

    @property
    def name(self) -> str:
        """The canonical name, from :func:`canonical_name`."""
        return canonical_name(self.individual, self.bodypart)

    @property
    def is_3d(self) -> bool:
        return "z" in self.axes

    def channel(self, axis: str) -> str:
        """The flat channel name carrying *axis* for this point."""
        return f"{self.name}{_SEPARATOR}{axis}"

    @property
    def likelihood_channel(self) -> str | None:
        """The flat channel carrying this point's confidence, when it has one."""
        return f"{self.name}{_SEPARATOR}likelihood" if self.has_likelihood else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "individual": self.individual,
            "bodypart": self.bodypart,
            "axes": list(self.axes),
            "has_likelihood": self.has_likelihood,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PosePoint:
        return cls(
            individual=str(data.get("individual", "")),
            bodypart=str(data.get("bodypart", "")),
            axes=tuple(str(axis) for axis in data.get("axes", ())),
            has_likelihood=bool(data.get("has_likelihood", False)),
        )


@dataclass(frozen=True)
class PoseSchema:
    """The structure of one pose source, as its loader declares it.

    Built by the loader and carried to every consumer on
    :class:`~avialsync.core.inspection.SourceInspection`, which the import
    manifest already persists -- so a cache hit, where the loader is never
    opened at all, still knows what its channels mean.
    """

    points: tuple[PosePoint, ...] = ()
    frame_indexed: bool = False
    #: Columns the format derives from the coordinates rather than measures:
    #: ``x_ens_median``, ``x_ens_var``, ``zscore``, ``nll``, ``x_posterior_var``.
    #: Declared by the loader so the importer can decline to pyramid eleven
    #: columns per body part for data nothing reads, instead of a config key
    #: every caller has to remember to pass.
    derived: tuple[str, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        """A schema with no points is not a pose."""
        return bool(self.points)

    @property
    def is_3d(self) -> bool:
        """Whether this source carries a 3D pose.

        A property of the file, which the loader can simply state. The EKS
        loader used to infer it by testing a count of ``_x``/``_y``/``_z``
        columns against ``% 3 == 0``, so a flat 2D file with three body parts
        was 3D and one with two was not (D-140).
        """
        return any(point.is_3d for point in self.points)

    @property
    def multi_animal(self) -> bool:
        return any(point.individual for point in self.points)

    @property
    def individuals(self) -> tuple[str, ...]:
        """Every individual named, in first-seen order; empty for single-animal."""
        seen: list[str] = []
        for point in self.points:
            if point.individual and point.individual not in seen:
                seen.append(point.individual)
        return tuple(seen)

    def points_with(self, *axes: str) -> tuple[PosePoint, ...]:
        """The points carrying every one of *axes* -- an overlay's ``x``/``y``."""
        wanted = set(axes)
        return tuple(point for point in self.points if wanted <= set(point.axes))

    def point(self, name: str) -> PosePoint | None:
        """The point called *name*, or ``None``."""
        return next((p for p in self.points if p.name == name), None)

    def coordinate_channels(self, *axes: str) -> tuple[str, ...]:
        """Flat channel names for *axes* across every point that has them.

        With no *axes*, every axis every point carries. This is what an importer
        asks for when it wants coordinates and not derived columns.
        """
        order = axes or _AXIS_ORDER
        return tuple(
            point.channel(axis) for point in self.points for axis in order if axis in point.axes
        )

    @classmethod
    def from_channels(cls, channels: Iterable[str], *, frame_indexed: bool = False) -> PoseSchema:
        """Build a schema from flat ``point_axis`` names.

        For a loader whose format gives it names and nothing else -- and for
        test doubles standing in for one. It is deliberately a *loader-side*
        constructor: a loader may declare its structure however it likes, but a
        consumer reads the declaration and never reconstructs it, which is the
        whole point of D-140. Names carrying no individual produce points whose
        individual is empty, because that is what the names say.
        """
        axes: dict[str, list[str]] = {}
        likelihood: set[str] = set()
        for channel in channels:
            split = split_channel(channel)
            if split is not None:
                axes.setdefault(split[0], []).append(split[1])
                continue
            point, separator, suffix = channel.rpartition(_SEPARATOR)
            if separator and suffix.lower() == "likelihood":
                axes.setdefault(point, [])
                likelihood.add(point)
        return cls(
            points=tuple(
                PosePoint(
                    individual="",
                    bodypart=name,
                    axes=tuple(a for a in _AXIS_ORDER if a in found),
                    has_likelihood=name in likelihood,
                )
                for name, found in axes.items()
                if found
            ),
            frame_indexed=frame_indexed,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "points": [point.as_dict() for point in self.points],
            "frame_indexed": self.frame_indexed,
            "derived": list(self.derived),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PoseSchema:
        return cls(
            points=tuple(PosePoint.from_dict(p) for p in data.get("points", ())),
            frame_indexed=bool(data.get("frame_indexed", False)),
            derived=tuple(str(d) for d in data.get("derived", ())),
        )
