"""Generate AvialSync's platform icon assets from its canonical raster source."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PNG_SIZE = 512
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
ICNS_SIZES = [(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)]


def _square_icon(source: Path, size: int) -> Image.Image:
    """Return a high-quality square icon without stretching or cropping artwork."""
    with Image.open(source) as image:
        artwork = image.convert("RGBA")
        square_size = max(artwork.size)
        square = Image.new("RGBA", (square_size, square_size), (0, 0, 0, 0))
        offset = ((square_size - artwork.width) // 2, (square_size - artwork.height) // 2)
        square.alpha_composite(artwork, offset)
        return square.resize((size, size), Image.Resampling.LANCZOS)


def generate(source: Path, output_root: Path) -> None:
    """Write Linux, Windows, macOS, and runtime assets below ``output_root``."""
    image = _square_icon(source, PNG_SIZE)
    targets = (
        output_root / "src/avialsync/resources/avialsync.png",
        output_root / "packaging/linux/avialsync.png",
    )
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format="PNG", optimize=True)

    windows_icon = output_root / "packaging/windows/avialsync.ico"
    windows_icon.parent.mkdir(parents=True, exist_ok=True)
    image.save(windows_icon, format="ICO", sizes=ICO_SIZES)

    macos_icon = output_root / "packaging/macos/avialsync.icns"
    macos_icon.parent.mkdir(parents=True, exist_ok=True)
    image.save(macos_icon, format="ICNS", sizes=ICNS_SIZES)


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "assets/avial_sync.png",
        help="canonical PNG source (non-square artwork is transparently center-padded)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT,
        help="directory in which to write generated assets",
    )
    return parser.parse_args()


def main() -> None:
    """Generate platform icon files."""
    args = parse_args()
    generate(args.source.resolve(), args.output_root.resolve())


if __name__ == "__main__":
    main()
