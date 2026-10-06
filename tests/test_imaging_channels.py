"""Acquired channels are named, chosen and overlaid apart from their display colour (D-195)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile

pytest.importorskip("h5py")

from avialsync.core.registry import LoaderRegistry  # noqa: E402
from avialsync.loaders.imaging_loader import TIFFImagingLoader  # noqa: E402
from avialsync.loaders.nwb_session import NWBSessionSource  # noqa: E402
from avialsync.loaders.nwb_stack import NWBStackSource  # noqa: E402
from tests.nwb_fixture import NWBSpec, _imaging_frames, red_frames, write_nwb  # noqa: E402


def _imaging_items(path: Path) -> list:
    layout = NWBSessionSource().scan(path, LoaderRegistry())
    return [item for item in layout.items if item.loader is NWBStackSource]


def test_nwb_series_of_one_acquisition_open_as_the_channels_of_one_stack(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb", NWBSpec(red_channel=True))
    items = _imaging_items(path)
    assert len(items) == 1, "green and red are one acquisition, not two sources"
    item = items[0]
    assert item.config == {
        "channels": ["/acquisition/TwoPhotonSeries", "/acquisition/TwoPhotonSeriesRed"]
    }
    source = NWBStackSource()
    try:
        info = source.open(item.path, item.config)
        assert info.channel_count == 2
        assert info.channel_names == ("TwoPhotonSeries", "TwoPhotonSeriesRed")
        assert np.array_equal(source.read_frame(3, 0), _imaging_frames("uint16")[3])
        assert np.array_equal(source.read_frame(3, 1), red_frames()[3])
    finally:
        source.close()


def test_series_on_another_clock_stay_separate(tmp_path: Path) -> None:
    """A 5-frame series on the same plane is not a channel of a 12-frame one."""
    path = write_nwb(tmp_path / "s.nwb", NWBSpec(second_imaging=True))
    assert [item.config for item in _imaging_items(path)] == [{}, {}]


def test_a_single_series_is_named_by_its_optical_channel(tmp_path: Path) -> None:
    path = write_nwb(tmp_path / "s.nwb")
    source = NWBStackSource()
    try:
        info = source.open(path / "acquisition" / "TwoPhotonSeries", {})
        assert info.channel_names == ("green",)
    finally:
        source.close()


def test_merged_series_are_named_by_what_tells_them_apart() -> None:
    from avialsync.loaders.nwb_stack import _distinct_names

    assert _distinct_names(["TwoPhotonSeriesGreen", "TwoPhotonSeriesRed"]) == ("Green", "Red")
    assert _distinct_names(["Ch_a", "Ch_b"]) == ("a", "b")


def test_ome_channel_names_reach_the_viewer(tmp_path: Path) -> None:
    path = tmp_path / "two.ome.tif"
    stack = np.zeros((3, 2, 4, 5), np.uint16)
    tifffile.imwrite(
        path,
        stack,
        ome=True,
        metadata={"axes": "TCYX", "TimeIncrement": 0.1, "Channel": {"Name": ["GCaMP", "tdTom"]}},
    )
    reader = TIFFImagingLoader()
    try:
        assert reader.open(path, {}).channel_names == ("GCaMP", "tdTom")
    finally:
        reader.close()
