"""Application status beside the job activity area (D-170)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QLabel, QWidget

from avialsync.ui.i18n import tr
from avialsync.ui.theme import status_color


class StatusLine(QLabel):
    """A transient, palette-aware status with no stylesheet or blocking dialog."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._message = ""
        self._severity = "info"
        self.setAccessibleName(tr("Application status"))
        self.setToolTip(tr("Non-blocking application status"))
        self.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._status_clear_timer = QTimer(self)
        self._status_clear_timer.setSingleShot(True)
        self._status_clear_timer.timeout.connect(self.clear_status)
        self.hide()

    def status_text(self) -> str:
        """Return the currently displayed message, without its visual prefix."""
        return self._message

    def set_status(self, message: str, severity: str = "info") -> None:
        """Show *message* until replaced, or for five seconds if transient."""
        self._message = message
        self._severity = severity
        prefixes = {
            "info": tr("Status"),
            "busy": tr("Working"),
            "warning": tr("Warning"),
            "error": tr("Error"),
        }
        self.setText(f"{prefixes.get(severity, tr('Status'))}: {message}")
        self.setToolTip(self.text())
        self.setAccessibleDescription(self.text())
        self.show()
        if severity == "busy":
            self._status_clear_timer.stop()
        else:
            self._status_clear_timer.start(5000)
        self.update()

    def clear_status(self) -> None:
        """Clear a finished status without altering the job area."""
        self._message = ""
        self.clear()
        self.hide()

    def ink_color(self) -> QColor:
        """Return the current palette's ink for the message's severity."""
        return status_color(self.palette(), self._severity)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw status ink from the current palette on every repaint."""
        del event
        painter = QPainter(self)
        painter.setPen(self.ink_color())
        painter.drawText(self.contentsRect(), self.alignment(), self.text())
        painter.end()
