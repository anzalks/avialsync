"""Diagnostics module for KinoChronix."""

import sys

from PySide6.QtWidgets import QMessageBox

_LIBMPV_AVAILABLE = None

def probe_libmpv(parent=None) -> bool:
    """Probe for libmpv. Show a dialog if missing and return False."""
    global _LIBMPV_AVAILABLE
    if _LIBMPV_AVAILABLE is not None:
        return _LIBMPV_AVAILABLE

    try:
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
