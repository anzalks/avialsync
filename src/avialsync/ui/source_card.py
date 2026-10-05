"""Pieces of a compact source card in the Sources page (D-175, DS-7).

A card shows what a source is at a glance -- kind, name, quality, visibility --
and keeps the rest one click away: offset and drift behind a Timing
disclosure, Properties, Copy details and Remove in one overflow menu. The
disclosure wraps the card's own spin boxes rather than copies of them, so the
offset a user drags is still the one authority and D-087's drag coalescing is
unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QHBoxLayout,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from avialsync.ui.elided_label import ElidedLabel
from avialsync.ui.i18n import tr
from avialsync.ui.icons import set_svg_icon
from avialsync.ui.time_format import format_number

__all__ = [
    "TimingDisclosure",
    "kind_glyph",
    "open_split_button",
    "overflow_button",
    "short_path",
]


def short_path(path: str, base: str | None = None) -> str:
    """*path* relative to *base* when inside it, else ``…/parent/name`` (F-26).

    A temporary or deep absolute path says nothing the file name and its
    folder do not, and it is the widest text a card would otherwise show.
    """
    target = Path(path)
    if base:
        try:
            return target.relative_to(Path(base)).as_posix()
        except ValueError:
            pass
    if target.parent.name:
        return f"…/{target.parent.name}/{target.name}"
    return target.name


def kind_glyph(name: str, accessible_name: str, parent: QWidget | None = None) -> QToolButton:
    """A palette-inked glyph naming a source's kind; inert, never a control."""
    glyph = QToolButton(parent)
    glyph.setAutoRaise(True)
    glyph.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    glyph.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    glyph.setIconSize(QSize(16, 16))
    glyph.setAccessibleName(accessible_name)
    glyph.setToolTip(accessible_name)
    set_svg_icon(glyph, name)
    return glyph


def overflow_button(
    parent: QWidget,
    accessible_name: str,
    items: list[tuple[str, Callable[[], None], bool]],
) -> QToolButton:
    """A ``⋯`` button whose menu holds *items*: ``(label, slot, destructive)``.

    Destructive items sit last, after a separator, and carry the bin glyph as
    well as their label, so they are told apart by shape and place, not hue.
    """
    button = QToolButton(parent)
    button.setAutoRaise(True)
    button.setAccessibleName(accessible_name)
    button.setToolTip(accessible_name)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    set_svg_icon(button, "more")
    menu = QMenu(button)
    menu.setAccessibleName(accessible_name)
    ordinary = [item for item in items if not item[2]]
    destructive = [item for item in items if item[2]]
    for label, slot, _ in ordinary:
        menu.addAction(label).triggered.connect(slot)
    if ordinary and destructive:
        menu.addSeparator()
    for label, slot, _ in destructive:
        action = menu.addAction(label)
        action.setProperty("av_role", "destructive")
        action.setIcon(_danger_icon(button))
        action.triggered.connect(slot)
    button.setMenu(menu)
    return button


def _danger_icon(owner: QToolButton):  # noqa: ANN202 -- QIcon, imported lazily
    from avialsync.ui.icons import svg_icon

    return svg_icon(owner, owner.palette(), "remove", "danger")


def open_split_button(parent: QWidget, primary: QAction, others: list[QAction]) -> QToolButton:
    """One Open button: a click runs *primary*, the arrow offers every open action.

    The button *is* *primary* (``setDefaultAction``), so its label is the
    action's own (rule 15); the arrow's menu holds the same QAction objects.
    """
    button = QToolButton(parent)
    button.setDefaultAction(primary)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    menu = QMenu(button)
    menu.setAccessibleName(tr("Open sources"))
    for action in [primary, *others]:
        menu.addAction(action)
    button.setMenu(menu)
    button.setAccessibleName(primary.text().replace("&", ""))
    button.setAccessibleDescription(tr("Open videos; the arrow offers every kind of source"))
    set_svg_icon(button, "open")
    return button


class TimingDisclosure(QWidget):
    """``▸ Timing  +0.000000 s · 0.0 ppm`` over the card's own spin boxes."""

    def __init__(
        self,
        body: QWidget,
        offset_spin: QDoubleSpinBox,
        drift_spin: QDoubleSpinBox,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._offset = offset_spin
        self._drift = drift_spin
        self.body = body
        self.toggle = QToolButton(self)
        self.toggle.setCheckable(True)
        self.toggle.setAutoRaise(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setAccessibleName(tr("Timing"))
        self.toggle.setAccessibleDescription(tr("Show or hide this source's offset and drift"))
        self.toggle.setText(tr("Timing"))
        self.toggle.toggled.connect(self._set_open)
        # The values elide rather than widen the sidebar past its minimum.
        self.summary_label = ElidedLabel("", self, Qt.TextElideMode.ElideRight)
        self.summary_label.setAccessibleName(tr("Offset and drift"))
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.toggle)
        header.addWidget(self.summary_label, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addLayout(header)
        layout.addWidget(body)
        offset_spin.valueChanged.connect(self._refresh)
        drift_spin.valueChanged.connect(self._refresh)
        self._set_open(False)

    def is_open(self) -> bool:
        return self.toggle.isChecked()

    def set_open(self, opened: bool) -> None:
        self.toggle.setChecked(opened)

    def _set_open(self, opened: bool) -> None:
        self.body.setVisible(opened)
        set_svg_icon(self.toggle, "chevron-down" if opened else "chevron-right")
        self._refresh()

    def summary(self) -> str:
        """The values the closed disclosure shows inline."""
        offset = self._offset.value()
        sign = "+" if offset >= 0 else "−"
        return tr("{sign}{offset} s · {drift} ppm").format(
            sign=sign,
            offset=format_number(abs(offset), self._offset.decimals()),
            drift=format_number(self._drift.value(), self._drift.decimals()),
        )

    def _refresh(self, *_args: object) -> None:
        self.summary_label.setText(self.summary())
        self.toggle.setToolTip(tr("Offset and drift: {values}").format(values=self.summary()))


def copy_to_clipboard(text: str) -> None:
    """Put *text* on the clipboard, as Copy details does."""
    clipboard = QApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(text)
