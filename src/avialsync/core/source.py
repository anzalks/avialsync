"""Source plugin abstract base classes."""

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class ChannelInfo:
    """Metadata for a single data channel."""

    name: str
    unit: str
    dtype: str
    rate_hz: float | None  # None indicates irregular sampling


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    """Format-neutral video metadata exposed by every video source.

    Timestamp-derived rate fields are authoritative when present.  The nominal
    rate remains visible because containers commonly declare a CFR rate even
    when their presentation timestamps prove that the media is VFR.
    """

    container: str = ""
    codec: str = "unknown"
    profile: str = ""
    pixel_format: str = ""
    width: int = 0
    height: int = 0
    nominal_fps: float = 0.0
    measured_fps: float = 0.0
    min_frame_rate: float = 0.0
    max_frame_rate: float = 0.0
    is_vfr: bool = False
    frame_count: int | None = None
    duration: float = 0.0
    start_time: float | None = None
    file_size_bytes: int = 0


#: Where to break a class name into words: after a lower-case run, and before
#: the last capital of a capital run that starts a new word.  The second case is
#: what keeps an acronym together — ``AOLSession`` is "AOL Session", not "AOL
#: Session" spelt "AOLSession" nor "A O L Session".
_NAME_WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def default_display_name(cls: type) -> str:
    """Derive a readable format name from a class name.

    ``AOLEksLoader`` becomes "AOL Eks", ``CSVLoader`` becomes "CSV",
    ``VideoStandardLoader`` becomes "Video Standard". Only a fallback: a
    format that cares how it is listed overrides ``display_name``.

    A plugin that does not override this is listed by whatever comes out, so the
    acronym case is not cosmetic. The previous rule split only after a
    lower-case letter, which never broke a capital run: ``AOLSession`` came back
    as "AOLSession" — the very example this docstring claimed to handle.
    """
    name = cls.__name__
    for suffix in ("Loader", "Source"):
        if name.endswith(suffix) and name != suffix:
            name = name[: -len(suffix)]
    return _NAME_WORD_BOUNDARY.sub(" ", name) or cls.__name__


class _Nameable:
    """Naming hooks shared by every source contract.

    The import dialog once held a table mapping loader class names to labels,
    which meant adding a format meant editing the UI, and third-party plugins
    were listed by bare class name because they were not in the table. A format
    names itself instead.

    **Convention: name the kind of data, never the rig.** ``"Video"``,
    ``"IMU / Motion Data"``, ``"TTL Events"`` — a camera is a camera whichever
    system recorded it, and an IMU stream is the same shape of data wherever it
    came from. Which rig an item belongs to is the session's business and
    already sits in its :attr:`SessionItem.label`; repeating it here produced
    "Open Ephys Video" for something that is simply a video.

    One reader commonly serves several kinds — every stream of an acquisition
    recording goes through the same one — so a reader offers each kind it can be
    meant as, via :meth:`display_aliases`, and a session picks between them with
    :attr:`SessionItem.kind`. Without that an 18-channel IMU was typed
    "Electrophysiology Data" purely because neo is what reads it.

    Names must be unique across all registered plugins, aliases included: the
    import dialog is a picker, and two identical entries cannot be told apart.
    """

    @classmethod
    def display_name(cls) -> str:
        """Return the human-readable name for this format."""
        return default_display_name(cls)

    @classmethod
    def display_aliases(cls) -> list[str]:
        """Return extra labels this loader should also be offered under.

        For a general-purpose format that users think of by *purpose* rather
        than by encoding — a CSV that is a TTL log, a trigger list, or a plain
        trace. Each alias appears as its own choice, all resolving here.
        """
        return []


@dataclass(frozen=True)
class SessionItem:
    """One file a session contributes, with the loader and config it needs.

    ``loader`` may be ``None`` to let the registry resolve it by capability,
    which is what a session should do for ordinary media it does not own the
    format of.
    """

    path: Path
    loader: type["TimeSeriesSource | VideoSource"] | None = None
    config: dict[str, Any] = field(default_factory=dict)

    #: What to call this item in the import dialog, when its filename is not
    #: enough. A session already knows what each piece *is* — how many channels,
    #: at what rate — while the dialog can only re-derive a name from the path,
    #: and four streams of one recording all read as their directory names with
    #: nothing to say which is the 30 kHz one. Empty means "use the filename".
    #:
    #: Deliberately not part of ``config``: config is hashed into the sidecar
    #: cache key, so wording a label better would invalidate every cache built
    #: with the old one — several gigabytes rebuilt to reword a table cell.
    label: str = ""

    #: What kind of data this is, in the user's terms — "Video", "IMU / Motion
    #: Data", "TTL Events". One loader commonly reads several kinds: every
    #: stream of an acquisition recording goes through the same reader, so an
    #: 18-channel IMU was typed "Electrophysiology Data" purely because neo is
    #: what reads it. The kind must match one of the loader's own
    #: :meth:`~_Nameable.display_name` or :meth:`~_Nameable.display_aliases`
    #: labels, since it selects among them; empty means the loader's own name.
    kind: str = ""


@dataclass(frozen=True)
class SessionLayout:
    """What a recording folder contains, plus the settings that span it.

    Session-wide settings are fields rather than another entry in ``items``.
    They were once smuggled through the item list as a fake ``Path`` row, which
    every consumer then had to recognise and strip; anything that forgot leaked
    a non-existent file into the import dialog.
    """

    items: list[SessionItem] = field(default_factory=list)

    #: UTC epoch that session-relative timestamps are measured from. ``0.0``
    #: means the session declares no absolute anchor and times stay relative.
    anchor_epoch: float = 0.0

    #: Nominal camera rate shared by the session's video and frame-indexed
    #: sources. ``0.0`` means unknown; sources then resolve their own.
    camera_fps: float = 0.0

    #: Body-part pairs to draw as a skeleton over pose data, if any.
    skeleton: list[tuple[str, str]] | None = None


class SessionSource(_Nameable, ABC):
    """Optional plugin contract for a whole recording folder.

    Additive to API v1 and outside it: ``TimeSeriesSource`` and ``VideoSource``
    are unchanged, and a plugin that implements neither this nor anything else
    is unaffected. Implement it when one directory *is* the recording — several
    videos, pose data, and instrument traces that only mean something together,
    with a shared clock.

    Without it a folder can still be claimed, by returning a non-zero
    ``can_open`` from an ordinary loader, but that yields exactly one source.
    This is what lets one folder fan out into many, each with its own loader and
    role, which is the difference between "a directory of files" and "a session".

    Registered under the ``avialsync.sessions`` entry-point group, separately
    from ``avialsync.loaders``: a session scanner is asked about directories
    before per-file capability resolution runs at all.
    """

    @classmethod
    @abstractmethod
    def can_open(cls, path: Path) -> float:
        """Return 0..1 confidence that *path* is a session this can lay out.

        Called with directories. Must be cheap — it runs for every dropped
        folder, on the scan thread, before anything is read.
        """

    @abstractmethod
    def scan(self, path: Path, registry: Any) -> SessionLayout:
        """Return the session's contents and the settings that span them.

        ``registry`` resolves loaders by capability, so a session names its own
        formats explicitly and defers ordinary media to whatever can read it.
        Runs off the UI thread; it may read files, and must not touch Qt.
        """


class TimeSeriesSource(_Nameable, ABC):
    """Frozen v1 plugin contract for chunked time-series ingestion.

    Instances are created and used by :class:`engine.importer.ImportWorker` on a
    background thread.  Implementations must not retain Qt objects.  The importer
    owns cache construction, decimation, gap detection, and all subsequent reads.
    """

    @classmethod
    @abstractmethod
    def can_open(cls, path: Path) -> float:
        """Return a confidence in ``[0.0, 1.0]`` without expensive I/O."""
        pass

    @abstractmethod
    def open(self, path: Path, config: dict[str, Any]) -> None:
        """Read metadata required for :meth:`channels` and :meth:`read_chunks`.

        ``config`` is plugin-defined, JSON-serialisable import configuration.
        Raise a typed source error with actionable context when it cannot be read.
        """
        pass

    @abstractmethod
    def channels(self) -> list[ChannelInfo]:
        """Return stable metadata for every importable channel."""
        pass

    @abstractmethod
    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield one-dimensional ``float64`` time/value chunks for *ch*.

        Chunks, including their boundaries, must be globally chronological.
        Duplicate timestamps must keep the final value.  A loader may sort its
        input or raise :class:`NonMonotonicTimeError`; it must never silently emit
        decreasing times.  NaN and infinity values pass through.  Core computes
        gaps after ingest using a 10× median-sample-interval threshold.
        """
        pass

    def is_frame_indexed(self) -> bool:
        """Return True if this source stores frame numbers instead of wall-clock time.

        Frame-indexed sources require an explicit fps to convert frame indices to seconds.
        The UI uses this flag to drive automatic fps resolution from loaded video (D-019).
        Default False; loaders that store raw frame counters should override to return True.
        """
        return False


class VideoSource(_Nameable, ABC):
    """Frozen v1 plugin contract for video sources.

    ``open`` and optional ``prepare`` run in a background worker.  The returned
    media path is opened by mpv only after this work has completed successfully.
    """

    @classmethod
    @abstractmethod
    def can_open(cls, path: Path) -> float:
        """Return 0..1 confidence that this loader can open the file."""
        pass

    @abstractmethod
    def open(self, path: Path, config: dict[str, Any]) -> None:
        """Probe source metadata; this method may perform blocking I/O."""
        pass

    @abstractmethod
    def needs_conversion(self) -> bool:
        """Return True if this source needs proxy conversion (e.g., image seq)."""
        pass

    @abstractmethod
    def prepare(self, progress_cb: Callable[[float], None]) -> Path:
        """Produce an mpv-playable cached proxy and report progress in ``[0, 1]``."""
        pass

    @abstractmethod
    def media_path(self) -> Path:
        """Return what mpv actually plays (proxy-aware)."""
        pass

    @abstractmethod
    def start_time(self) -> float | None:
        """Return an optional UTC-epoch metadata guess; user offset always wins."""
        pass

    @abstractmethod
    def time_bounds(self) -> tuple[float, float]:
        """Return source coverage in master-time seconds.

        Sources with a metadata start return ``(start_time, start_time + duration)``;
        sources without one return media-relative ``(0.0, duration)``.
        """
        pass

    @abstractmethod
    def frame_times(self) -> np.ndarray | None:
        """Per-frame timestamps if the container has them."""
        pass

    @abstractmethod
    def fps(self) -> float:
        """Nominal frames per second."""
        pass

    def exact_time_mapping(self) -> tuple[np.ndarray, np.ndarray] | None:
        """Return per-frame ``(master_time, source_time)`` evidence, or ``None``.

        Additive default, so frozen v1 video plugins are unaffected.  Override it
        when the acquisition system recorded when each frame was actually
        exposed — a timestamp sidecar, a hardware trigger log — and the container
        therefore cannot be trusted to say when its frames belong on the
        timeline.  Dropped frames and variable rates make that a piecewise
        relationship that no offset and drift pair can express, which is why this
        returns a table rather than two numbers.

        Both arrays must be the same length and strictly increasing.  The result
        is treated the same as an accepted synchronization proposal, so returning
        a guess here silently overrides what the user would otherwise be asked
        to confirm; return ``None`` when the evidence is absent.
        """
        return None

    def video_metadata(self) -> VideoMetadata:
        """Return format-neutral inspection metadata.

        This additive default preserves compatibility with frozen v1 video
        plugins.  Loaders should override it when they can provide richer
        stream and timestamp evidence.
        """
        start, end = self.time_bounds()
        return VideoMetadata(
            nominal_fps=self.fps(),
            measured_fps=self.fps(),
            duration=max(0.0, end - start),
            start_time=self.start_time(),
        )

    @abstractmethod
    def label(self) -> str:
        """Camera label for the UI."""
        pass
