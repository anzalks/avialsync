"""Unit coverage for the local release-preparation helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _release_tool():
    path = Path("tools/prepare_release.py")
    spec = importlib.util.spec_from_file_location("prepare_release", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("version", ["0.1.0", "0.1.0b1", "1.2rc3", "2.0.0.dev1"])
def test_validate_version_accepts_canonical_public_versions(version: str) -> None:
    """The helper accepts normal final and prerelease version forms."""
    _release_tool().validate_version(version)


@pytest.mark.parametrize("version", ["v0.1.0", "1.0-beta1", "01.0", "1.0+local"])
def test_validate_version_rejects_ambiguous_or_local_versions(version: str) -> None:
    """Tags and PyPI metadata must use a single canonical version spelling."""
    tool = _release_tool()
    with pytest.raises(tool.ReleasePreparationError):
        tool.validate_version(version)


def test_replace_declared_version_updates_only_the_expected_declaration(tmp_path: Path) -> None:
    """Version authority updates cannot silently replace unrelated quoted text."""
    tool = _release_tool()
    metadata = tmp_path / "pyproject.toml"
    metadata.write_text('[project]\nversion = "0.0.1"\n', encoding="utf-8")

    tool.replace_declared_version(metadata, tool.PYPROJECT_VERSION_PATTERN, "0.1.0b1")

    assert metadata.read_text(encoding="utf-8") == '[project]\nversion = "0.1.0b1"\n'
