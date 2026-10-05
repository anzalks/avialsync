"""The shared guided-step panel (D-176, INTERFACE_DESIGN_PLAN §4.4, DS-8).

Wheel, prop, identity and alignment flows each explained themselves in
paragraphs beside a dozen equally weighted buttons (F-15). A step panel shows
one thing at a time: where the user is, one sentence, one primary next action,
a short row of secondary ones, destructive choices in an overflow, and the
detail behind "More…". The flows keep their own widgets and signals; this only
decides where each sits and how much it asks to be pressed.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.design_tokens import ControlRole, apply_role, spacing
from avialsync.ui.empty_note import WRAP_WIDTH_PX
from avialsync.ui.i18n import tr
from avialsync.ui.icons import set_svg_icon
from avialsync.ui.theme import set_bold

__all__ = ["StepPanel"]


class StepPanel(QFrame):
    """Title and progress, one instruction, one primary, secondary row, overflow, More…."""

    #: Emitted with the docs URL when "Learn more" is followed.
    learn_more_requested = Signal(str)

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)
        self.setAccessibleName(title or tr("Guided steps"))
        gap = spacing("s", self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(gap * 2, gap * 2, gap * 2, gap * 2)
        layout.setSpacing(gap)

        header = QHBoxLayout()
        self.title = QLabel(title, self)
        self.title.setWordWrap(True)
        set_bold(self.title)
        self.progress = QLabel(self)
        self.progress.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.title, 1)
        header.addWidget(self.progress)
        layout.addLayout(header)

        self.instruction = QLabel(self)
        self.instruction.setWordWrap(True)
        self.instruction.setAccessibleName(tr("What to do next"))
        layout.addWidget(self.instruction)

        self._primary_row = QHBoxLayout()
        layout.addLayout(self._primary_row)
        # A column, so the panel never asks for more than a 280 px page (R3).
        self._secondary_row = QGridLayout()
        self._secondary_row.setSpacing(gap)
        layout.addLayout(self._secondary_row)
        self._controls = QVBoxLayout()
        self._controls.setSpacing(gap)
        layout.addLayout(self._controls)
        self._overflow_sources: list[tuple[QAbstractButton, QAction]] = []

        self.overflow = QToolButton(self)
        self.overflow.setAutoRaise(True)
        self.overflow.setAccessibleName(tr("More choices"))
        self.overflow.setToolTip(tr("More choices"))
        self.overflow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        set_svg_icon(self.overflow, "more")
        self.overflow.setMenu(QMenu(self.overflow))
        self.overflow.hide()

        self.more_toggle = QToolButton(self)
        self.more_toggle.setCheckable(True)
        self.more_toggle.setAutoRaise(True)
        self.more_toggle.setText(tr("More…"))
        self.more_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.more_toggle.setAccessibleName(tr("More detail"))
        self.more_toggle.setAccessibleDescription(tr("Show or hide the explanation for this step"))
        set_svg_icon(self.more_toggle, "chevron-right")
        self.more_toggle.toggled.connect(self._show_more)
        self.learn_more = QLabel(self)
        self.learn_more.setOpenExternalLinks(False)
        self.learn_more.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.learn_more.setAccessibleName(tr("Learn more in the user guide"))
        self.learn_more.linkActivated.connect(self._open_link)
        self.learn_more.hide()
        footer = QHBoxLayout()
        footer.addWidget(self.more_toggle)
        footer.addStretch(1)
        footer.addWidget(self.learn_more)
        footer.addWidget(self.overflow)
        layout.addLayout(footer)

        self.more = QWidget(self)
        self._more_layout = QVBoxLayout(self.more)
        self._more_layout.setContentsMargins(0, 0, 0, 0)
        self._more_layout.setSpacing(gap)
        layout.addWidget(self.more)
        self.more.hide()
        self.more_toggle.hide()

    def sizeHint(self) -> QSize:  # noqa: N802
        """Prefer a narrow page: the instruction wraps rather than widening it (R3)."""
        hint = super().sizeHint()
        hint.setWidth(min(hint.width(), max(self.minimumSizeHint().width(), WRAP_WIDTH_PX)))
        return hint

    # ── content ─────────────────────────────────────────────────────

    def set_title(self, title: str) -> None:
        self.title.setText(title)
        self.setAccessibleName(title)

    def set_progress(self, step: int, total: int) -> None:
        """Show ``Step step of total`` with a dot per step; 0 total hides it."""
        if total <= 0:
            self.progress.clear()
            return
        step = max(1, min(step, total))
        dots = "●" * step + "○" * (total - step)
        self.progress.setText(
            f"{dots}\n{tr('Step {step} of {total}').format(step=step, total=total)}"
        )
        self.progress.setAccessibleName(tr("Step {step} of {total}").format(step=step, total=total))

    def set_instruction(self, text: str) -> None:
        """One sentence: what to do now. Detail goes in :meth:`add_more`."""
        self.instruction.setText(text)

    def set_primary(self, button: QAbstractButton) -> None:
        """The one action that moves the flow on; at most one per panel (R2)."""
        while self._primary_row.count():
            item = self._primary_row.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()
        apply_role(button, ControlRole.PRIMARY)
        button.setParent(self)
        self._primary_row.addWidget(button)
        button.show()

    def add_secondary(self, buttons: Sequence[QAbstractButton]) -> None:
        """Ordinary choices beneath the primary, one per line.

        Side by side, two labels set the page's minimum width; stacked, the
        widest single label does, which is what keeps a page inside 280 px.
        """
        for button in buttons:
            button.setParent(self)
            self._secondary_row.addWidget(button, self._secondary_row.rowCount(), 0)
            button.show()

    def use_instruction_label(self, label: QLabel) -> None:
        """Make a flow's existing status label the instruction line it already is."""
        outer = self.layout()
        assert isinstance(outer, QVBoxLayout)
        index = outer.indexOf(self.instruction)
        outer.removeWidget(self.instruction)
        self.instruction.deleteLater()
        label.setParent(self)
        label.setWordWrap(True)
        outer.insertWidget(index, label)
        self.instruction = label

    def add_controls(self, item: QWidget | QLayout) -> None:
        """A flow's own control group (point pickers, fields) under the actions."""
        if isinstance(item, QWidget):
            self._controls.addWidget(item)
        else:
            self._controls.addLayout(item)

    def add_overflow(self, button: QAbstractButton, *, destructive: bool = False) -> None:
        """Move *button*'s command into the overflow menu, keeping the button as its source.

        The menu entry triggers the button, so its enablement, tooltip and
        handler stay where the flow already manages them.
        """
        menu = self.overflow.menu()
        assert menu is not None
        if destructive and menu.actions():
            menu.addSeparator()
        action = menu.addAction(button.text())
        action.setToolTip(button.toolTip() or button.accessibleDescription())
        if destructive:
            action.setProperty("av_role", str(ControlRole.DESTRUCTIVE))
            from avialsync.ui.icons import svg_icon

            action.setIcon(svg_icon(self.overflow, self.palette(), "remove", "danger"))
        action.setEnabled(button.isEnabled())
        action.triggered.connect(button.click)
        button.setParent(self)
        button.hide()
        # The flow enables, disables and relabels the button; the entry follows.
        self._overflow_sources.append((button, action))
        button.installEventFilter(self)
        self.overflow.show()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() in (QEvent.Type.EnabledChange, QEvent.Type.ToolTipChange):
            for button, action in self._overflow_sources:
                if button is watched:
                    action.setEnabled(button.isEnabled())
                    action.setText(button.text())
        return super().eventFilter(watched, event)

    def add_more(self, widget: QWidget) -> None:
        """Explanation, legends, evidence: behind "More…" (R4)."""
        self._more_layout.addWidget(widget)
        self.more_toggle.show()

    def set_learn_more(self, url: str) -> None:
        """Link the step to its page in the user guide (DS-13)."""
        self.learn_more.setText(f'<a href="{url}">{tr("Learn more")}</a>')
        self.learn_more.setToolTip(url)
        self.learn_more.show()

    # ── behaviour ───────────────────────────────────────────────────

    def _show_more(self, opened: bool) -> None:
        self.more.setVisible(opened)
        set_svg_icon(self.more_toggle, "chevron-down" if opened else "chevron-right")

    def _open_link(self, url: str) -> None:
        self.learn_more_requested.emit(url)
        QDesktopServices.openUrl(QUrl(url))
