"""Regression checks for the shared cross-platform CI and release contract."""

from pathlib import Path

WORKFLOW_PATHS = (
    Path(".github/workflows/ci.yml"),
    Path(".github/workflows/release.yml"),
)
TEST_COMMAND = (
    "pytest -x -q --durations=20 --timeout=60 --timeout-method=thread --ignore=tests/benchmarks"
)
WINDOWS_LIBMPV_SHA256 = "FAA0BE46643CD889A1D816696F60B9962D7BB70E9D9D6E619DA368D0B22211D6"


def test_cross_platform_quality_workflows_share_headless_media_contract() -> None:
    """CI and tag quality runs must exercise the same supported media boundary."""
    video_pane_path = Path("src/avialview/ui/video_pane.py")
    video_pane = video_pane_path.read_text(encoding="utf-8")

    for workflow_path in WORKFLOW_PATHS:
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "QT_QPA_PLATFORM: offscreen" in workflow
        assert "QT_QPA_PLATFORM: windows" not in workflow
        assert "os: [ubuntu-latest, macos-latest, windows-latest]" in workflow
        assert 'python-version: ["3.11", "3.12"]' in workflow
        assert "ffmpeg libmpv2 libegl1" in workflow
        assert "brew install ffmpeg mpv" in workflow
        assert WINDOWS_LIBMPV_SHA256 in workflow
        assert "libmpv import succeeded" in workflow
        assert TEST_COMMAND in workflow
        assert "actions/checkout@v5" in workflow
        assert "actions/setup-python@v6" in workflow

    assert "if is_offscreen:" in video_pane
    assert 'vo="null"' in video_pane
    assert 'sys.platform in ("darwin", "win32")' in video_pane


def test_release_bundle_uses_the_verified_windows_libmpv() -> None:
    """Release installers must not switch to an unverified mpv source on Windows."""
    release_workflow = WORKFLOW_PATHS[1].read_text(encoding="utf-8")

    assert "choco install --no-progress ffmpeg mpv" not in release_workflow
    assert "Join-Path $env:RUNNER_TEMP 'libmpv'" in release_workflow
    assert "C:\\ProgramData\\chocolatey\\lib\\ffmpeg" in release_workflow
    assert '--source "$env:RUNNER_TEMP\\libmpv"' in release_workflow


def test_release_appimage_tool_has_ubuntu_fuse_2_compatibility() -> None:
    """Ubuntu 24.04 must provide AppImageTool's libfuse.so.2 runtime ABI."""
    release_workflow = WORKFLOW_PATHS[1].read_text(encoding="utf-8")

    assert "libfuse2t64" in release_workflow


def test_release_tags_must_reference_main() -> None:
    """A version tag must not release a side branch or detached commit."""
    release_workflow = WORKFLOW_PATHS[1].read_text(encoding="utf-8")

    assert "verify_release_ref:" in release_workflow
    assert "git fetch origin main" in release_workflow
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" origin/main' in release_workflow


def test_release_tag_must_agree_with_the_declared_version() -> None:
    """PyPI and the GitHub release must not publish two different versions.

    Nothing tied the tag to pyproject.toml, so tagging v0.1.0b5 against a tree
    still declaring 0.1.0b4 would have uploaded the wrong version under the
    right tag, only failing once the artifacts were already public.
    """
    release_workflow = WORKFLOW_PATHS[1].read_text(encoding="utf-8")

    assert "Require the tag to match the declared package version" in release_workflow
    assert 'project["project"]["version"]' in release_workflow
    assert "src/avialview/__init__.py" in release_workflow


def test_prerelease_tags_are_not_published_as_stable_releases() -> None:
    """A PEP 440 pre-release tag must be marked as one on the release page."""
    release_workflow = WORKFLOW_PATHS[1].read_text(encoding="utf-8")

    assert "prerelease=" in release_workflow
    assert "prerelease: ${{ needs.verify_release_ref.outputs.prerelease == 'true' }}" in (
        release_workflow
    )
    # An installer-less release is a silent failure, not a successful one.
    assert "fail_on_unmatched_files: true" in release_workflow


def test_macos_disk_image_ships_a_launchable_application() -> None:
    """A one-directory tree is not a macOS app; Finder opens it in Terminal."""
    release_workflow = WORKFLOW_PATHS[1].read_text(encoding="utf-8")
    spec = Path("packaging/avialview.spec").read_text(encoding="utf-8")
    make_dmg = Path("packaging/macos/make_dmg.sh").read_text(encoding="utf-8")

    assert "name='AvialView.app'" in spec
    assert "bundle_identifier=" in spec
    assert "make_dmg.sh dist/AvialView.app" in release_workflow
    assert '*.app) cp -R "$bundle_dir" "$staging_dir/AvialView.app"' in make_dmg
    assert "needs: verify_release_ref" in release_workflow
