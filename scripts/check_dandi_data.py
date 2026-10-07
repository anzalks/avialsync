"""Inspect an NWB file or DANDI asset without downloading the full recording.

Run with ``conda run -n avialsync python scripts/check_dandi_data.py PATH_OR_URL``.
Add ``--compare-pynwb`` when PyNWB is installed to check its object reader too.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from avialsync.loaders import nwb_format, nwb_read
from avialsync.loaders.nwb_storage import valid_dandi_url


def inspect(path: Path) -> None:
    """Print storage metadata and bounded sample probes for each series."""
    contents = nwb_format.scan(path)
    print(f"NWB {contents.version}; {len(contents.series)} series")
    print(f"Reference epoch: {contents.reference_epoch}")
    with nwb_format.open_file(path) as handle:
        for info in contents.series:
            print(f"{info.path}: {info.kind}, {info.length} samples, {info.dtype}")
            if info.length and info.kind in {"signal", "imaging", "annotation"}:
                first = nwb_read.read_times(handle, info, 0, 1)[0]
                last = nwb_read.read_times(handle, info, info.length - 1, info.length)[0]
                print(f"  Time: {first:.6f}–{last:.6f} s")
    for reason in contents.declined:
        print(f"Skipped: {reason}")


def compare_pynwb(path: Path) -> None:
    """Read the same HDF5 file through PyNWB when explicitly requested."""
    from pynwb import NWBHDF5IO

    with nwb_format.open_file(path) as handle:
        with NWBHDF5IO(file=handle, load_namespaces=False) as io:
            file = io.read()
            print(f"PyNWB: {len(file.acquisition)} acquisition objects")


def main() -> int:
    """Inspect one local file/store or public DANDI content URL."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Local .nwb/.nwb.zarr path or DANDI asset URL")
    parser.add_argument("--compare-pynwb", action="store_true")
    args = parser.parse_args()
    source = str(args.source)
    if source.startswith("https://"):
        if not valid_dandi_url(source):
            parser.error("Enter a DANDI NWB asset download or S3 content URL")
        with tempfile.TemporaryDirectory(prefix="avialsync-nwb-check-") as temporary:
            path = Path(temporary) / "asset.nwb-link"
            path.write_text(json.dumps({"url": source}), encoding="utf-8")
            inspect(path)
            if args.compare_pynwb:
                compare_pynwb(path)
    else:
        path = Path(source).expanduser()
        inspect(path)
        if args.compare_pynwb:
            compare_pynwb(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
