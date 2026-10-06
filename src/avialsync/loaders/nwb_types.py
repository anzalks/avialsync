"""Which NWB types are which, including types an extension defines (D-188).

A file carries the specification of every namespace it uses, extensions
included, under ``/specifications``. Reading the ``neurodata_type_def`` /
``neurodata_type_inc`` pairs out of it is what tells this application that an
extension's ``MyTwoPhotonSeries`` is an ``ImageSeries`` -- and so pictures --
without a table here that would have to know every extension ever published.
"""

from __future__ import annotations

import json
from typing import Any

import h5py

from avialsync.loaders.nwb_text import text


def type_ancestry(handle: h5py.File) -> dict[str, str]:
    """Map each type the file's cached specifications define to its parent.

    Core types are listed too, from the core namespace the file carries, so a
    ``TwoPhotonSeries`` is known to be an ``ImageSeries`` without a table here
    that would have to track the schema. A file that cached nothing still works
    for the core types through :data:`CORE_PARENTS`.
    """
    parents = dict(CORE_PARENTS)
    specifications = handle.get("specifications")
    if not isinstance(specifications, h5py.Group):
        return parents
    for namespace in specifications.values():
        if not isinstance(namespace, h5py.Group):
            continue
        for version in namespace.values():
            if not isinstance(version, h5py.Group):
                continue
            for document in version.values():
                if not isinstance(document, h5py.Dataset):
                    continue
                try:
                    spec = json.loads(text(document[()]))
                except (TypeError, ValueError):
                    continue
                _collect_parents(spec, parents)
    return parents


def _collect_parents(node: Any, parents: dict[str, str]) -> None:
    if isinstance(node, dict):
        defined = node.get("neurodata_type_def")
        included = node.get("neurodata_type_inc")
        if isinstance(defined, str) and isinstance(included, str) and defined != included:
            parents.setdefault(defined, included)
        for value in node.values():
            _collect_parents(value, parents)
    elif isinstance(node, list):
        for value in node:
            _collect_parents(value, parents)


def is_a(neurodata_type: str, base: str, ancestry: dict[str, str]) -> bool:
    current, hops = neurodata_type, 0
    while current and hops < 32:
        if current == base:
            return True
        current = ancestry.get(current, "")
        hops += 1
    return False


#: The core types this module asks about, with their parents. The cached
#: specification normally supplies these; listed here so a file written without
#: one is read the same way.
CORE_PARENTS: dict[str, str] = {
    "ElectricalSeries": "TimeSeries",
    "SpikeEventSeries": "ElectricalSeries",
    "SpatialSeries": "TimeSeries",
    "RoiResponseSeries": "TimeSeries",
    "AnnotationSeries": "TimeSeries",
    "IntervalSeries": "TimeSeries",
    "DecompositionSeries": "TimeSeries",
    "AbstractFeatureSeries": "TimeSeries",
    "IndexSeries": "TimeSeries",
    "OptogeneticSeries": "TimeSeries",
    "PatchClampSeries": "TimeSeries",
    "CurrentClampSeries": "PatchClampSeries",
    "IZeroClampSeries": "CurrentClampSeries",
    "CurrentClampStimulusSeries": "PatchClampSeries",
    "VoltageClampSeries": "PatchClampSeries",
    "VoltageClampStimulusSeries": "PatchClampSeries",
    "ImageSeries": "TimeSeries",
    "ImageMaskSeries": "ImageSeries",
    "OpticalSeries": "ImageSeries",
    "TwoPhotonSeries": "ImageSeries",
    "OnePhotonSeries": "ImageSeries",
}
