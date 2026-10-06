"""How two-photon planes become screen pixels: levels, averaging, overlay (D-186).

Everything here runs on an imaging reader thread, never on the UI thread, for
the reason D-093 gives for video: a window applied after an 8-bit reduction
stretches data that was already discarded. The raw plane is windowed here, in
its own units, before anything is reduced to a byte.

**Brightness and contrast are a view of one window, not a second one.** Each
channel stores the reference window measured from its data (``auto_low`` and
``auto_high``) and two dimensionless controls. Contrast narrows or widens the
window around its centre by powers of two; brightness moves the centre by a
fraction of the reference width. The stored numbers reproduce the same picture
when a session is reopened at a different frame, which a window measured from
"whatever frame showed first" would not.

**The moving average is centred and has an odd length**, so the averaged image
shown at frame *i* is centred on frame *i*. A trailing average would shift every
transient by half the window, which on a synchronisation tool is a timing
error, not a display preference. At the ends of the stack the window is
truncated rather than shifted for the same reason.

**Channel colour never carries meaning alone** (D-094): the UI labels each
channel with its colour's name, and the default sets were measured under all
three simulated deficiencies (``tests/test_imaging_display.py``).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any

import numpy as np

__all__ = [
    "CHANNEL_COLORS",
    "MAX_AVERAGE",
    "ChannelView",
    "ImagingView",
    "auto_window",
    "average_range",
    "compose",
    "default_colors",
    "odd_average",
]

#: Channel colours by name, as 0-255 RGB. Additive primaries and secondaries,
#: which is what an overlay of fluorescence channels conventionally uses: two
#: co-localised signals add up to white rather than to an arbitrary blend.
CHANNEL_COLORS: dict[str, tuple[int, int, int]] = {
    "grey": (255, 255, 255),
    "green": (0, 255, 0),
    "magenta": (255, 0, 255),
    "cyan": (0, 255, 255),
    "yellow": (255, 255, 0),
    "red": (255, 0, 0),
    "blue": (0, 0, 255),
}

#: Defaults by channel count. Green and magenta are the field's standard
#: two-channel pair and stay apart under every colour vision deficiency; the
#: third and fourth were chosen by the same measurement, not by hue spacing.
_DEFAULTS: tuple[str, ...] = ("green", "magenta", "cyan", "yellow")

#: Longest moving average offered. With the reader's raw-plane cache this keeps
#: a two-channel 512x512 stack inside its memory bound while sliding by one
#: read per frame during playback.
MAX_AVERAGE = 31

#: Contrast at +1 narrows the window 16x and at -1 widens it 16x.
_CONTRAST_OCTAVES = 4.0

#: Percentiles for the reference window: a hot or dead pixel must not set it.
_AUTO_PERCENTILES = (0.5, 99.5)


def default_colors(count: int) -> tuple[str, ...]:
    """Return the default colour name for each of *count* channels."""
    if count <= 1:
        return ("grey",) * max(count, 0)
    return tuple(_DEFAULTS[index % len(_DEFAULTS)] for index in range(count))


@dataclasses.dataclass(frozen=True)
class ChannelView:
    """How one channel is shown: visibility, colour, and its display window."""

    visible: bool = True
    color: str = "grey"
    #: Reference window in raw pixel units; ``None`` until measured.
    auto_low: float | None = None
    auto_high: float | None = None
    #: -1..1, moving the window centre by up to its full reference width.
    brightness: float = 0.0
    #: -1..1, scaling the window width by up to 16x either way.
    contrast: float = 0.0

    @property
    def measured(self) -> bool:
        """Whether the reference window has been measured from data."""
        return self.auto_low is not None and self.auto_high is not None

    def window(self) -> tuple[float, float]:
        """Return the effective ``(low, high)`` in raw pixel units."""
        low = 0.0 if self.auto_low is None else float(self.auto_low)
        high = 1.0 if self.auto_high is None else float(self.auto_high)
        width = max(high - low, 1e-9)
        centre = (low + high) / 2.0 - _clamp(self.brightness) * width
        span = width * 2.0 ** (-_CONTRAST_OCTAVES * _clamp(self.contrast))
        return centre - span / 2.0, centre + span / 2.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise for the session file."""
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChannelView:
        """Read a stored channel, tolerating missing keys and unknown colours."""
        color = str(data.get("color", "grey"))
        low = data.get("auto_low")
        high = data.get("auto_high")
        return cls(
            visible=bool(data.get("visible", True)),
            color=color if color in CHANNEL_COLORS else "grey",
            auto_low=None if low is None else float(low),
            auto_high=None if high is None else float(high),
            brightness=_clamp(float(data.get("brightness", 0.0))),
            contrast=_clamp(float(data.get("contrast", 0.0))),
        )


@dataclasses.dataclass(frozen=True)
class ImagingView:
    """The display choices for one imaging stack."""

    channels: tuple[ChannelView, ...] = ()
    #: Frames in the centred moving average; always odd, 1 means none.
    average: int = 1

    @classmethod
    def for_channels(cls, count: int) -> ImagingView:
        """Return the default view of a stack with *count* channels."""
        return cls(channels=tuple(ChannelView(color=c) for c in default_colors(count)))

    def fitted(self, count: int) -> ImagingView:
        """Return this view with exactly *count* channels and a valid average.

        A stored view can disagree with the file it describes -- the file was
        re-exported with another channel, or the session was edited by hand --
        and that must not stop the stack from opening.
        """
        defaults = default_colors(count)
        channels = list(self.channels[:count])
        channels += [ChannelView(color=defaults[i]) for i in range(len(channels), count)]
        return ImagingView(channels=tuple(channels), average=odd_average(self.average))

    def with_channel(self, index: int, channel: ChannelView) -> ImagingView:
        """Return a copy with channel *index* replaced."""
        channels = list(self.channels)
        channels[index] = channel
        return dataclasses.replace(self, channels=tuple(channels))

    def to_dict(self) -> dict[str, Any]:
        """Serialise for the session file."""
        return {"average": self.average, "channels": [c.to_dict() for c in self.channels]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImagingView:
        """Read a stored view; an empty dict is the default view."""
        channels = tuple(ChannelView.from_dict(dict(c)) for c in data.get("channels", []))
        return cls(channels=channels, average=odd_average(int(data.get("average", 1))))


def odd_average(frames: int) -> int:
    """Clamp a moving-average length to an odd number in ``[1, MAX_AVERAGE]``."""
    frames = min(max(int(frames), 1), MAX_AVERAGE)
    return frames if frames % 2 else frames - 1


def average_range(index: int, count: int, frames: int) -> range:
    """Frame indices averaged for the picture shown at *index*.

    Centred on *index* and truncated, never shifted, at either end of the stack.
    """
    half = odd_average(frames) // 2
    return range(max(index - half, 0), min(index + half + 1, count))


def auto_window(plane: np.ndarray) -> tuple[float, float]:
    """Measure a reference window from the finite pixels of *plane*."""
    finite = plane[np.isfinite(plane)] if plane.dtype.kind == "f" else plane.reshape(-1)
    if finite.size == 0:
        return 0.0, 1.0
    low, high = np.percentile(finite, _AUTO_PERCENTILES)
    low_value, high_value = float(low), float(high)
    if high_value <= low_value:
        # A flat plane would divide by zero; one count of width shows it flat.
        high_value = low_value + 1.0
    return low_value, high_value


def compose(planes: Sequence[tuple[np.ndarray, ChannelView]]) -> np.ndarray:
    """Window each visible plane and add them into one 8-bit image.

    Returns a C-contiguous ``(H, W)`` array when the only plane is grey -- a
    third of the bytes to convert and upload -- and ``(H, W, 3)`` RGB otherwise.
    NaN pixels show as black. An empty sequence is a caller error.
    """
    if not planes:
        raise ValueError("compose() needs at least one visible plane")
    if len(planes) == 1 and planes[0][1].color == "grey":
        plane, channel = planes[0]
        return _to_byte(_windowed(plane, channel))

    height, width = planes[0][0].shape
    total = np.zeros((height, width, 3), dtype=np.float32)
    for plane, channel in planes:
        scaled = _windowed(plane, channel)
        rgb = CHANNEL_COLORS.get(channel.color, CHANNEL_COLORS["grey"])
        for component, weight in enumerate(rgb):
            if weight:
                total[..., component] += scaled * (weight / 255.0)
    return _to_byte(total)


def _windowed(plane: np.ndarray, channel: ChannelView) -> np.ndarray:
    low, high = channel.window()
    scaled = (plane.astype(np.float32, copy=False) - np.float32(low)) * np.float32(
        1.0 / (high - low)
    )
    np.nan_to_num(scaled, copy=False, nan=0.0)
    return scaled


def _to_byte(values: np.ndarray) -> np.ndarray:
    np.clip(values, 0.0, 1.0, out=values)
    values *= 255.0
    values += 0.5
    return np.ascontiguousarray(values, dtype=np.uint8)


def _clamp(value: float) -> float:
    return min(max(float(value), -1.0), 1.0)
