"""Report the version of running code even when editable metadata is stale."""

from __future__ import annotations

import runpy
from importlib import metadata
from types import SimpleNamespace

import pytest

from avialsync import __version__
from avialsync.core import artifact_provenance
from avialsync.ui import about


@pytest.mark.parametrize("installed", ["0.0.1", None])
def test_about_reports_the_running_version(monkeypatch, installed: str | None) -> None:
    """Reinstalling editable metadata is not required to label running code."""
    original = metadata.version

    def package_version(name: str) -> str:
        if name != "avialsync":
            return original(name)
        if installed is None:
            raise metadata.PackageNotFoundError(name)
        return installed

    monkeypatch.setattr(metadata, "version", package_version)
    assert about.version_report().splitlines()[0] == f"AvialSync {__version__}"


def test_export_provenance_reports_the_running_version(monkeypatch) -> None:
    monkeypatch.setattr(metadata, "distribution", lambda _name: SimpleNamespace(version="0.0.1"))
    assert artifact_provenance.record("snapshot")["software"] == f"avialsync {__version__}"


def test_documentation_reports_the_running_version(monkeypatch) -> None:
    monkeypatch.setattr(metadata, "distribution", lambda _name: SimpleNamespace(version="0.0.1"))
    assert runpy.run_path("docs/conf.py")["release"] == __version__
