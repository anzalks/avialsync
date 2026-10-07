"""Shared playback-speed choices for the transport and video export dialogs."""

from __future__ import annotations

PLAYBACK_RATE_STEPS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 10.0)


def rate_label(rate: float) -> str:
    """Format one numeric playback rate for a compact selector."""
    return f"{rate}x" if rate >= 0.1 else f"{rate:.2f}x"
