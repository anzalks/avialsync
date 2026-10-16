"""Custom painters read the application's explicit accent through a widget palette."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from avialsync.ui import theme


def test_a_widget_palette_inherits_the_explicit_accent(qapp: QApplication, qtbot) -> None:
    """A widget palette has no resolve mask, so the dimmed Highlight was drawn instead."""
    previous = qapp.palette()
    palette = QPalette(previous)
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#063c9f"))
    palette.setColor(QPalette.ColorRole.Accent, QColor("#0a60ff"))
    qapp.setPalette(palette)
    try:
        widget = QWidget()
        qtbot.addWidget(widget)

        assert theme._accent(widget.palette()).name() == "#0a60ff"
    finally:
        qapp.setPalette(previous)


def test_a_palette_with_its_own_highlight_keeps_it(qapp: QApplication) -> None:
    previous = qapp.palette()
    palette = QPalette(previous)
    palette.setColor(QPalette.ColorRole.Accent, QColor("#0a60ff"))
    qapp.setPalette(palette)
    try:
        own = QPalette(QColor("#202020"))
        own.setColor(QPalette.ColorRole.Highlight, QColor("#aa3300"))
        own.setResolveMask(0)

        assert theme._accent(own).name() == "#aa3300"
    finally:
        qapp.setPalette(previous)
