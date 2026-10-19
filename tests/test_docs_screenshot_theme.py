"""Every published screenshot shows the dark theme, so the guide reads as one application.

The generators pin it through ``tools/screenshot_kit.pin_appearance``; this checks
the committed images, so one regenerated on a light-mode desktop by a tool that
forgot the pin is caught before it ships. The one exception is the image whose
subject is the Light theme itself.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

SCREENSHOTS = Path(__file__).resolve().parents[1] / "docs" / "_static" / "screenshots"
#: Images that exist to show the other theme.
LIGHT_BY_DESIGN = {"feature_light_theme.png"}
#: Mean luminance (0–255) of the window chrome along the edges. The dark theme
#: measures 24–52 across the current set and the light theme 221.
DARK_CEILING = 110.0


def _edge_luminance(path: Path) -> float:
    with Image.open(path) as image:
        pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    height, width = pixels.shape[:2]
    band_h, band_w = max(1, height // 20), max(1, width // 20)
    edges = np.concatenate(
        [
            pixels[:band_h].reshape(-1, 3),
            pixels[-band_h:].reshape(-1, 3),
            pixels[:, :band_w].reshape(-1, 3),
        ]
    )
    return float((edges @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).mean())


IMAGES = sorted(p for p in SCREENSHOTS.iterdir() if p.suffix.lower() in {".png", ".gif"})


def test_the_screenshot_folder_is_not_empty() -> None:
    assert IMAGES, f"no screenshots found in {SCREENSHOTS}"


@pytest.mark.parametrize("path", IMAGES, ids=lambda path: path.name)
def test_each_screenshot_is_in_the_documented_theme(path: Path) -> None:
    luminance = _edge_luminance(path)
    if path.name in LIGHT_BY_DESIGN:
        assert luminance > DARK_CEILING, f"{path.name} should show the Light theme"
    else:
        assert luminance < DARK_CEILING, (
            f"{path.name} is light (edge luminance {luminance:.0f}); regenerate it with a tool "
            "that calls screenshot_kit.pin_appearance"
        )
