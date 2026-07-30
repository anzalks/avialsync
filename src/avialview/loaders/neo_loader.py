"""Neo-based Electrophysiology Data Loader."""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import neo
import numpy as np

from avialview.core.source import ChannelInfo, TimeSeriesSource

logger = logging.getLogger(__name__)


def _fit_length(batch: np.ndarray, expected: int) -> np.ndarray:
    """Trim or NaN-pad *batch* to *expected* samples.

    Neo resolves a lazy ``time_slice`` by timestamp, so a batch boundary can land
    one sample either side of the index range the caller asked for.  Padding is
    NaN rather than zero: a missing sample is missing, never a real value.
    """
    if len(batch) == expected:
        return batch
    if len(batch) > expected:
        return batch[:expected]
    padded = np.full(expected, np.nan, dtype=np.float64)
    padded[: len(batch)] = batch
    return padded


# Explicit ephys extension whitelist — can_open returns 0.0 for anything not here.
# This prevents neo from claiming CSV, TXT, or unknown binary files (D-019).
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".nix",  # NIX (G-Node)
        ".ncs",  # Neuralynx Continuously Sampled
        ".nse",  # Neuralynx Single Electrode
        ".ntt",  # Neuralynx Tetrode
        ".nev",  # Neuralynx / BlackRock events
        ".plx",  # Plexon PLX
        ".smr",  # CED Spike2
        ".edf",  # European Data Format
        ".abf",  # Axon Binary File
        ".mcd",  # Multi Channel Systems
        ".continuous",  # OpenEphys single-channel file (usually inside a dir bundle)
    }
)


class NeoLoader(TimeSeriesSource):
    """Loads electrophysiology data using the neo library."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._schema_channels: list[ChannelInfo] = []
        self._block: neo.Block | None = None
        self._lazy = False

        # We store metadata for chunk reading:
        # channel_name -> (segment_index, analogsignal_index, channel_index_in_analogsignal)
        self._channel_map: dict[str, tuple[int, int, int]] = {}

    @classmethod
    def _find_dataset_root(cls, path: Path) -> Path | None:
        """Find the true ephys root by scanning up to depth 3 for signatures."""
        if not path.is_dir():
            return None

        signatures = {
            "structure.oebin",
            "*.xml",
            "*.continuous",
            "*.ap.meta",
            "*.lf.meta",
            "*.ncs",
            "*.nix",
        }

        # Shallow BFS up to depth 3
        queue = [(path, 0)]
        while queue:
            current_path, depth = queue.pop(0)

            # Check for signatures
            for sig in signatures:
                if sig.startswith("*."):
                    if next(current_path.glob(sig), None):
                        return current_path
                elif (current_path / sig).exists():
                    return current_path

            if depth < 2:  # 0, 1, 2 (max depth 3 search)
                try:
                    for child in current_path.iterdir():
                        if child.is_dir():
                            queue.append((child, depth + 1))
                except PermissionError:
                    pass
        return None

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Return 1.0 for whitelisted ephys formats; 0.0 for everything else.

        Directories are accepted only when _find_dataset_root locates an ephys
        dataset signature (structure.oebin, *.ncs, *.ap.meta, etc.).  Files must
        match SUPPORTED_EXTENSIONS before any header probe is attempted — this
        prevents neo from claiming .csv, .txt, or unknown binaries.
        """
        if path.is_dir():
            root = cls._find_dataset_root(path)
            if root is not None:
                # Prevent neo from aggressively swallowing a parent folder (e.g. dragging a whole
                # session folder containing videos and an ephys sub-sub-folder) by only claiming
                # the directory if the dataset root is the directory itself or an immediate child.
                try:
                    if len(root.relative_to(path).parts) <= 1:
                        return 1.0
                except ValueError:
                    pass
            return 0.0

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return 0.0

        # Cheap header probe for whitelisted extensions
        try:
            if neo.io.get_io(str(path)) is not None:
                return 1.0
        except Exception:
            logger.debug("Neo rejected candidate %s", path, exc_info=True)

        return 0.0

    def open(self, path: Path, config: dict[str, Any]) -> None:
        self._path = path
        self._config = config

        resolved_path = path
        try:
            neo.io.get_io(str(resolved_path))
        except Exception:
            root = self._find_dataset_root(path)
            if root:
                resolved_path = root

        # Use Neo to read the first block.  Lazy mode returns proxy signals whose
        # samples stay on disk until a slice is requested, so a 50 kHz multi-hour
        # recording never has to fit in RAM.  Not every Neo IO implements it, so
        # fall back to an eager read and let read_chunks slice the loaded array.
        io_instance = neo.io.get_io(str(resolved_path))
        try:
            self._block = io_instance.read_block(lazy=True)
            self._lazy = True
        except (TypeError, ValueError, NotImplementedError) as error:
            logger.info(
                "Neo IO %s has no lazy mode (%s); reading eagerly.", type(io_instance), error
            )
            self._block = io_instance.read_block()
            self._lazy = False

        self._schema_channels = []
        self._channel_map = {}

        t_start = float("inf")
        t_stop = float("-inf")

        for seg_idx, segment in enumerate(self._block.segments):
            for asig_idx, asig in enumerate(segment.analogsignals):
                sr = float(asig.sampling_rate.magnitude)
                start_time = float(asig.t_start.magnitude)
                length = asig.shape[0]
                end_time = start_time + (length / sr)

                t_start = min(t_start, start_time)
                t_stop = max(t_stop, end_time)

                # Check for channel names
                ch_names = asig.name
                if isinstance(ch_names, str):
                    ch_names = (
                        [ch_names]
                        if asig.shape[1] == 1
                        else [f"{ch_names}_{i}" for i in range(asig.shape[1])]
                    )
                elif ch_names is None:
                    ch_names = [f"Signal_{seg_idx}_{asig_idx}_{i}" for i in range(asig.shape[1])]

                # Some formats store array_annotations['channel_names']
                if "channel_names" in asig.array_annotations:
                    ch_names = asig.array_annotations["channel_names"]

                for ch_idx, ch_name in enumerate(ch_names):
                    # Ensure uniqueness
                    unique_name = str(ch_name)
                    counter = 1
                    while unique_name in self._channel_map:
                        unique_name = f"{ch_name}_{counter}"
                        counter += 1

                    # Neo often loads data as float32 or float64. We preserve the underlying dtype.
                    # Attempt to extract scientific unit from Neo quantities
                    unit_str = "uV"
                    if hasattr(asig, "units") and hasattr(asig.units, "dimensionality"):
                        unit_str = str(asig.units.dimensionality.string)

                    dtype = getattr(asig, "dtype", np.dtype(np.float64))
                    self._schema_channels.append(
                        ChannelInfo(name=unique_name, unit=unit_str, dtype=str(dtype), rate_hz=sr)
                    )
                    self._channel_map[unique_name] = (seg_idx, asig_idx, ch_idx)

        self._event_map = {}
        for seg_idx, segment in enumerate(self._block.segments):
            for ev_idx, event in enumerate(segment.events):
                ch_names = event.name
                if isinstance(ch_names, str) and ch_names:
                    ch_names = [f"Evt-{ch_names}"]
                else:
                    ch_names = [f"Event_{seg_idx}_{ev_idx}"]

                for ch_name in ch_names:
                    unique_name = str(ch_name)
                    counter = 1
                    while unique_name in self._channel_map or unique_name in self._event_map:
                        unique_name = f"{ch_name}_{counter}"
                        counter += 1

                    self._schema_channels.append(
                        ChannelInfo(name=unique_name, unit="TTL", dtype="float32", rate_hz=30000.0)
                    )
                    self._event_map[unique_name] = (seg_idx, ev_idx)

        if t_start == float("inf"):
            t_start, t_stop = 0.0, 0.0

    def channels(self) -> list[ChannelInfo]:
        return self._schema_channels

    def _read_samples(
        self,
        asig: Any,
        ch_idx: int,
        start: int,
        stop: int,
        sample_rate: float,
        t_start: float,
    ) -> np.ndarray:
        """Return one bounded sample batch for a single channel.

        A lazy Neo proxy is asked for the time slice directly so only the batch
        reaches memory.  Eager signals are sliced in place, which is still bounded
        because the batch is a view until ``np.asarray`` copies it.
        """
        if self._lazy and hasattr(asig, "load"):
            import quantities as pq

            window = (
                (t_start + start / sample_rate) * pq.s,
                (t_start + stop / sample_rate) * pq.s,
            )
            loaded = asig.load(time_slice=window, channel_indexes=[ch_idx])
            batch = np.asarray(loaded.magnitude, dtype=np.float64).ravel()
            # Neo resolves slice edges by timestamp, so trim/pad to the exact
            # requested batch length rather than trusting the boundary rounding.
            return _fit_length(batch, stop - start)
        return np.asarray(asig[start:stop, ch_idx].magnitude, dtype=np.float64).ravel()

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        if self._block is None:
            raise RuntimeError(f"Cannot read channel {ch}")

        if ch in self._channel_map:
            seg_idx, asig_idx, ch_idx = self._channel_map[ch]
            asig = self._block.segments[seg_idx].analogsignals[asig_idx]

            batch_size = 100000
            length = asig.shape[0]
            sr = float(asig.sampling_rate.magnitude)
            start_time = float(asig.t_start.magnitude)

            for i in range(0, length, batch_size):
                end_idx = min(i + batch_size, length)
                chunk_data = self._read_samples(asig, ch_idx, i, end_idx, sr, start_time)
                t_chunk = start_time + (np.arange(i, end_idx) / sr)
                yield t_chunk, chunk_data

        elif ch in self._event_map:
            seg_idx, ev_idx = self._event_map[ch]
            event = self._block.segments[seg_idx].events[ev_idx]
            ev_times = np.asarray(event.times.magnitude, dtype=np.float64)

            # Determine bounds and rate from analogous signals or fallback
            sr = 30000.0
            start_time = 0.0
            length = 0
            if self._block.segments[seg_idx].analogsignals:
                asig = self._block.segments[seg_idx].analogsignals[0]
                sr = float(asig.sampling_rate.magnitude)
                start_time = float(asig.t_start.magnitude)
                length = asig.shape[0]
            else:
                start_time = float(np.min(ev_times)) if len(ev_times) > 0 else 0.0
                end_time = float(np.max(ev_times)) if len(ev_times) > 0 else 1.0
                length = int((end_time - start_time) * sr) + 1

            batch_size = 100000
            for i in range(0, length, batch_size):
                end_idx = min(i + batch_size, length)
                t_chunk = start_time + (np.arange(i, end_idx) / sr)
                chunk_data = np.zeros(end_idx - i, dtype=np.float32)

                if len(ev_times) > 0:
                    chunk_start = t_chunk[0]
                    chunk_end = t_chunk[-1]
                    # We add a tiny margin to avoid missing boundary events
                    mask = (ev_times >= chunk_start - 1.0 / sr) & (ev_times <= chunk_end + 1.0 / sr)
                    for et in ev_times[mask]:
                        idx = int(np.round((et - chunk_start) * sr))
                        if 0 <= idx < len(chunk_data):
                            chunk_data[idx] = 1.0

                yield t_chunk, chunk_data
        else:
            raise RuntimeError(f"Cannot read channel {ch}")
