"""The inspector's page rail: icon and label buttons beside a page stack (D-172).

Six text tabs in a 280 px pane elided to "Sour…" and "Mess…" (F-13). A rail
stacks its buttons vertically, so a label is as wide as the rail, never a
share of it; when the window is too short for every button the rail scrolls
vertically instead of cropping one.

The public surface mirrors the part of ``QTabWidget`` the window, the session
and workspace persistence, and the screenshot tools already use (``addTab``,
``currentIndex``, ``setCurrentWidget``, ``tabText`` …), so moving from tabs to
a rail changed what the inspector looks like and nothing that drives it.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.design_tokens import spacing
from avialsync.ui.i18n import tr
from avialsync.ui.icons import set_svg_icon

__all__ = ["INSPECTOR_PAGES", "InspectorNav"]

#: Inspector pages by their persisted name, in rail order. A name, not an
#: index, so reordering or adding a page never restores the wrong one.
INSPECTOR_PAGES = ("sources", "values", "messages", "changes", "props")


class InspectorNav(QWidget):
    """A vertically scrolling page rail and the page it selects."""

    currentChanged = Signal(int)  # noqa: N815 -- the QTabWidget signal it replaces

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: list[QToolButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self.setCurrentIndex)

        self._rail = QWidget()
        self._rail_layout = QVBoxLayout(self._rail)
        gap = spacing("xs", self)
        self._rail_layout.setContentsMargins(gap, gap, gap, gap)
        self._rail_layout.setSpacing(gap)
        self._rail_layout.addStretch(1)

        self.rail_scroll = QScrollArea(self)
        self.rail_scroll.setObjectName("inspector_rail")
        self.rail_scroll.setAccessibleName(tr("Inspector pages"))
        self.rail_scroll.setAccessibleDescription(
            tr("Choose an inspector page. Scrolls vertically when the window is short.")
        )
        self.rail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rail_scroll.setWidgetResizable(True)
        self.rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rail_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.rail_scroll.verticalScrollBar().setAccessibleName(tr("Scroll the inspector pages"))
        self.rail_scroll.setWidget(self._rail)
        self.rail_scroll.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        # The rail may be shorter than its buttons; it must never set the
        # window's minimum height (640x480 floor).
        self.rail_scroll.setMinimumHeight(0)

        self._stack = QStackedWidget(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        separator = QFrame(self)
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(self.rail_scroll)
        layout.addWidget(separator)
        layout.addWidget(self._stack, 1)

    # ── QTabWidget-compatible surface ───────────────────────────────

    def addTab(self, page: QWidget, label: str, icon: str | None = None) -> int:  # noqa: N802
        """Append *page* under *label*, shown with AvialSync glyph *icon*."""
        index = self._stack.addWidget(page)
        button = QToolButton(self._rail)
        button.setText(label)
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setAccessibleName(label)
        button.setAccessibleDescription(tr("Show the {page} page").format(page=label))
        button.setToolTip(label)
        button.installEventFilter(self)
        if icon is not None:
            set_svg_icon(button, icon)
        self._group.addButton(button, index)
        self._rail_layout.insertWidget(self._rail_layout.count() - 1, button)
        self._buttons.append(button)
        if index == 0:
            button.setChecked(True)
        self._fit_rail_width()
        return index

    def count(self) -> int:
        return self._stack.count()

    def currentIndex(self) -> int:  # noqa: N802
        return self._stack.currentIndex()

    def currentWidget(self) -> QWidget | None:  # noqa: N802
        return self._stack.currentWidget()

    def widget(self, index: int) -> QWidget | None:
        return self._stack.widget(index)

    def indexOf(self, page: QWidget) -> int:  # noqa: N802
        return self._stack.indexOf(page)

    def tabText(self, index: int) -> str:  # noqa: N802
        return self._buttons[index].text()

    def button(self, index: int) -> QToolButton:
        """The rail button that selects page *index*."""
        return self._buttons[index]

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < self.count() or index == self.currentIndex():
            if 0 <= index < self.count():
                self._buttons[index].setChecked(True)
            return
        self._stack.setCurrentIndex(index)
        self._buttons[index].setChecked(True)
        self.rail_scroll.ensureWidgetVisible(self._buttons[index])
        self.currentChanged.emit(index)

    def setCurrentWidget(self, page: QWidget) -> None:  # noqa: N802
        self.setCurrentIndex(self.indexOf(page))

    # ── persistence ─────────────────────────────────────────────────

    def save_page(self, settings: QSettings) -> None:
        """Remember the current page by name under ``inspector/page``."""
        if 0 <= self.currentIndex() < len(INSPECTOR_PAGES):
            settings.setValue("inspector/page", INSPECTOR_PAGES[self.currentIndex()])

    def restore_page(self, settings: QSettings) -> None:
        """Show the saved page, reading the pre-D-172 ``inspector/tab`` index once."""
        page = settings.value("inspector/page", None)
        if isinstance(page, str) and page in INSPECTOR_PAGES:
            index = INSPECTOR_PAGES.index(page)
        else:
            raw = settings.value("inspector/tab", 0, type=int)
            index = raw if isinstance(raw, int) else 0
        self.setCurrentIndex(max(0, min(index, self.count() - 1)))

    # ── behaviour ───────────────────────────────────────────────────

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """Up and Down move between pages, as arrows move between tabs."""
        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            step = {Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1}.get(Qt.Key(event.key()), 0)
            if step and watched in self._buttons:
                target = (self._buttons.index(watched) + step) % len(self._buttons)
                self.setCurrentIndex(target)
                self._buttons[target].setFocus(Qt.FocusReason.TabFocusReason)
                return True
        return super().eventFilter(watched, event)

    def changeEvent(self, event: QEvent) -> None:
        """Re-measure the labels when the font changes, so none ever elides."""
        if event.type() == QEvent.Type.FontChange:
            self._fit_rail_width()
        super().changeEvent(event)

    def _fit_rail_width(self) -> None:
        widest = max((button.sizeHint().width() for button in self._buttons), default=0)
        margins = self._rail_layout.contentsMargins()
        bar = self.rail_scroll.verticalScrollBar().sizeHint().width()
        self.rail_scroll.setFixedWidth(widest + margins.left() + margins.right() + bar)
