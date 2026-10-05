"""The documentation screenshot tools never touch the operator's own state.

They build and close a real ``MainWindow``, and closing a window that holds
anything writes the recovery snapshot unconditionally (D-089). Without a
sandbox, photographing the docs replaced the operator's unsaved-work snapshot
with a synthetic session and wrote geometry and preferences into their
installed application (INTERFACE_DESIGN_PLAN F-36). Checked in a fresh
interpreter, because the test suite's own sandbox would hide a missing one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

_PROBE = """
import json, sys
sys.path.insert(0, sys.argv[1])
import screenshot_kit
from avialsync.ui.app_settings import app_settings
from avialsync.core.cache import cache_root
from avialsync.ui import recovery
print(json.dumps({
    "sandbox": str(screenshot_kit.USER_STATE_SANDBOX),
    "settings": app_settings().fileName(),
    "recovery": str(recovery.recovery_dir()),
    "cache": str(cache_root()),
}))
"""


def test_importing_the_kit_sandboxes_settings_recovery_and_cache() -> None:
    env = {key: value for key, value in os.environ.items() if key != "AVIALSYNC_CACHE_DIR"}
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, str(REPOSITORY_ROOT / "tools")],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=60,
    )
    paths = json.loads(result.stdout.strip().splitlines()[-1])
    sandbox = Path(paths["sandbox"]).resolve()

    assert sandbox.is_relative_to(Path(tempfile.gettempdir()).resolve())
    for key in ("settings", "recovery", "cache"):
        assert Path(paths[key]).resolve().is_relative_to(sandbox), (key, paths[key])
