"""Tests for the NeoLoader ephys data plugin."""

from pathlib import Path
import pytest
import numpy as np
from kinochronix.loaders.neo_loader import NeoLoader

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
        assert ch.name == f"CH{i+1}"
        assert ch.rate_hz == 30000.0
        assert ch.unit == "uV"
        
    # 3. Test time bounds
    bounds = loader.time_bounds()
    assert bounds[0] == 0.0
    assert bounds[1] > 0.0
    assert abs(bounds[1] - 10.0) < 0.1  # We generated 10 seconds of mock data
    
    # 4. Test chunk reading
    # Read the first channel
    chunks = list(loader.read_chunks("CH1"))
    assert len(chunks) > 0
    
    # Check the first chunk
    t_chunk, v_chunk = chunks[0]
    assert len(t_chunk) == len(v_chunk)
    assert t_chunk[0] == 0.0
    
    # Verify the chunk is actual data (not all zeros, since it's a sine wave)
    assert np.any(v_chunk != 0)
