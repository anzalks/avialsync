"""Default axis readings and the alternatives the imaging pane offers (D-194)."""

from avialsync.core.imaging_axes import axis_choices, default_axes, describe_axes, valid_axes


def test_a_valid_tag_is_kept_and_an_invalid_one_replaced():
    assert default_axes((5, 3, 8, 8), "CTYX") == "CTYX"
    assert default_axes((2000, 60, 80), "ZYX") == "TYX", "ImageJ slices of a movie"
    assert default_axes((2000, 60, 80), "QYX") == "TYX"


def test_sizes_decide_an_untagged_stack():
    assert default_axes((100, 2, 32, 32)) == "TCYX"
    assert default_axes((2, 100, 32, 32)) == "CTYX"
    assert default_axes((100, 12, 32, 32)) == "TZYX", "more than four is not channels"
    assert default_axes((100, 12, 2, 32, 32)) == "TZCYX"


def test_every_offered_order_is_valid_and_time_first_leads():
    choices = axis_choices((100, 2, 32, 32))
    assert choices[0].startswith("T")
    assert set(choices) == {"TCYX", "TZYX", "CTYX", "ZTYX"}
    assert all(valid_axes((100, 2, 32, 32), axes) for axes in choices)
    assert axis_choices((100, 32, 32)) == ["TYX"], "a movie has nothing to choose"


def test_orders_are_named_by_meaning_and_size():
    assert describe_axes((100, 2, 32, 32), "TCYX") == "Time 100 · Channels 2"
