import logging
from pathlib import Path

from avialview.loaders.neo_loader import NeoLoader

logging.basicConfig(level=logging.INFO)
base_dir = Path("TENSS26_Anzal")
ephys_dir = base_dir / "2026-06-21_17-54-56"

loader = NeoLoader()
if loader.can_open(ephys_dir) > 0:
    loader.open(ephys_dir, {})
    channels = loader.channels()
    print(f"Loaded {len(channels)} channels.")
    for ch in channels:
        print(f"  - {ch.name} ({ch.rate_hz} Hz, {ch.unit}, {ch.dtype})")
else:
    print("Cannot open ephys data.")
