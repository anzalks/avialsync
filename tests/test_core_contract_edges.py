"""Boundary contracts for clocks, imaging axes, projection and plugin defaults."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from avialsync.core.alignment import residual_trend
from avialsync.core.drift import drift_from_legacy_entry
from avialsync.core.errors import PropModelError
from avialsync.core.imaging_axes import axis_choices, default_axes
from avialsync.core.imaging_display import ImagingView
from avialsync.core.plane_view import PlaneView
from avialsync.core.source import TriggerSource
from avialsync.core.toml_format import toml_value
from avialsync.core.trials import TimeWarp
from avialsync.core.triggers import Reconciliation, TriggerKind, TriggerTrain
from tests.test_core_plugin_validation import SeriesSource


def test_unsupported_image_dimensions_do_not_offer_a_false_axis_order() -> None:
    assert axis_choices((512, 512)) == []
    assert axis_choices((1, 2, 3, 4, 512, 512)) == []
    assert default_axes((512, 512)) == ""
    assert default_axes((10, 20, 30, 40, 512, 512)) == ""
    assert len(ImagingView.for_channels(2).channels) == 2


def test_unsupported_drift_value_and_toml_object_are_rejected() -> None:
    with pytest.raises(ValueError, match="must be a number"):
        drift_from_legacy_entry({"drift_ms_per_hour": object()})
    with pytest.raises(TypeError, match="Cannot write"):
        toml_value(object())


def test_residual_trend_needs_a_positive_time_span() -> None:
    assert residual_trend(np.array([1.0, 1.0, 1.0]), np.array([0.0, 1.0, 2.0])) == 0.0


def test_collapsed_gap_vector_mapping_matches_the_scalar_authority() -> None:
    warp = TimeWarp(((2.0, 4.0), (6.0, 9.0)))
    times = np.array([-1.0, 0.0, 2.0, 3.0, 4.0, 6.0, 8.0, 9.0, 10.0])
    np.testing.assert_array_equal(warp.to_view_array(times), [warp.to_view(t) for t in times])
    np.testing.assert_array_equal(warp.breaks, [2.0, 4.0])
    assert hash(warp) == hash(TimeWarp(warp.gaps))
    assert {warp: "same"}[TimeWarp(warp.gaps)] == "same"


def test_short_trigger_trains_do_not_invent_span_or_exposure() -> None:
    empty = TriggerTrain(TriggerKind.FRAME_STROBE, "source", np.array([]), np.array([]))
    assert empty.span == 0.0 and empty.mean_exposure is None
    one = TriggerTrain(TriggerKind.FRAME_STROBE, "source", np.array([1.0]))
    assert one.span == 0.0
    train = TriggerTrain(
        TriggerKind.FRAME_STROBE, "source", np.array([1.0, 2.0]), np.array([0.1, 0.3])
    )
    assert train.span == 1.0 and train.mean_exposure == pytest.approx(0.2)
    assert "no trigger" in Reconciliation(2, 3, TriggerKind.FRAME_TRIGGER).explain()


@pytest.mark.parametrize(
    ("plane", "image"),
    [
        ([(0, 0)], [(0, 0)]),
        ([(0, 0), (1, 0), (1, 1), (0, 1)], [(0, 0), (1, 0), (np.nan, 1), (0, 1)]),
        ([(0, 0), (1, 0), (2, 0), (3, 0)], [(0, 0), (1, 0), (2, 0), (3, 0)]),
        ([(0, 0), (1, 0), (1, 1), (0, 1)], [(0, 0), (1, 1), (1, 0), (0, 1)]),
    ],
)
def test_plane_view_rejects_incomplete_nonfinite_or_impossible_correspondences(
    plane: list, image: list
) -> None:
    with pytest.raises(PropModelError):
        PlaneView(plane, image)


def test_projection_and_inverse_hide_nonfinite_points() -> None:
    points = [(0, 0), (1, 0), (1, 1), (0, 1)]
    view = PlaneView(points, points)
    assert view.pixel(np.nan, 0.0) is None
    assert view.plane(np.nan, 0.0) is None
    assert view.pixel(0.5, 0.5) == pytest.approx((0.5, 0.5))


def test_plugin_defaults_declare_no_guessed_partner_or_trigger_semantics(tmp_path: Path) -> None:
    class Events(TriggerSource):
        @classmethod
        def can_open(cls, path: Path) -> float:
            return 1.0

        def open(self, path: Path, config: dict) -> None:
            return None

        def trains(self) -> list[str]:
            return []

        def kind_of(self, train_id: str) -> str:
            return "sync_train"

        def read_train(self, train_id: str) -> tuple[np.ndarray, None]:
            return np.array([]), None

    assert SeriesSource.plugin_id() == "seriessource"
    assert Events.suggest_trains(tmp_path) == []
    assert Events().target_hint("unknown") == ""
