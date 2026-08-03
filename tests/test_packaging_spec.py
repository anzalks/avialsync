"""Regression checks for the PyInstaller specification."""

from pathlib import Path


def test_spec_resolves_the_project_root_from_packaging_directory() -> None:
    """SPECPATH is the packaging directory, not the spec-file path."""
    spec = Path("packaging/avialsync.spec").read_text(encoding="utf-8")

    assert "project_root = Path(SPECPATH).parent" in spec
    assert "project_root = Path(SPECPATH).parent.parent" not in spec
    assert "project_root / 'src' / 'avialsync' / '__main__.py'" in spec


def test_spec_only_includes_explicitly_staged_media() -> None:
    """An unset media path must not accidentally mean the working directory."""
    spec = Path("packaging/avialsync.spec").read_text(encoding="utf-8")

    assert 'media_root_value = os.environ.get("AVIALSYNC_MEDIA_ROOT")' in spec
    assert "if media_root_value:" in spec
    assert 'Path(os.environ.get("AVIALSYNC_MEDIA_ROOT", ""))' not in spec
