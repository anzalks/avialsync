"""The wheel fitted from a few clicked bars, against a wheel whose truth is known (D-113).

The rig is synthetic ground truth (``tests/wheel_fixture.py``). The fit is judged
against the wheel that made the clicks, which is the only way to know it is
right rather than merely consistent.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from avialsync.core.commands import SetWheelCommand
from avialsync.core.errors import WheelFitError
from avialsync.core.wheel import (
    LEFT,
    RIGHT,
    EncoderBinding,
    EndClick,
    Wheel,
    WheelCheck,
    WheelSpec,
    WheelStore,
    fit_issue,
    project_bars,
)
from avialsync.core.wheel_check import check, observed_turn, settle_sign
from avialsync.core.wheel_file import (
    is_wheel_path,
    read_wheels,
    wheel_path,
    write_removed,
    write_wheel,
)
from avialsync.core.wheel_fit import fit_wheel
from tests.wheel_fixture import CAMERAS, TRUTH, clicks_for


def _angle(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    cosine = abs(float(np.dot(a, b)) / (np.linalg.norm(a) * np.linalg.norm(b)))
    return math.degrees(math.acos(min(1.0, cosine)))


# ── fitting ──────────────────────────────────────────────────────────


def test_three_neighbouring_bars_recover_the_wheel() -> None:
    fit = fit_wheel(WheelSpec("wheel", 36), clicks_for([0, 1, 2]), CAMERAS)
    geometry = fit.geometry
    assert _angle(geometry.axle, TRUTH.axle) < 1.0
    assert geometry.radius == pytest.approx(TRUTH.radius, rel=0.05)
    assert geometry.half_width == pytest.approx(TRUTH.half_width, rel=0.05)
    assert np.linalg.norm(np.subtract(geometry.centre, TRUTH.centre)) < 5.0
    assert fit.indices == (0, 1, 2)
    assert fit.median_px < 1.5
    assert not fit.skipped


def test_the_generated_bars_land_where_the_real_ones_are() -> None:
    """Generation is the point: bars nobody clicked must still be in the right place."""
    geometry = fit_wheel(WheelSpec("wheel", 36), clicks_for([0, 1, 2]), CAMERAS).geometry
    fitted, truth = geometry.bar_ends(), TRUTH.bar_ends()
    # The half of the wheel the cameras face, where the drawn bars are read.
    near = slice(0, 9)
    errors = [
        float(
            np.max(
                np.linalg.norm(
                    camera.project(fitted[near].reshape(-1, 3))
                    - camera.project(truth[near].reshape(-1, 3)),
                    axis=1,
                )
            )
        )
        for camera in CAMERAS.values()
    ]
    assert max(errors) < 10.0


def test_two_bars_pick_the_centre_beyond_them() -> None:
    """Two bars fit two wheels; the real axle is on the side away from the cameras."""
    fit = fit_wheel(WheelSpec("wheel", 36), clicks_for([0, 1]), CAMERAS)
    assert fit.can_flip
    assert np.linalg.norm(np.subtract(fit.geometry.centre, TRUTH.centre)) < 10.0
    flipped = fit_wheel(WheelSpec("wheel", 36), clicks_for([0, 1]), CAMERAS, flipped=True)
    assert flipped.geometry.centre[2] > 150.0, "the mirrored wheel sits above the bars"


def test_two_cameras_and_two_complete_bars_are_enough() -> None:
    """A missing view and a partly clicked third bar cannot block the fit."""
    clicks = clicks_for([0, 1, 2])
    complete = [click.without_view("Right") for click in clicks[:4]]
    partial_third = clicks[4].without_view("Right")
    cameras = {name: CAMERAS[name] for name in ("Front", "Left")}
    fit = fit_wheel(WheelSpec("wheel", 36), [*complete, partial_third], cameras)
    assert fit.indices == (0, 1)
    assert len(fit.residuals) == 8
    assert np.linalg.norm(np.subtract(fit.geometry.centre, TRUTH.centre)) < 10.0


def test_fit_quality_rejects_barrel_like_mismatch() -> None:
    """A solved model with large camera errors is not trusted as a wheel."""
    clicks = clicks_for([0, 1])
    fit = fit_wheel(WheelSpec("wheel", 36), clicks, CAMERAS)
    assert fit_issue(fit, clicks) is None
    far = dataclasses.replace(
        fit,
        residuals=tuple(dataclasses.replace(residual, pixels=60.0) for residual in fit.residuals),
    )
    assert fit_issue(far, clicks) == "clicks_far_from_fit"
    shifted = []
    for click in clicks:
        x, y = next((x, y) for camera, x, y in click.views if camera == "Left")
        shifted.append(click.with_view("Left", x + 60.0, y))
    inconsistent = fit_wheel(WheelSpec("wheel", 36), shifted, CAMERAS)
    assert fit_issue(inconsistent, shifted) == "clicks_far_from_fit"
    # Fits no longer skip a slot (D-123), but a file written before could.
    stepped = dataclasses.replace(fit, indices=(0, 2))
    assert fit_issue(stepped, clicks) == "bars_not_neighbours"


def test_a_typed_radius_is_checked_against_theclicks_for() -> None:
    spec = WheelSpec("wheel", 36, radius=100.0, units="mm")
    fit = fit_wheel(spec, clicks_for([0, 1, 2]), CAMERAS)
    assert fit.geometry.radius == 100.0
    assert fit.implied_radius == pytest.approx(100.0, rel=0.05)


def test_a_wrong_radius_shows_in_the_implied_one() -> None:
    """A radius typed in centimetres against millimetres must not pass quietly."""
    spec = WheelSpec("wheel", 36, radius=10.0, units="mm")
    fit = fit_wheel(spec, clicks_for([0, 1, 2]), CAMERAS)
    assert fit.implied_radius is not None
    assert abs(fit.implied_radius - 10.0) / 10.0 > 0.5


def test_a_radius_without_units_is_not_used() -> None:
    spec = WheelSpec("wheel", 36, radius=10.0, units="")
    assert spec.known_radius is None
    fit = fit_wheel(spec, clicks_for([0, 1, 2]), CAMERAS)
    assert fit.implied_radius is None
    assert fit.geometry.radius == pytest.approx(100.0, rel=0.05)


def test_clicked_bars_are_taken_as_neighbours_in_click_order() -> None:
    """D-123: the fit never re-derives slots; a skipped bar shows as click error."""
    clean = fit_wheel(WheelSpec("wheel", 36), clicks_for([0, 1, 2]), CAMERAS)
    stepped = fit_wheel(WheelSpec("wheel", 36), clicks_for([0, 1, 3]), CAMERAS)
    assert [abs(i) for i in clean.indices] == [0, 1, 2]
    assert [abs(i) for i in stepped.indices] == [0, 1, 2]
    assert not stepped.skipped
    assert stepped.max_px > 10 * clean.max_px


def test_a_radius_ten_times_off_is_visible_in_the_implied_radius() -> None:
    fit = fit_wheel(WheelSpec("wheel", 36, radius=10.0, units="mm"), clicks_for([0, 1]), CAMERAS)
    assert fit.implied_radius == pytest.approx(TRUTH.radius, rel=0.02)


def test_the_residuals_report_every_click() -> None:
    fit = fit_wheel(WheelSpec("wheel", 36), clicks_for([0, 1, 2]), CAMERAS)
    assert len(fit.residuals) == 3 * 2 * len(CAMERAS)
    assert all(abs(s) < 1.0 for s in fit.spacing_deg)
    assert all(p < 2.0 for p in fit.parallel_deg)


def test_one_bar_is_not_a_wheel() -> None:
    with pytest.raises(WheelFitError, match="at least two bars"):
        fit_wheel(WheelSpec("wheel", 36), clicks_for([0]), CAMERAS)


def test_an_end_seen_by_one_camera_does_not_count() -> None:
    clicks = list(clicks_for([0, 1]))
    clicks[3] = EndClick(clicks[3].bar, clicks[3].side, clicks[3].views[:1])
    with pytest.raises(WheelFitError):
        fit_wheel(WheelSpec("wheel", 36), clicks, CAMERAS)


def test_too_few_bars_on_the_wheel_is_refused() -> None:
    with pytest.raises(WheelFitError, match="at least 3 bars"):
        fit_wheel(WheelSpec("wheel", 2), clicks_for([0, 1]), CAMERAS)


def test_a_click_replaces_the_earlier_one_in_that_camera() -> None:
    click = EndClick(0, LEFT).with_view("Front", 1.0, 2.0).with_view("Front", 3.0, 4.0)
    assert click.views == (("Front", 3.0, 4.0),)
    assert click.without_view("Front").views == ()


# ── seeing it ────────────────────────────────────────────────────────


def test_bars_behind_the_wheel_are_not_facing_the_camera() -> None:
    camera = CAMERAS["Front"]
    _, in_front, facing = project_bars(TRUTH, TRUTH.bar_ends(), camera)
    assert in_front.all()
    assert facing[0], "the top bar faces a camera above and in front"
    assert not facing[18], "the bottom bar is behind the plate"


def test_a_turn_is_right_handed_about_the_axle() -> None:
    turned = TRUTH.bar_ends(90.0)
    # Bar 0 starts at +z; a quarter turn about +x carries it to -y.
    assert np.allclose(turned[0].mean(axis=0), [0.0, -100.0, 0.0], atol=1e-9)


# ── the encoder ──────────────────────────────────────────────────────


def _check_at(turn: float, frame: int, reference: float, sign: float) -> WheelCheck:
    """A click on a visible bar end with the true wheel turned by *turn*."""
    camera = CAMERAS["Front"]
    ends = TRUTH.bar_ends(turn)
    pixels, in_front, facing = project_bars(TRUTH, ends, camera)
    seen = np.flatnonzero(in_front & facing)
    x, y = pixels[seen[len(seen) // 2], 0]
    return WheelCheck(frame, reference + turn / sign, "Front", float(x), float(y))


def test_the_observed_turn_is_found_to_within_a_bar_gap() -> None:
    click = _check_at(47.0, 10, 0.0, 1.0)
    turn, off = observed_turn(TRUTH, CAMERAS["Front"], click.x, click.y)
    assert turn == pytest.approx(47.0 % 10.0, abs=0.05)
    assert off < 0.5


def test_checks_settle_a_reversed_encoder() -> None:
    reference = 12.0
    truth_sign = -1.0
    checks = (
        _check_at(-47.0, 100, reference, truth_sign),
        _check_at(-133.0, 200, reference, truth_sign),
    )
    assumed = EncoderBinding("enc", "encoder_angle", reference_angle=reference, sign=1.0)
    settled, results = settle_sign(TRUTH, assumed, CAMERAS, checks)
    assert settled.sign == truth_sign
    assert settled.measured
    assert all(abs(r.residual_deg) < 0.5 for r in results)


def test_one_check_does_not_settle_the_sign() -> None:
    checks = (_check_at(-47.0, 100, 0.0, -1.0),)
    assumed = EncoderBinding("enc", "encoder_angle", reference_angle=0.0)
    settled, _ = settle_sign(TRUTH, assumed, CAMERAS, checks)
    assert settled.sign == -1.0
    assert not settled.measured


def test_a_check_close_to_the_reference_cannot_tell_signs_apart() -> None:
    binding = EncoderBinding("enc", "encoder_angle", reference_angle=0.0)
    item = _check_at(3.0, 5, 0.0, 1.0)
    assert not check(TRUTH, binding, CAMERAS["Front"], item).informative


# ── the store and the file ───────────────────────────────────────────


def _wheel() -> Wheel:
    clicks = clicks_for([0, 1, 2])
    spec = WheelSpec("wheel", 36, radius=100.0, units="mm")
    binding = EncoderBinding(
        "enc.txt",
        "encoder_angle",
        12.0,
        sign=-1.0,
        checks=(WheelCheck(3, 40.0, "Front", 1.0, 2.0),),
    )
    return Wheel(
        spec, 7, clicks, fit_wheel(spec, clicks, CAMERAS), binding=binding, calibration="c.toml"
    )


def test_the_store_reports_only_real_changes() -> None:
    store = WheelStore()
    heard: list[str | None] = []
    store.observe(heard.append)
    wheel = _wheel()
    assert store.set("wheel", wheel)
    assert not store.set("wheel", wheel)
    assert store.set("wheel", None)
    assert heard == ["wheel", "wheel"]


def test_a_wheel_survives_its_file(tmp_path) -> None:
    wheel = _wheel()
    path = write_wheel(tmp_path / "pose-3d", wheel)
    assert is_wheel_path(path)
    wheels, unreadable = read_wheels(tmp_path / "pose-3d")
    assert unreadable == []
    assert wheels == [wheel]


def test_a_removed_wheel_keeps_its_file(tmp_path) -> None:
    write_wheel(tmp_path, _wheel())
    path = write_removed(tmp_path, "wheel")
    assert path is not None and path.exists()
    assert read_wheels(tmp_path) == ([], [])


def test_a_damaged_file_costs_only_its_own_wheel(tmp_path) -> None:
    write_wheel(tmp_path, _wheel())
    (tmp_path / "broken.wheel.toml").write_text("[wheel\n", encoding="utf-8")
    wheels, unreadable = read_wheels(tmp_path)
    assert len(wheels) == 1
    assert unreadable == ["broken.wheel.toml"]


def test_the_binding_turns_by_sign_and_ratio() -> None:
    binding = EncoderBinding("enc", "a", reference_angle=10.0, sign=-1.0, ratio=0.5)
    assert binding.turn(30.0) == -10.0
    assert dataclasses.replace(binding, sign=1.0).turn(30.0) == 10.0


def test_ends_clicked_the_other_way_round_are_named() -> None:
    """A bar clicked right-end-first would cancel the axle out of the mean."""
    clicks = list(clicks_for([0, 1, 2]))
    left, right = clicks[2], clicks[3]
    clicks[2] = EndClick(left.bar, RIGHT, left.views)
    clicks[3] = EndClick(right.bar, LEFT, right.views)
    with pytest.raises(WheelFitError, match="opposite order"):
        fit_wheel(WheelSpec("wheel", 36), clicks, CAMERAS)


def test_the_bar_diameter_travels_in_the_wheel_file(tmp_path) -> None:
    fit = fit_wheel(WheelSpec("wheel", 36), clicks_for([0, 1]), CAMERAS)
    wheel = Wheel(WheelSpec("wheel", 36), 7, clicks_for([0, 1]), fit, bar_diameter=6.5)
    write_wheel(tmp_path, wheel)
    assert read_wheels(tmp_path)[0] == [wheel]
    plain = dataclasses.replace(wheel, bar_diameter=None)
    write_wheel(tmp_path, plain)
    assert "bar_diameter" not in wheel_path(tmp_path, "wheel").read_text()
    assert read_wheels(tmp_path)[0] == [plain], "a file without it reads as not set"


def test_diameter_steps_merge_into_one_undo_step() -> None:
    fit = fit_wheel(WheelSpec("wheel", 36), clicks_for([0, 1]), CAMERAS)
    base = Wheel(WheelSpec("wheel", 36), 7, clicks_for([0, 1]), fit)
    thin = dataclasses.replace(base, bar_diameter=4.0)
    thick = dataclasses.replace(base, bar_diameter=5.0)
    merged = SetWheelCommand("wheel", base, thin).merge_with(SetWheelCommand("wheel", thin, thick))
    assert merged == SetWheelCommand("wheel", base, thick)
    refit = dataclasses.replace(thick, flipped=True)
    assert (
        SetWheelCommand("wheel", thin, thick).merge_with(SetWheelCommand("wheel", thick, refit))
        is None
    ), "a re-fit after it stays its own step"
