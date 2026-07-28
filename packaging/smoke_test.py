"""Launch a built AvialView bundle headlessly and require a clean shutdown."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def bundle_executable(bundle_dir: Path, platform: str = sys.platform) -> Path:
    """Return the platform executable in a PyInstaller one-directory bundle."""
    executable_name = "avialview.exe" if platform == "win32" else "avialview"
    candidates = (
        bundle_dir / executable_name,
        bundle_dir / "AvialView.app" / "Contents" / "MacOS" / "avialview",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"No AvialView executable found in {bundle_dir}. Expected {executable_name}."
    )


def smoke_bundle(bundle_dir: Path, timeout: float = 20.0, *, demo: bool = False) -> None:
    """Require the bundled Qt application to construct and close successfully."""
    executable = bundle_executable(bundle_dir)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    try:
        with tempfile.TemporaryDirectory(
            prefix=".avialview-smoke-", dir=bundle_dir.parent
        ) as demo_dir:
            command = [str(executable)]
            if demo:
                command.append("demo")
                env["AVIALVIEW_DEMO_DIR"] = demo_dir
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
            f"AvialView bundle did not close within {timeout:.0f} seconds"
        ) from error
    except subprocess.CalledProcessError as error:
        details = (error.stderr or error.stdout or "no diagnostic output").strip()
        raise RuntimeError(f"AvialView bundle startup failed: {details}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    smoke_bundle(args.bundle_dir.resolve(), args.timeout, demo=args.demo)
    print("AvialView bundle smoke test passed")


if __name__ == "__main__":
    main()
