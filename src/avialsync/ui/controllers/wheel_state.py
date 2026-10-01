"""Transient presentation state for wheel placement and rendering.

Accepted wheels live in the document-backed WheelStore. This object contains
only an in-progress gesture, derived render caches, and one-shot notices.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from avialsync.core.source import RotaryHint
from avialsync.core.wheel import WheelSpec
from avialsync.ui.controllers.wheel_placement import WheelPlacement


@dataclass
class WheelState:
    """Wheel UI state owned by one main window."""

    placement: WheelPlacement | None = None
    refits: dict[str, WheelSpec] = field(default_factory=dict)
    diameter_preview: dict[str, float] = field(default_factory=dict)
    checking: str | None = None
    cache: dict[str, tuple[object, Any]] = field(default_factory=dict)
    announced_files: set[str] = field(default_factory=set)
    adopt_folders: set[Path] = field(default_factory=set)
    session_rotary: RotaryHint | None = None
    pane_source: Callable[[str, float], object] | None = None
