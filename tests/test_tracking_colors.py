"""The 2D overlay and the 3D view must agree on every body part's colour."""

import itertools
import math

import pytest

from avialsync.ui.tracking_colors import (
    POINT_COLORS,
    PointColorRegistry,
    color_for_point,
    register_points,
)


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Isolate each test from the module-level registry both views share."""
    from avialsync.ui.tracking_colors import REGISTRY

    REGISTRY.reset()
    yield
    REGISTRY.reset()


def test_the_same_body_part_is_one_colour_in_both_views() -> None:
    """The 2D CSV and the 3D EKS CSV name overlapping parts in different orders.

    Colour must follow the name, not the column position, or ``nose`` renders
    one colour over the video and another in the 3D view.
    """
    overlay_2d = ["nose", "left_ear", "right_ear", "tail_base"]
    pose_3d = ["tail_base", "nose", "spine_mid", "left_ear"]  # different order and set

    register_points(overlay_2d)
    register_points(pose_3d)

    for shared in set(overlay_2d) & set(pose_3d):
        assert color_for_point(shared) == color_for_point(shared)
    assert color_for_point("nose") != color_for_point("tail_base")


def test_a_loaded_point_set_gets_distinct_colours() -> None:
    """The previous hash-based rule collided: 10 parts drew only 3 of 6 colours."""
    names = [f"point_{i}" for i in range(len(POINT_COLORS))]

    register_points(names)

    assert len({color_for_point(n) for n in names}) == len(POINT_COLORS)


def test_loading_a_second_source_never_recolours_points_already_on_screen() -> None:
    """Recolouring mid-session would relabel points the user is watching."""
    register_points(["nose", "tail_base"])
    before = {n: color_for_point(n) for n in ("nose", "tail_base")}

    register_points(["aardvark_part", "nose", "zebra_part"])  # sorts around the existing two

    assert {n: color_for_point(n) for n in before} == before


def test_an_unregistered_name_still_paints() -> None:
    """Loose ``*_x``/``*_y`` readers reach the overlay without load-time routing."""
    color = color_for_point("never_registered")

    assert color in POINT_COLORS
    assert color_for_point("never_registered") == color  # and stays put


def test_palette_colours_are_perceptually_separable() -> None:
    """Muted colours crowd Lab space; guard against a future edit crowding it more."""

    def to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
        def linear(channel: int) -> float:
            u = channel / 255.0
            return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4

        r, g, b = (linear(c) for c in rgb)
        x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
        y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

        def f(t: float) -> float:
            return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

        fx, fy, fz = f(x), f(y), f(z)
        return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)

    closest = min(
        math.dist(to_lab(a), to_lab(b)) for a, b in itertools.combinations(POINT_COLORS, 2)
    )

    assert closest > 20.0, f"closest pair is only deltaE {closest:.1f} apart"


def test_registry_rejects_an_empty_palette() -> None:
    with pytest.raises(ValueError):
        PointColorRegistry(palette=())
