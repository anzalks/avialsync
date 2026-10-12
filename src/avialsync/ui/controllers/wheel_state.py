"""Transient presentation state for wheel placement and rendering.

Accepted wheels live in the document-backed PropStore. This object contains
only an in-progress gesture, derived render caches, and one-shot notices.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from avialsync.core.rotary_calibration import RotaryCalibrationProposal
from avialsync.core.source import RotaryHint
from avialsync.core.wheel import WheelSpec
from avialsync.ui.controllers.wheel_placement import WheelPlacement


@dataclass(frozen=True)
class RotationPreview:
    """One unsaved visual alignment for the frame currently under review."""

    frame: int
    adjustment_degrees: float


@dataclass
class WheelState:
    """Wheel UI state owned by one main window."""

    placement: WheelPlacement | None = None
    refits: dict[str, WheelSpec] = field(default_factory=dict)
    diameter_preview: dict[str, float] = field(default_factory=dict)
    checking: str | None = None
    #: Wheel whose later-frame visual alignments are being collected for a fit.
    calibrating: str | None = None
    #: Live, unsaved bar rotation keyed by wheel name.  It is deliberately
    #: presentation state: moving a slider must not make a document mutation.
    rotation_preview: dict[str, RotationPreview] = field(default_factory=dict)
    #: Whether the master clock already has the observer that moves the
    #: adjustment slider to the frame the user navigates to.
    rotation_clock_subscribed: bool = False
    #: Explicitly unaccepted transfer proposals, keyed by wheel name.
    motion_proposals: dict[str, RotaryCalibrationProposal] = field(default_factory=dict)
    #: Wheels with a background rotation fit currently running.
    motion_fitting: set[str] = field(default_factory=set)
    cache: dict[str, tuple[object, Any]] = field(default_factory=dict)
    session_rotary: RotaryHint | None = None
    pane_source: Callable[[str, float], object] | None = None
