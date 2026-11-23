"""First/last fixtures preserve clicked endpoints and fill the requested total."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from avialsync.core.errors import PropModelError
from avialsync.core.ladder_support import lay_out_rungs, rung_places
from avialsync.core.physical_props import Ladder, LadderPoint, LadderStep, RungPattern, StepClick
from avialsync.core.prop_file import read_props, write_prop
from avialsync.ui.prop_support_drawing import rung_pixels, rung_positions
from tests.wheel_fixture import CAMERAS


@pytest.mark.parametrize("dimension", [2, 3])
def test_first_and_last_footholds_fill_exactly_thirty_positions(dimension: int) -> None:
    first = (10.0, 20.0, 70.0)[:dimension]
    last = (300.0, 600.0, 70.0)[:dimension]
    steps = ((first,), (last,))
    layout = lay_out_rungs(steps, (0, 1, 30), between_endpoints=True)
    assert len(layout.walkway) == 30
    assert layout.walkway[0] == (first,) and layout.walkway[-1] == (last,)
    assert [number for number, _points in layout.generated] == list(range(2, 30))
    for number, (point,) in layout.generated:
        expected = np.asarray(first) + (number - 1) / 29 * (np.asarray(last) - first)
        np.testing.assert_allclose(point, expected)
    assert rung_places(steps, (0, 1, 30), between_endpoints=True) == (0.0, 1.0)
    assert lay_out_rungs(steps, (0, 1, 2), between_endpoints=True).generated == ()


def test_first_last_rungs_preserve_perspective_and_pair_their_ends() -> None:
    camera = CAMERAS["Front"]

    def rung(index: int):
        return tuple(tuple(camera.project(np.array((20.0 * index, y, 70.0)))[0]) for y in (-10, 10))

    layout = lay_out_rungs((rung(0), tuple(reversed(rung(5)))), (0, 1, 6), between_endpoints=True)
    assert len(layout.walkway) == 6
    for number, points in layout.generated:
        np.testing.assert_allclose(points, rung(number - 1), atol=1e-8)


def test_clicked_middle_step_replaces_its_guide_and_keeps_walkway_order() -> None:
    first, middle, last = ((0.0, 0.0),), ((50.0, 2.0),), ((100.0, 0.0),)
    layout = lay_out_rungs((first, middle, last), (0, 2, 5), between_endpoints=True)
    assert [number for number, _p in layout.generated] == [2, 4]
    assert layout.walkway[2] == middle
    assert len(layout.walkway) == 5


@pytest.mark.parametrize(
    "steps",
    [
        (((0.0, 0.0),), (None,)),
        ((None,), ((10.0, 0.0),)),
        (((0.0, 0.0),), ((0.0, 0.0),)),
        (((0.0, 0.0),), ((10.0, 0.0), (10.0, 5.0))),
    ],
)
def test_incomplete_or_coincident_anchors_never_invent_geometry(steps) -> None:
    assert lay_out_rungs(steps, (0, 1, 30), between_endpoints=True).generated == ()


def _ladder(*, solved: bool = False) -> Ladder:
    points = []
    for x in (0.0, 100.0):
        xyz = (x, 0.0, 70.0)
        clicks = []
        for name in ("Front", "Left") if solved else ("Front",):
            pixel = CAMERAS[name].project(np.asarray(xyz))[0]
            clicks.append(StepClick(name, 7, float(pixel[0]), float(pixel[1])))
        point = LadderPoint(tuple(clicks))
        points.append(point.resolved(CAMERAS) if solved else point)
    return Ladder(
        "endpoint ladder",
        tuple(LadderStep(str(i), f"Observed {i}", (point,)) for i, point in enumerate(points)),
        support="centre_beam",
        pattern=RungPattern("0", "1", 6, between_endpoints=True),
    )


def test_endpoint_mode_round_trips_in_the_current_prop_format(tmp_path) -> None:
    ladder = _ladder()
    target = write_prop(tmp_path, ladder)
    assert "version = 3" in target.read_text()
    assert "[context]" in target.read_text()
    assert "pattern_endpoints = true" in target.read_text()
    assert read_props(tmp_path) == ([ladder], [])
    adjacent = dataclasses.replace(ladder, pattern=RungPattern("0", "1", 6))
    write_prop(tmp_path, adjacent)
    assert read_props(tmp_path) == ([adjacent], [])
    with pytest.raises(PropModelError, match="true or false"):
        RungPattern("a", "b", 6, between_endpoints="yes")


def test_image_only_footholds_stay_in_their_view_and_remain_estimates() -> None:
    ladder = _ladder()
    pixels = [[(p.clicks[0].x, p.clicks[0].y, True) for p in s.points] for s in ladder.steps]
    drawings = rung_pixels(ladder, pixels)
    guides = [points for label, points, _closed in drawings if label]
    assert len(guides) == 4 and all(len(points) == 1 for points in guides)
    assert all(not pixel[2] for points in guides for pixel in points if pixel is not None)
    assert rung_pixels(ladder, [[None], [None]]) == [("", (None, None), False)]
    assert rung_positions(ladder) == [("", (None, None), False)]


def test_solved_footholds_use_even_3d_spacing_before_camera_projection() -> None:
    ladder = _ladder(solved=True)
    camera = CAMERAS["Right"]

    def project(xyz):
        x, y = camera.project(np.asarray(xyz))[0]
        return float(x), float(y), False

    pixels = [[project(p.xyz) for p in step.points] for step in ladder.steps]
    drawings = rung_pixels(ladder, pixels, project=project)
    expected = [project((x, 0.0, 70.0)) for x in (20, 40, 60, 80)]
    guides = [points[0] for label, points, _c in drawings if label]
    np.testing.assert_allclose(guides, expected)
    assert len([points for label, points, _c in rung_positions(ladder) if label]) == 4


def test_solved_neighbour_rungs_project_3d_guides_through_lens_distortion() -> None:
    """Neighbour-extended 3D rungs honour radial lens distortion instead of 2D homography."""
    distorted_cam = dataclasses.replace(
        CAMERAS["Front"],
        distortions=np.asarray([-0.35, 0.12, 0.0, 0.0, 0.0], dtype=np.float64),
    )
    cameras = {**CAMERAS, "Front": distorted_cam}

    steps = []
    for idx, x in enumerate((0.0, 12.0)):
        pts = []
        for y in (-8.0, 8.0):
            xyz = np.asarray((x, y, 70.0), dtype=np.float64)
            clicks = tuple(
                StepClick(
                    name,
                    0,
                    float(cameras[name].project(xyz)[0, 0]),
                    float(cameras[name].project(xyz)[0, 1]),
                )
                for name in ("Front", "Left")
            )
            pts.append(LadderPoint(clicks).resolved(cameras))
        steps.append(LadderStep(str(idx), f"Rung {idx + 1}", tuple(pts)))

    ladder = Ladder(
        "distorted_neighbour_ladder",
        tuple(steps),
        support="side_rails",
        pattern=RungPattern("0", "1", 8, between_endpoints=False),
    )

    def project(xyz: tuple[float, float, float]) -> tuple[float, float, bool]:
        px, py = distorted_cam.project(np.asarray(xyz, dtype=np.float64))[0]
        return float(px), float(py), False

    step_pixels = [
        [(p.clicks[0].x, p.clicks[0].y, True) for p in step.points] for step in ladder.steps
    ]
    drawings = rung_pixels(ladder, step_pixels, project=project)
    # Rung 8 (7 spacings from Rung 1 -> x = 84.0) is captioned at the far end of the run.
    far_guide = [pts for label, pts, _c in drawings if "8" in label][0]
    expected_far = tuple(project((84.0, y, 70.0)) for y in (-8.0, 8.0))
    np.testing.assert_allclose(far_guide, expected_far, atol=1e-4)
