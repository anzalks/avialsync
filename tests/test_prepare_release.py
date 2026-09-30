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


def _copy_authorities(tool, tmp_path: Path) -> Path:
    """Copy the real version-bearing files, at their real relative paths, into *tmp_path*."""
    for path, _ in tool.version_authorities(Path.cwd()):
        target = tmp_path / path.relative_to(Path.cwd())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def test_every_pattern_matches_exactly_once_in_the_real_file() -> None:
    """A reformatted file must fail here, not half-way through a release."""
    tool = _release_tool()
    for path, pattern in tool.version_authorities(Path.cwd()):
        tool.replaced_version_text(path, pattern, "9.9.9")


def test_update_rewrites_every_authority_to_one_version(tmp_path: Path) -> None:
    """After a bump the four files agree, whatever they said before."""
    tool = _release_tool()
    root = _copy_authorities(tool, tmp_path)

    updated = tool.update_version_authorities(root, "0.2.0b1")

    assert len(updated) == 4
    for path, pattern in tool.version_authorities(root):
        assert len(pattern.findall(path.read_text(encoding="utf-8"))) == 1
        assert '"0.2.0b1"' in path.read_text(encoding="utf-8"), path


def test_update_touches_nothing_when_one_authority_cannot_be_matched(tmp_path: Path) -> None:
    """A failure part-way must not leave the files naming different versions."""
    tool = _release_tool()
    root = _copy_authorities(tool, tmp_path)
    recipe = root / "packaging/conda/meta.yaml"
    recipe.write_text("package:\n  name: avialsync\n", encoding="utf-8")
    before = {path: path.read_text(encoding="utf-8") for path, _ in tool.version_authorities(root)}

    with pytest.raises(tool.ReleasePreparationError):
        tool.update_version_authorities(root, "0.2.0b1")

    assert {path: path.read_text(encoding="utf-8") for path in before} == before
