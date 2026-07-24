import neo, numpy as np
io = neo.io.get_io('examples/data/openephys_mock/experiment1')
blk = io.read_block()
asig = blk.segments[0].analogsignals[0]
val = asig[:, 0]
print("Shape:", val.shape)
val2 = np.asarray(asig[:, 0].magnitude)
print("Shape after np.asarray:", val2.shape)
