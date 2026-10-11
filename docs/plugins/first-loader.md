# Your first loader

A loader reads one file into channels. Subclass `TimeSeriesSource` and implement four methods.

```python
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from avialsync.core.source import ChannelInfo, TimeSeriesSource


class ToyBinarySource(TimeSeriesSource):
    """Read .toybin files: little-endian (time, value) float64 pairs."""

    _dtype = np.dtype([("time", "<f8"), ("value", "<f8")])

    @classmethod
    def can_open(cls, path: Path) -> float:
        # 0..1 confidence, from the name alone: this runs for every dropped file.
        return 1.0 if path.suffix.lower() == ".toybin" else 0.0

    def open(self, path: Path, config: dict) -> None:
        self._path = path

    def channels(self) -> list[ChannelInfo]:
        return [ChannelInfo(name="value", unit="V", dtype="float64", rate_hz=None)]

    def read_chunks(self, ch: str) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        records = np.memmap(self._path, dtype=self._dtype, mode="r")
        for start in range(0, len(records), 1_000_000):
            block = records[start : start + 1_000_000]
            yield np.asarray(block["time"]), np.asarray(block["value"])
```

The rules `read_chunks` must keep:

- Each chunk is two one-dimensional arrays of the same length: times in seconds, and values.
- Times never go backwards, within a chunk or across chunks. Sort the input, or raise
  `NonMonotonicTimeError`.
- NaN stays NaN. A sentinel such as `-9999` becomes NaN only when the user's config says so.
- AvialSync builds the cache, the decimation and the gap detection. A loader only reads.

`open()` and `read_chunks()` run on a worker thread and must not touch Qt.

Save it as `toy_binary.py` in the plugins folder (see [Installing and testing](installing-and-testing.md)).
It then appears in the import review as **Toy Binary**. Override `display_name()` to name the kind of
data rather than the rig: `"Wheel Encoder"`, not `"My Lab Wheel"`.

## Optional extras

`ChannelInfo` also takes `shown=False` (start hidden), `description` (inspector text) and `trigger`
([Trigger lines](trigger-lines.md)). A loader may also define `messages()` for notes the file
carries, and `read_all_chunks()` to parse a one-pass format once instead of once per channel; both are
described in the [plugin reference](../plugin-guide.md).
