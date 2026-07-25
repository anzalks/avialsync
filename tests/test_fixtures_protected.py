"""Regression guard: make_fixtures._clean_generated() must never delete permanent fixtures."""

from __future__ import annotations

import pathlib


def test_clean_generated_preserves_kcx_files(tmp_path: pathlib.Path) -> None:
    """_clean_generated() deletes generated subdirs but leaves .kcx files intact."""
    from tools.make_fixtures import _GENERATED_SUBDIRS, _clean_generated

    # Create permanent .kcx fixtures
    for name in ("session_v1.kcx", "session_v2.kcx", "session_v3.kcx"):
        (tmp_path / name).write_text('{"version": 1}')

    # Create generated subdirectories
    for subdir in _GENERATED_SUBDIRS:
        p = tmp_path / subdir
        p.mkdir()
        (p / "dummy.dat").write_bytes(b"\x00")

    _clean_generated(tmp_path)

    # All .kcx files must survive
    for name in ("session_v1.kcx", "session_v2.kcx", "session_v3.kcx"):
        assert (tmp_path / name).exists(), f"{name} was deleted by _clean_generated"

    # All generated subdirs must be gone
    for subdir in _GENERATED_SUBDIRS:
        assert not (tmp_path / subdir).exists(), f"{subdir} was not cleaned"


def test_clean_generated_is_idempotent(tmp_path: pathlib.Path) -> None:
    """Running _clean_generated twice must not error (no dirs to remove second time)."""
    from tools.make_fixtures import _clean_generated

    (tmp_path / "session_v1.kcx").write_text('{"version": 1}')

    _clean_generated(tmp_path)
    _clean_generated(tmp_path)  # must not raise

    assert (tmp_path / "session_v1.kcx").exists()


def test_permanent_fixtures_exist_in_repo() -> None:
    """session_v1.kcx, session_v2.kcx, session_v3.kcx must be committed in tests/fixtures/."""
    fixtures = pathlib.Path(__file__).parent / "fixtures"
    for name in ("session_v1.kcx", "session_v2.kcx", "session_v3.kcx"):
        path = fixtures / name
        assert path.exists(), (
            f"{name} missing from tests/fixtures/ — commit it or run: python tools/make_fixtures.py"
        )
        assert path.stat().st_size > 0, f"{name} is empty"
