"""Diagnostics module for KinoChronix."""

import sys

from PySide6.QtWidgets import QMessageBox

_LIBMPV_AVAILABLE = None


def _configure_macos_env() -> None:
    """
    Configure dyld paths on macOS.

    Homebrew does not add its lib directory to the standard Python linker paths
    by default. We elegantly inject the Homebrew lib directory so ctypes can
    find libmpv natively without breaking standard library resolution.
    """
    if sys.platform != "darwin":
        return

    import os
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

    _configure_macos_env()

    try:
        import mpv  # noqa: F401

        _LIBMPV_AVAILABLE = True
        return True
    except OSError:
        _LIBMPV_AVAILABLE = False

        # Show guided dialog
        msg = QMessageBox(parent)
        msg.setWindowTitle("Missing libmpv")
        msg.setIcon(QMessageBox.Icon.Critical)

        if sys.platform == "darwin":
            install_cmd = "brew install mpv"
        elif sys.platform == "win32":
            install_cmd = "Auto-fetch will be implemented in future phase."
        else:
            install_cmd = "sudo apt install libmpv-dev OR sudo dnf install mpv-libs"

        text = (
            "KinoChronix requires 'libmpv' for hardware-accelerated video playback, but it "
            "could not be found on your system.\n\n"
            "Please install it to enable video features:\n"
            f"{install_cmd}"
        )
        msg.setText(text)
        msg.exec()
        return False
