"""Regression checks for the PyInstaller specification."""

from pathlib import Path


def test_spec_resolves_the_project_root_from_packaging_directory() -> None:
    """SPECPATH is the packaging directory, not the spec-file path."""
    spec = Path("packaging/avialview.spec").read_text(encoding="utf-8")

    assert "project_root = Path(SPECPATH).parent" in spec
    assert "project_root = Path(SPECPATH).parent.parent" not in spec
    assert "project_root / 'src' / 'avialview' / '__main__.py'" in spec
