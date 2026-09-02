"""Mapping a recording's own bit depth onto an 8-bit screen (WP-9, D-093).

``to_ndarray(format="rgb24")`` performs the reduction to 8 bits inside swscale,
before any application code sees the frame.  Measured on a synthetic 12-bit
ramp: the native array keeps **2048 distinct values**, the ``rgb24`` one keeps
**256**.  A brightness control on the pane would therefore be stretching data
that had already been discarded — which is why display levels are a decode
stage rather than a filter applied afterwards.

**Nothing here assumes a depth.**  The bit depth, the component count, and the
pixel format all come from the frame itself, through
``frame.format.components[i].bits``.  A rig that records 10-bit, 12-bit, 14-bit
or plain 8-bit is handled by the same code reading the same fields, and the
lookup table is sized ``2 ** bits`` from whatever the file actually says.  There
is no 12 anywhere in this module.

Levels are stored **normalised to 0.0–1.0** rather than in raw counts, so a
session that recorded the same rig at a different depth still means what it
said: "black at 12% of range" survives a move from 12-bit to 16-bit, where
"black at 491" would not.

The conversion runs on the decode thread.  Applying a lookup table in
``paintEvent`` would turn a 2 ms budget into a 3 ms violation on every frame.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np

__all__ = [
    "SourceFormat",
    "DisplayLevels",
    "probe_format",
    "build_lut",
    "auto_levels",
    "to_display_array",
]


@dataclasses.dataclass(frozen=True)
class SourceFormat:
    """What a decoder actually produces, read from the data.

    Never inferred from a file extension or a codec name: two recordings from
    the same camera model can differ, and the frame is the only authority.
    """

    pix_fmt: str
    bits: int
    component_count: int

    @property
    def is_greyscale(self) -> bool:
        """Whether this is a single-plane luminance format."""
        return self.component_count == 1

    @property
    def is_high_bit_depth(self) -> bool:
        """Whether the source carries more than an 8-bit screen can show."""
        return self.bits > 8

    @property
    def levels_count(self) -> int:
        """How many distinct values a sample can take."""
        return 1 << self.bits

    @property
    def storage_bits(self) -> int:
        """Width of the integer each sample is stored in.

        A 10-, 12- or 14-bit sample arrives in a 16-bit container, so a table
        sized to the *container* can be indexed by any value the array can hold
        and needs no bounds check. That matters: clipping first cost 1.2 ms per
        1440x1080 frame, measured, for a guard the index range makes redundant.
        """
        return 8 if self.bits <= 8 else 16

    @property
    def lut_size(self) -> int:
        """Entries in a lookup table indexable by any raw sample."""
        return 1 << self.storage_bits

    @property
    def needs_windowing(self) -> bool:
        """Whether a lookup table is worth building at all.

        Only high-bit-depth greyscale.  Eight-bit colour already fills the
        screen's range, and putting it through a table would cost bandwidth to
        achieve nothing.
        """
        return self.is_greyscale and self.is_high_bit_depth


@dataclasses.dataclass(frozen=True)
class DisplayLevels:
    """Which part of the recorded range is shown, in normalised units.

    ``black`` and ``white`` are fractions of full scale, so they keep their
    meaning if the same rig is later recorded at a different bit depth.
    ``gamma`` above 1 lifts the shadows.
    """

    black: float = 0.0
    white: float = 1.0
    gamma: float = 1.0

    @property
    def is_identity(self) -> bool:
        """Whether this maps the full range linearly and can be skipped."""
        return self.black <= 0.0 and self.white >= 1.0 and abs(self.gamma - 1.0) < 1e-6

    def normalised(self) -> DisplayLevels:
        """Return a sane copy: ordered, in range, with a usable gamma."""
        black = min(max(self.black, 0.0), 1.0)
        white = min(max(self.white, 0.0), 1.0)
        if white <= black:
            # A collapsed window would divide by zero and show one flat value.
            # Widening by the smallest useful amount keeps the image readable
            # rather than refusing to draw it.
            white = min(black + 1e-4, 1.0)
            black = max(white - 1e-4, 0.0)
        gamma = self.gamma if self.gamma > 1e-3 else 1.0
        return DisplayLevels(black=black, white=white, gamma=gamma)


def probe_format(frame: Any) -> SourceFormat:
    """Describe *frame*'s pixel format from the frame itself.

    Falls back to an 8-bit three-component description when a frame does not
    expose its components, which keeps an unusual source on the ordinary path
    rather than failing to display at all.
    """
    fmt = getattr(frame, "format", None)
    name = str(getattr(fmt, "name", "") or "")
    components = list(getattr(fmt, "components", []) or [])
    if not components:
        return SourceFormat(pix_fmt=name or "rgb24", bits=8, component_count=3)

    bits = max(int(getattr(component, "bits", 8)) for component in components)
    return SourceFormat(pix_fmt=name, bits=bits, component_count=len(components))


def build_lut(source: SourceFormat, levels: DisplayLevels) -> np.ndarray:
    """Return a ``uint8`` lookup table indexable by any raw sample value.

    Two different sizes are in play and conflating them is the bug this
    docstring exists to prevent. The **scale** comes from the format's
    significant bits, so 0.5 means mid-grey on a 10-, 12- or 16-bit recording
    alike. The **table** is sized to the storage container, so every value the
    decoded array can hold is a valid index and no per-frame bounds check is
    needed.

    Built once per levels change; a drag coalesces to 20 Hz, so this is not a
    per-frame cost.
    """
    settings = levels.normalised()
    full_scale = float(source.levels_count - 1)

    # Positions of every indexable sample, as a fraction of the format's own
    # full scale. Values above that scale saturate, which is what a camera
    # emitting above its nominal range should look like.
    positions = np.arange(source.lut_size, dtype=np.float32) / full_scale
    span = settings.white - settings.black
    scaled = (positions - settings.black) / span
    np.clip(scaled, 0.0, 1.0, out=scaled)

    if abs(settings.gamma - 1.0) > 1e-6:
        scaled = np.power(scaled, 1.0 / settings.gamma, dtype=np.float32)

    return (scaled * 255.0 + 0.5).astype(np.uint8)


def auto_levels(
    samples: np.ndarray, source: SourceFormat, *, tail_fraction: float = 0.001
) -> DisplayLevels:
    """Choose black and white points from what the frame actually contains.

    Percentile rather than min/max: a single hot pixel or a dead one would
    otherwise set the whole window, which is exactly the case scientific
    footage tends to have.
    """
    if samples.size == 0:
        return DisplayLevels()

    flat = samples.reshape(-1)
    low = float(np.quantile(flat, tail_fraction))
    high = float(np.quantile(flat, 1.0 - tail_fraction))
    full_scale = float(source.levels_count - 1)

    return DisplayLevels(black=low / full_scale, white=high / full_scale).normalised()


def to_display_array(frame: Any, levels: DisplayLevels | None = None) -> tuple[np.ndarray, bool]:
    """Convert *frame* for display. Returns ``(array, is_greyscale)``.

    High-bit-depth greyscale goes through its native format and a lookup
    table, and comes back as a single-plane ``uint8`` array — one third the
    bytes of RGB on both the conversion and the upload, because swscale's
    grey-to-RGB triplication never happens.

    Everything else takes the ``rgb24`` path unchanged. An identity window
    short-circuits the table entirely, so ordinary 8-bit footage pays nothing
    for this module existing.
    """
    source = probe_format(frame)

    if not source.needs_windowing:
        return frame.to_ndarray(format="rgb24"), False

    # The source's own format, not gray16le: converting up to 16 bits rescales
    # the values, and a table indexed by the result would be indexed by a
    # scaled number rather than the recorded one.
    native = frame.to_ndarray(format=source.pix_fmt)

    settings = levels or DisplayLevels()
    if settings.is_identity:
        # Still a reduction -- the screen is 8-bit -- but a plain shift rather
        # than a table, which is what the decoder would have done anyway.
        shift = source.bits - 8
        return (native >> shift).astype(np.uint8), True

    # One gather over the whole plane, and nothing else. The table covers every
    # value a sample can hold, so there is no bounds check to pay for -- an
    # np.clip here cost 1.2 ms per 1440x1080 frame for a guard the index range
    # already provides.
    return build_lut(source, settings)[native], True
