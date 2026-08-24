"""Regression checks for the shared cross-platform CI and release contract."""

import ast
from pathlib import Path

import yaml

WORKFLOW_PATHS = (
    Path(".github/workflows/ci.yml"),
    Path(".github/workflows/release.yml"),
)
TEST_COMMAND = (
    "pytest --maxfail=5 -q --durations=20 --timeout=60 --timeout-method=thread"
    " --ignore=tests/benchmarks"
)
#: Bump deliberately, never incidentally — this is what release installers bundle.
WINDOWS_FFMPEG_VERSION = "9.0.0"


def test_cross_platform_quality_workflows_share_headless_media_contract() -> None:
    """CI and tag quality runs must exercise the same supported media boundary."""
    video_pane_path = Path("src/avialsync/ui/video_pane.py")
    video_pane = video_pane_path.read_text(encoding="utf-8")

    for workflow_path in WORKFLOW_PATHS:
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "QT_QPA_PLATFORM: offscreen" in workflow
        assert "QT_QPA_PLATFORM: windows" not in workflow
        # Pinned images: a floating label already broke this pipeline once,
        # when an image bump renamed fuse to libfuse2t64.
        assert "os: [ubuntu-24.04, macos-15, windows-2022]" in workflow
        assert "-latest" not in workflow
        assert 'python-version: ["3.11", "3.12"]' in workflow
        # FFmpeg encodes the fixtures; libegl1 is Qt's Linux floor. No video
        # library is installed on any platform any more — the decoder arrives
        # with the wheel (D-075), and the probe below proves it did.
        assert "ffmpeg libegl1" in workflow
        assert "brew install ffmpeg" in workflow
        assert "import av" in workflow
        # Comments are stripped first so the change can be *explained* in the
        # workflow without the explanation tripping the guard.
        instructions = "\n".join(
            line for line in workflow.splitlines() if not line.strip().startswith("#")
        )
        assert "mpv" not in instructions, (
            "CI must not install, fetch, or import a video library again: PyAV "
            "carries its own FFmpeg, so there is no DLL to pin (D-075)"
        )
        assert TEST_COMMAND in workflow
        assert "actions/checkout@v5" in workflow
        assert "actions/setup-python@v6" in workflow

    # The pane used to fork three ways — a Qt OpenGL render context on
    # Windows/macOS, native `wid` embedding on Linux, and a `vo=null` headless
    # case for CI — so "does it work on this OS" was a real question and CI's
    # job was to answer it on all three. D-075 removed the fork: every platform
    # decodes to a QImage and blits it, headless or not. The guard is now that
    # the fork stays gone, because reintroducing one would quietly restore a
    # class of bug CI can only catch after the fact (AGENTS.md rule 6).
    # Checked against the parsed module rather than its text, so the rule can
    # be *described* in a docstring without tripping the guard that enforces it.
    tree = ast.parse(video_pane)
    platform_reads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "platform"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    ]
    assert not platform_reads, (
        "video_pane.py must not branch on the platform: rendering is one path "
        f"on every OS since D-075 (line {platform_reads[0].lineno if platform_reads else 0})"
    )

    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert "mpv" not in imported
    assert not any(name.startswith("PySide6.QtOpenGL") for name in imported)


def test_release_bundles_stage_no_media_runtime() -> None:
    """Installers carry no separately-staged media runtime (D-075).

    Every media binary now arrives inside PyAV's wheel and is collected by
    PyInstaller's `av` hook, so the bundling job downloads nothing, verifies no
    checksum, and copies no libraries. The staging script is deleted; asserting
    its absence is what keeps a supply-chain step from returning quietly.
    """
    release_workflow = WORKFLOW_PATHS[1].read_text(encoding="utf-8")

    assert "fetch_media_libs" not in release_workflow
    assert "--media-root" not in release_workflow
    assert "sourceforge.net" not in release_workflow


def test_windows_ffmpeg_is_pinned_everywhere_it_is_installed() -> None:
    """An unpinned ffmpeg is both a CI flake and an unreproducible installer.

    Chocolatey moved 8.1.2 -> 9.0.0 between two runs an hour apart; ffmpeg 9
    removed ``-vsync`` and both Windows jobs went red with no commit in
    between. Re-running the last green run at the same SHA reproduced it.

    FFmpeg is now only a *build-time* dependency: it encodes the test fixtures
    that ``tools/make_fixtures.py`` generates. Nothing is staged into a bundle
    from it any more (D-075), so an unpinned version is a CI flake rather than
    an unreproducible installer — still worth pinning, for a smaller reason
    than before.
    """
    for workflow_path in WORKFLOW_PATHS:
        workflow = workflow_path.read_text(encoding="utf-8")
        for line in workflow.splitlines():
            stripped = line.strip()
            if not stripped.startswith("choco install") or "ffmpeg" not in stripped:
                continue
            assert f"--version={WINDOWS_FFMPEG_VERSION}" in stripped, (
                f"{workflow_path}: unpinned ffmpeg install: {stripped}"
            )


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


def test_only_a_version_tag_starts_a_release() -> None:
    """Pushing a branch must never publish, and neither must a non-version tag.

    workflow_dispatch can be launched from any ref, so the tag requirement is
    re-checked inside the job rather than left to the trigger alone.
    """
    release_workflow = WORKFLOW_PATHS[1].read_text(encoding="utf-8")

    assert 'tags: ["v[0-9]*"]' in release_workflow
    assert "branches:" not in release_workflow
    assert "refs/tags/*) ;;" in release_workflow


def test_every_release_job_is_gated_on_the_ref_check() -> None:
    """No job may build or publish without the tag having been verified."""
    workflow = yaml.safe_load(WORKFLOW_PATHS[1].read_text(encoding="utf-8"))
    jobs = workflow["jobs"]

    def gated(name: str, seen: frozenset[str] = frozenset()) -> bool:
        """Return whether *name* is transitively downstream of the gate."""
        needs = jobs[name].get("needs") or []
        needs = [needs] if isinstance(needs, str) else needs
        return bool(needs) and all(
            need == "verify_release_ref" or gated(need, seen | {name}) for need in needs
        )

    ungated = [name for name in jobs if name != "verify_release_ref" and not gated(name)]
    assert not ungated, f"These run without the tag being verified: {ungated}"


def test_release_tag_must_agree_with_the_declared_version() -> None:
    """PyPI and the GitHub release must not publish two different versions.

    Nothing tied the tag to pyproject.toml, so tagging v0.1.0b5 against a tree
    still declaring 0.1.0b4 would have uploaded the wrong version under the
    right tag, only failing once the artifacts were already public.
    """
    release_workflow = WORKFLOW_PATHS[1].read_text(encoding="utf-8")

    assert "Require the tag to match the declared package version" in release_workflow
    assert 'project["project"]["version"]' in release_workflow
    assert "src/avialsync/__init__.py" in release_workflow


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
    spec = Path("packaging/avialsync.spec").read_text(encoding="utf-8")
    make_dmg = Path("packaging/macos/make_dmg.sh").read_text(encoding="utf-8")

    assert "name='AvialSync.app'" in spec
    assert "bundle_identifier=" in spec
    assert "make_dmg.sh dist/AvialSync.app" in release_workflow
    assert '*.app) cp -R "$bundle_dir" "$staging_dir/AvialSync.app"' in make_dmg
    assert "needs: verify_release_ref" in release_workflow


def test_signing_is_wired_but_optional() -> None:
    """Signing must run when secrets exist and be skipped, not fail, when not.

    BLUEPRINT.md Phase 5 asks for signing "stubbed behind secrets-present
    conditionals": forks and an unconfigured repository must still produce a
    release, unsigned.
    """
    release_workflow = WORKFLOW_PATHS[1].read_text(encoding="utf-8")

    for guard in (
        "runner.os == 'Windows' && env.WINDOWS_CERTIFICATE_PFX != ''",
        "runner.os == 'macOS' && env.MACOS_CERTIFICATE_P12 != ''",
        "runner.os == 'macOS' && env.MACOS_NOTARY_APPLE_ID != ''",
    ):
        assert guard in release_workflow, guard
    assert "sign.ps1 -Path installer-output/AvialSync-Setup.exe" in release_workflow
    assert "sign_notarize.sh sign dist/AvialSync.app" in release_workflow
    assert "sign_notarize.sh notarize installer-output/AvialSync.dmg" in release_workflow


def test_macos_is_signed_before_the_image_is_built_and_notarized_after() -> None:
    """Order is load-bearing: the image must carry the signed .app.

    Notarization then has a Developer ID signature to accept, and stapling
    applies to the artifact users download.
    """
    release_workflow = WORKFLOW_PATHS[1].read_text(encoding="utf-8")

    sign = release_workflow.index("sign_notarize.sh sign dist/AvialSync.app")
    build = release_workflow.index("make_dmg.sh dist/AvialSync.app")
    notarize = release_workflow.index("sign_notarize.sh notarize")

    assert sign < build < notarize


def test_signing_scripts_refuse_to_run_without_credentials() -> None:
    """A half-configured secret must stop the release, not ship unsigned."""
    notarize = Path("packaging/macos/sign_notarize.sh").read_text(encoding="utf-8")
    windows = Path("packaging/windows/sign.ps1").read_text(encoding="utf-8")

    assert "refusing to continue" in notarize
    assert "refusing to continue" in windows
    # Signatures that are not timestamped expire with the certificate and make
    # already-shipped installers start warning.
    assert "--timestamp" in notarize
    assert "/tr $TimestampUrl" in windows


#: Characters Windows forbids in a path component. All are legal on POSIX, which
#: is exactly why one reaches a commit without anybody noticing.
_WINDOWS_ILLEGAL = '<>:"|?*'

#: Names Windows reserves whatever the extension, inherited from DOS devices.
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{n}" for n in range(1, 10)),
    *(f"LPT{n}" for n in range(1, 10)),
}


def test_every_tracked_path_can_exist_on_windows() -> None:
    """A path Windows cannot create fails the job in checkout, before any test.

    This is not a style rule. A stray macOS Finder alias — ``Users:.fileloc``,
    whose name embeds the path it points at, colon included — was committed and
    took down both Windows jobs at ``actions/checkout``: nothing was built, no
    test ran, and the log points at the checkout action rather than at anything
    in the repository. The other five matrix jobs passed, so the failure reads
    like flaky infrastructure.

    Guarding it here rather than trusting ``.gitignore``: an ignore rule only
    covers the patterns somebody thought of, and this one is cheap and total.
    """
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")

    offenders: list[str] = []
    for path in filter(None, tracked):
        for part in Path(path).parts:
            if any(character in part for character in _WINDOWS_ILLEGAL):
                offenders.append(f"{path} (illegal character)")
            elif part.rstrip(". ") != part:
                offenders.append(f"{path} (trailing dot or space)")
            elif part.split(".")[0].upper() in _WINDOWS_RESERVED:
                offenders.append(f"{path} (reserved device name)")

    assert not offenders, (
        "These tracked paths cannot be checked out on Windows, so the Windows "
        "CI jobs will fail before running anything:\n  " + "\n  ".join(sorted(set(offenders)))
    )


def test_no_python_in_the_repository_imports_mpv() -> None:
    """libmpv is gone from the tests too, not only from the product (D-086).

    The benchmark suite kept a libmpv comparison arm long after the application
    stopped using it, so ``import mpv`` and a ``find_library`` patch survived in
    tree — opt-in, but installable, and the only reason a second video backend
    still had to exist anywhere. Its measurements are a recorded table in
    BLUEPRINT.md; re-deriving them was never worth keeping a whole backend
    reachable for.

    Checked against each parsed module rather than its text, so history can
    still be *described* in a docstring — as this one does — without tripping
    the guard that enforces it.
    """
    offenders: list[str] = []
    for source in (*Path("src").rglob("*.py"), *Path("tests").rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        if "mpv" in imported:
            offenders.append(str(source))

    assert not offenders, (
        f"PyAV is the only video backend (D-075, D-086); these import mpv: {offenders}"
    )


def test_the_scrub_benchmark_measures_one_backend() -> None:
    """The seek benchmark must not grow a second backend back (D-086).

    A comparison arm is how the last one persisted: gated behind an environment
    variable, skipped by default, and therefore never noticed. An env-var gate
    naming a video library is the shape to reject, not the import alone.
    """
    benchmark = Path("tests/benchmarks/test_seek_backends.py").read_text(encoding="utf-8")
    instructions = "\n".join(
        line for line in benchmark.splitlines() if not line.strip().startswith("#")
    )
    assert "AVIALSYNC_BENCH_LIBMPV" not in instructions
    assert "find_library" not in instructions
