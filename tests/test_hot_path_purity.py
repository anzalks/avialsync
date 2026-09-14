"""Nothing on a UI callback may fork a process or re-derive a constant.

Both halves of this were found by profiling a 128-row zoom, where they were
between them most of the frame.

`theme.system_accent` asks macOS for the user's accent colour with
``defaults read -g AppleAccentColor`` and cached the answer -- but only when
there *was* one. The key is unset until someone picks a colour in System
Settings, so on a default Mac the lookup failed, cached nothing, and forked
again on the next call. `evidence_color` and the transport's painter both sit
in repaint paths, so a zoom across 128 rows spawned processes (D-111).

The memo is one name, so `_macos_accent = None` clears all of it -- a second
flag beside it would let a caller reset half the cache.

`_fit_affine` ran `np.polyfit(x, y, 1)` -- a Vandermonde matrix and an SVD --
to obtain the two numbers of a straight line, several hundred times per
alignment preview.
"""

from __future__ import annotations

import subprocess

import numpy as np
import pytest
from PySide6.QtGui import QPalette

from avialsync.core.sync import _fit_affine
from avialsync.ui import theme


@pytest.fixture
def unprobed_accent(monkeypatch: pytest.MonkeyPatch):
    """Reset the accent memo, as an appearance change does."""
    monkeypatch.setattr(theme, "_macos_accent", None)


class TestTheAccentIsAskedForOnce:
    def test_a_mac_with_no_explicit_accent_is_asked_once(
        self, qapp, monkeypatch: pytest.MonkeyPatch, unprobed_accent
    ) -> None:
        """The default macOS configuration, and the one that used to re-fork."""
        calls: list[list[str]] = []

        def fake_run(command, **_kwargs):
            calls.append(list(command))
            raise subprocess.CalledProcessError(1, command)

        monkeypatch.setattr(theme.sys, "platform", "darwin")
        monkeypatch.setattr(theme.subprocess, "run", fake_run)
        palette = QPalette()

        for _ in range(50):
            theme.system_accent(palette)

        assert len(calls) == 1, (
            f"the accent preference was read {len(calls)} times; a negative "
            "answer must be remembered as firmly as a positive one"
        )

    def test_a_mac_with_an_accent_is_also_asked_once(
        self, qapp, monkeypatch: pytest.MonkeyPatch, unprobed_accent
    ) -> None:
        calls: list[list[str]] = []

        def fake_run(command, **_kwargs):
            calls.append(list(command))
            return subprocess.CompletedProcess(command, 0, stdout="4\n", stderr="")

        monkeypatch.setattr(theme.sys, "platform", "darwin")
        monkeypatch.setattr(theme.subprocess, "run", fake_run)
        palette = QPalette()

        colours = [theme.system_accent(palette).name() for _ in range(50)]

        assert len(calls) == 1
        assert len(set(colours)) == 1, "the memo must not change what is returned"

    def test_an_appearance_change_asks_again(
        self, qapp, monkeypatch: pytest.MonkeyPatch, unprobed_accent
    ) -> None:
        """The memo is a cache, not a one-shot: the user can change the setting."""
        calls: list[list[str]] = []

        def fake_run(command, **_kwargs):
            calls.append(list(command))
            raise subprocess.CalledProcessError(1, command)

        monkeypatch.setattr(theme.sys, "platform", "darwin")
        monkeypatch.setattr(theme.subprocess, "run", fake_run)
        palette = QPalette()
        theme.system_accent(palette)

        monkeypatch.setattr(theme, "_macos_accent", None)
        theme.system_accent(palette)

        assert len(calls) == 2


class TestTheLineFitIsClosedForm:
    """Same answer as polyfit, without the SVD."""

    def test_it_matches_polyfit_on_a_drifting_train(self) -> None:
        reference = np.arange(0.0, 5_000.0, 0.5)
        target = reference + 1.25 + 3.5e-6 * reference

        slope, offset = _fit_affine(reference, target)
        expected_slope, expected_offset = np.polyfit(reference, target, 1)

        # Far tighter than the 1e-5 ppm the fit's own tests assert.
        assert slope == pytest.approx(expected_slope, abs=1e-12)
        assert offset == pytest.approx(expected_offset, abs=1e-9)

    def test_it_matches_polyfit_on_noisy_evidence(self) -> None:
        rng = np.random.default_rng(7)
        reference = np.sort(rng.uniform(0.0, 5_000.0, 2_000))
        target = 1.0000035 * reference + 1.25 + rng.normal(0.0, 1e-4, 2_000)

        slope, offset = _fit_affine(reference, target)
        expected_slope, expected_offset = np.polyfit(reference, target, 1)

        assert slope == pytest.approx(expected_slope, abs=1e-12)
        assert offset == pytest.approx(expected_offset, abs=1e-9)

    def test_two_points_still_fit_exactly(self) -> None:
        slope, offset = _fit_affine(np.array([10.0, 20.0]), np.array([11.0, 21.5]))

        assert slope == pytest.approx(1.05)
        assert offset == pytest.approx(0.5)

    def test_events_at_one_instant_do_not_produce_a_nan_mapping(self) -> None:
        """polyfit answered this with a RankWarning and a NaN slope."""
        slope, offset = _fit_affine(np.array([4.0, 4.0, 4.0]), np.array([9.0, 9.0, 9.0]))

        assert np.isfinite(slope) and np.isfinite(offset)
        assert slope == pytest.approx(1.0)
        assert offset == pytest.approx(5.0)
