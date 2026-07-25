"""Tests for the explicit performance-runner calibration policy."""

from tests.benchmarks import test_bench_pyramid, test_bench_sync


def test_reference_tier_enforces_raw_marks(monkeypatch) -> None:
    """A labelled reference runner must never receive a calibration multiplier."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("AVIALVIEW_HOSTED_CI", raising=False)

    assert test_bench_pyramid._budget_multiplier() == 1.0
    assert test_bench_sync._budget_multiplier() == 1.0


def test_hosted_tier_uses_one_uniform_documented_calibration(monkeypatch) -> None:
    """Hosted CI must use exactly the same multiplier for every timing path."""
    monkeypatch.setenv("AVIALVIEW_HOSTED_CI", "true")

    assert test_bench_pyramid._budget_multiplier() == 8.0
    assert test_bench_sync._budget_multiplier() == 8.0
