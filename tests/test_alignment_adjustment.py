"""Manual corrections preserve measured nonlinear timing and remain reversible."""

import numpy as np
import pytest

from avialsync.core.timeline import TimeMap


def test_exact_mapping_survives_offset_and_rate_adjustments() -> None:
    mapping = TimeMap(2.0, 0.0)
    master = np.array([0.0, 1.0, 3.0, 5.0])
    source = np.array([2.0, 3.1, 5.0, 7.2])
    mapping.set_exact_mapping(master, source)
    original = mapping.copy()
    mapping.adjust_mapping(2.1, 360.0)
    assert mapping.has_exact_mapping
    assert mapping._exact_master is original._exact_master
    for time in [0.2, 0.8, 2.0, 4.0]:
        expected = original.to_source(time * 1.0001 + 0.1)
        assert mapping.to_source(time) == pytest.approx(expected)
        assert mapping.to_master(expected) == pytest.approx(time)
    mapping.adjust_mapping(2.0, 0.0)
    assert mapping.to_source_array(master) == pytest.approx(source)


def test_adjusted_exact_export_round_trip_retains_the_evaluated_mapping() -> None:
    mapping = TimeMap()
    mapping.set_exact_mapping(np.array([100.0, 101.0, 103.0]), np.array([0.0, 1.1, 3.0]))
    mapping.adjust_mapping(0.25, 100.0)
    restored = TimeMap.from_record(mapping.to_record())
    for time in [99.9, 100.5, 102.0]:
        assert restored.to_source(time) == pytest.approx(mapping.to_source(time))
        assert restored.contains_master_time(time) == mapping.contains_master_time(time)
        assert restored.rate_scale_at(time) == pytest.approx(mapping.rate_scale_at(time))
