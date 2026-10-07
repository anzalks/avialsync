"""A real theme switch must reach stylesheet widgets and button icons.

Both of these looked fine until the appearance changed at runtime, which is why
every check here drives an actual Dark/Light switch rather than handing a widget
a palette directly. Setting a palette on the widget is exactly the path Qt still
delivers; the theme switch is the one it does not.

*Stylesheet widgets.* A widget carrying a stylesheet never receives a palette
event when the application palette changes, so ``follow_palette`` — which only
listened for one — froze every widget it managed at the launch theme: channel
names and the "Video Properties" header rendered white on the Light surface.

*Icons.* Qt's standard media and reload glyphs are drawn in one fixed ink. On
macOS that is black, so under Dark the transport buttons showed black glyphs on
dark grey beside correctly light labels.

Assertions are properties — an icon's ink matches its label, a sheet carries the
live palette's colour — never hex values.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QImage, QPalette
from PySide6.QtWidgets import QApplication, QPushButton, QStyle, QVBoxLayout, QWidget

from avialsync.ui import theme
from avialsync.ui.icons import set_glyph_icon, set_status_icon

#: Lightness gap below which a glyph stops reading against its button.
_MIN_CONTRAST = 0.35


@pytest.fixture
def switch(qapp: QApplication) -> Iterator[object]:
    """Yield a function applying an appearance, restoring the palette afterwards.

    ``persist=False`` keeps the switch out of settings, and the entry palette is
    put back so no later test builds its widgets under this one's theme.
    """
    entry = QPalette(qapp.palette())
    dark = qapp.property("avialsync_theme_dark")
    native = qapp.property("avialsync_theme_native")

    def apply(pref: str) -> None:
        theme._apply(qapp, pref, persist=False)
        qapp.processEvents()

    try:
        yield apply
    finally:
        qapp.setPalette(entry)
        qapp.setProperty("avialsync_theme_dark", dark)
        qapp.setProperty("avialsync_theme_native", native)


def _ink(icon: QIcon, mode: QIcon.Mode = QIcon.Mode.Normal) -> QColor:
    """Return the colour of an icon's most opaque pixel."""
    image = icon.pixmap(QSize(16, 16), mode).toImage()
    best, best_alpha = QColor(), -1
    for y in range(image.height()):
        for x in range(image.width()):
            colour = image.pixelColor(x, y)
            if colour.alpha() > best_alpha:
                best, best_alpha = colour, colour.alpha()
    assert best_alpha > 0, "the icon rendered nothing"
    return best


def test_a_stylesheet_widget_follows_a_real_theme_switch(qtbot, switch) -> None:
    """The bug as reported: a followed colour stayed on the launch theme."""
    root = QWidget()
    QVBoxLayout(root)
    header = QPushButton("Video Properties")
    root.layout().addWidget(header)
    qtbot.addWidget(root)

    switch(theme.THEME_DARK)
    theme.follow_palette(
        header,
        lambda p: f"text-align:left;color: {p.color(QPalette.ColorRole.ButtonText).name()};",
    )
    root.show()

    for pref in (theme.THEME_LIGHT, theme.THEME_DARK, theme.THEME_LIGHT):
        switch(pref)
        expected = QApplication.palette().color(QPalette.ColorRole.ButtonText).name()
        assert expected in header.styleSheet(), f"{pref} left the header on the previous theme"


def test_a_followed_colour_is_not_read_back_from_its_own_sheet(qtbot, switch) -> None:
    """A sheet naming ``color`` writes it into the widget's palette.

    Reading ``widget.palette()`` to rebuild the sheet therefore fed the
    outgoing colour straight back in, which is how the header stayed white even
    once something did notice the switch.
    """
    root = QWidget()
    QVBoxLayout(root)
    label = QPushButton("Hg")
    root.layout().addWidget(label)
    qtbot.addWidget(root)

    switch(theme.THEME_DARK)
    theme.follow_palette(
        label, lambda p: f"color: {p.color(QPalette.ColorRole.ButtonText).name()};"
    )
    dark_sheet = label.styleSheet()
    switch(theme.THEME_LIGHT)

    assert label.styleSheet() != dark_sheet


def test_glyph_ink_matches_the_button_label(qtbot, switch) -> None:
    """A glyph reads exactly like the text beside it, in both appearances."""
    button = QPushButton("Play")
    qtbot.addWidget(button)
    set_glyph_icon(button, QStyle.StandardPixmap.SP_MediaPlay)

    for pref in (theme.THEME_DARK, theme.THEME_LIGHT):
        switch(pref)
        palette = button.palette()
        ink = _ink(button.icon())
        label = palette.color(QPalette.ColorRole.ButtonText)
        surface = palette.color(QPalette.ColorRole.Button)
        assert abs(ink.lightnessF() - label.lightnessF()) < 0.05, f"{pref}: ink is not the label's"
        assert abs(ink.lightnessF() - surface.lightnessF()) > _MIN_CONTRAST, (
            f"{pref}: the glyph does not read against its button"
        )


def test_a_disabled_glyph_dims_with_its_label(qtbot, switch) -> None:
    button = QPushButton("Play")
    qtbot.addWidget(button)
    set_glyph_icon(button, QStyle.StandardPixmap.SP_MediaPlay)
    switch(theme.THEME_DARK)

    disabled = button.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
    ink = _ink(button.icon(), QIcon.Mode.Disabled)
    assert abs(ink.lightnessF() - disabled.lightnessF()) < 0.05


def test_changing_a_glyph_reuses_its_follower(qtbot) -> None:
    """Play→Pause must replace what is followed, not stack a second listener."""
    from PySide6.QtCore import QObject

    button = QPushButton()
    qtbot.addWidget(button)
    set_glyph_icon(button, QStyle.StandardPixmap.SP_MediaPlay)
    set_glyph_icon(button, QStyle.StandardPixmap.SP_MediaPause)
    set_glyph_icon(button, QStyle.StandardPixmap.SP_MediaPlay)

    followers = [c for c in button.findChildren(QObject) if type(c).__name__ == "_IconFollower"]
    assert len(followers) == 1


@pytest.mark.parametrize("pref", [theme.THEME_DARK, theme.THEME_LIGHT])
def test_severity_badges_read_and_differ(qtbot, switch, pref: str) -> None:
    """A warning and an error must be visible on the window and tellable apart."""
    switch(pref)
    badges = {}
    for severity in ("warning", "error", "info"):
        button = QPushButton()
        button.setIconSize(QSize(16, 16))
        qtbot.addWidget(button)
        set_status_icon(button, severity)
        badges[severity] = button.icon().pixmap(QSize(16, 16)).toImage()

    def disc(image: QImage) -> QColor:
        # Left of centre on the middle row: inside the disc at any pixel ratio,
        # and clear of the glyph whatever font the platform draws it in.
        return image.pixelColor(round(image.width() * 0.18), image.height() // 2)

    window = QApplication.palette().color(QPalette.ColorRole.Window)
    for severity, image in badges.items():
        fill = disc(image)
        assert fill.alpha() > 0, f"{severity}: no badge drawn"
        assert abs(fill.lightnessF() - window.lightnessF()) > 0.2 or fill.saturationF() > 0.3, (
            f"{severity} badge vanishes into the window"
        )
    warning, error = disc(badges["warning"]), disc(badges["error"])
    assert warning.hueF() != pytest.approx(error.hueF(), abs=0.02)


def test_transport_labels_are_not_clipped(qtbot) -> None:
    """Fixed widths cut "Back 1 s" and "Next frame" off once an icon sat beside them."""
    from avialsync.ui.transport import Transport

    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1600, transport.sizeHint().height())
    transport.show()
    qtbot.waitExposed(transport)

    for button in (
        transport._jump_back_btn,
        transport._step_back_btn,
        transport.play_btn,
        transport._step_fwd_btn,
        transport._jump_fwd_btn,
    ):
        assert button.width() >= button.sizeHint().width(), f"{button.text()!r} is clipped"

    width = transport.play_btn.width()
    transport.set_playing(True)
    assert transport.play_btn.width() == width, "toggling playback reflowed the row"


def test_the_values_tab_sits_on_the_same_surface_as_its_neighbours(qtbot) -> None:
    """Its scroll area filled a Window-coloured slab inside the group box, so
    one tab of six sat on a different surface from the rest."""
    from PySide6.QtWidgets import QFrame

    from avialsync.ui.readout_panel import ReadoutPanel

    panel = ReadoutPanel()
    qtbot.addWidget(panel)

    assert panel._scroll.frameShape() == QFrame.Shape.NoFrame
    assert not panel._scroll.viewport().autoFillBackground()
    assert not panel._content.autoFillBackground(), "QScrollArea.setWidget turned it back on"


def test_the_empty_changes_message_wraps_instead_of_clipping(qtbot) -> None:
    """Centred and unwrapped in a narrow sidebar, it lost a word at each end."""
    from avialsync.core.identity_swaps import SwapStore
    from avialsync.core.point_edits import PointEditStore
    from avialsync.ui.annotations import AnnotationStore
    from avialsync.ui.changes_panel import ChangesPanel

    panel = ChangesPanel(AnnotationStore(), PointEditStore(), SwapStore())
    qtbot.addWidget(panel)

    # D-176: the message is an EmptyNote now; its sentence still wraps.
    assert panel._empty.label.wordWrap()


def test_the_empty_state_does_not_fill_a_slab_behind_its_message(qtbot) -> None:
    """``QScrollArea.setWidget`` turns the content's fill back on, so switching
    it off before the call — as this did — never took effect."""
    from PySide6.QtWidgets import QScrollArea

    from avialsync.ui.empty_state import EmptyState

    empty = EmptyState()
    qtbot.addWidget(empty)
    scroll = empty.findChild(QScrollArea)
    assert scroll is not None
    assert not scroll.widget().autoFillBackground()
