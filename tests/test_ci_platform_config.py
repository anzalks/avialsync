"""Regression checks for the Qt platform selection in CI."""

from pathlib import Path


def test_windows_ci_uses_native_qt_platform_backend() -> None:
    """The X11-oriented offscreen plugin must never be forced on Windows."""
    workflow_path = Path(".github/workflows/ci.yml")
    workflow = workflow_path.read_text(encoding="utf-8")

    assert "name: Run Tests (native Windows Qt backend)" in workflow
    assert "if: runner.os == 'Windows'" in workflow
    assert "QT_QPA_PLATFORM: windows" in workflow
