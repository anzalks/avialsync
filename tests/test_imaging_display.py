"""Levels, brightness/contrast, moving average and overlay for imaging (D-190)."""

import numpy as np
import pytest

from avialsync.core.imaging_display import (
    CHANNEL_COLORS,
    MAX_AVERAGE,
    ChannelView,
    ImagingView,
    auto_window,
    average_range,
    compose,
    default_colors,
    odd_average,
)
from avialsync.ui.cvd import DEFICIENCIES, minimum_separation

# ── the moving average never shifts time ─────────────────────────────


@pytest.mark.parametrize("frames", [1, 3, 5, 31])
def test_the_average_is_centred_on_the_shown_frame(frames):
    window = average_range(50, 100, frames)
    assert len(window) == frames
    assert (window.start + window.stop - 1) / 2 == 50, "a trailing average would shift events"


def test_the_average_is_truncated_at_the_ends_not_shifted():
    """Shifting the window inward would show later frames as if they were frame 0."""
    assert list(average_range(0, 100, 5)) == [0, 1, 2]
    assert list(average_range(99, 100, 5)) == [97, 98, 99]
    assert list(average_range(0, 1, 31)) == [0]


def test_average_lengths_are_odd_and_bounded():
    assert [odd_average(n) for n in (0, 1, 2, 3, 4, 99)] == [1, 1, 1, 3, 3, MAX_AVERAGE]


# ── levels ───────────────────────────────────────────────────────────


def test_auto_window_ignores_a_hot_pixel():
    plane = np.full((100, 100), 200, np.uint16)
    plane[:50] = 100
    plane[0, 0] = 65535
    low, high = auto_window(plane)
    assert (low, high) == (100.0, 200.0)


def test_auto_window_of_a_flat_or_empty_plane_is_still_a_window():
    assert auto_window(np.full((4, 4), 7, np.uint16)) == (7.0, 8.0)
    assert auto_window(np.full((4, 4), np.nan, np.float32)) == (0.0, 1.0)


def test_brightness_and_contrast_move_and_scale_the_measured_window():
    neutral = ChannelView(auto_low=100.0, auto_high=200.0)
    assert neutral.window() == (100.0, 200.0)
    brighter = ChannelView(auto_low=100.0, auto_high=200.0, brightness=0.5)
    assert brighter.window() == (50.0, 150.0), "brighter moves the window down"
    sharper = ChannelView(auto_low=100.0, auto_high=200.0, contrast=0.25)
    assert sharper.window() == (125.0, 175.0), "a quarter of full contrast halves the width"


def test_windowing_keeps_the_raw_range_until_the_last_step():
    """A 12-bit ramp windowed to 1000-1255 must map one count to one grey level."""
    ramp = np.arange(1000, 1256, dtype=np.uint16).reshape(16, 16)
    image = compose([(ramp, ChannelView(auto_low=1000.0, auto_high=1255.0))])
    assert image.dtype == np.uint8 and image.ndim == 2
    assert np.unique(image).size == 256


# ── overlay ──────────────────────────────────────────────────────────


def test_two_channels_overlay_additively_in_their_colours():
    green_signal = np.array([[0.0, 1.0], [0.0, 1.0]], np.float32)
    magenta_signal = np.array([[0.0, 0.0], [1.0, 1.0]], np.float32)
    image = compose(
        [
            (green_signal, ChannelView(color="green", auto_low=0.0, auto_high=1.0)),
            (magenta_signal, ChannelView(color="magenta", auto_low=0.0, auto_high=1.0)),
        ]
    )
    assert image.shape == (2, 2, 3)
    assert image[0, 0].tolist() == [0, 0, 0]
    assert image[0, 1].tolist() == [0, 255, 0]
    assert image[1, 0].tolist() == [255, 0, 255]
    assert image[1, 1].tolist() == [255, 255, 255], "co-localised signal reads as white"


def test_nan_pixels_show_black_rather_than_poisoning_the_frame():
    plane = np.array([[np.nan, 1.0]], np.float32)
    image = compose([(plane, ChannelView(auto_low=0.0, auto_high=1.0))])
    assert image.tolist() == [[0, 255]]


def test_compose_without_a_visible_plane_is_a_caller_error():
    with pytest.raises(ValueError):
        compose([])


@pytest.mark.parametrize("count", [2, 3, 4])
def test_default_channel_colours_survive_colour_vision_deficiency(count):
    """D-094: the defaults clear the same floor the plot palette does."""
    palette = tuple(CHANNEL_COLORS[name] for name in default_colors(count))
    for deficiency in DEFICIENCIES:
        assert minimum_separation(palette, deficiency) >= 0.05, (count, deficiency)


# ── persistence ──────────────────────────────────────────────────────


def test_a_view_round_trips_and_survives_a_file_with_more_channels():
    view = ImagingView(
        channels=(ChannelView(color="magenta", auto_low=3.0, auto_high=9.0, contrast=0.2),),
        average=5,
    )
    restored = ImagingView.from_dict(view.to_dict())
    assert restored == view
    widened = restored.fitted(3)
    assert len(widened.channels) == 3
    assert widened.channels[0] == view.channels[0], "existing choices are kept"
    assert not widened.channels[2].measured


def test_a_hand_edited_view_is_clamped_rather_than_refused():
    view = ImagingView.from_dict(
        {"average": 4, "channels": [{"color": "ultraviolet", "brightness": 9}]}
    )
    assert view.average == 3
    assert view.channels[0].color == "grey"
    assert view.channels[0].brightness == 1.0


def test_channels_named_by_a_colour_start_in_that_colour():
    from avialsync.core.imaging_display import ImagingView, default_colors

    assert default_colors(2, ("Red", "Green")) == ("red", "green")
    assert default_colors(2, ("GCaMP", "tdTomato")) == ("green", "magenta")
    assert default_colors(2) == ("green", "magenta")
    view = ImagingView().fitted(2, ("Red", "Green"))
    assert [channel.color for channel in view.channels] == ["red", "green"]
    # A stored choice is kept: the name only seeds channels the view lacks.
    kept = ImagingView(channels=(view.channels[0].__class__(color="cyan"),)).fitted(
        2, ("Red", "Green")
    )
    assert [channel.color for channel in kept.channels] == ["cyan", "green"]
