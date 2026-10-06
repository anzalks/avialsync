"""Read-only storage adapters for local and streamed NWB containers.

The NWB scanners use the small group/dataset API shared by h5py and Zarr.
Only this module chooses a storage backend; samples remain sliced by nwb_read.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import h5py

from avialsync.core.errors import FileUnreadableError

LINK_SUFFIX = ".nwb-link"


def is_dataset(value: Any) -> bool:
    """Whether *value* is an HDF5 or Zarr array."""
    if isinstance(value, h5py.Dataset):
        return True
    try:
        import zarr

        return isinstance(value, zarr.Array)
    except ImportError:
        return False


def is_group(value: Any) -> bool:
    """Whether *value* is an HDF5 or Zarr group."""
    if isinstance(value, h5py.Group):
        return True
    try:
        import zarr

        return isinstance(value, zarr.Group)
    except ImportError:
        return False


def children(group: Any) -> list[Any]:
    """Return a group's children without requiring Zarr's missing values()."""
    return [group[key] for key in group.keys()]


def remote_url(path: Path) -> str | None:
    """Return the URL in an NWB link file, rejecting malformed links."""
    if not path.name.endswith(LINK_SUFFIX):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        url = payload["url"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise FileUnreadableError(f"{path.name} is not a valid NWB link ({error}).") from error
    if not isinstance(url, str) or not valid_dandi_url(url):
        raise FileUnreadableError(f"{path.name} does not contain a DANDI NWB asset URL.")
    return url


def source_label(path: Path) -> str:
    """Use an asset ID, rather than the local link's hash, in the session UI."""
    url = remote_url(path)
    if url is None:
        return path.name
    parts = [part for part in urlparse(url).path.split("/") if part]
    asset = parts[-2] if parts and parts[-1] == "download" else parts[-1]
    return f"DANDI {asset[:12]}"


def valid_dandi_url(url: str) -> bool:
    """Accept a DANDI asset download or its public S3 content URL."""
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname
        in {
            "api.dandiarchive.org",
            "dandiarchive.s3.amazonaws.com",
        }
        and (
            "/download/" in parsed.path
            or parsed.path.lower().endswith(".nwb")
            or (
                parsed.hostname == "dandiarchive.s3.amazonaws.com"
                and parsed.path.startswith(("/blobs/", "/zarr/"))
            )
        )
    )


def create_remote_link(url: str) -> Path:
    """Persist a stream address outside the derived-data cache for session restore."""
    if not valid_dandi_url(url):
        raise FileUnreadableError("Enter a DANDI NWB asset download or S3 content URL.")
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    folder = base / "avialsync" / "remote"
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    target = folder / f"dandi-{digest}{LINK_SUFFIX}"
    if not target.exists():
        target.write_text(json.dumps({"url": url}) + "\n", encoding="utf-8")
    return target


class ZarrFile:
    """Give a Zarr root the context and key API of a read-only h5py file."""

    def __init__(self, root: Any) -> None:
        self._root = root
        self.attrs = root.attrs

    @property
    def root(self) -> Any:
        """The group exposed to the shared structural scanner."""
        return self._root

    def __enter__(self) -> ZarrFile:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def __getitem__(self, key: str) -> Any:
        return self._root[key]

    def __contains__(self, key: str) -> bool:
        return key in self._root

    def get(self, key: str) -> Any:
        return self._root.get(key)


class RemoteFile:
    """Close both HDF5 and its range-reading HTTP handle after each operation."""

    def __init__(self, handle: h5py.File, stream: Any) -> None:
        self._handle = handle
        self._stream = stream

    @property
    def root(self) -> h5py.File:
        """The HDF5 file exposed to the shared structural scanner."""
        return self._handle

    def __enter__(self) -> h5py.File:
        return self._handle

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        """Release HDF5 before its backing range stream."""
        try:
            self._handle.close()
        finally:
            self._stream.close()


def is_remote_zarr(url: str) -> bool:
    """Whether a DANDI content URL names a Zarr object store."""
    parsed = urlparse(url)
    return parsed.path.startswith("/zarr/") or ".nwb.zarr" in parsed.path.lower()


def open_zarr(path: Path | str) -> ZarrFile:
    """Open an NWB Zarr v2 or v3 store without materialising its arrays.

    Older hdmf-zarr stores wrote numeric fill values for object arrays. Zarr 3
    rejects that old metadata even though PyNWB wrote it. Correct only that
    metadata in memory at the store boundary; the recording stays untouched.
    """
    try:
        import zarr
        from zarr.storage import FsspecStore, LocalStore, WrapperStore

        class _NWBStore(WrapperStore):
            async def get(self, key: str, prototype: Any, byte_range: Any = None) -> Any:
                value = await super().get(key, prototype, byte_range)
                if key != ".zmetadata" or value is None:
                    return value
                metadata = json.loads(value.to_bytes())
                for item in metadata.get("metadata", {}).values():
                    if (
                        isinstance(item, dict)
                        and item.get("dtype") == "|O"
                        and item.get("fill_value") == 0
                    ):
                        item["fill_value"] = ""
                return prototype.buffer.from_bytes(json.dumps(metadata).encode("utf-8"))

        location = str(path)
        base = (
            FsspecStore.from_url(location, read_only=True)
            if location.startswith(("https://", "http://"))
            else LocalStore(location, read_only=True)
        )
        return ZarrFile(zarr.open_group(_NWBStore(base), mode="r"))
    except Exception as error:  # noqa: BLE001 - optional Zarr backend and remote store errors
        raise FileUnreadableError(f"{path} could not be opened as NWB Zarr ({error}).") from error


def open_remote(path: Path) -> RemoteFile:
    """Open a DANDI HDF5 asset with HTTP range reads, not a full download."""
    url = remote_url(path)
    assert url is not None
    try:
        import fsspec  # type: ignore[import-untyped]  # fsspec has no py.typed marker

        stream = fsspec.open(url, "rb", block_size=256 * 1024).open()
        try:
            handle = h5py.File(stream, "r")
        except BaseException:
            stream.close()
            raise
        return RemoteFile(handle, stream)
    except Exception as error:  # noqa: BLE001 - remote filesystem and HDF5 plugin boundary
        raise FileUnreadableError(f"DANDI asset could not be streamed ({error}).") from error
