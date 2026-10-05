"""Accessible descriptions of the surfaces AvialSync paints itself (D-179, DS-12).

Plot rows, Data Streams lanes, video panes and the 3D view are drawn, not built
from labelled widgets, so assistive technology saw a nameless rectangle (F-32).
Each such widget registers here with a role and a *describer*. Qt asks for an
accessible interface through the factory installed below, and the interface
answers ``Value`` and ``Description`` by calling the describer at that moment.

Values are computed on query and never pushed: nothing here runs on the 60 Hz
clock tick, and no code calls ``QAccessible.updateAccessibility`` per frame.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtGui import QAccessible, QAccessibleInterface
from PySide6.QtWidgets import QAccessibleWidget, QWidget

__all__ = ["register_painted"]

Describer = Callable[[], str]

_REGISTRY: dict[int, tuple[QAccessible.Role, Describer, Describer]] = {}
_installed = False


class _PaintedAccessible(QAccessibleWidget):
    """A widget's interface whose value and description are read when asked."""

    def __init__(
        self, widget: QWidget, role: QAccessible.Role, value: Describer, detail: Describer
    ) -> None:
        super().__init__(widget, role)
        self._value = value
        self._detail = detail

    def text(self, kind: QAccessible.Text) -> str:
        try:
            if kind == QAccessible.Text.Value:
                return self._value()
            if kind == QAccessible.Text.Description:
                return self._detail() or super().text(kind)
        except (RuntimeError, AttributeError, ValueError):
            # A describer reading a widget mid-teardown answers with nothing
            # rather than taking the assistive client down with it.
            return ""
        return super().text(kind)


def _factory(_classname: str, obj: QObject) -> QAccessibleInterface | None:
    entry = _REGISTRY.get(id(obj))
    if entry is None or not isinstance(obj, QWidget):
        return None
    role, value, detail = entry
    return _PaintedAccessible(obj, role, value, detail)


def register_painted(
    widget: QWidget,
    role: QAccessible.Role,
    value: Describer,
    detail: Describer | None = None,
) -> None:
    """Describe *widget* to assistive technology through *value* and *detail*.

    Both are called only when a client asks; they must be cheap and must not
    touch disk or the decoder.
    """
    global _installed
    if not _installed:
        QAccessible.installFactory(_factory)
        _installed = True
    key = id(widget)
    _REGISTRY[key] = (role, value, detail or (lambda: ""))
    widget.destroyed.connect(lambda _obj=None, key=key: _REGISTRY.pop(key, None))
