"""Why a fit's precision is unverified, and the overlap the match rate counts over."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from avialsync.core.sync import SyncFit, overlap_count, with_precision


def _fit(**changes: object) -> SyncFit:
    base = SyncFit(0.0, 0.0, 0.0, 0.0, 10, 0, reference_count=10, target_count=10)
    return dataclasses.replace(base, **changes)


_EVENTS = np.arange(0.0, 10.0, 1.0)


def test_a_verified_fit_names_no_shortfall() -> None:
    fit = with_precision(_fit(), _EVENTS, _EVENTS, (0.0, 9.0), 0.001)

    assert fit.precision_verified
    assert fit.precision_shortfall == ""


@pytest.mark.parametrize(
    ("fit", "span", "events", "phrase"),
    [
        (_fit(max_residual=0.002), (0.0, 9.0), _EVENTS, "worst residual 2.000 ms"),
        (_fit(measurement_resolution=0.01), (0.0, 9.0), _EVENTS, "timestamp resolution"),
        (_fit(), (0.0, 100.0), np.array([0.0, 100.0]), "gap between matched events"),
        (_fit(), (0.0, 60.0), _EVENTS, "lies beyond the matched events"),
    ],
)
def test_each_failed_check_is_named(
    fit: SyncFit, span: tuple[float, float], events: np.ndarray, phrase: str
) -> None:
    judged = with_precision(fit, events, events, span, 0.001)

    assert not judged.precision_verified
    assert phrase in judged.precision_shortfall


def test_match_rate_uses_the_overlap_when_measured() -> None:
    assert _fit(matched_count=10, reference_count=50).match_rate == pytest.approx(0.2)
    overlapped = _fit(matched_count=10, reference_count=50, overlap_reference_count=10)
    assert overlapped.match_rate == pytest.approx(1.0)
    assert overlapped.paired_of == 10
    # A matched count over the measured overlap never reads as more than all.
    assert _fit(matched_count=12, overlap_reference_count=10).match_rate == 1.0


def test_overlap_counts_mapped_reference_events_inside_the_target() -> None:
    reference = np.arange(0.0, 100.0, 1.0)

    assert overlap_count(reference, 1.0, 5.0, (5.0, 24.0), 0.1) == 20
    assert overlap_count(reference, 1.0, 0.0, (200.0, 300.0), 0.1) == 0


def test_the_denominator_is_described_only_when_it_differs() -> None:
    whole = _fit(matched_count=10, reference_count=10, overlap_reference_count=10)
    part = _fit(matched_count=10, reference_count=50, overlap_reference_count=10)

    assert "overlap" not in whole.describe()
    assert "in the overlap (50 in the whole reference)" in part.describe()
