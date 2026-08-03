"""Prepare, validate, commit, tag, and push an AvialView PyPI release.

Run from any directory with ``conda run -n avialview python tools/prepare_release.py 0.1.0b1``.
The GitHub tag workflow remains the only publisher; this helper never uploads a package itself.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

VERSION_PATTERN = re.compile(
    r"^(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*))*(?:(?:a|b|rc)(?:0|[1-9]\d*))?(?:\.post(?:0|[1-9]\d*))?(?:\.dev(?:0|[1-9]\d*))?$"
)
PYPROJECT_VERSION_PATTERN = re.compile(r'^(version\s*=\s*")[^"]+("\s*)$', re.MULTILINE)
MODULE_VERSION_PATTERN = re.compile(r'^(__version__\s*=\s*")[^"]+("\s*)$', re.MULTILINE)
RECIPE_VERSION_PATTERN = re.compile(r'^({% set version = ")[^"]+("\s*%}\s*)$', re.MULTILINE)
IGNORED_DIRTY_PATHS = frozenset({"graphify-out/graph.json"})


class ReleasePreparationError(RuntimeError):
    """Raised when release preparation would create an unsafe tag."""


def repository_root() -> Path:
    """Return the repository root containing this script."""
    return Path(__file__).resolve().parents[1]


def run_command(command: Sequence[str], root: Path, *, capture: bool = False) -> str:
    """Run one argument-list command from the repository root."""
    print("+", " ".join(command))
    result = subprocess.run(
        command,
        cwd=root,
        check=False,
        text=True,
        capture_output=capture,
    )
    if result.returncode:
        message = result.stderr.strip() if capture else f"exit status {result.returncode}"
        raise ReleasePreparationError(f"Command failed: {' '.join(command)} ({message})")
    return result.stdout if capture else ""


def validate_version(version: str) -> None:
    """Require the canonical public PEP 440 versions used by AvialView releases."""
    if not VERSION_PATTERN.fullmatch(version):
        raise ReleasePreparationError(
            f"{version!r} is not a canonical public PEP 440 version; use forms such as 0.1.0b1."
        )


def replace_declared_version(path: Path, pattern: re.Pattern[str], version: str) -> None:
    """Replace precisely one quoted version declaration in *path*."""
    text = path.read_text(encoding="utf-8")
    updated, replacements = pattern.subn(rf"\g<1>{version}\g<2>", text)
    if replacements != 1:
        raise ReleasePreparationError(f"Expected exactly one version declaration in {path}.")
    path.write_text(updated, encoding="utf-8")


def dirty_paths(root: Path) -> set[str]:
    """Return changed paths, excluding the user-managed offline Graphify graph."""
    status = run_command(("git", "status", "--porcelain"), root, capture=True)
    paths = {line[3:] for line in status.splitlines() if len(line) >= 4}
    return paths - IGNORED_DIRTY_PATHS


def ensure_preconditions(root: Path, version: str) -> None:
    """Check branch, worktree, and local/remote tag uniqueness before editing."""
    if dirty_paths(root):
        raise ReleasePreparationError(
            "Commit or discard unrelated worktree changes before a release."
        )
    branch = run_command(("git", "branch", "--show-current"), root, capture=True).strip()
    if branch != "main":
        raise ReleasePreparationError(
            f"Release preparation requires main, not {branch or 'detached HEAD'}."
        )
    tag = f"v{version}"
    if run_command(("git", "tag", "--list", tag), root, capture=True).strip():
        raise ReleasePreparationError(f"Local tag {tag} already exists.")
    remote_tag = run_command(
        ("git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"), root, capture=True
    )
    if remote_tag.strip():
        raise ReleasePreparationError(f"Remote tag {tag} already exists.")


def run_package_preflight(root: Path) -> None:
    """Build into a temporary directory and validate the exact publishable artifacts."""
    with tempfile.TemporaryDirectory(prefix="avialview-release-") as output:
        run_command((sys.executable, "-m", "build", "--outdir", output), root)
        distributions = sorted(Path(output).glob("*"))
        if len(distributions) != 2:
            raise ReleasePreparationError("Expected exactly one wheel and one source distribution.")
        run_command(
            (sys.executable, "-m", "twine", "check", *(str(item) for item in distributions)), root
        )


def prepare_release(root: Path, version: str, *, dry_run: bool) -> None:
    """Update version authorities and optionally create and publish the release tag."""
    validate_version(version)
    ensure_preconditions(root, version)
    if dry_run:
        print(f"Dry run passed: would prepare and push v{version}.")
        return

    replace_declared_version(root / "pyproject.toml", PYPROJECT_VERSION_PATTERN, version)
    replace_declared_version(root / "src/avialview/__init__.py", MODULE_VERSION_PATTERN, version)
    # The conda recipe is a third version authority: left behind, it publishes
    # the previous release's source archive under the new version's name.
    replace_declared_version(root / "packaging/conda/meta.yaml", RECIPE_VERSION_PATTERN, version)
    run_command(
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_packaging_metadata.py",
            "tests/test_conda_recipe.py",
        ),
        root,
    )
    run_package_preflight(root)
    tag = f"v{version}"
    run_command(
        ("git", "add", "pyproject.toml", "src/avialview/__init__.py", "packaging/conda/meta.yaml"),
        root,
    )
    run_command(("git", "commit", "-m", f"chore(release): prepare {version}"), root)
    run_command(("git", "tag", "-a", tag, "-m", f"AvialView {version}"), root)
    run_command(("git", "push", "origin", "main", tag), root)


def main() -> int:
    """Parse command-line arguments and prepare one tag-triggered release."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Canonical PEP 440 version, for example 0.1.0b1.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate without changing or pushing anything."
    )
    args = parser.parse_args()
    try:
        prepare_release(repository_root(), args.version, dry_run=args.dry_run)
    except ReleasePreparationError as error:
        print(f"Release preparation stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
