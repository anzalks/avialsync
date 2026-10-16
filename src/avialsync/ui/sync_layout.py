"""Reuse the same setup/results controls across wide and narrow displays."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QScrollArea, QTabWidget, QVBoxLayout

from avialsync.ui.i18n import tr
from avialsync.ui.sync_form import describe

if TYPE_CHECKING:
    from avialsync.ui.sync_wizard import SyncWizard


def install_pages(wizard: SyncWizard, layout: QVBoxLayout) -> None:
    """Keep a single set of fields, plots and scroll positions during resize."""
    wizard._result_scroll = QScrollArea(wizard)
    wizard._result_scroll.setWidgetResizable(True)
    describe(
        wizard._result_scroll, tr("Alignment results"), tr("Scroll to inspect the complete result.")
    )
    wizard._result_scroll.setWidget(wizard._results)
    wizard._pages = QTabWidget(wizard)
    describe(wizard._pages, tr("Alignment steps"), tr("Choose Settings or Results."))
    wizard._pages.hide()
    wizard._body.addWidget(wizard._scroll)
    wizard._body.addWidget(wizard._result_scroll)
    wizard._body.setSizes([380, 620])
    layout.addWidget(wizard._body, 1)
    layout.addWidget(wizard._pages, 1)


def responsive_layout(wizard: SyncWizard) -> None:
    """Give narrow screens one full-height, independently scrollable page."""
    wide = wizard.width() >= max(900, wizard.fontMetrics().horizontalAdvance("M") * 70)
    if wide and wizard._pages.count():
        for page in (wizard._scroll, wizard._result_scroll):
            wizard._pages.removeTab(wizard._pages.indexOf(page))
            wizard._body.addWidget(page)
            # A tab page that was not current is left explicitly hidden, and a
            # splitter does not show it again: widening a narrowed dialog left
            # nothing but its footer.
            page.show()
        wizard._pages.hide()
        wizard._body.show()
        wizard._body.setSizes([380, 620])
    elif not wide and not wizard._pages.count():
        wizard._pages.addTab(wizard._scroll, tr("Settings"))
        wizard._pages.addTab(wizard._result_scroll, tr("Results"))
        wizard._body.hide()
        wizard._pages.show()
        if wizard.proposal is not None:
            # Narrowing after a preview keeps the result, not the form, in view:
            # Apply sits in the footer and should not appear beside settings.
            wizard._pages.setCurrentWidget(wizard._result_scroll)


def show_results(wizard: SyncWizard) -> None:
    """Reveal the result of an explicit preview gesture on a narrow display."""
    if wizard._pages.count():
        wizard._pages.setCurrentWidget(wizard._result_scroll)
