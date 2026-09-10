"""The one dialog for text the user asked to see (D-107).

Five places used to raise a bare ``QMessageBox`` to show a block of text: the
"Show details" behind a failure, Diagnostics, About, the citation metadata, and
a missing import report.  ``QMessageBox`` is the wrong widget for all of them.
It does not scroll, so a diagnostics dump grew the box until it ran off the
screen; its label is not a text view, so long lines could not be read; and
whether the content could be copied depended on which of the five you opened —
About and the citation had a Copy button, Diagnostics and Show details did not,
for no reason a user could infer.

This is one modal that a user explicitly asked for, which is the case AGENTS
rule 11 permits.  What it must not do is lose or hide the text: the body
scrolls, selects, and copies, and every caller gets the same Copy button.

Keeping it inside ``ui/feedback/`` is deliberate.  That package is the only
place allowed to construct a ``QMessageBox``-shaped thing at all, and
``tests/test_feedback_surface.py`` enforces exactly that boundary, so a sixth
ad-hoc dialect cannot be added somewhere else without failing CI.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.i18n import tr

__all__ = ["TextDialog", "show_text"]


class TextDialog(QDialog):
    """A titled, scrollable, copyable block of text."""

    def __init__(
        self,
        title: str,
        body: str,
        *,
        lead: str = "",
        monospace: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(560, 360)

        layout = QVBoxLayout(self)

        if lead:
            lead_label = QLabel(lead)
            lead_label.setWordWrap(True)
            lead_label.setAccessibleName(title)
            layout.addWidget(lead_label)

        #: Public so tests can read what was shown without scraping widgets.
        self.body = QPlainTextEdit(body)
        self.body.setReadOnly(True)
        self.body.setAccessibleName(tr("{title} details").format(title=title))
        self.body.setAccessibleDescription(
            tr("Read-only text. Use the Copy button to put it on the clipboard.")
        )
        if monospace:
            # Columns only line up in a fixed pitch, and every caller here is
            # showing something aligned in columns or wrapped at a fixed width.
            font = QFont(self.body.font())
            font.setStyleHint(QFont.StyleHint.Monospace)
            font.setFamily("monospace")
            self.body.setFont(font)
        layout.addWidget(self.body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        #: Public for the same reason as `body`.
        self.copy_button = buttons.addButton(tr("Copy"), QDialogButtonBox.ButtonRole.ActionRole)
        self.copy_button.setAccessibleName(tr("Copy this text to the clipboard"))
        self.copy_button.clicked.connect(self._copy)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._text = body

    def _copy(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._text)


def show_text(
    parent: QWidget | None,
    title: str,
    body: str,
    *,
    lead: str = "",
    monospace: bool = True,
) -> TextDialog:
    """Show *body* in a :class:`TextDialog` and return it once dismissed."""
    dialog = TextDialog(title, body, lead=lead, monospace=monospace, parent=parent)
    dialog.exec()
    return dialog
