"""Build a miniature Open Ephys binary recording for tests.

Small enough to write in a ``tmp_path`` and real enough that neo opens it, so the
loader tests exercise the same code path a rig recording does rather than a mock
standing in for it.  Nothing here reads the user's own field data (AGENTS §5).

Layout produced, matching Open Ephys GUI v0.6+::

    <root>/2026-06-21_17-54-56/Record Node 1/experiment1/recording1/
        structure.oebin
        sync_messages.txt
        continuous/Board-1.<stream>/{continuous.dat,timestamps.npy,sample_numbers.npy}
        events/Board-1.<stream>/TTL/{timestamps,sample_numbers,states,full_words}.npy
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

#: Local wall-clock name Open Ephys gives its session directory.
RECORD_DIR_NAME = "2026-06-21_17-54-56"

#: UTC epoch written to ``sync_messages.txt``.  Three hours behind
#: :data:`RECORD_DIR_NAME`, so the fixture carries a +03:00 rig offset to derive.
SOFTWARE_EPOCH_MS = 1782053697004

#: Acquisition-clock time of the first sample, in seconds.
FIRST_SAMPLE_TIME = 5.0


@dataclass
class StreamSpec:
    """One continuous stream to write into the fixture."""

    name: str
    sample_rate: float
    channels: list[str]
    samples: int
    bit_volts: float = 0.195
    units: str = "uV"
    #: Acquisition-clock time of this stream's first sample.
    t_start: float = FIRST_SAMPLE_TIME

    @property
    def folder_name(self) -> str:
        return f"Board-1.{self.name}"


@dataclass
class TTLSpec:
    """A TTL line to write as rising/falling edge pairs."""

    stream: str
    rise_times: list[float]
    width: float = 0.004
    line: int = 1


@dataclass
class RecordingSpec:
    """Everything one ``recordingN`` directory should contain."""

    streams: list[StreamSpec]
    ttl: TTLSpec | None = None
    software_epoch_ms: int | None = SOFTWARE_EPOCH_MS
    record_dir_name: str = RECORD_DIR_NAME
    extra_messages: list[str] = field(default_factory=list)


def default_spec() -> RecordingSpec:
    """Return a two-stream recording with a TTL line, as most tests want it."""
    return RecordingSpec(
        streams=[
            StreamSpec(name="board", sample_rate=1000.0, channels=["CH1", "CH2"], samples=2000),
            StreamSpec(
                name="aux",
                sample_rate=100.0,
                channels=["AUX1"],
                samples=200,
                bit_volts=1.0,
                units="V",
                t_start=FIRST_SAMPLE_TIME + 0.01,
            ),
        ],
        ttl=TTLSpec(stream="board", rise_times=[5.5, 5.6, 5.7, 5.8, 6.5]),
    )


def write_recording(root: Path, spec: RecordingSpec | None = None) -> Path:
    """Write *spec* under *root* and return the ``recording1`` directory."""
    spec = spec or default_spec()
    recording = root / spec.record_dir_name / "Record Node 1" / "experiment1" / "recording1"
    (recording / "continuous").mkdir(parents=True, exist_ok=True)

    # ``settings.xml`` beside the record node is what used to capture the
    # dataset-root search before ``structure.oebin`` was looked for first.
    (recording.parents[1] / "settings.xml").write_text("<SETTINGS/>", encoding="utf-8")

    manifest: dict[str, object] = {"GUI version": "1.0.2", "continuous": [], "events": []}

    for stream in spec.streams:
        _write_stream(recording, stream)
        assert isinstance(manifest["continuous"], list)
        manifest["continuous"].append(_stream_manifest(stream))

    if spec.ttl is not None:
        _write_ttl(recording, spec)
        assert isinstance(manifest["events"], list)
        manifest["events"].append(_ttl_manifest(spec.ttl))

    (recording / "structure.oebin").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    _write_sync_messages(recording, spec)
    return recording


def _write_stream(recording: Path, stream: StreamSpec) -> None:
    directory = recording / "continuous" / stream.folder_name
    directory.mkdir(parents=True, exist_ok=True)

    count = len(stream.channels)
    # A distinct ramp per channel, so a test can tell channels apart by value.
    index = np.arange(stream.samples, dtype=np.int16)
    data = np.empty((stream.samples, count), dtype=np.int16)
    for column in range(count):
        data[:, column] = index + column * 100
    data.tofile(directory / "continuous.dat")

    first_sample = int(round(stream.t_start * stream.sample_rate))
    sample_numbers = np.arange(first_sample, first_sample + stream.samples, dtype=np.int64)
    np.save(directory / "sample_numbers.npy", sample_numbers)
    np.save(
        directory / "timestamps.npy",
        (sample_numbers / stream.sample_rate).astype(np.float64),
    )


def _stream_manifest(stream: StreamSpec) -> dict[str, object]:
    return {
        "folder_name": f"{stream.folder_name}/",
        "sample_rate": stream.sample_rate,
        "source_processor_name": "Board",
        "source_processor_id": 1,
        "stream_name": stream.name,
        "recorded_processor": "Record Node",
        "recorded_processor_id": 1,
        "num_channels": len(stream.channels),
        "channels": [
            {
                "channel_name": name,
                "description": "test channel",
                "identifier": "test.continuous",
                "history": "Board -> Record Node",
                "bit_volts": stream.bit_volts,
                "units": stream.units,
                "type": 0,
            }
            for name in stream.channels
        ],
    }


def _write_ttl(recording: Path, spec: RecordingSpec) -> None:
    ttl = spec.ttl
    assert ttl is not None
    stream = next(item for item in spec.streams if item.name == ttl.stream)
    directory = recording / "events" / f"{stream.folder_name}" / "TTL"
    directory.mkdir(parents=True, exist_ok=True)

    rises = np.asarray(ttl.rise_times, dtype=np.float64)
    times = np.empty(2 * len(rises), dtype=np.float64)
    times[0::2] = rises
    times[1::2] = rises + ttl.width

    states = np.empty(len(times), dtype=np.int16)
    states[0::2] = ttl.line
    states[1::2] = -ttl.line

    np.save(directory / "timestamps.npy", times)
    np.save(directory / "states.npy", states)
    np.save(
        directory / "sample_numbers.npy",
        np.round(times * stream.sample_rate).astype(np.int64),
    )
    np.save(
        directory / "full_words.npy",
        np.where(states > 0, 1 << (ttl.line - 1), 0).astype(np.uint64),
    )


def _ttl_manifest(ttl: TTLSpec) -> dict[str, object]:
    return {
        "folder_name": f"Board-1.{ttl.stream}/TTL/",
        "channel_name": "Board TTL Input",
        "description": "TTL input",
        "identifier": "test.ttl",
        "sample_rate": 1000.0,
        "type": "int16",
        "source_processor": "Board",
        "stream_name": ttl.stream,
        "initial_state": 0,
    }


def _write_sync_messages(recording: Path, spec: RecordingSpec) -> None:
    lines: list[str] = []
    if spec.software_epoch_ms is not None:
        lines.append(
            "Software Time (milliseconds since midnight Jan 1st 1970 UTC): "
            f"{spec.software_epoch_ms}"
        )
    for stream in spec.streams:
        start = int(round(stream.t_start * stream.sample_rate))
        lines.append(
            f"Start Time for Board (1) - {stream.name} @ {stream.sample_rate:g} Hz: {start}"
        )
    lines.extend(spec.extra_messages)
    (recording / "sync_messages.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
