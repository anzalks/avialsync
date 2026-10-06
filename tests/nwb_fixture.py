"""Write small NWB 2.x files for tests, with h5py alone (D-188).

The layout follows the NWB 2 HDF5 schema -- the attributes, the
``DynamicTableRegion`` references, the ragged ``_index`` columns -- closely
enough that pynwb reads these files back (checked when this was written, against
pynwb 4.2). The test suite does not depend on pynwb; the point of matching it is
that a passing test here means a real file of the same shape loads.

Every array is deterministic, so a test can assert exact values.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import h5py
import numpy as np

SESSION_START = "2024-03-05T10:00:00+00:00"
SESSION_EPOCH = 1709632800.0

#: Electrode ids deliberately not 0..n-1, so a test can tell an id from a column.
ELECTRODE_IDS = (10, 11, 12, 13)
ROI_IDS = (3, 5, 8)
EPHYS_RATE = 1000.0
EPHYS_SAMPLES = 2500
#: Raw int16 counts * channel_conversion * conversion -> volts.
EPHYS_CONVERSION = 1e-6
EPHYS_CHANNEL_CONVERSION = (1.0, 2.0, 0.5, 1.0)
IMAGING_FRAMES = 12
IMAGING_SHAPE = (9, 7)
IMAGING_RATE = 30.0
POSITION_SAMPLES = 400


@dataclass
class NWBSpec:
    """What :func:`write_nwb` puts in the file. Each part can be switched off."""

    session_start: str = SESSION_START
    ephys: bool = True
    position: bool = True
    imaging: bool = True
    imaging_dtype: str = "uint16"
    imaging_start: float = 0.5
    second_imaging: bool = False
    #: A red channel recorded with the green: same plane, shape and timestamps.
    red_channel: bool = False
    fluorescence: bool = True
    intervals: bool = True
    trials: bool = True
    units: bool = True
    annotations: bool = True
    external_video: str | None = None
    declined: bool = True
    extension_imaging: bool = False
    position_timestamps: np.ndarray | None = None
    extra: dict[str, object] = field(default_factory=dict)


def _dtype(data: np.ndarray) -> object:
    """Strings as HDF5 variable-length UTF-8, the way NWB writers store them."""
    return h5py.string_dtype() if data.dtype == object else data.dtype


def _attrs(
    obj: h5py.HLObject, neurodata_type: str, namespace: str = "core", **extra: object
) -> None:
    obj.attrs["neurodata_type"] = neurodata_type
    obj.attrs["namespace"] = namespace
    obj.attrs["object_id"] = str(uuid.uuid4())
    for key, value in extra.items():
        obj.attrs[key] = value


def _series(
    parent: h5py.Group,
    name: str,
    neurodata_type: str,
    data: np.ndarray,
    unit: str,
    *,
    rate: float | None = None,
    start: float = 0.0,
    timestamps: np.ndarray | None = None,
    conversion: float = 1.0,
    offset: float = 0.0,
    namespace: str = "core",
) -> h5py.Group:
    group = parent.create_group(name)
    _attrs(group, neurodata_type, namespace, description="test series", comments="no comments")
    dataset = group.create_dataset("data", data=data, dtype=_dtype(data))
    dataset.attrs["unit"] = unit
    dataset.attrs["conversion"] = conversion
    dataset.attrs["offset"] = offset
    dataset.attrs["resolution"] = -1.0
    if timestamps is not None:
        stamps = group.create_dataset("timestamps", data=np.asarray(timestamps, dtype=np.float64))
        stamps.attrs["interval"] = 1
        stamps.attrs["unit"] = "seconds"
    else:
        assert rate is not None
        starting = group.create_dataset("starting_time", data=float(start))
        starting.attrs["rate"] = float(rate)
        starting.attrs["unit"] = "seconds"
    return group


def _table(
    parent: h5py.Group, name: str, neurodata_type: str, rows: int, columns: list[str]
) -> h5py.Group:
    group = parent.create_group(name)
    _attrs(
        group,
        neurodata_type,
        description=f"{name} table",
        colnames=np.array(columns, dtype=h5py.string_dtype()),
    )
    ids = group.create_dataset("id", data=np.arange(rows, dtype=np.int64))
    _attrs(ids, "ElementIdentifiers", "hdmf-common")
    return group


def _column(table: h5py.Group, name: str, data: np.ndarray) -> h5py.Dataset:
    column = table.create_dataset(name, data=data, dtype=_dtype(data))
    _attrs(column, "VectorData", "hdmf-common", description=name)
    return column


def _region(group: h5py.Group, name: str, table: h5py.Group, rows: list[int]) -> None:
    region = group.create_dataset(name, data=np.asarray(rows, dtype=np.int64))
    _attrs(region, "DynamicTableRegion", "hdmf-common", description=name)
    region.attrs["table"] = table.ref


def write_nwb(path: Path, spec: NWBSpec | None = None) -> Path:
    """Write an NWB file holding what *spec* asks for, and return its path."""
    spec = spec or NWBSpec()
    with h5py.File(path, "w") as f:
        _attrs(f, "NWBFile", nwb_version="2.6.0")
        f.attrs["nwb_version"] = "2.6.0"
        f.create_dataset("session_start_time", data=spec.session_start)
        f.create_dataset("timestamps_reference_time", data=spec.session_start)
        f.create_dataset("identifier", data="avialsync-test")
        f.create_dataset("session_description", data="fixture")
        f.create_dataset("file_create_date", data=[spec.session_start], dtype=h5py.string_dtype())
        for section in (
            "acquisition",
            "analysis",
            "processing",
            "stimulus/presentation",
            "stimulus/templates",
            "general",
        ):
            f.require_group(section)
        f.create_group("general/devices")
        acquisition = f["acquisition"]

        if spec.ephys:
            ecephys = f.create_group("general/extracellular_ephys")
            device = f["general/devices"].create_group("probe")
            _attrs(device, "Device")
            group = ecephys.create_group("shank0")
            _attrs(group, "ElectrodeGroup", description="shank", location="CA1")
            group["device"] = h5py.SoftLink(device.name)
            electrodes = _table(
                ecephys,
                "electrodes",
                "DynamicTable",
                len(ELECTRODE_IDS),
                ["location", "group", "group_name"],
            )
            electrodes["id"][...] = np.asarray(ELECTRODE_IDS, dtype=np.int64)
            _column(electrodes, "location", np.array(["CA1"] * len(ELECTRODE_IDS), dtype=object))
            refs = electrodes.create_dataset(
                "group", data=[group.ref] * len(ELECTRODE_IDS), dtype=h5py.ref_dtype
            )
            _attrs(refs, "VectorData", "hdmf-common", description="group")
            _column(
                electrodes, "group_name", np.array(["shank0"] * len(ELECTRODE_IDS), dtype=object)
            )
            raw = (np.arange(EPHYS_SAMPLES)[:, None] * np.array([1, 2, 3, 4])[None, :]).astype(
                np.int16
            )
            series = _series(
                acquisition,
                "ElectricalSeries",
                "ElectricalSeries",
                raw,
                "volts",
                rate=EPHYS_RATE,
                conversion=EPHYS_CONVERSION,
            )
            _region(series, "electrodes", electrodes, list(range(len(ELECTRODE_IDS))))
            conversion = series.create_dataset(
                "channel_conversion", data=np.asarray(EPHYS_CHANNEL_CONVERSION, dtype=np.float32)
            )
            conversion.attrs["axis"] = 1

        if spec.position:
            position = acquisition.create_group("Position")
            _attrs(position, "Position")
            times = spec.position_timestamps
            if times is None:
                times = np.arange(POSITION_SAMPLES) * 0.01 + 0.2
            xy = np.stack(
                [np.sin(np.arange(len(times)) * 0.1), np.cos(np.arange(len(times)) * 0.1)], axis=1
            )
            spatial = _series(
                position, "SpatialSeries", "SpatialSeries", xy, "meters", timestamps=times
            )
            spatial.create_dataset("reference_frame", data="arena corner")

        if spec.imaging:
            plane = _imaging_plane(f)
            frames = _imaging_frames(spec.imaging_dtype)
            times = spec.imaging_start + np.arange(IMAGING_FRAMES) / IMAGING_RATE
            two_photon = _series(
                acquisition, "TwoPhotonSeries", "TwoPhotonSeries", frames, "n.a.", timestamps=times
            )
            two_photon["imaging_plane"] = h5py.SoftLink(plane.name)
            if spec.second_imaging:
                green = _series(
                    acquisition,
                    "TwoPhotonSeriesGreen",
                    "TwoPhotonSeries",
                    frames[:5],
                    "n.a.",
                    rate=IMAGING_RATE,
                )
                green["imaging_plane"] = h5py.SoftLink(plane.name)
            if spec.red_channel:
                red = _series(
                    acquisition,
                    "TwoPhotonSeriesRed",
                    "TwoPhotonSeries",
                    red_frames(),
                    "n.a.",
                    timestamps=times,
                )
                red["imaging_plane"] = h5py.SoftLink(plane.name)
                optical = plane.create_group("red")
                _attrs(optical, "OpticalChannel")
                optical.create_dataset("description", data="red")
                optical.create_dataset("emission_lambda", data=610.0)

        if spec.extension_imaging:
            frames = _imaging_frames("uint16")
            _series(
                acquisition,
                "LabScope",
                "LabScopeSeries",
                frames,
                "n.a.",
                rate=IMAGING_RATE,
                namespace="ndx-labscope",
            )
            _cache_extension_spec(f)

        if spec.external_video is not None:
            video = _series(
                acquisition,
                "BehaviorVideo",
                "ImageSeries",
                np.zeros((0, 0, 0), dtype=np.uint8),
                "n.a.",
                rate=IMAGING_RATE,
                start=1.5,
            )
            video.create_dataset(
                "external_file", data=[spec.external_video], dtype=h5py.string_dtype()
            )
            video["external_file"].attrs["starting_frame"] = np.array([0])
            video.create_dataset("format", data="external")

        processing = f["processing"]
        if spec.fluorescence or spec.intervals:
            ophys = processing.create_group("ophys")
            _attrs(ophys, "ProcessingModule", description="optical physiology")
            behavior = processing.create_group("behavior")
            _attrs(behavior, "ProcessingModule", description="behaviour")
        if spec.fluorescence:
            segmentation = ophys.create_group("ImageSegmentation")
            _attrs(segmentation, "ImageSegmentation")
            planes = _table(
                segmentation, "PlaneSegmentation", "PlaneSegmentation", len(ROI_IDS), ["image_mask"]
            )
            _column(planes, "image_mask", np.ones((len(ROI_IDS), *IMAGING_SHAPE), dtype=np.float32))
            planes["id"][...] = np.asarray(ROI_IDS, dtype=np.int64)
            planes["imaging_plane"] = h5py.SoftLink(_imaging_plane(f).name)
            for interface in ("DfOverF", "Fluorescence"):
                container = ophys.create_group(interface)
                _attrs(container, interface)
                traces = np.arange(IMAGING_FRAMES * len(ROI_IDS), dtype=np.float32).reshape(
                    IMAGING_FRAMES, len(ROI_IDS)
                )
                rois = _series(
                    container,
                    "RoiResponseSeries",
                    "RoiResponseSeries",
                    traces,
                    "n.a.",
                    rate=IMAGING_RATE,
                    start=0.5,
                )
                _region(rois, "rois", planes, list(range(len(ROI_IDS))))
        if spec.intervals:
            epochs = behavior.create_group("BehavioralEpochs")
            _attrs(epochs, "BehavioralEpochs")
            edges = np.array([1, -1, 1, -1], dtype=np.int8)
            _series(
                epochs,
                "reward",
                "IntervalSeries",
                edges,
                "n/a",
                timestamps=np.array([2.0, 2.05, 3.0, 3.0004]),
            )

        if spec.trials:
            intervals = f.require_group("intervals")
            trials = _table(
                intervals,
                "trials",
                "TimeIntervals",
                3,
                ["start_time", "stop_time", "condition", "correct"],
            )
            _column(trials, "start_time", np.array([1.0, 4.0, 7.0]))
            _column(trials, "stop_time", np.array([3.0, 6.5, 9.0]))
            _column(trials, "condition", np.array(["left", "right", "left"], dtype=object))
            _column(trials, "correct", np.array([True, False, True]))

        if spec.units:
            units = _table(f, "units", "Units", 3, ["spike_times"])
            spikes = np.array([1.0, 1.5, 2.25, 0.5, 0.75], dtype=np.float64)
            _column(units, "spike_times", spikes)
            index = units.create_dataset(
                "spike_times_index", data=np.array([3, 3, 5], dtype=np.uint64)
            )
            _attrs(index, "VectorIndex", "hdmf-common", description="index")
            index.attrs["target"] = units["spike_times"].ref
            units["id"][...] = np.array([7, 8, 9], dtype=np.int64)

        if spec.annotations:
            notes = _series(
                acquisition,
                "notes",
                "AnnotationSeries",
                np.array(["start", "lick bout", "end"], dtype=object),
                "n/a",
                timestamps=np.array([0.1, 5.0, 9.5]),
            )
            notes["data"].attrs["conversion"] = -1.0

        if spec.declined and spec.ephys:
            waveforms = np.zeros((4, 2, 8), dtype=np.int16)
            events = _series(
                acquisition,
                "SpikeWaveforms",
                "SpikeEventSeries",
                waveforms,
                "volts",
                timestamps=np.array([0.1, 0.2, 0.3, 0.4]),
            )
            _region(events, "electrodes", f["general/extracellular_ephys/electrodes"], [0, 1])

    return path


def _imaging_plane(f: h5py.File) -> h5py.Group:
    """The one imaging plane every optical object links to, made on first use."""
    if "general/optophysiology/plane0" in f:
        return f["general/optophysiology/plane0"]
    optical = f.require_group("general/optophysiology")
    plane = optical.create_group("plane0")
    _attrs(plane, "ImagingPlane")
    for key, value in (
        ("description", "plane"),
        ("excitation_lambda", 920.0),
        ("indicator", "GCaMP"),
        ("location", "V1"),
    ):
        plane.create_dataset(key, data=value)
    microscope = f["general/devices"].require_group("microscope")
    _attrs(microscope, "Device")
    plane["device"] = h5py.SoftLink(microscope.name)
    channel = plane.create_group("green")
    _attrs(channel, "OpticalChannel")
    channel.create_dataset("description", data="green")
    channel.create_dataset("emission_lambda", data=520.0)
    return plane


def _imaging_frames(dtype: str) -> np.ndarray:
    """Distinct frames whose pixels encode their frame and position, in *dtype*."""
    count = IMAGING_FRAMES * IMAGING_SHAPE[0] * IMAGING_SHAPE[1]
    base = np.arange(count, dtype=np.float64).reshape(IMAGING_FRAMES, *IMAGING_SHAPE)
    if dtype == "uint16":
        return (base * 97 % 65536).astype(np.uint16)
    if dtype == "uint8":
        return (base % 256).astype(np.uint8)
    if dtype == "int16":
        return (base * 41 % 60000 - 30000).astype(np.int16)
    if dtype == "float32":
        return (base / count - 0.25).astype(np.float32)
    raise ValueError(dtype)


def _cache_extension_spec(f: h5py.File) -> None:
    """Cache a minimal extension namespace defining ``LabScopeSeries`` as an ``ImageSeries``."""
    group = f.require_group("specifications/ndx-labscope/0.1.0")
    spec = {
        "groups": [
            {
                "neurodata_type_def": "LabScopeSeries",
                "neurodata_type_inc": "TwoPhotonSeries",
                "doc": "A lab's own two-photon series.",
            }
        ]
    }
    group.create_dataset("ndx-labscope.extensions", data=json.dumps(spec))
    group.create_dataset("namespace", data=json.dumps({"namespaces": [{"name": "ndx-labscope"}]}))


def write_nwb1(path: Path) -> Path:
    """Write NWB 1.x series in its acquisition/timeseries layout."""
    with h5py.File(path, "w") as f:
        f.create_dataset("nwb_version", data="NWB-1.0.6")
        f.create_dataset("general/session_start_time", data=SESSION_START)
        root = f.create_group("acquisition/timeseries")
        voltage = root.create_group("voltage")
        voltage.attrs["ancestry"] = np.array(["TimeSeries", "ElectricalSeries"], dtype="S")
        data = voltage.create_dataset("data", data=np.arange(10, dtype=np.int16))
        data.attrs["unit"] = "volts"
        data.attrs["conversion"] = 1e-6
        starting = voltage.create_dataset("starting_time", data=0.25)
        starting.attrs["rate"] = 1000.0
        imaging = root.create_group("camera")
        imaging.attrs["ancestry"] = np.array(["TimeSeries", "ImageSeries"], dtype="S")
        frames = imaging.create_dataset("data", data=_imaging_frames("uint16")[:3])
        frames.attrs["unit"] = "n.a."
        imaging.create_dataset("timestamps", data=np.array([0.5, 0.6, 0.7]))
    return path


def write_zarr_nwb(path: Path, *, zarr_format: int = 3) -> Path:
    """Write the NWB series layout used by PyNWB's Zarr backend."""
    import zarr

    root = zarr.open_group(str(path), mode="w", zarr_format=zarr_format)
    root.attrs["nwb_version"] = "2.11.0"
    root.create_array("session_start_time", data=np.asarray(SESSION_START))
    root.create_array("timestamps_reference_time", data=np.asarray(SESSION_START))
    acquisition = root.create_group("acquisition")
    signal = acquisition.create_group("voltage")
    signal.attrs["neurodata_type"] = "TimeSeries"
    data = signal.create_array("data", data=np.arange(10, dtype=np.int16))
    data.attrs["unit"] = "volts"
    data.attrs["conversion"] = 1e-6
    start = signal.create_array("starting_time", data=np.asarray(0.25))
    start.attrs["rate"] = 1000.0
    imaging = acquisition.create_group("camera")
    imaging.attrs["neurodata_type"] = "ImageSeries"
    frames = imaging.create_array("data", data=_imaging_frames("uint16")[:3])
    frames.attrs["unit"] = "n.a."
    imaging.create_array("timestamps", data=np.array([0.5, 0.6, 0.7]))
    return path


def red_frames() -> np.ndarray:
    """The red channel's frames: the green ones offset, so the two never match."""
    return (_imaging_frames("uint16").astype(np.int64) + 1000).astype(np.uint16)
