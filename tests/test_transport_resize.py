"""Regression tests: transport A/B pins must realign after window resize."""

import pytest
from PySide6.QtWidgets import QStyle, QStyleOptionSlider

from kinochronix.ui.transport import Transport


@pytest.fixture
def transport(qtbot):
    t = Transport()
    qtbot.addWidget(t)
    t.resize(700, 50)
    t.show()
    qtbot.waitExposed(t)
    qtbot.wait(20)
    return t


# ── helper: compute expected pin x at current slider geometry ──────────────


def _expected_pin_x(transport: Transport, frac: float) -> int:
    """Return the correct x for a pin at *frac* given the slider's current geometry."""
    opt = QStyleOptionSlider()
    transport.slider.initStyleOption(opt)
    groove = transport.slider.style().subControlRect(
        QStyle.ComplexControl.CC_Slider,
        opt,
        QStyle.SubControl.SC_SliderGroove,
        transport.slider,
    )
    g_global = transport.slider.mapToParent(groove.topLeft())
    return g_global.x() + int(frac * groove.width()) - 1


# ── tests ──────────────────────────────────────────────────────────────────


def test_pin_in_realigns_after_resize(qtbot, transport):
    """A/B in-pin must sit at the correct groove fraction after a resize."""
    transport.set_bounds(0.0, 10.0)
    transport.set_time(5.0)  # slider at midpoint → frac 0.5
    transport._on_ab_in()

    assert transport._pin_in.isVisible()
    # Sanity: pin is correct at initial size
    assert transport._pin_in.geometry().x() == _expected_pin_x(transport, 0.5)

    # Resize to a wider width — groove coordinates change
    transport.resize(transport.width() + 300, transport.height())
    qtbot.wait(20)

    expected = _expected_pin_x(transport, 0.5)
    actual = transport._pin_in.geometry().x()
    assert actual == expected, f"Pin did not realign: actual={actual}, expected={expected}"


def test_pin_out_realigns_after_resize(qtbot, transport):
    """A/B out-pin realigns after resize (non-midpoint fraction)."""
    transport.set_bounds(0.0, 12.0)
    transport.set_time(9.0)  # frac = 9/12 = 0.75
    transport._on_ab_out()

    assert transport._pin_out.isVisible()

    transport.resize(transport.width() // 2, transport.height())
    qtbot.wait(20)

    expected = _expected_pin_x(transport, 0.75)
    assert transport._pin_out.geometry().x() == expected, (
        f"Out-pin did not realign: actual={transport._pin_out.geometry().x()}, expected={expected}"
    )


def test_both_pins_realign_after_resize(qtbot, transport):
    """Both A/B pins realign independently after a single resize."""
    transport.set_bounds(0.0, 10.0)
    transport.set_time(2.0)
    transport._on_ab_in()  # frac 0.2
    transport.set_time(8.0)
    transport._on_ab_out()  # frac 0.8

    transport.resize(transport.width() + 200, transport.height())
    qtbot.wait(20)

    assert transport._pin_in.geometry().x() == _expected_pin_x(transport, 0.2), (
        "In-pin not realigned"
    )
    assert transport._pin_out.geometry().x() == _expected_pin_x(transport, 0.8), (
        "Out-pin not realigned"
    )


def test_hidden_pins_stay_hidden_after_resize(qtbot, transport):
    """No pins are shown after resize if none were set."""
    transport.resize(transport.width() + 100, transport.height())
    qtbot.wait(20)
    assert not transport._pin_in.isVisible()
    assert not transport._pin_out.isVisible()


def test_pin_survives_multiple_resizes(qtbot, transport):
    """Pin remains correctly positioned across consecutive resizes."""
    transport.set_bounds(0.0, 20.0)
    transport.set_time(10.0)  # frac 0.5
    transport._on_ab_in()

    for delta in (150, -100, 200, -50):
        transport.resize(transport.width() + delta, transport.height())
        qtbot.wait(20)
        expected = _expected_pin_x(transport, 0.5)
        actual = transport._pin_in.geometry().x()
        assert actual == expected, (
            f"Pin wrong at width {transport.width()}: actual={actual}, expected={expected}"
        )
