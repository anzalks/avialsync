"""DANDI HDF5 assets are read by ranges and can be restored from link files."""

from __future__ import annotations

import json
import re
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import h5py
import numpy as np
import pytest

from avialsync.loaders import nwb_format, nwb_storage
from avialsync.loaders.nwb_loader import NWBLoader
from avialsync.loaders.nwb_stack import NWBStackSource
from tests.nwb_fixture import NWBSpec, write_nwb, write_zarr_nwb


def test_dandi_link_is_persistent_and_rejects_other_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nwb_storage.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    url = "https://api.dandiarchive.org/api/assets/123/download/"
    link = nwb_storage.create_remote_link(url)
    assert link == nwb_storage.create_remote_link(url)
    assert nwb_storage.remote_url(link) == url
    assert not str(link).startswith(str(tmp_path / "cache"))
    assert not nwb_storage.valid_dandi_url("https://example.com/file.nwb")


def test_remote_nwb_reads_ranges_without_downloading_whole_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_nwb(tmp_path / "remote.nwb", NWBSpec(imaging=False, fluorescence=False))
    with h5py.File(path, "a") as handle:
        # Data is deterministic, and much larger than the requested series.
        handle.create_dataset("unused_padding", data=np.arange(2_000_000, dtype=np.int32))
    content = path.read_bytes()

    class RangeHandler(BaseHTTPRequestHandler):
        bytes_sent = 0

        def do_HEAD(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()

        def do_GET(self) -> None:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
            if match is None:
                # A metadata-only GET may read headers to learn the length.
                self.send_response(200)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                return
            start = int(match.group(1))
            stop = min(int(match.group(2) or len(content) - 1), len(content) - 1)
            payload = content[start : stop + 1]
            self.send_response(206)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Content-Range", f"bytes {start}-{stop}/{len(content)}")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(payload)
            type(self).bytes_sent += len(payload)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/remote.nwb"
        monkeypatch.setattr(nwb_storage, "valid_dandi_url", lambda value: value == url)
        link = tmp_path / "remote.nwb-link"
        link.write_text(json.dumps({"url": url}), encoding="utf-8")
        contents = nwb_format.scan(link)
        assert any(info.name == "ElectricalSeries" for info in contents.series)
        loader = NWBLoader()
        loader.open(link, {})
        times, values = next(loader.read_chunks("ElectricalSeries.ch10"))
        assert times[1] == pytest.approx(0.001)
        assert values[1] == pytest.approx(1e-6)
        assert RangeHandler.bytes_sent < len(content) // 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_remote_zarr_reads_consolidated_metadata_and_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zarr

    folder = write_zarr_nwb(tmp_path / "remote.nwb.zarr", zarr_format=2)
    zarr.consolidate_metadata(str(folder))

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/{folder.name}/"
        monkeypatch.setattr(nwb_storage, "valid_dandi_url", lambda value: value == url)
        link = tmp_path / "remote-zarr.nwb-link"
        link.write_text(json.dumps({"url": url}), encoding="utf-8")
        contents = nwb_format.scan(link)
        assert {info.name for info in contents.series} == {"camera", "voltage"}
        loader = NWBLoader()
        loader.open(link, {})
        times, values = next(loader.read_chunks("voltage"))
        assert times[1] == pytest.approx(0.251)
        assert values[1] == pytest.approx(1e-6)
        imaging = NWBStackSource()
        try:
            metadata = imaging.open(link / "acquisition" / "camera", {})
            assert metadata.frame_times.tolist() == pytest.approx([0.5, 0.6, 0.7])
            assert imaging.read_frame(1).shape == (9, 7)
        finally:
            imaging.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
