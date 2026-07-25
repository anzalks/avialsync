"""Tests for the NeoLoader ephys data plugin."""

from pathlib import Path

import numpy as np
import pytest

from avialview.loaders.neo_loader import SUPPORTED_EXTENSIONS, NeoLoader

# ---------------------------------------------------------------------------
# can_open whitelist tests — no fixture needed
# ---------------------------------------------------------------------------


def test_can_open_zero_for_csv(tmp_path: Path):
    """NeoLoader must never claim .csv files."""
    f = tmp_path / "data.csv"
    f.write_text("time,val\n0,1\n")
    assert NeoLoader.can_open(f) == 0.0


def test_can_open_zero_for_txt(tmp_path: Path):
    """NeoLoader must return 0.0 for plain text files."""
    f = tmp_path / "notes.txt"
    f.write_bytes(b"hello world\n")
    assert NeoLoader.can_open(f) == 0.0


def test_can_open_zero_for_random_binary(tmp_path: Path):
    """NeoLoader must return 0.0 for files with a non-whitelisted extension."""
    f = tmp_path / "data.bin"
    f.write_bytes(bytes(range(256)))
    assert NeoLoader.can_open(f) == 0.0


def test_can_open_positive_for_oebin_dir(tmp_path: Path):
    """Directory containing structure.oebin is recognised as OpenEphys dataset."""
    oe_dir = tmp_path / "session"
    oe_dir.mkdir()
    (oe_dir / "structure.oebin").write_text("{}")
    assert NeoLoader.can_open(oe_dir) == 1.0


def test_can_open_zero_for_empty_dir(tmp_path: Path):
    """Directory with no ephys signatures should score 0.0."""
    plain_dir = tmp_path / "nothing"
    plain_dir.mkdir()
    assert NeoLoader.can_open(plain_dir) == 0.0


def test_supported_extensions_excludes_generic_formats():
    """Verify .csv, .txt, .json, .py are not in the whitelist."""
    for ext in (".csv", ".txt", ".json", ".py", ".bin"):
        assert ext not in SUPPORTED_EXTENSIONS, f"{ext} must not be in SUPPORTED_EXTENSIONS"


def test_registry_picks_csv_loader_for_csv(tmp_path: Path):
    """LoaderRegistry must prefer CSVLoader over NeoLoader for .csv files."""
    from avialview.core.registry import LoaderRegistry
    from avialview.loaders.csv_loader import CSVLoader

    f = tmp_path / "data.csv"
    f.write_text("time,val\n0.0,1.0\n1.0,2.0\n")
    registry = LoaderRegistry()
    best = registry.find_best_loader(f)
    assert best is CSVLoader, f"Expected CSVLoader, got {best}"


# ---------------------------------------------------------------------------
# Legacy fixture-based test
# ---------------------------------------------------------------------------


def test_neoloader_openephys(tmp_path: Path):
    """Test loading a mock OpenEphys dataset."""
    # The fixture path is located in tools output or examples
    fixture_path = Path("tests/fixtures/openephys_mock")

    if not fixture_path.exists():
        pytest.skip("OpenEphys mock fixture not generated.")

    loader = NeoLoader()

    # 1. Test can_open logic
    # The root folder should return 1.0 because of our recursive check
    assert NeoLoader.can_open(fixture_path) == 1.0

    # 2. Test open and channel discovery
    loader.open(fixture_path, {})
    channels = loader.channels()

    # The mock has 4 channels (CH1, CH2, CH3, CH4)
    assert len(channels) == 4
    for i, ch in enumerate(channels):
        assert ch.name == f"CH{i + 1}"
        assert ch.rate_hz == 30000.0
        assert ch.unit == "uV"

    # 3. Test chunk reading
    # Read the first channel
    chunks = list(loader.read_chunks("CH1"))
    assert len(chunks) > 0

    # Check the first chunk
    t_chunk, v_chunk = chunks[0]
    assert len(t_chunk) == len(v_chunk)
    assert t_chunk[0] == 0.0

    # Verify the chunk is actual data (not all zeros, since it's a sine wave)
    assert np.any(v_chunk != 0)
