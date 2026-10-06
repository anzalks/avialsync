"""Text as h5py hands it back, made into ``str`` (D-188).

HDF5 strings arrive as ``bytes``, ``str`` or zero-dimensional arrays of either,
depending on how the writer declared them; MatNWB and pynwb differ.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def text(value: Any) -> str:
    """Return *value* as text, decoding bytes as UTF-8."""
    if isinstance(value, bytes | np.bytes_):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray) and value.size == 1:
        return text(value.reshape(-1)[0])
    return str(value) if value is not None else ""
