"""Regression checks for the PyInstaller specification."""

from pathlib import Path


def test_spec_resolves_the_project_root_from_packaging_directory() -> None:
    """SPECPATH is the packaging directory, not the spec-file path."""
    spec = Path("packaging/avialsync.spec").read_text(encoding="utf-8")

    assert "project_root = Path(SPECPATH).parent" in spec
    assert "project_root = Path(SPECPATH).parent.parent" not in spec
    assert "project_root / 'src' / 'avialsync' / '__main__.py'" in spec


def test_spec_stages_no_media_of_its_own() -> None:
    """The bundle carries no separately-staged media runtime (D-075).

    PyInstaller collects PyAV's own shared libraries through the `av` hook, so
    there is nothing left for the spec to stage. This used to read
    `AVIALSYNC_MEDIA_ROOT`, and the hazard it guarded — an unset value quietly
    meaning "the working directory" — is gone with the variable. Asserting the
    absence keeps a staging path from creeping back in without a decision.
    """
    spec = Path("packaging/avialsync.spec").read_text(encoding="utf-8")

    assert "AVIALSYNC_MEDIA_ROOT" not in spec
    assert "media_binaries" not in spec
    assert "binaries=[]," in spec
