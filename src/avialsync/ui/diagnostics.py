"""Diagnostics module for AvialSync.

Reports hardware decode capability and disk read speed.

There is no decoder-availability probe any more, and there must not be one
again: PyAV carries its own FFmpeg inside its wheel, so the missing-library case
the old libmpv probe defended against cannot occur — pip either installed the
decoder or the install itself failed (D-075 superseding D-013).
"""

import os
import sys
import tempfile
import threading
import time

from PySide6.QtWidgets import QMessageBox

_STARTUP_DIAGNOSTICS: dict | None = None
_STARTUP_DIAGNOSTICS_LOCK = threading.Lock()


def probe_hwdec() -> dict:
    """Report which hardware decoders FFmpeg was built against.

    Informational only.  Software decode measured 558 fps per camera at
    1440x1080 against the ~180 fps needed to feed three panes, so **hardware
    decode is not required to meet any budget** (D-075).  This is surfaced
    because 12-bit footage is the case where it can still matter, and a user
    should be able to see what their machine offers rather than guess.

    Returns:
        A dict with ``available`` (bool) and ``decoders`` (list of names).
    """
    result: dict = {"available": False, "decoders": []}
    try:
        from av.codec.hwaccel import hwdevices_available

        decoders = sorted(str(device) for device in hwdevices_available())
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        return result
    result["available"] = bool(decoders)
    result["decoders"] = decoders
    return result


def probe_disk_speed(path: str | None = None) -> float:
    """Measure sequential read speed in MB/s.

    Writes and reads a temporary 32 MB file. Returns MB/s.
    """
    size = 32 * 1024 * 1024  # 32 MB
    data = os.urandom(size)

    target_dir = path or tempfile.gettempdir()

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target_dir, prefix=".avv_speed_test_", delete=False
        ) as tmp:
            tmp_path = tmp.name

            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())

        # Drop caches as much as possible (open fresh)
        start = time.monotonic()
        with open(tmp_path, "rb") as f:
            _ = f.read()
        elapsed = time.monotonic() - start

        if elapsed > 0:
            return (size / (1024 * 1024)) / elapsed
        return 0.0
    except OSError:
        return 0.0
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass


def run_startup_diagnostics(parent=None) -> dict:
    """Run startup diagnostics in a background thread.

    Returns a dict that is populated asynchronously — ``hwdec`` and
    ``disk_speed_mbps`` arrive once the thread finishes.
    """
    global _STARTUP_DIAGNOSTICS

    with _STARTUP_DIAGNOSTICS_LOCK:
        if _STARTUP_DIAGNOSTICS is not None:
            return _STARTUP_DIAGNOSTICS

        diag: dict = {
            "hwdec": {},
            "disk_speed_mbps": 0.0,
        }
        _STARTUP_DIAGNOSTICS = diag

    def _probe():
        diag["hwdec"] = probe_hwdec()
        diag["disk_speed_mbps"] = probe_disk_speed()

        if diag["disk_speed_mbps"] < 50.0 and parent is not None:

            def _warn():
                QMessageBox.warning(
                    parent,
                    "Slow Disk Detected",
                    f"Disk: {diag['disk_speed_mbps']:.0f} MB/s\n\n"
                    "Multi-camera scrubbing may be sluggish. "
                    "Consider using an SSD or generating "
                    "proxy files (File → Generate Proxy).",
                )

            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, _warn)

    t = threading.Thread(target=_probe, daemon=True, name="avialsync-diagnostics")
    t.start()

    return diag


def _pyav_version() -> str:
    """Return the installed PyAV version, for a copyable bug report."""
    try:
        import av

        return str(av.__version__)
    except Exception:
        return "unknown"


def format_diagnostics(diag: dict) -> str:
    """Format diagnostics dict as a copyable text block."""
    lines = [
        "AvialSync Diagnostics",
        "=" * 40,
        f"Platform: {sys.platform}",
        f"Python: {sys.version}",
        f"Decoder: PyAV {_pyav_version()}",
    ]

    hwdec = diag.get("hwdec", {})
    if hwdec.get("available"):
        lines.append(f"HW decode: {', '.join(hwdec['decoders'])}")
    else:
        lines.append("HW decode: not available (not required)")

    speed = diag.get("disk_speed_mbps", 0)
    lines.append(f"Disk speed: {speed:.0f} MB/s")

    # A plugin that fails to import looks exactly like one that was never
    # installed — its formats just do not appear. Naming the failure here is the
    # only place the person who installed it will see it.
    plugin_errors = diag.get("plugin_errors") or []
    if plugin_errors:
        lines.append("")
        lines.append(f"Plugins that failed to load ({len(plugin_errors)}):")
        lines.extend(f"  {source}: {reason}" for source, reason in plugin_errors)

    return "\n".join(lines)
