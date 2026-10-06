"""Ground-truth tests for time-indexed image planes (D-186).

Every stack here is written by the test with known pixels and known times, so
each assertion checks a plane against the array it came from rather than
against what the reader happened to return last time.
"""

from xml.etree import ElementTree

import h5py
import numpy as np
import pytest
import tifffile

from avialsync.core.errors import ImagingChoiceRequired, SourceOpenError
from avialsync.core.registry import LoaderRegistry
from avialsync.loaders.imaging_loader import HDF5ImagingLoader, TIFFImagingLoader, _ome_plane_times


def test_hdf5_reads_only_selected_plane_and_explicit_times(tmp_path):
    """A frame request must retain its source timestamp and original pixel range."""
    path = tmp_path / "stack.h5"
    stack = np.arange(4 * 3 * 5, dtype=np.uint16).reshape(4, 3, 5) * 100
    with h5py.File(path, "w") as handle:
        handle.create_dataset("images", data=stack, chunks=(1, 3, 5))
        handle.create_dataset("timestamps", data=np.array([0.0, 0.1, 0.22, 0.35]))
    reader = HDF5ImagingLoader()
    info = reader.open(path, {"dataset": "images"})
    assert info.frame_count == 4
    assert info.channel_count == 1
    assert info.frame_times.tolist() == [0.0, 0.1, 0.22, 0.35]
    assert info.timing_source == "frame_times"
    np.testing.assert_array_equal(reader.read_frame(2), stack[2])
    reader.close()


def test_hdf5_asks_for_axes_then_reads_each_channel(tmp_path):
    """A channel dimension is never silently read as time or space."""
    path = tmp_path / "stack.hdf5"
    stack = np.arange(3 * 2 * 4 * 5, dtype=np.uint16).reshape(3, 2, 4, 5)
    with h5py.File(path, "w") as handle:
        handle.create_dataset("images", data=stack)
    reader = HDF5ImagingLoader()
    with pytest.raises(ImagingChoiceRequired) as asked:
        reader.open(path, {"dataset": "images", "fps": 10})
    assert asked.value.choice == "axes"
    info = reader.open(path, {"axes": "TCYX", "fps": 10})
    assert info.channel_count == 2
    assert info.frame_times.tolist() == [0.0, 0.1, 0.2]
    np.testing.assert_array_equal(reader.read_frame(1, 0), stack[1, 0])
    np.testing.assert_array_equal(reader.read_frame(1, 1), stack[1, 1])
    reader.close()


def test_hdf5_lists_datasets_when_more_than_one_could_be_the_stack(tmp_path):
    path = tmp_path / "two.h5"
    with h5py.File(path, "w") as handle:
        handle.create_dataset("raw", data=np.zeros((3, 4, 5), np.uint16))
        handle.create_dataset("registered", data=np.zeros((3, 4, 5), np.uint16))
    reader = HDF5ImagingLoader()
    with pytest.raises(ImagingChoiceRequired) as asked:
        reader.open(path, {"fps": 5})
    assert asked.value.choice == "dataset"
    assert set(asked.value.options) == {"raw", "registered"}


def test_hdf5_asks_for_a_depth_plane_and_reads_only_that_plane(tmp_path):
    path = tmp_path / "volume.h5"
    stack = np.arange(3 * 4 * 2 * 6 * 7, dtype=np.uint16).reshape(3, 4, 2, 6, 7)
    with h5py.File(path, "w") as handle:
        handle.create_dataset("images", data=stack).attrs["axes"] = "TZCYX"
    reader = HDF5ImagingLoader()
    with pytest.raises(ImagingChoiceRequired) as asked:
        reader.open(path, {"fps": 2})
    assert asked.value.choice == "z"
    assert asked.value.options == ("0", "1", "2", "3")
    reader.open(path, {"fps": 2, "z": 2})
    np.testing.assert_array_equal(reader.read_frame(1, 1), stack[1, 2, 1])
    reader.close()


def test_a_typed_frame_rate_wins_over_the_files_own(tmp_path):
    """File timing is a default; what the user typed is applied (AGENTS traps)."""
    path = tmp_path / "rate.h5"
    with h5py.File(path, "w") as handle:
        handle.create_dataset("images", data=np.zeros((3, 4, 5), np.uint16)).attrs["fps"] = 30.0
    reader = HDF5ImagingLoader()
    assert reader.open(path, {}).frame_times[1] == pytest.approx(1 / 30)
    info = reader.open(path, {"fps": 15.0})
    assert info.frame_times[1] == pytest.approx(1 / 15)
    assert info.timing_source == "import frame rate"
    reader.close()


def test_tiff_reads_one_page(tmp_path):
    """Page indexing is stable for a plain multi-page 16-bit TIFF."""
    path = tmp_path / "stack.tiff"
    stack = np.arange(4 * 6 * 7, dtype=np.uint16).reshape(4, 6, 7)
    tifffile.imwrite(path, stack, photometric="minisblack")
    reader = TIFFImagingLoader()
    info = reader.open(path, {"fps": 20})
    assert (info.frame_count, info.height, info.width) == (4, 6, 7)
    np.testing.assert_array_equal(reader.read_frame(3), stack[3])
    reader.close()


def test_ome_tiff_channels_are_read_separately_with_their_times(tmp_path):
    """A multi-channel OME stack keeps time and channel indices distinct."""
    path = tmp_path / "multi.ome.tif"
    stack = np.arange(3 * 2 * 8 * 9, dtype=np.uint16).reshape(3, 2, 8, 9)
    tifffile.imwrite(path, stack, ome=True, metadata={"axes": "TCYX", "TimeIncrement": 0.1})
    reader = TIFFImagingLoader()
    info = reader.open(path, {})
    assert info.frame_count == 3
    assert info.channel_count == 2
    assert info.frame_times.tolist() == [0.0, 0.1, 0.2]
    np.testing.assert_array_equal(reader.read_frame(2, 0), stack[2, 0])
    np.testing.assert_array_equal(reader.read_frame(2, 1), stack[2, 1])
    with pytest.raises(SourceOpenError):
        reader.read_frame(2, 2)
    reader.close()


def test_scanimage_interleaved_channels_are_split_and_timed_by_its_scan_rate(tmp_path):
    """ScanImage writes channel-interleaved pages and keeps its rate in frame data.

    The software tag uses ScanImage's own ``SI.`` key format, which is what
    ``tifffile`` recognises; an aborted acquisition's trailing page is dropped
    rather than shown as half a time point.
    """
    path = tmp_path / "file_00001.tif"
    frames, channels = 5, 2
    stack = np.arange(frames * channels * 4 * 6, dtype=np.int16).reshape(frames, channels, 4, 6)
    software = (
        "SI.hChannels.channelSave = [1;2]\n"
        "SI.hFastZ.enable = false\n"
        "SI.hStackManager.numSlices = 1\n"
        "SI.hRoiManager.scanFrameRate = 30.02\n"
        "SI.hRoiManager.scanVolumeRate = 30.02"
    )
    pages = list(stack.reshape(frames * channels, 4, 6)) + [np.zeros((4, 6), np.int16)]
    with tifffile.TiffWriter(path, bigtiff=True) as writer:
        for page in pages:
            writer.write(page, software=software, photometric="minisblack", metadata=None)
    reader = TIFFImagingLoader()
    info = reader.open(path, {})
    assert (info.frame_count, info.channel_count) == (frames, channels)
    assert info.frame_times[1] == pytest.approx(1 / 30.02)
    for frame in (0, 3):
        for channel in (0, 1):
            np.testing.assert_array_equal(reader.read_frame(frame, channel), stack[frame, channel])
    reader.close()


def test_ome_plane_times_keep_variable_acquisition_intervals():
    """DeltaT for the chosen plane beats a nominal constant frame rate."""
    pixels = ElementTree.fromstring(
        '<Pixels><Plane TheT="0" TheC="0" DeltaT="0"/>'
        '<Plane TheT="1" TheC="0" DeltaT="110" DeltaTUnit="ms"/>'
        '<Plane TheT="2" TheC="0" DeltaT="250" DeltaTUnit="ms"/>'
        '<Plane TheT="0" TheC="1" DeltaT="5"/></Pixels>'
    )
    times = _ome_plane_times(pixels, "TCYX", 0, 3)
    assert times is not None
    assert times.tolist() == [0.0, 0.11, 0.25]


def test_missing_timing_is_asked_for_not_invented(tmp_path):
    """No synthetic frame rate is invented for an untimed acquisition."""
    path = tmp_path / "stack.tif"
    tifffile.imwrite(path, np.zeros((3, 4, 5), dtype=np.uint16), photometric="minisblack")
    reader = TIFFImagingLoader()
    with pytest.raises(ImagingChoiceRequired) as asked:
        reader.open(path, {})
    assert asked.value.choice == "fps"


def test_non_increasing_timestamps_are_refused_with_a_reason(tmp_path):
    path = tmp_path / "stack.h5"
    with h5py.File(path, "w") as handle:
        handle.create_dataset("images", data=np.zeros((3, 4, 5), np.uint16))
        handle.create_dataset("timestamps", data=np.array([0.0, 0.2, 0.1]))
    with pytest.raises(SourceOpenError, match="strictly increasing"):
        HDF5ImagingLoader().open(path, {})


def test_registry_routes_hdf5_and_tiff_to_imaging_sources(tmp_path):
    """Drag/drop capability resolution keeps stacks out of the video path."""
    registry = LoaderRegistry(plugin_dirs=[])
    assert registry.find_best_loader(tmp_path / "stack.h5") is HDF5ImagingLoader
    assert registry.find_best_loader(tmp_path / "stack.tif") is TIFFImagingLoader
