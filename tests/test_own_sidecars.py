"""AvialSync's own sidecar files are never offered back as data to import.

Each is a well-formed CSV or TOML that a generic loader claims on extension
alone. The swap sidecar was missing from both filters -- its own docstring said
drop scanning and sniffing consulted it, and neither did -- so dropping a
folder with identity swaps offered ``pose.csv.avialswap.csv`` as a time series,
pre-selected, and the import then failed to parse it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from avialsync.core.registry import LoaderRegistry, is_own_sidecar
from avialsync.engine.drop_worker import DropScanWorker

_ROWS = "frame,value\n1,2.0\n2,3.0\n"
SIDECARS = [
    "pose.csv.avialswap.csv",
    "pose.csv.avialfix.csv",
    "session.custom_markers.csv",
]


@pytest.mark.parametrize("name", SIDECARS)
def test_no_loader_claims_one_of_our_sidecars(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_text(_ROWS, encoding="utf-8")

    assert is_own_sidecar(path)
    assert LoaderRegistry().find_best_loader(path) is None


def test_a_folder_scan_offers_the_data_and_none_of_its_sidecars(tmp_path: Path) -> None:
    (tmp_path / "pose.csv").write_text(_ROWS, encoding="utf-8")
    for name in SIDECARS:
        (tmp_path / name).write_text(_ROWS, encoding="utf-8")
    registry = LoaderRegistry()

    offered = {
        path.name
        for path, _loader, _config in DropScanWorker([tmp_path], registry)._collect_drop_candidates(
            tmp_path
        )
    }

    assert "pose.csv" in offered
    assert offered.isdisjoint(SIDECARS)
