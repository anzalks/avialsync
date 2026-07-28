import numpy as np
from avialview.core.sync import fit_exact_index_mapping

ref = np.linspace(0, 10, 100)
tgt = np.linspace(0, 10, 100)
proposal = fit_exact_index_mapping(ref, tgt, 0)
print(proposal.acceptable)
