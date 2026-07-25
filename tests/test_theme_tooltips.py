"""Theme tests for readable tooltips on all supported appearances."""

from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from kinochronix.ui import theme


def test_tooltip_styles_define_explicit_foreground_and_background() -> None:
    """Tooltips stay readable even when a native platform tooltip is unreliable."""
    dark = theme._palette_with_surfaces(True, QColor("#b455ff"))
    light = theme._palette_with_surfaces(False, QColor("#b455ff"))

    dark_qss = theme._qss(dark, dark=True, native=False)
    light_qss = theme._qss(light, dark=False, native=False)

    assert "QToolTip" in dark_qss
    assert "background-color: #2d2d2d" in dark_qss
    assert "color: #f5f5f5" in dark_qss
    assert "background-color: #ffffff" in light_qss
    assert "color: #1b1b1b" in light_qss


def test_explicit_appearances_preserve_the_platform_accent() -> None:
    """A custom OS accent must flow into links and interactive controls."""
    accent = QColor("#b455ff")
    light = theme._palette_with_surfaces(False, accent)
    dark = theme._palette_with_surfaces(True, accent)

    assert light.color(QPalette.ColorRole.Link) == accent
    assert dark.color(QPalette.ColorRole.Link) == accent
    assert "#b455ff" in theme._qss(light, dark=False, native=False)


def test_macos_accent_uses_the_system_preference_not_selection_blue(monkeypatch) -> None:
    """macOS custom-painted elements must use its Accent Color setting."""
    palette = QPalette()
    monkeypatch.setattr(theme, "_macos_accent", None)
    monkeypatch.setattr(theme.sys, "platform", "darwin")
    monkeypatch.setattr(
        theme.subprocess,
        "run",
        lambda *_args, **_kwargs: type("Result", (), {"stdout": "5\n"})(),
    )

    assert theme.system_accent(palette).name() == "#bf5af2"


def test_system_qss_applies_the_platform_accent_to_the_seek_control() -> None:
    """System mode keeps native controls while making the seek accent unambiguous."""
    palette = QPalette()
    qss = theme._qss(palette, dark=False, native=True, accent=QColor("#b455ff"))

    assert "QToolTip" in qss
    assert "QSlider" in qss
    assert "#b455ff" in qss


def test_toggle_applies_light_then_restores_system_palette(monkeypatch) -> None:
    """The visible toggle must retain the captured native accent in every mode."""
    values: dict[str, object] = {"theme/preference": theme.THEME_SYSTEM}

    class Settings:
        def __init__(self, *_args: object) -> None:
            pass

        def value(self, key: str, default: object = None) -> object:
            return values.get(key, default)

        def setValue(self, key: str, value: object) -> None:
            values[key] = value

    monkeypatch.setattr(theme, "QSettings", Settings)
    app = QApplication.instance() or QApplication([])
    native_accent = app.palette().color(QPalette.ColorRole.Highlight)

    theme.apply_theme(app, theme.THEME_LIGHT)
    assert values["theme/preference"] == theme.THEME_LIGHT
    assert app.palette().color(QPalette.ColorRole.Link) == native_accent
    assert bool(app.property("kinochronix_theme_dark")) is False

    theme.apply_theme(app, theme.THEME_SYSTEM)
    assert app.palette().color(QPalette.ColorRole.Highlight) == native_accent
    assert "QSlider" in app.styleSheet()


def test_font_preference_scales_from_and_restores_the_system_font(monkeypatch) -> None:
    """Small/Medium/Large are relative preferences, while System is exact restoration."""
    values: dict[str, object] = {"font/preference": theme.FONT_SYSTEM}

    class Settings:
        def __init__(self, *_args: object) -> None:
            pass

        def value(self, key: str, default: object = None) -> object:
            return values.get(key, default)

        def setValue(self, key: str, value: object) -> None:
            values[key] = value

    monkeypatch.setattr(theme, "QSettings", Settings)
    app = QApplication.instance() or QApplication([])
    monkeypatch.delitem(theme._system_fonts, id(app), raising=False)
    original_size = app.font().pointSizeF()

    theme.apply_font_size(app, theme.FONT_LARGE)
    assert app.font().pointSizeF() > original_size
    assert values["font/preference"] == theme.FONT_LARGE

    theme.apply_font_size(app, theme.FONT_SYSTEM)
    assert app.font().pointSizeF() == original_size


def test_demo_launcher_uses_the_application_theme() -> None:
    """The demo must use the same saved appearance as the production app."""
    launcher = Path("tools/launch_demo.py").read_text(encoding="utf-8")
    assert "load_saved_theme(app)" in launcher
    assert "ToolTipBase" not in launcher
