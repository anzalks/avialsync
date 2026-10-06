"""Phase 9 control roles and bundled glyph behavior (D-168, D-169)."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QAbstractButton, QPushButton

from avialsync.ui.design_tokens import ControlRole, apply_role, role_of
from avialsync.ui.icon_glyphs import GLYPHS
from avialsync.ui.icons import set_svg_icon
from avialsync.ui.main_window import MainWindow


def _ink(button: QPushButton) -> QColor:
    """Find a nontransparent icon pixel without depending on stroke placement."""
    image = button.icon().pixmap(24, 24).toImage()
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() > 200:
                return color
    raise AssertionError("the icon rendered no visible pixels")


@pytest.mark.parametrize("name", sorted(GLYPHS))
def test_every_bundled_glyph_renders(name: str, qtbot) -> None:
    """An invalid SVG must not silently leave an icon-only command blank."""
    button = QPushButton()
    qtbot.addWidget(button)
    set_svg_icon(button, name)
    assert button.icon().isNull() is False
    _ink(button)


def test_svg_icon_follows_palette_without_stylesheet(qtbot) -> None:
    """The same button's ink changes across Light and Dark palette roles."""
    button = QPushButton()
    qtbot.addWidget(button)
    set_svg_icon(button, "play")
    for ink in (QColor("#eeeeee"), QColor("#181818")):
        palette = QPalette(button.palette())
        palette.setColor(QPalette.ColorRole.ButtonText, ink)
        button.setPalette(palette)
        assert _ink(button).rgb() == ink.rgb()
    assert not button.styleSheet()


def test_roles_keep_tool_names_and_mark_destructive_shape(qtbot) -> None:
    """A glyph-only tool remains named; a destructive action has a bin shape."""
    tool = QPushButton("Zoom in")
    destructive = QPushButton("Remove")
    qtbot.addWidget(tool)
    qtbot.addWidget(destructive)
    apply_role(tool, ControlRole.TOOL, "zoom-in")
    apply_role(destructive, ControlRole.DESTRUCTIVE)
    assert tool.text() == ""
    assert tool.accessibleName() == tool.toolTip() == "Zoom in"
    assert role_of(destructive) is ControlRole.DESTRUCTIVE
    assert not destructive.icon().isNull()


def test_constructed_window_has_declared_roles(qtbot) -> None:
    """Every existing button has a role; the Open buttons have one primary (D-181)."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    buttons = window.findChildren(QAbstractButton)
    assert buttons
    missing = [
        (type(button).__name__, button.text(), button.objectName())
        for button in buttons
        if not button.objectName().startswith("qt_") and not button.property("av_role")
    ]
    assert not missing, missing
    sidebar = window.sidebar
    open_buttons = (
        sidebar.btn_open_video,
        sidebar.btn_open_sensor,
        sidebar.btn_open_imaging,
        sidebar.btn_open_session,
        sidebar.btn_align,
        sidebar.btn_reset_session,
    )
    primaries = [role_of(button) is ControlRole.PRIMARY for button in open_buttons]
    assert primaries == [True, False, False, False, False, False]
    window.close()
