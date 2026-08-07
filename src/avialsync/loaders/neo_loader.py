"""Neo-based electrophysiology loader — the single ingest path for ephys data.

Every acquisition system AvialSync reads samples from goes through neo, so the
rest of the application sees one shape of data no matter which rig produced it.
Format-specific knowledge that neo does *not* model — where a recording sits in a
folder tree, and how its acquisition clock relates to wall clock — lives in the
session plugin beside it, never here.

Two things this loader does that a naive neo wrapper does not:

*   A stream is imported as **one** source, not one per channel.  All channels of
    a neo signal stream share a clock, and importing them separately wrote a
    full-resolution float64 timestamp array per channel — 32 identical 191 MB
    copies for one 30 kHz headstage.  ``read_all_chunks`` hands the importer a
    shared time base instead, which is the difference between a 7 GB sidecar and
    a 14 GB one.
*   TTL events become a **square wave from edge timestamps**, not a dense trace.
    Rendering a 30 kHz logic line as 30 kHz samples costs hundreds of megabytes
    to draw a signal with a few thousand transitions in it, and decimation then
    swallows the single-sample pulses that were the whole point.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import neo
import numpy as np

from avialsync.core.errors import SourceOpenError
from avialsync.core.source import ChannelInfo, TimeSeriesSource
from avialsync.loaders.open_ephys_format import find_recordings, is_recording_dir

logger = logging.getLogger(__name__)

#: Explicit ephys extension whitelist — ``can_open`` returns 0.0 for anything not
#: here, so neo cannot claim a CSV, a text file, or an unknown binary (D-019).
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

#: Directory signatures for formats whose dataset root is a folder.  Searched
#: only after :func:`find_recordings`, because ``*.xml`` also matches Open Ephys'
#: ``settings.xml`` and would otherwise resolve the root to the record-node
#: directory rather than to the recording that actually holds the samples.
_DIRECTORY_SIGNATURES: tuple[str, ...] = (
    "*.continuous",
    "*.ap.meta",
    "*.lf.meta",
    "*.ncs",
    "*.xml",
)

#: Suffixes whose presence beside a dataset means the folder is a *session* —
#: several recordings that only mean something together — and belongs to a
#: ``SessionSource``, not to one loader.  Claiming such a folder here is how a
#: drop that contained cameras and ephys used to arrive as ephys alone.
_SESSION_SIBLING_SUFFIXES: frozenset[str] = frozenset(
    {".mp4", ".mov", ".mkv", ".avi", ".webm", ".csv", ".tsv"}
)

#: Values held in memory at once by a bulk read, across all channels of a stream.
#: 8 M float64 is ~64 MB, which keeps a 32-channel headstage bounded while still
#: amortising neo's per-slice overhead.
_BULK_TARGET_VALUES = 8_000_000

#: Samples per single-channel chunk on the legacy per-channel path.
_CHUNK_SAMPLES = 100_000

#: Characters Windows rejects in a filename.  A channel name becomes a cache
#: filename, and neo names an unnamed signal things like
#: ``Channels: (Eul-Y Eul-R Eul-P)`` — legal on POSIX, unwritable on Windows.
_UNSAFE_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_channel_name(name: str) -> str:
    """Return *name* reduced to characters legal in a cache filename everywhere."""
    cleaned = _UNSAFE_NAME_CHARS.sub("_", str(name)).strip().rstrip(".")
    return cleaned or "channel"


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


class NeoLoader(TimeSeriesSource):
    """Loads electrophysiology data using the neo library."""

    @classmethod
    def display_name(cls) -> str:
        return "Electrophysiology Data"

    @classmethod
    def display_aliases(cls) -> list[str]:
        """Kinds of data an acquisition recording carries besides the ephys.

        One recording's streams all come through this reader, so typing them by
        the reader called an 18-channel IMU — Euler angles, acceleration,
        gravity, temperature — "Electrophysiology Data" purely because neo is
        what reads it. A session names the kind it means with ``SessionItem.kind``;
        every one of these resolves back here.
        """
        return ["IMU / Motion Data", "TTL Events", "Auxiliary / Diagnostics"]

    def __init__(self) -> None:
        self._path: Path | None = None
        self._config: dict[str, Any] = {}
        self._schema_channels: list[ChannelInfo] = []
        self._block: neo.Block | None = None
        self._io: Any = None
        self._lazy = False

        #: channel name -> (segment index, analogsignal index, column index)
        self._channel_map: dict[str, tuple[int, int, int]] = {}
        #: channel name -> (segment index, event channel index, label)
        self._event_map: dict[str, tuple[int, int, str]] = {}
        #: Set when every selected signal shares one clock, which is what lets
        #: the importer store a single timestamp array for the whole stream.
        self._shared_clock: tuple[int, float, float, int] | None = None

        #: Bound bulk reader, or ``None`` when the selection spans several
        #: clocks.  ``ImportWorker`` probes this attribute and falls back to the
        #: per-channel path, so a mixed selection still imports correctly rather
        #: than silently interleaving two time bases.
        self.read_all_chunks: Callable[[], Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]] | (
            None
        ) = None

    # ── Capability resolution ────────────────────────────────────────────

    @classmethod
    def _find_dataset_root(cls, path: Path) -> Path | None:
        """Find the dataset root neo should be pointed at, or ``None``.

        Open Ephys recordings are resolved first and by their manifest, so the
        root is the ``recordingN`` directory that holds the samples.  Matching
        ``*.xml`` first used to resolve it to the record-node directory instead,
        because ``settings.xml`` lives there — same tree, wrong level, and no
        error to say so.
        """
        if not path.is_dir():
            return None

        recordings = find_recordings(path)
        if recordings:
            return recordings[0]

        # Shallow BFS for formats identified by a file pattern rather than a
        # manifest.  Depth 2 is deliberate: these signatures are weak, and a
        # deep match is more likely a coincidence than a dataset.
        queue: list[tuple[Path, int]] = [(path, 0)]
        while queue:
            current, depth = queue.pop(0)
            for signature in _DIRECTORY_SIGNATURES:
                if next(current.glob(signature), None):
                    return current
            if depth >= 2:
                continue
            try:
                children = sorted(child for child in current.iterdir() if child.is_dir())
            except OSError as error:
                logger.debug("Skipping unreadable directory %s: %s", current, error)
                continue
            for child in children:
                if child.name.startswith(".") or child.name.endswith(".avialcache"):
                    continue
                queue.append((child, depth + 1))
        return None

    @classmethod
    def _claims_directory(cls, path: Path) -> bool:
        """Return whether *path* is a dataset rather than a session containing one.

        A recording directory is always claimed.  Above that, the folder is only
        this loader's if everything beside the dataset belongs to it: a drop that
        also holds cameras or tracking exports is a session, and handing the whole
        thing to one loader is what made those siblings disappear.
        """
        if is_recording_dir(path):
            return True
        try:
            entries = list(path.iterdir())
        except OSError as error:
            logger.debug("Cannot inspect %s for sibling media: %s", path, error)
            return False
        for entry in entries:
            if entry.name.startswith(".") or entry.name.endswith(".avialcache"):
                continue
            if entry.is_file() and entry.suffix.lower() in _SESSION_SIBLING_SUFFIXES:
                return False
        return True

    @classmethod
    def can_open(cls, path: Path) -> float:
        """Return 1.0 for whitelisted ephys formats; 0.0 for everything else.

        Directories are accepted only when a dataset root is found *and* the
        directory holds nothing that marks it as a multi-source session.
        Files must match :data:`SUPPORTED_EXTENSIONS` before any header probe.
        """
        if path.is_dir():
            if cls._find_dataset_root(path) is None:
                return 0.0
            return 1.0 if cls._claims_directory(path) else 0.0

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return 0.0

        try:
            if neo.io.get_io(str(path)) is not None:
                return 1.0
        except Exception:  # noqa: BLE001 - neo raises broadly when it declines a file
            logger.debug("Neo rejected candidate %s", path, exc_info=True)

        return 0.0

    # ── Opening ─────────────────────────────────────────────────────────

    def open(self, path: Path, config: dict[str, Any]) -> None:
        """Open *path*, optionally narrowed to one stream or to its events.

        Config keys:
            ``root``: the dataset directory to hand neo, when it differs from
                *path*.  A session points each stream at its own directory so the
                streams get separate sidecar caches — a cache is named after its
                source path, so sources sharing one path overwrite each other —
                while neo is still opened on the recording that contains them.
            ``stream_id``: import only the neo signal stream with this id.  All
                its channels share a clock, which enables the bulk read path.
            ``events``: when true, import TTL event channels instead of signals.
        """
        self._path = path
        self._config = config

        configured_root = config.get("root")
        resolved_path = Path(configured_root) if configured_root else path
        if not configured_root:
            try:
                neo.io.get_io(str(resolved_path))
            except Exception:  # noqa: BLE001 - probing whether neo accepts the path as given
                root = self._find_dataset_root(path)
                if root:
                    resolved_path = root

        # Lazy mode returns proxy signals whose samples stay on disk until a
        # slice is requested, so a 50 kHz multi-hour recording never has to fit
        # in RAM.  Not every neo IO implements it; fall back to an eager read and
        # let the readers slice the loaded array.
        self._io = neo.io.get_io(str(resolved_path))
        try:
            self._block = self._io.read_block(lazy=True)
            self._lazy = True
        except (TypeError, ValueError, NotImplementedError) as error:
            logger.info("Neo IO %s has no lazy mode (%s); reading eagerly.", type(self._io), error)
            self._block = self._io.read_block()
            self._lazy = False

        self._schema_channels = []
        self._channel_map = {}
        self._event_map = {}
        self._shared_clock = None
        self.read_all_chunks = None

        if config.get("events"):
            self._build_event_schema()
        else:
            self._build_signal_schema(config.get("stream_id"))

        if not self._schema_channels:
            raise SourceOpenError(
                f"Neo found no importable channels in {path}"
                + (f" for stream {config['stream_id']!r}." if "stream_id" in config else ".")
            )

    def _build_signal_schema(self, stream_id: str | None) -> None:
        """Describe every selected analogue channel and note whether one clock spans them."""
        assert self._block is not None
        clocks: set[tuple[int, float, float, int]] = set()

        for seg_idx, segment in enumerate(self._block.segments):
            for asig_idx, asig in enumerate(segment.analogsignals):
                if stream_id is not None and str(asig.annotations.get("stream_id")) != str(
                    stream_id
                ):
                    continue
                rate = float(asig.sampling_rate.magnitude)
                start = float(asig.t_start.magnitude)
                length = int(asig.shape[0])
                clocks.add((seg_idx, start, rate, length))

                unit = "uV"
                if hasattr(asig, "units") and hasattr(asig.units, "dimensionality"):
                    unit = str(asig.units.dimensionality.string)
                dtype = str(getattr(asig, "dtype", np.dtype(np.float64)))

                for col, raw_name in enumerate(self._column_names(asig, seg_idx, asig_idx)):
                    name = self._unique(safe_channel_name(raw_name))
                    self._schema_channels.append(
                        ChannelInfo(name=name, unit=unit, dtype=dtype, rate_hz=rate)
                    )
                    self._channel_map[name] = (seg_idx, asig_idx, col)

        if len(clocks) == 1:
            self._shared_clock = next(iter(clocks))
            self.read_all_chunks = self._read_all_chunks
        elif len(clocks) > 1:
            logger.info(
                "Neo selection spans %d distinct clocks; importing channel by channel.",
                len(clocks),
            )

    @staticmethod
    def _column_names(asig: Any, seg_idx: int, asig_idx: int) -> list[str]:
        """Return one name per column of *asig*, preferring neo's own labels."""
        annotated = asig.array_annotations.get("channel_names")
        if annotated is not None and len(annotated) == asig.shape[1]:
            return [str(value) for value in annotated]
        name = asig.name
        if isinstance(name, str) and name:
            if asig.shape[1] == 1:
                return [name]
            return [f"{name}_{index}" for index in range(asig.shape[1])]
        return [f"Signal_{seg_idx}_{asig_idx}_{index}" for index in range(asig.shape[1])]

    def _unique(self, name: str) -> str:
        """Return *name*, suffixed if a channel already claimed it."""
        candidate = name
        counter = 1
        while candidate in self._channel_map or candidate in self._event_map:
            candidate = f"{name}_{counter}"
            counter += 1
        return candidate

    def _build_event_schema(self) -> None:
        """Describe one channel per TTL line that actually recorded transitions.

        Empty event channels are skipped rather than described.  An Open Ephys
        ``MessageCenter`` with no messages used to become a channel, and the
        per-channel reader then synthesised a zero for every sample of the
        recording — 24 million of them to represent nothing at all.
        """
        assert self._block is not None
        for seg_idx, segment in enumerate(self._block.segments):
            for ev_idx, event in enumerate(segment.events):
                labels = self._event_labels(seg_idx, ev_idx, event)
                if labels is None:
                    continue
                event_name = str(event.name or f"Event_{seg_idx}_{ev_idx}")
                for label in labels:
                    stem = f"TTL-{label}" if label else event_name
                    name = self._unique(safe_channel_name(stem))
                    self._schema_channels.append(
                        ChannelInfo(name=name, unit="TTL", dtype="float64", rate_hz=None)
                    )
                    self._event_map[name] = (seg_idx, ev_idx, label)

    def _event_labels(self, seg_idx: int, ev_idx: int, event: Any) -> list[str] | None:
        """Return the distinct line labels on an event channel, or ``None`` to skip it."""
        try:
            times, _durations, labels = self._raw_events(seg_idx, ev_idx)
        except SourceOpenError:
            logger.warning(
                "Neo event channel %r could not be read; skipping it.", event.name, exc_info=True
            )
            return None
        if len(times) == 0:
            logger.info("Skipping empty neo event channel %r.", event.name)
            return None
        if labels is None or len(labels) != len(times):
            return [""]
        distinct = sorted({str(value) for value in labels})
        # A text annotation stream (Open Ephys ``MessageCenter``) has free-form
        # labels and no logic level to plot; a TTL line is numbered.
        if not all(value.isdigit() for value in distinct):
            logger.info("Skipping non-numeric neo event channel %r.", event.name)
            return None
        return distinct

    def _raw_events(self, seg_idx: int, ev_idx: int) -> tuple[np.ndarray, np.ndarray | None, Any]:
        """Return ``(times_s, durations_s, labels)`` for one neo event channel.

        Durations come from the raw layer because they are what carries the
        falling edge; the object layer's ``Event`` keeps only the rising one, and
        a square wave needs both.
        """
        if self._io is not None and hasattr(self._io, "get_event_timestamps"):
            try:
                raw_times, raw_durations, labels = self._io.get_event_timestamps(
                    block_index=0, seg_index=seg_idx, event_channel_index=ev_idx
                )
            except Exception as error:  # noqa: BLE001 - neo raw layer, third-party
                raise SourceOpenError(f"Neo could not read event channel {ev_idx}.") from error
            times = np.asarray(
                self._io.rescale_event_timestamp(raw_times, dtype="float64"), dtype=np.float64
            )
            durations = self._rescale_durations(raw_durations)
            return times, durations, labels

        assert self._block is not None
        event = self._block.segments[seg_idx].events[ev_idx]
        loaded = event.load() if hasattr(event, "load") else event
        times = np.asarray(loaded.times.magnitude, dtype=np.float64)
        return times, None, getattr(loaded, "labels", None)

    def _rescale_durations(self, raw_durations: Any) -> np.ndarray | None:
        if raw_durations is None:
            return None
        rescale = getattr(self._io, "rescale_epoch_duration", None)
        if callable(rescale):
            try:
                return np.asarray(rescale(raw_durations, dtype="float64"), dtype=np.float64)
            except Exception:  # noqa: BLE001 - not every raw IO implements it consistently
                logger.debug("Neo could not rescale event durations; using them as seconds.")
        return np.asarray(raw_durations, dtype=np.float64)

    def channels(self) -> list[ChannelInfo]:
        return self._schema_channels

    # ── Reading ─────────────────────────────────────────────────────────

    def _signal(self, seg_idx: int, asig_idx: int) -> Any:
        assert self._block is not None
        return self._block.segments[seg_idx].analogsignals[asig_idx]

    def _load_window(self, asig: Any, start: int, stop: int, rate: float, t_start: float) -> Any:
        """Return the ``[start, stop)`` sample window of *asig*, all columns."""
        if not (self._lazy and hasattr(asig, "load")):
            return asig[start:stop]
        import quantities as pq

        window = ((t_start + start / rate) * pq.s, (t_start + stop / rate) * pq.s)
        return asig.load(time_slice=window)

    def _read_all_chunks(self) -> Iterator[dict[str, tuple[np.ndarray, np.ndarray]]]:
        """Yield every selected channel per chunk, sharing one timestamp array.

        Only offered when :meth:`open` proved the selection sits on a single
        clock, so the importer can keep one timestamp array for the whole stream
        instead of an identical copy behind every channel.
        """
        if self._shared_clock is None:  # pragma: no cover - guarded at bind time
            raise SourceOpenError("Neo bulk read requires a single-clock selection.")
        _seg, t_start, rate, length = self._shared_clock

        columns_by_signal: dict[tuple[int, int], list[tuple[int, str]]] = {}
        for name, (seg_idx, asig_idx, col) in self._channel_map.items():
            columns_by_signal.setdefault((seg_idx, asig_idx), []).append((col, name))

        batch = max(1, _BULK_TARGET_VALUES // max(1, len(self._channel_map)))
        for start in range(0, length, batch):
            stop = min(start + batch, length)
            times = t_start + np.arange(start, stop, dtype=np.float64) / rate
            chunk: dict[str, tuple[np.ndarray, np.ndarray]] = {}
            for (seg_idx, asig_idx), columns in columns_by_signal.items():
                window = self._load_window(
                    self._signal(seg_idx, asig_idx), start, stop, rate, t_start
                )
                values = np.asarray(getattr(window, "magnitude", window), dtype=np.float64)
                for col, name in columns:
                    chunk[name] = (times, _fit_length(values[:, col], stop - start))
            yield chunk

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        if self._block is None:
            raise SourceOpenError(f"Neo source has not been opened; cannot read channel {ch}.")
        if ch in self._channel_map:
            return self._read_signal_chunks(ch)
        if ch in self._event_map:
            return self._read_event_chunks(ch)
        raise SourceOpenError(f"Neo source has no channel {ch}.")

    def _read_signal_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        seg_idx, asig_idx, col = self._channel_map[ch]
        asig = self._signal(seg_idx, asig_idx)
        length = int(asig.shape[0])
        rate = float(asig.sampling_rate.magnitude)
        t_start = float(asig.t_start.magnitude)

        for start in range(0, length, _CHUNK_SAMPLES):
            stop = min(start + _CHUNK_SAMPLES, length)
            window = self._load_window(asig, start, stop, rate, t_start)
            values = np.asarray(getattr(window, "magnitude", window), dtype=np.float64)
            times = t_start + np.arange(start, stop, dtype=np.float64) / rate
            yield times, _fit_length(values[:, col], stop - start)

    def _read_event_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield one TTL line as a square wave built from its own edge timestamps.

        Two samples per pulse — high at the rising edge, low at the falling one —
        so the transitions keep their exact recorded times and stay usable as
        synchronization evidence.  A dense trace at the acquisition rate would
        preserve neither: it costs a timestamp per sample, and decimating it for
        display drops the narrow pulses entirely.
        """
        seg_idx, ev_idx, label = self._event_map[ch]
        times, durations, labels = self._raw_events(seg_idx, ev_idx)
        if label and labels is not None and len(labels) == len(times):
            selected = np.asarray([str(value) == label for value in labels], dtype=bool)
            times = times[selected]
            durations = None if durations is None else durations[selected]
        if len(times) == 0:  # pragma: no cover - empty channels are filtered at open()
            return

        order = np.argsort(times, kind="stable")
        rise = times[order]
        widths = self._pulse_widths(rise, None if durations is None else durations[order])
        fall = rise + widths

        samples = np.empty(2 * len(rise), dtype=np.float64)
        samples[0::2] = rise
        samples[1::2] = fall
        values = np.empty_like(samples)
        values[0::2] = 1.0
        values[1::2] = 0.0
        yield samples, values

    def _pulse_widths(self, rise: np.ndarray, durations: np.ndarray | None) -> np.ndarray:
        """Return each pulse's width, clamped so the wave stays strictly increasing.

        A recorded duration is used when neo reports one.  Without it the pulse
        becomes a single acquisition tick wide, which still marks the rising edge
        at its true time — the falling edge is simply not evidence we have.
        """
        tick = self._acquisition_tick()
        if durations is None:
            widths = np.full(len(rise), tick, dtype=np.float64)
        else:
            widths = np.asarray(durations, dtype=np.float64).copy()
            widths[~np.isfinite(widths)] = tick
            widths = np.maximum(widths, tick)
        if len(rise) > 1:
            # A glitched or overlapping pulse must not put the falling edge at or
            # past the next rising one: the ingest contract requires strictly
            # increasing timestamps, and a loader may never emit otherwise.
            headroom = np.diff(rise) * 0.5
            widths[:-1] = np.minimum(widths[:-1], headroom)
        # ``np.asarray`` is a no-op on an array that already has this dtype; it
        # is here because NumPy 2.4's stubs type ``np.maximum`` as returning
        # ``Any`` while 2.5's do not, so without it this file's type-checks
        # depend on which NumPy the checker happens to find (HANDOUT.md trap 26).
        clamped = np.maximum(widths, np.spacing(np.abs(rise) + 1.0))
        return np.asarray(clamped, dtype=np.float64)

    def _acquisition_tick(self) -> float:
        """Return one sample period of the fastest stream, as a minimum pulse width."""
        assert self._block is not None
        rates = [
            float(asig.sampling_rate.magnitude)
            for segment in self._block.segments
            for asig in segment.analogsignals
            if float(asig.sampling_rate.magnitude) > 0
        ]
        return 1.0 / max(rates) if rates else 1e-6
