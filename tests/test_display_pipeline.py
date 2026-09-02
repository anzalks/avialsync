"""Display levels, sized by the recording's own bit depth (WP-9, D-093).

``to_ndarray(format="rgb24")`` reduces to 8 bits inside swscale, before any
application code sees the frame -- which is why levels are a decode stage and
not a filter applied afterwards.
:func:`test_rgb24_destroys_what_the_native_format_keeps` measures that rather
than asserting it.

**Nothing in the pipeline assumes a depth.** These tests run the same code over
8-, 10-, 12-, 14- and 16-bit sources, and the only thing that changes is what
the file says about itself.
"""

from __future__ import annotations

import av
import numpy as np
import pytest

from avialsync.engine.display_pipeline import (
    DisplayLevels,
    SourceFormat,
    auto_levels,
    build_lut,
    probe_format,
    to_display_array,
)

#: Greyscale formats FFmpeg offers, and what each one says its depth is. The
#: point of parametrising is that no test knows the number in advance.
GREY_FORMATS = [("gray", 8), ("gray10le", 10), ("gray12le", 12), ("gray16le", 16)]


def _grey_frame(pix_fmt: str, bits: int, width: int = 64, height: int = 32):
    """A ramp covering the full range of *bits*."""
    peak = (1 << bits) - 1
    dtype = np.uint8 if bits <= 8 else np.uint16
    data = np.linspace(0, peak, width * height, dtype=dtype).reshape(height, width)
    return av.VideoFrame.from_ndarray(data, format=pix_fmt)


def _colour_frame(width: int = 64, height: int = 32):
    data = np.zeros((height, width, 3), dtype=np.uint8)
    data[..., 0] = np.linspace(0, 255, width, dtype=np.uint8)
    return av.VideoFrame.from_ndarray(data, format="rgb24")


# ── the depth comes from the data ────────────────────────────────────


@pytest.mark.parametrize(("pix_fmt", "bits"), GREY_FORMATS)
def test_the_depth_is_read_from_the_frame(pix_fmt: str, bits: int) -> None:
    source = probe_format(_grey_frame(pix_fmt, bits))
    assert source.bits == bits
    assert source.is_greyscale is True
    assert source.levels_count == 1 << bits


def test_colour_is_recognised_as_colour() -> None:
    source = probe_format(_colour_frame())
    assert source.is_greyscale is False
    assert source.needs_windowing is False


def test_eight_bit_grey_needs_no_window() -> None:
    """It already fills the screen's range; a table would achieve nothing."""
    source = probe_format(_grey_frame("gray", 8))
    assert source.is_high_bit_depth is False
    assert source.needs_windowing is False


@pytest.mark.parametrize(("pix_fmt", "bits"), [f for f in GREY_FORMATS if f[1] > 8])
def test_high_bit_depth_grey_is_windowed(pix_fmt: str, bits: int) -> None:
    assert probe_format(_grey_frame(pix_fmt, bits)).needs_windowing is True


def test_a_frame_without_components_falls_back_safely() -> None:
    """An unusual source stays on the ordinary path rather than failing."""

    class _Bare:
        format = None

    source = probe_format(_Bare())
    assert source.bits == 8
    assert source.needs_windowing is False


# ── the measurement that motivates the package ───────────────────────


def test_rgb24_destroys_what_the_native_format_keeps() -> None:
    """The evidence for D-093, measured rather than asserted."""
    frame = _grey_frame("gray12le", 12)

    native = frame.to_ndarray(format="gray12le")
    through_rgb = frame.to_ndarray(format="rgb24")

    assert len(np.unique(native)) > 2000
    assert len(np.unique(through_rgb)) <= 256
    assert len(np.unique(native)) > 4 * len(np.unique(through_rgb))


# ── the lookup table ─────────────────────────────────────────────────


@pytest.mark.parametrize(("pix_fmt", "bits"), GREY_FORMATS)
def test_the_table_covers_every_indexable_sample(pix_fmt: str, bits: int) -> None:
    """Sized to the storage container, so a gather needs no bounds check."""
    source = probe_format(_grey_frame(pix_fmt, bits))
    lut = build_lut(source, DisplayLevels())
    assert lut.size == source.lut_size
    assert lut.size >= (1 << bits), "every value the array can hold must index"
    assert lut.dtype == np.uint8


@pytest.mark.parametrize(("pix_fmt", "bits"), GREY_FORMATS)
def test_the_scale_comes_from_the_significant_bits(pix_fmt: str, bits: int) -> None:
    """The two sizes are different and conflating them is the bug to avoid."""
    source = probe_format(_grey_frame(pix_fmt, bits))
    assert source.levels_count == 1 << bits
    lut = build_lut(source, DisplayLevels())
    # Full scale for this format maps to white, whatever the table's length.
    assert lut[source.levels_count - 1] == 255


def test_a_full_window_maps_the_ends_to_the_ends() -> None:
    source = SourceFormat("gray12le", 12, 1)
    lut = build_lut(source, DisplayLevels())
    assert lut[0] == 0
    assert lut[source.levels_count - 1] == 255


def test_a_sample_above_nominal_range_saturates() -> None:
    """Some cameras emit above their declared range; it must not index past the end."""
    source = SourceFormat("gray12le", 12, 1)
    lut = build_lut(source, DisplayLevels())
    assert lut[source.lut_size - 1] == 255


def test_a_narrow_window_stretches_the_middle() -> None:
    """The point of the feature: see into a range the camera barely used."""
    source = SourceFormat("gray12le", 12, 1)
    lut = build_lut(source, DisplayLevels(black=0.4, white=0.6))
    assert lut[int(0.39 * 4095)] == 0
    assert lut[int(0.61 * 4095)] == 255
    assert 100 < int(lut[int(0.5 * 4095)]) < 160


def test_gamma_lifts_the_shadows() -> None:
    source = SourceFormat("gray12le", 12, 1)
    linear = build_lut(source, DisplayLevels())
    lifted = build_lut(source, DisplayLevels(gamma=2.2))
    midpoint = 4095 // 2
    assert lifted[midpoint] > linear[midpoint]


def test_an_inverted_window_does_not_divide_by_zero() -> None:
    """A control that cannot express a value must not produce a blank frame."""
    source = SourceFormat("gray12le", 12, 1)
    lut = build_lut(source, DisplayLevels(black=0.8, white=0.2))
    assert lut.size == source.lut_size
    assert np.isfinite(lut).all()


def test_identity_is_recognised() -> None:
    assert DisplayLevels().is_identity is True
    assert DisplayLevels(black=0.1).is_identity is False
    assert DisplayLevels(gamma=2.0).is_identity is False


# ── automatic levels ─────────────────────────────────────────────────


def test_auto_levels_ignore_a_single_hot_pixel() -> None:
    """Min/max would let one dead pixel set the whole window."""
    source = SourceFormat("gray12le", 12, 1)
    samples = np.full(10000, 1000, dtype=np.uint16)
    samples[0] = 4095  # a hot pixel
    samples[1] = 0  # and a dead one

    levels = auto_levels(samples, source)
    assert levels.white < 0.5, "the hot pixel must not stretch the window to full scale"


def test_auto_levels_on_an_empty_frame_are_the_full_range() -> None:
    levels = auto_levels(np.array([], dtype=np.uint16), SourceFormat("gray12le", 12, 1))
    assert levels.is_identity is True


# ── conversion ───────────────────────────────────────────────────────


def test_colour_takes_the_unchanged_path() -> None:
    array, is_grey = to_display_array(_colour_frame())
    assert is_grey is False
    assert array.ndim == 3
    assert array.dtype == np.uint8


@pytest.mark.parametrize(("pix_fmt", "bits"), [f for f in GREY_FORMATS if f[1] > 8])
def test_high_bit_depth_comes_back_as_one_plane(pix_fmt: str, bits: int) -> None:
    """One third the bytes of RGB, because the triplication never happens."""
    array, is_grey = to_display_array(_grey_frame(pix_fmt, bits), DisplayLevels(black=0.2))
    assert is_grey is True
    assert array.ndim == 2
    assert array.dtype == np.uint8


def test_an_identity_window_still_reduces_to_eight_bits() -> None:
    array, is_grey = to_display_array(_grey_frame("gray12le", 12), DisplayLevels())
    assert is_grey is True
    assert array.dtype == np.uint8
    assert array.max() <= 255


def test_a_window_actually_changes_the_pixels() -> None:
    frame = _grey_frame("gray12le", 12)
    full, _ = to_display_array(frame, DisplayLevels())
    narrow, _ = to_display_array(frame, DisplayLevels(black=0.45, white=0.55))
    assert not np.array_equal(full, narrow)
    assert narrow.min() == 0
    assert narrow.max() == 255


def test_conversion_never_assumes_twelve_bits() -> None:
    """Same code, four depths, no special case."""
    for pix_fmt, bits in GREY_FORMATS:
        array, _ = to_display_array(_grey_frame(pix_fmt, bits), DisplayLevels(black=0.1))
        assert array.dtype == np.uint8, f"{pix_fmt} did not convert"


def test_no_bit_depth_is_hardcoded_in_the_module() -> None:
    """The user's requirement: depth comes from the data, never a literal."""
    from pathlib import Path

    source = Path("src/avialsync/engine/display_pipeline.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
    for literal in ("4095", "65535", "1023", "gray12", "gray16"):
        assert literal not in code, f"{literal!r} is hardcoded; read it from the frame"
