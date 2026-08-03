"""Theme tests for appearance-only changes on all supported appearances."""

import gc
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSlider, QWidget

from avialsync.ui import theme
from avialsync.ui.plot_pane import PlotPane
from avialsync.ui.transport import Transport


def test_explicit_palettes_define_readable_tooltip_colours() -> None:
    """Tooltips remain readable through palette roles, not a global stylesheet."""
    dark = theme._palette_with_surfaces(True, QColor("#b455ff"))
    light = theme._palette_with_surfaces(False, QColor("#b455ff"))

    assert dark.color(QPalette.ColorRole.ToolTipBase) == QColor("#2d2d2d")
    assert dark.color(QPalette.ColorRole.ToolTipText) == QColor("#f5f5f5")
    assert light.color(QPalette.ColorRole.ToolTipBase) == QColor("#ffffff")
    assert light.color(QPalette.ColorRole.ToolTipText) == QColor("#1b1b1b")


def test_explicit_appearances_preserve_the_platform_accent() -> None:
    """A custom OS accent must flow into links and interactive controls."""
    accent = QColor("#b455ff")
    light = theme._palette_with_surfaces(False, accent)
    dark = theme._palette_with_surfaces(True, accent)

    assert light.color(QPalette.ColorRole.Link) == accent
    assert dark.color(QPalette.ColorRole.Link) == accent
    assert light.color(QPalette.ColorRole.Highlight) == accent


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


def test_toggle_applies_light_then_restores_system_palette(monkeypatch) -> None:
    """The visible toggle retains the accent without installing a control stylesheet."""
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
    assert bool(app.property("avialsync_theme_dark")) is False

    theme.apply_theme(app, theme.THEME_SYSTEM)
    assert app.palette().color(QPalette.ColorRole.Highlight) == native_accent
    assert app.styleSheet() == ""


def test_theme_switch_preserves_seek_and_plot_interaction_state(monkeypatch, qtbot) -> None:
    """Themes change colours only; seek semantics and plot navigation survive intact."""
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
    monkeypatch.delitem(theme._system_palettes, id(app), raising=False)

    transport = Transport()
    plot = PlotPane()
    qtbot.addWidget(transport)
    qtbot.addWidget(plot)
    transport.resize(1000, 220)
    transport.show()
    plot.show()
    transport.set_bounds(0.0, 100.0)
    transport.set_time(37.25)
    transport.set_playing(True)
    transport.ab_in()
    plot.follow_playhead = True
    plot_item = plot.graphics_layout.addPlot()
    plot_item.setXRange(12.0, 38.0, padding=0)
    qtbot.wait(10)

    option = QStyleOptionSlider()
    transport.slider.initStyleOption(option)
    style = transport.slider.style()
    before = {
        "slider_geometry": transport.slider.geometry(),
        "slider_value": transport.slider.value(),
        "slider_range": (transport.slider.minimum(), transport.slider.maximum()),
        "slider_orientation": transport.slider.orientation(),
        "groove": style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            transport.slider,
        ),
        "handle": style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            transport.slider,
        ),
        "playing": transport.play_btn.isChecked(),
        "ab_in": transport._ab_in_t,
        "follow_playhead": plot.follow_playhead,
        "plot_range": tuple(plot_item.viewRange()[0]),
        "style_class": app.style().metaObject().className(),
    }

    for preference in (theme.THEME_DARK, theme.THEME_LIGHT, theme.THEME_SYSTEM):
        theme.apply_theme(app, preference)
        qtbot.wait(10)
        transport.slider.initStyleOption(option)
        assert transport.slider.geometry() == before["slider_geometry"]
        assert transport.slider.value() == before["slider_value"]
        assert (transport.slider.minimum(), transport.slider.maximum()) == before["slider_range"]
        assert transport.slider.orientation() == before["slider_orientation"]
        assert (
            style.subControlRect(
                QStyle.ComplexControl.CC_Slider,
                option,
                QStyle.SubControl.SC_SliderGroove,
                transport.slider,
            )
            == before["groove"]
        )
        assert (
            style.subControlRect(
                QStyle.ComplexControl.CC_Slider,
                option,
                QStyle.SubControl.SC_SliderHandle,
                transport.slider,
            )
            == before["handle"]
        )
        assert transport.play_btn.isChecked() == before["playing"]
        assert transport._ab_in_t == before["ab_in"]
        assert plot.follow_playhead == before["follow_playhead"]
        assert tuple(plot_item.viewRange()[0]) == pytest.approx(before["plot_range"])
        assert app.style().metaObject().className() == before["style_class"]
        assert app.styleSheet() == ""


def test_font_preference_scales_from_and_restores_the_system_font(monkeypatch, qtbot) -> None:
    """Small/Medium/Large apply to existing controls, while System restores the base size."""
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
    monkeypatch.delitem(theme._font_scales, id(app), raising=False)
    original_size = app.font().pointSizeF()
    transport = Transport()
    qtbot.addWidget(transport)
    original_time_size = transport._time_edit.font().pointSizeF()

    theme.apply_font_size(app, theme.FONT_LARGE)
    qtbot.wait(10)
    assert app.font().pointSizeF() > original_size
    assert transport._time_edit.font().pointSizeF() > original_time_size
    assert values["font/preference"] == theme.FONT_LARGE

    theme.apply_font_size(app, theme.FONT_SYSTEM)
    qtbot.wait(10)
    assert app.font().pointSizeF() == original_size
    assert transport._time_edit.font().pointSizeF() == original_time_size


# ── The font walk may not be interruptible by the collector ───────────
#
# The failure these guard against is a SIGSEGV, which cannot be asserted on:
# the process dies without raising, so a test that provoked it would take the
# run down with it rather than report. What is checked instead is the property
# that makes it impossible — that no Python object can be freed while Qt is
# handing over widget pointers (D-065).


def test_the_widget_snapshot_is_taken_with_the_collector_held_off(qtbot) -> None:
    """Collecting a cycle mid-snapshot frees widgets Qt has already handed over."""
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    qtbot.addWidget(window)
    observed: list[bool] = []

    real_top_level = app.topLevelWidgets

    def spy() -> list[QWidget]:
        observed.append(gc.isenabled())
        return real_top_level()

    app.topLevelWidgets = spy  # type: ignore[method-assign]
    try:
        theme._live_widgets(app)
    finally:
        del app.topLevelWidgets

    assert observed, "the snapshot did not go through topLevelWidgets"
    assert not any(observed), "widget pointers were converted with the collector armed"


def test_the_collector_is_left_as_it_was_found() -> None:
    """Pausing collection around the snapshot must not outlive it."""
    app = QApplication.instance() or QApplication([])

    assert gc.isenabled(), "precondition: the suite runs with collection on"
    theme._live_widgets(app)
    assert gc.isenabled(), "the collector was left disabled"

    gc.disable()
    try:
        theme._live_widgets(app)
        assert not gc.isenabled(), "a caller's disabled collector was switched back on"
    finally:
        gc.enable()


def test_the_walk_still_reaches_widgets_nested_in_a_window(qtbot) -> None:
    """Rooting the snapshot in the window trees may not narrow what it covers."""
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    child = QWidget(window)
    grandchild = QWidget(child)
    qtbot.addWidget(window)

    reached = theme._live_widgets(app)

    for widget in (window, child, grandchild):
        assert widget in reached, "a widget in a live window tree was not reached"


def test_the_walk_reaches_a_parentless_widget(qtbot) -> None:
    """A widget with no parent is a top-level window in Qt, so it is still covered."""
    app = QApplication.instance() or QApplication([])
    orphan = QWidget()
    qtbot.addWidget(orphan)

    assert orphan in theme._live_widgets(app)


def test_demo_launcher_uses_the_application_theme() -> None:
    """The demo must use the same saved appearance as the production app."""
    launcher = Path("tools/launch_demo.py").read_text(encoding="utf-8")
    application = Path("src/avialsync/__main__.py").read_text(encoding="utf-8")
    assert "from avialsync.__main__ import main" in launcher
    assert "load_saved_theme(app)" in application
    assert "ToolTipBase" not in launcher
