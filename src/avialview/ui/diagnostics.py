"""Diagnostics module for AvialView.

Probes for libmpv, hardware decode capability, and disk read speed.
"""

import os
import sys
import tempfile
import threading
import time

from PySide6.QtWidgets import QMessageBox

from avialview.runtime import configure_media_runtime

_LIBMPV_AVAILABLE: bool | None = None
_STARTUP_DIAGNOSTICS: dict | None = None
_STARTUP_DIAGNOSTICS_LOCK = threading.Lock()


def _configure_macos_env() -> None:
    """Configure dyld paths on macOS for Homebrew libmpv."""
    if sys.platform != "darwin":
        return

    import platform

    brew_lib = "/opt/homebrew/lib" if platform.machine() == "arm64" else "/usr/local/lib"
    if os.path.exists(os.path.join(brew_lib, "libmpv.dylib")):
        fallback = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = f"{brew_lib}:{fallback}"


def probe_libmpv(parent=None) -> bool:
    """Probe for libmpv. Show a dialog if missing and return False."""
    global _LIBMPV_AVAILABLE
    if _LIBMPV_AVAILABLE is not None:
        return _LIBMPV_AVAILABLE

    configure_media_runtime()
    _configure_macos_env()

    try:
        import mpv  # noqa: F401

        _LIBMPV_AVAILABLE = True
        return True
    except OSError:
        _LIBMPV_AVAILABLE = False

        msg = QMessageBox(parent)
        msg.setWindowTitle("Missing libmpv")
        msg.setIcon(QMessageBox.Icon.Critical)

        if sys.platform == "darwin":
            install_cmd = "brew install mpv"
        elif sys.platform == "win32":
            install_cmd = (
                "Install AvialView-Setup.exe for the bundled runtime. For a source checkout, "
                "place libmpv-2.dll in the conda environment's Library\\bin directory."
            )
        else:
            install_cmd = "sudo apt install libmpv-dev OR sudo dnf install mpv-libs"

        text = (
            "AvialView requires 'libmpv' for hardware-accelerated "
            "video playback, but it could not be found on your "
            "system.\n\n"
            "Please install it to enable video features:\n"
            f"{install_cmd}"
        )
        msg.setText(text)
        msg.exec()
        return False


def probe_hwdec() -> dict:
    """Probe hardware decode capabilities via mpv.

    Returns a dict with 'available' (bool) and 'decoders' (list).
    """
    result: dict = {"available": False, "decoders": []}

    if not _LIBMPV_AVAILABLE:
        return result

    try:
        import mpv

        player = mpv.MPV(vo="null", hwdec="auto")
        hwdec = player.hwdec
        result["available"] = hwdec not in (None, "no", "")
        if result["available"]:
            result["decoders"] = [str(hwdec)]
        player.terminate()
    except Exception:
        pass

    return result


def probe_disk_speed(path: str | None = None) -> float:
    """Measure sequential read speed in MB/s.

    Writes and reads a temporary 32 MB file. Returns MB/s.
    """
    size = 32 * 1024 * 1024  # 32 MB
    data = os.urandom(size)

    target_dir = path or tempfile.gettempdir()

    try:
        tmp_path = os.path.join(target_dir, ".avv_speed_test")

        with open(tmp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        # Drop caches as much as possible (open fresh)
        start = time.monotonic()
        with open(tmp_path, "rb") as f:
            _ = f.read()
        elapsed = time.monotonic() - start

        os.unlink(tmp_path)

        if elapsed > 0:
            return (size / (1024 * 1024)) / elapsed
        return 0.0
    except Exception:
        return 0.0


def run_startup_diagnostics(parent=None) -> dict:
    """Run startup diagnostics in a background thread.

    Returns a dict that is populated asynchronously — the
    ``libmpv`` key is filled immediately; ``hwdec`` and
    ``disk_speed_mbps`` arrive once the thread finishes.
    """
    global _STARTUP_DIAGNOSTICS

    with _STARTUP_DIAGNOSTICS_LOCK:
        if _STARTUP_DIAGNOSTICS is not None:
            return _STARTUP_DIAGNOSTICS

        diag: dict = {
            "libmpv": _LIBMPV_AVAILABLE or False,
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

    t = threading.Thread(target=_probe, daemon=True, name="avialview-diagnostics")
    t.start()

    return diag


def format_diagnostics(diag: dict) -> str:
    """Format diagnostics dict as a copyable text block."""
    lines = [
        "AvialView Diagnostics",
        "=" * 40,
        f"Platform: {sys.platform}",
        f"Python: {sys.version}",
        f"libmpv: {'found' if diag.get('libmpv') else 'MISSING'}",
    ]

    hwdec = diag.get("hwdec", {})
    if hwdec.get("available"):
        lines.append(f"HW decode: {', '.join(hwdec['decoders'])}")
    else:
        lines.append("HW decode: not available")

    speed = diag.get("disk_speed_mbps", 0)
    lines.append(f"Disk speed: {speed:.0f} MB/s")

    return "\n".join(lines)
