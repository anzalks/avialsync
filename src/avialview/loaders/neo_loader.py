"""Neo-based Electrophysiology Data Loader."""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import neo
import numpy as np

from avialview.core.source import ChannelInfo, TimeSeriesSource

logger = logging.getLogger(__name__)

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

        # Use Neo to read the first block
        io_instance = neo.io.get_io(str(resolved_path))
        self._block = io_instance.read_block()

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

        if t_start == float("inf"):
            t_start, t_stop = 0.0, 0.0

    def channels(self) -> list[ChannelInfo]:
        return self._schema_channels

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        if self._block is None or ch not in self._channel_map:
            raise RuntimeError(f"Cannot read channel {ch}")

        seg_idx, asig_idx, ch_idx = self._channel_map[ch]
        asig = self._block.segments[seg_idx].analogsignals[asig_idx]

        batch_size = 100000
        length = asig.shape[0]
        sr = float(asig.sampling_rate.magnitude)
        start_time = float(asig.t_start.magnitude)

        # Extract the specific column for this channel as a standard numpy array
        # to strip neo's Quantity wrapper which can cause issues with downstream math.
        # We also .ravel() it to flatten the (N, 1) shape returned by AnalogSignal indexing to (N,)
        data = np.asarray(asig[:, ch_idx].magnitude).ravel()

        for i in range(0, length, batch_size):
            end_idx = min(i + batch_size, length)
            chunk_data = data[i:end_idx]

            # Generate deterministic time chunk
            t_chunk = start_time + (np.arange(i, end_idx) / sr)

            yield t_chunk, chunk_data
