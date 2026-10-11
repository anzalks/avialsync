"""Launch a built AvialSync bundle headlessly and require a clean shutdown."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def bundle_executable(bundle_dir: Path, platform: str = sys.platform) -> Path:
    """Return the platform executable in a PyInstaller one-directory bundle."""
    executable_name = "avialsync.exe" if platform == "win32" else "avialsync"
    candidates = (
        bundle_dir / executable_name,
        bundle_dir / "AvialSync.app" / "Contents" / "MacOS" / "avialsync",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"No AvialSync executable found in {bundle_dir}. Expected {executable_name}."
    )


def smoke_bundle(
    bundle_dir: Path,
    timeout: float = 20.0,
    *,
    demo: bool = False,
    qt_platform: str = "offscreen",
) -> None:
    """Require the bundled Qt application to construct and close successfully.

    ``qt_platform`` selects the Qt platform plugin. The default keeps every
    runner headless, but "offscreen" proves nothing about the plugin a user's
    desktop actually loads: a bundle can pass headlessly and still fail to open
    a window for want of the xcb plugin or its libraries. Release CI runs this
    a second time under a real display server with "xcb".
    """
    executable = bundle_executable(bundle_dir)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = qt_platform
    # Let the application give up first. Its own deadline reports what it was
    # still waiting for ("videos=4/4, channels=6/42"); being killed from out
    # here reports only that 120 seconds passed, which is what made an
    # unsatisfiable gate take a bisect to diagnose.
    env["AVIALSYNC_SMOKE_DEADLINE_S"] = f"{max(5.0, timeout - 10.0):.1f}"
    try:
        with tempfile.TemporaryDirectory(
            prefix=".avialsync-smoke-", dir=bundle_dir.parent
        ) as demo_dir:
            command = [str(executable)]
            if demo:
                command.append("demo")
                env["AVIALSYNC_DEMO_DIR"] = demo_dir
            command.append("--smoke-test")
            subprocess.run(
                command,
                cwd=bundle_dir,
                env=env,
                check=True,
                timeout=timeout,
                capture_output=True,
                text=True,
            )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"AvialSync bundle did not close within {timeout:.0f} seconds"
        ) from error
    except subprocess.CalledProcessError as error:
        details = (error.stderr or error.stdout or "no diagnostic output").strip()
        raise RuntimeError(f"AvialSync bundle startup failed: {details}") from error


_DROP_IN_FILE = """
from avialsync.core.source import SessionLayout, SessionSource


class SmokeFileSession(SessionSource):
    @classmethod
    def can_open(cls, path):
        return 0.0

    def scan(self, path, registry):
        return SessionLayout()
"""

_DROP_IN_PACKAGE = """
from .scanner import SmokePackageSession
"""

_DROP_IN_PACKAGE_MODULE = _DROP_IN_FILE.replace("SmokeFileSession", "SmokePackageSession")


def smoke_drop_in_plugins(bundle_dir: Path, timeout: float = 60.0) -> None:
    """Require the installed application to load drop-in plugins from the user's folder.

    The point of the drop-in folder is that an installed copy, which has no
    pip, still takes plugins: one ``.py`` file and one package folder are put
    in a throwaway home directory and the bundle must list both.
    """
    executable = bundle_executable(bundle_dir)
    with tempfile.TemporaryDirectory(prefix=".avialsync-home-", dir=bundle_dir.parent) as home:
        plugins = Path(home) / ".avialsync" / "plugins"
        (plugins / "smoke_package").mkdir(parents=True)
        (plugins / "smoke_file.py").write_text(_DROP_IN_FILE, encoding="utf-8")
        (plugins / "smoke_package" / "__init__.py").write_text(_DROP_IN_PACKAGE, encoding="utf-8")
        (plugins / "smoke_package" / "scanner.py").write_text(
            _DROP_IN_PACKAGE_MODULE, encoding="utf-8"
        )
        report = Path(home) / "plugins.txt"
        env = os.environ.copy()
        env.update({"HOME": home, "USERPROFILE": home})
        subprocess.run(
            [str(executable), "plugin-check", "--output", str(report)],
            cwd=bundle_dir,
            env=env,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
        text = report.read_text(encoding="utf-8") if report.is_file() else "(no report written)"
        for name in ("Smoke File Session", "Smoke Package Session"):
            if name not in text:
                raise RuntimeError(f"The bundle did not load the drop-in {name!r}:\n{text}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument(
        "--qt-platform",
        default="offscreen",
        help="Qt platform plugin to require; 'xcb' needs a running display server.",
    )
    args = parser.parse_args()
    smoke_bundle(
        args.bundle_dir.resolve(),
        args.timeout,
        demo=args.demo,
        qt_platform=args.qt_platform,
    )
    smoke_drop_in_plugins(args.bundle_dir.resolve())
    print(f"AvialSync bundle smoke test passed ({args.qt_platform}, drop-in plugins)")


if __name__ == "__main__":
    main()
