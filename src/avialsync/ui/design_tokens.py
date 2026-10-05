"""Spacing, density and control roles: the choices panels stop making alone (D-168).

Every panel chose its own margins and every button looked like every other
one, so nothing on a surface said which control was the next step and which
one threw work away (INTERFACE_DESIGN_PLAN F-24). This module is where those
choices live.

**Control roles.** A button is *secondary* unless it says otherwise; the other
three are opt-in and built without a stylesheet, because a stylesheet pins the
widget's palette and a theme switch never reaches it (AGENTS.md theme rules):

* ``primary`` — the next step on its surface. Bold text through
  ``theme.set_bold`` and, given one, a glyph. At most one per surface.
* ``tool`` — a glyph alone. The text moves to the tooltip and the accessible
  name, which must therefore exist, so the command still has a name for a
  screen reader, the palette, and a reader of the tooltip.
* ``destructive`` — throws work away (it is still undoable). Its glyph is drawn
  in the error colour, and the glyph's shape says the same thing.

The role is recorded on the widget (``av_role``), so a test can enumerate a
populated window and hold the rules above.
"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QAbstractButton, QApplication, QPushButton, QToolButton, QWidget

from avialsync.ui.icons import set_svg_icon
from avialsync.ui.theme import font_scale, set_bold, set_font_family

__all__ = [
    "DENSITY_ROW_HEIGHT",
    "SPACE",
    "ControlRole",
    "Density",
    "TypeRole",
    "apply_role",
    "spacing",
    "apply_type_role",
    "role_of",
]

#: Spacing steps in pixels. Margins and gaps take one of these, not a new number.
SPACE = {"xs": 2, "s": 4, "m": 8, "l": 12, "xl": 16, "xxl": 24}


def spacing(step: str, widget: QWidget) -> int:
    """Return a spacing step scaled with the widget's selected font size."""
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return max(1, round(SPACE[step] * font_scale(app)))
    return SPACE[step]


class TypeRole(StrEnum):
    """Text treatment shared by interface surfaces."""

    BODY = "body"
    CAPTION = "caption"
    HEADING = "heading"
    NUMERIC = "numeric"


def apply_type_role(widget: QWidget, role: TypeRole) -> None:
    """Apply a type role through Qt fonts, preserving palette inheritance."""
    widget.setProperty("av_type_role", str(role))
    if role is TypeRole.HEADING:
        set_bold(widget)
    elif role is TypeRole.NUMERIC:
        fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        set_font_family(widget, fixed.family())
    elif role is TypeRole.CAPTION:
        font = widget.font()
        if font.pointSizeF() > 0:
            font.setPointSizeF(max(1.0, font.pointSizeF() - 1.0))
        widget.setFont(font)


class Density(StrEnum):
    """How tightly strips, lanes and cards are packed."""

    COMFORTABLE = "comfortable"
    COMPACT = "compact"


#: Height of one text row (a lane, a list entry) at each density, in pixels
#: beyond the font's own line height.
DENSITY_ROW_HEIGHT = {Density.COMFORTABLE: SPACE["m"], Density.COMPACT: SPACE["s"]}


class ControlRole(StrEnum):
    """What a button is for, which decides how much it asks to be pressed."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    TOOL = "tool"
    DESTRUCTIVE = "destructive"


_ROLE_PROPERTY = "av_role"


def role_of(button: QAbstractButton) -> ControlRole:
    """The role *button* was given; secondary when it was given none."""
    value = button.property(_ROLE_PROPERTY)
    return ControlRole(value) if value else ControlRole.SECONDARY


def apply_role(button: QAbstractButton, role: ControlRole, icon: str | None = None) -> None:
    """Give *button* the look of *role*, optionally with AvialSync glyph *icon*."""
    button.setProperty(_ROLE_PROPERTY, str(role))
    if role is ControlRole.PRIMARY:
        set_bold(button)
        if isinstance(button, QPushButton):
            button.setDefault(True)
    if role is ControlRole.TOOL:
        _make_tool(button)
    if role is ControlRole.DESTRUCTIVE:
        set_svg_icon(button, icon or "remove", "danger")
    elif icon is not None:
        set_svg_icon(button, icon)


def _make_tool(button: QAbstractButton) -> None:
    """Move *button*'s text into its tooltip and accessible name, and flatten it."""
    text = button.text().replace("&", "").strip()
    if not button.accessibleName():
        button.setAccessibleName(text)
    if not button.toolTip():
        button.setToolTip(text or button.accessibleName())
    if not button.accessibleName():
        raise ValueError("a tool button needs a name: give it text or an accessible name")
    button.setText("")
    if isinstance(button, QToolButton):
        button.setAutoRaise(True)
    elif isinstance(button, QPushButton):
        button.setFlat(True)
