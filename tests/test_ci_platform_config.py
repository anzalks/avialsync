"""Regression checks for the Qt platform selection in CI."""

from pathlib import Path


def test_windows_ci_uses_headless_video_backend() -> None:
    """Displayless Windows CI must select VideoPane's null-video backend."""
    workflow_path = Path(".github/workflows/ci.yml")
    workflow = workflow_path.read_text(encoding="utf-8")
    video_pane_path = Path("src/avialview/ui/video_pane.py")
    video_pane = video_pane_path.read_text(encoding="utf-8")

    assert "QT_QPA_PLATFORM: offscreen" in workflow
    assert "QT_QPA_PLATFORM: windows" not in workflow
    assert "if is_offscreen:" in video_pane
    assert 'vo="null"' in video_pane
