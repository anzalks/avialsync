import neo
from pathlib import Path
path = Path("examples/data/openephys_mock/experiment1")
io = neo.io.get_io(str(path))
blk = io.read_block()
asig = blk.segments[0].analogsignals[0]
print("string:", str(asig.units.dimensionality.string))
