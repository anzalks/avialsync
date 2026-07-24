import math

from hypothesis import given
from hypothesis import strategies as st

from kinochronix.core.timeline import MasterClock, TimeMap


def test_master_clock_basic():
    clock = MasterClock()
    assert not clock.state.playing
    assert clock.state.rate == 1.0
    assert clock.state.t == 0.0

    # Callback test
    t_updates = []
    clock.subscribe(lambda t: t_updates.append(t))

    clock.set_bounds(0.0, 10.0)
    assert t_updates == [0.0]

    clock.seek(5.0)
    assert clock.state.t == 5.0
    assert t_updates[-1] == 5.0

    clock.play()
    assert clock.state.playing

    clock.advance(100.0)  # initializes _last_monotonic
    clock.advance(101.0)  # delta = 1.0
    assert clock.state.t == 6.0
    assert t_updates[-1] == 6.0

    # Advance backwards monotonic (should be ignored/clamped to 0)
    clock.advance(100.0)
    assert clock.state.t == 6.0

    clock.pause()
    assert not clock.state.playing
    clock.advance(102.0)
    assert clock.state.t == 6.0  # no change while paused

    # Play again and clamp bounds
    clock.play()
    clock.advance(103.0)  # init
    clock.advance(109.0)  # delta = 6.0, t = 12.0
    # should be clamped to 10.0 and paused
    assert clock.state.t == 10.0
    assert not clock.state.playing

    # Seek below bounds
    clock.seek(-5.0)
    assert clock.state.t == 0.0
    assert not clock.state.playing


def test_master_clock_rate():
    clock = MasterClock()
    clock.set_bounds(0.0, 100.0)
    clock.play()

    clock.advance(0.0)
    clock.set_rate(2.0)
    assert clock.state.rate == 2.0

    # Rate sets should re-anchor monotonic to prevent jumps if elapsed time happened
    clock.advance(1.0)
    assert clock.state.t == 0.0  # Delta ignored on first advance after set_rate

    clock.advance(2.0)
    assert clock.state.t == 2.0  # 1.0 delta * 2.0 rate

    # Check bounds clamping on rate
    clock.set_rate(10.0)
    assert clock.state.rate == 8.0  # max 8.0

    clock.set_rate(0.01)
    assert clock.state.rate == 0.1  # min 0.1


def test_zero_duration_bounds():
    clock = MasterClock()
    clock.set_bounds(5.0, 5.0)
    clock.seek(0.0)
    assert clock.state.t == 5.0

    clock.play()
    clock.advance(0.0)
    clock.advance(1.0)
    assert clock.state.t == 5.0
    assert not clock.state.playing


def test_inverted_bounds():
    clock = MasterClock()
    clock.set_bounds(10.0, 5.0)
    assert clock.state.bounds == (5.0, 10.0)


def test_pause_while_paused():
    clock = MasterClock()
    clock.pause()  # No-op
    assert not clock.state.playing


def test_play_while_playing():
    clock = MasterClock()
    clock.set_bounds(0.0, 10.0)
    clock.play()
    clock.advance(0.0)
    clock.play()  # No-op
    clock.advance(1.0)
    assert clock.state.t == 1.0


def test_advance_while_paused():
    clock = MasterClock()
    clock.advance(1.0)
    assert clock.state.t == 0.0


@given(
    offset=st.floats(min_value=-1e6, max_value=1e6),
    drift_ppm=st.floats(min_value=-1000.0, max_value=1000.0),
    t_source=st.floats(min_value=-1e6, max_value=1e6),
)
def test_timemap_inverses(offset: float, drift_ppm: float, t_source: float):
    # Skip NaNs and infs for exact identity tests
    if (
        math.isnan(offset)
        or math.isnan(drift_ppm)
        or math.isnan(t_source)
        or math.isinf(offset)
        or math.isinf(drift_ppm)
        or math.isinf(t_source)
    ):
        return

    tmap = TimeMap(offset=offset, drift_ppm=drift_ppm)
    t_master = tmap.to_master(t_source)
    t_source_roundtrip = tmap.to_source(t_master)

    assert abs(t_source - t_source_roundtrip) < 1e-9


@given(
    t_master=st.floats(min_value=-1e6, max_value=1e6),
    new_offset=st.floats(min_value=-100.0, max_value=100.0),
    new_drift=st.floats(min_value=-10.0, max_value=10.0),
)
def test_timemap_continuity_on_update(t_master: float, new_offset: float, new_drift: float):
    if (
        math.isnan(t_master)
        or math.isnan(new_offset)
        or math.isnan(new_drift)
        or math.isinf(t_master)
        or math.isinf(new_offset)
        or math.isinf(new_drift)
    ):
        return

    tmap = TimeMap(offset=5.0, drift_ppm=1.0)
    t_source_before = tmap.to_source(t_master)

    tmap.update(new_offset, new_drift, t_master)
    t_source_after = tmap.to_source(t_master)

    assert abs(t_source_before - t_source_after) < 1e-12


def test_drift_closed_form():
    """Drift of 2ppm over 1h maps within float64 precision of closed form value."""
    tmap = TimeMap(offset=0.0, drift_ppm=2.0)
    t_master = 3600.0  # 1 hour

    # Expected: t_source = t_master + drift * t_master
    # 3600 + (2.0 * 1e-6) * 3600 = 3600 + 0.0072 = 3600.0072
    expected = 3600.0072
    actual = tmap.to_source(t_master)

    assert abs(actual - expected) < 1e-12


def test_timemap_properties():
    tmap = TimeMap(offset=1.23, drift_ppm=4.5)
    assert tmap.offset == 1.23
    assert tmap.drift_ppm == 4.5
