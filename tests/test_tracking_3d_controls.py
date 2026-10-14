"""Compact 3D controls remain readable without widening the scene."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import QLabel

from avialsync.ui.design_tokens import ControlRole, role_of
from avialsync.ui.tracking_3d_pane import Tracking3DPane
from avialsync.ui.view_toolbar import ViewToolbar


def _pane(qtbot, width: int = 600, font_size: int | None = None) -> Tracking3DPane:
    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    if font_size is not None:
        font = pane.font()
        font.setPointSize(font_size)
        pane.setFont(font)
    action = QAction("3D reprojection", pane)
    action.setCheckable(True)
    pane.install_reprojection_action(action)
    pane.resize(width, 320)
    pane.show()
    qtbot.waitUntil(
        lambda: pane.header_scroll.viewport().height() >= pane.title_label.parentWidget().height()
    )
    return pane


@pytest.mark.parametrize("font_size", [None, 15])
@pytest.mark.parametrize("width", [340, 600])
def test_display_settings_fit_without_horizontal_scrolling(qtbot, font_size, width) -> None:
    """The screenshot's normal pane width must expose every header command."""
    pane = _pane(qtbot, width=width, font_size=font_size)
    qtbot.waitUntil(lambda: pane.header_scroll.horizontalScrollBar().maximum() == 0)
    viewport = pane.header_scroll.viewport()
    for control in (pane.up_axis_combo, pane.display_button, pane.fit_button):
        assert control.isVisible()
        assert viewport.rect().contains(control.mapTo(viewport, QPoint(0, 0)))
        assert viewport.rect().contains(control.mapTo(viewport, control.rect().bottomRight()))
    assert pane.bone_thickness.prefix() == ""
    assert pane.bone_thickness.suffix() == ""
    assert pane.bone_thickness.specialValueText() == ""
    assert not pane.bone_thickness.isVisible()
    assert pane.canvas.geometry().top() == 0
    assert pane.controls_scroll.geometry().top() > pane.canvas.geometry().bottom()


@pytest.mark.parametrize("font_size", [None, 15])
def test_narrow_pane_opens_complete_display_settings_without_resizing(qtbot, font_size) -> None:
    """The floating controls use their own space, independent of the pane width."""
    pane = _pane(qtbot, width=360, font_size=font_size)
    before = pane.size()
    qtbot.mouseClick(pane.display_button, Qt.MouseButton.LeftButton)
    popup = pane.display_popup
    qtbot.waitUntil(popup.isVisible)
    for control in (pane.bone_combo, pane.bone_style_combo, pane.bone_thickness):
        assert control.isVisible()
        assert control.width() >= control.minimumSizeHint().width()
        assert popup.rect().contains(control.mapTo(popup, control.rect().bottomRight()))
        assert control.font().pointSizeF() == pane.up_axis_combo.font().pointSizeF()
    assert pane.bone_combo.isEnabled()
    assert pane.bone_style_combo.isEnabled()
    for label in popup.findChildren(QLabel):
        if label.isVisible():
            assert popup.rect().contains(label.mapTo(popup, label.rect().bottomRight()))
        if label.isVisible() and label.hasHeightForWidth():
            assert label.height() >= label.heightForWidth(label.width())
    assert pane.size() == before
    qtbot.keyClick(pane.bone_combo, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not popup.isVisible())


def test_3d_glyph_buttons_match_the_video_toolbar(qtbot) -> None:
    """Every 3D command uses the existing native, palette-following tool style."""
    pane = _pane(qtbot)
    toolbar = ViewToolbar()
    qtbot.addWidget(toolbar)
    action = QAction("Fit All Videos", toolbar)
    toolbar.install_fit_videos_action(action)
    reference = toolbar.fit_videos_button
    for button in (pane.display_button, pane.reprojection_button, pane.fit_button):
        assert role_of(button) is ControlRole.TOOL
        assert button.isFlat() == reference.isFlat()
        assert button.iconSize() == reference.iconSize()
        assert not button.icon().isNull()
        assert button.text() == ""
        assert button.accessibleName()
        assert button.accessibleDescription()
        assert button.toolTip()
        assert button.style() is reference.style()
        assert button.styleSheet() == ""


def test_popup_uses_the_current_appearance_without_resetting_the_view(qtbot) -> None:
    """A floating window must inherit the pane's font and palette like camera levels."""
    pane = _pane(qtbot)
    pane.set_up_axis(1, True)
    pane.bone_thickness.setValue(1.9)
    qtbot.mouseClick(pane.display_button, Qt.MouseButton.LeftButton)
    palette = pane.palette()
    color = QColor(35, 45, 55)
    palette.setColor(QPalette.ColorRole.Window, color)
    pane.setPalette(palette)
    font = pane.font()
    font.setPointSize(16)
    pane.setFont(font)
    qtbot.waitUntil(lambda: pane.display_popup.palette().color(QPalette.ColorRole.Window) == color)
    assert pane.bone_thickness.font().pointSize() == 16
    assert pane.canvas.up_axis == 1
    assert pane.canvas.up_inverted
    assert pane.canvas.bone_thickness == pytest.approx(1.9)
    assert pane.bone_thickness.style() is pane.up_axis_combo.style()


def test_popup_accepts_keyboard_drawing_and_thickness_edits(qtbot) -> None:
    """The real popup supports editing rather than only programmatic setters."""
    pane = _pane(qtbot)
    qtbot.mouseClick(pane.display_button, Qt.MouseButton.LeftButton)
    qtbot.keyClick(pane.bone_style_combo, Qt.Key.Key_End)
    assert pane.bone_thickness.isEnabled()
    pane.bone_thickness.setFocus()
    pane.bone_thickness.selectAll()
    qtbot.keyClicks(pane.bone_thickness, "1.900")
    qtbot.keyClick(pane.bone_thickness, Qt.Key.Key_Return)
    assert pane.canvas.bone_thickness == pytest.approx(1.9)
    assert pane.display_popup.isVisible()
    qtbot.keyClick(pane.bone_thickness, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not pane.display_popup.isVisible())


def test_lines_and_tubes_follow_the_same_thickness_value(qtbot) -> None:
    """Changing the drawing style preserves the last entered tube diameter."""
    pane = _pane(qtbot)
    assert pane.bone_style_combo.currentText() == "Lines"
    assert not pane.bone_thickness.isEnabled()
    pane.bone_thickness.setValue(1.9)
    assert pane.bone_style_combo.currentText() == "Tubes"
    assert pane.bone_thickness.isEnabled()
    assert pane.canvas.bone_thickness == pytest.approx(1.9)
    pane.bone_style_combo.setCurrentIndex(0)
    pane.bone_style_combo.activated.emit(0)
    assert pane.canvas.bone_thickness == 0.0
    assert not pane.bone_thickness.isEnabled()
    pane.bone_style_combo.setCurrentIndex(1)
    pane.bone_style_combo.activated.emit(1)
    assert pane.canvas.bone_thickness == pytest.approx(1.9)
    assert pane.bone_thickness.isEnabled()
