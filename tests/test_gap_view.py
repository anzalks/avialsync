"""Streams that stop between a session's parts, and the collapsed view (D-218)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt

from avialsync.ui.transport import Transport


def _transport(qtbot) -> Transport:
    transport = Transport()
    qtbot.addWidget(transport)
    transport.resize(1220, 140)
    transport.show()
    qtbot.waitExposed(transport)
    transport.set_bounds(0.0, 110.0)
    return transport


def test_a_lane_is_empty_where_its_stream_recorded_nothing_between_parts(qtbot) -> None:
    transport = _transport(qtbot)
    transport.set_source_coverage("cam", 0.0, 110.0, "video", holes=[(10.0, 60.0)])
    lane = transport.overview._coverage_payloads()[0]
    assert lane.spans == ((0.0, 10.0), (60.0, 110.0))
    assert not lane.covers(30.0) and lane.covers(65.0)


def test_a_grouped_lane_keeps_its_members_gaps(qtbot) -> None:
    transport = _transport(qtbot)
    transport.set_source_coverage("trial_1.avi", 0.0, 10.0, "video", "camera 1")
    transport.set_source_coverage("trial_2.avi", 60.0, 70.0, "video", "camera 1")
    (lane,) = transport.overview._coverage_payloads()
    assert lane.members == 2
    assert lane.spans == ((0.0, 10.0), (60.0, 70.0))


def test_collapsing_skips_only_time_no_stream_recorded(qtbot) -> None:
    transport = _transport(qtbot)
    transport.set_source_coverage("cam", 0.0, 110.0, "video", holes=[(10.0, 60.0), (70.0, 100.0)])
    transport.set_source_coverage("enc", 0.0, 110.0, "data", holes=[(10.0, 60.0)])
    transport.set_collapse_gaps(True)
    # The encoder recorded 70-100 s, so only 10-60 s goes.
    assert transport.warp.gaps == ((10.0, 60.0),)
    overview = transport.overview
    # The strip runs 0-60 s of view time across its width.
    width = overview.width() - overview._LABEL_WIDTH - 1
    middle = overview._LABEL_WIDTH + width / 6  # view time 10 s: the break
    assert overview._time_at_x(middle) == pytest.approx(60.0, abs=0.2)
    assert overview._content_x(30.0) == overview._content_x(10.0)
    # The slider has no track for the collapsed gap.
    assert transport._t_from_slider(5000) == pytest.approx(80.0)
    assert transport._time_to_frac(80.0) == pytest.approx(0.5)
    assert "Collapsed" in overview._event_detail(overview._content_x(10.0), 10)

    transport.set_collapse_gaps(False)
    assert not transport.warp
    assert transport._t_from_slider(5000) == pytest.approx(55.0)


def test_a_gap_between_parts_is_not_listed_as_a_data_gap(qtbot) -> None:
    transport = _transport(qtbot)
    transport.set_source_coverage("enc", 0.0, 110.0, "data", holes=[(10.0, 60.0)])
    # The last sample before the hole stamps the gap, just short of it.
    transport.set_gap_events([9.995, 65.0])
    assert [time for time, _ in transport.overview._gap_events] == [65.0]


def test_seeking_on_a_break_lands_on_the_data_after_it(qtbot) -> None:
    transport = _transport(qtbot)
    transport.set_source_coverage("cam", 0.0, 110.0, "video", holes=[(10.0, 60.0)])
    transport.set_collapse_gaps(True)
    seeks: list[float] = []
    transport.overview.seek_requested.connect(seeks.append)
    overview = transport.overview
    qtbot.mouseClick(
        overview,
        Qt.MouseButton.LeftButton,
        pos=QPoint(overview._content_x(10.0), overview.height() // 2),
    )
    assert seeks and seeks[0] == pytest.approx(60.0, abs=0.5)


def test_playback_goes_on_from_the_data_after_a_collapsed_gap(window, qtbot) -> None:
    transport = window.transport
    transport.set_bounds(0.0, 110.0)
    transport.set_source_coverage("cam", 0.0, 110.0, "video", holes=[(10.0, 60.0)])
    transport.set_collapse_gaps(True)
    window._recompute_bounds()
    window.player.seek(20.0)
    window.player.set_playing(True)
    window.player._on_tick()
    assert window.clock.state.t >= 60.0
    window.player.set_playing(False)


def test_an_aol_experiments_streams_stop_between_its_trials(window, qtbot, tmp_path) -> None:
    from avialsync.loaders.aol_microscope_session import AOLMicroscopeTrialSource
    from avialsync.ui.controllers import drop_controller, gap_view
    from tests.test_aol_microscope_trial import _trial

    experiment = tmp_path / "experiment_1"
    experiment.mkdir()
    _trial(experiment / "12-00-00")
    _trial(experiment / "12-10-00", start_ms=1_700_000_600_000)
    layout = AOLMicroscopeTrialSource().scan(experiment, None)
    drop_controller.apply_session_layout(window, layout)
    item = layout.items[0]
    window._route_import_candidate(item.path, item.loader, dict(item.config))
    source_id = str(experiment)
    qtbot.waitUntil(lambda: source_id in window.transport.overview._coverage, timeout=10_000)
    gap_view.refresh_holes(window)
    spans = window.transport.overview.source_spans(source_id)
    assert len(spans) == 2
    assert spans[1][0] - spans[0][1] == pytest.approx(600.0 - 0.029, abs=0.01)
    window.transport.set_collapse_gaps(True)
    assert len(window.transport.warp.gaps) == 1


def test_the_preference_and_the_view_action_are_one_switch(window) -> None:
    from avialsync.ui.controllers import gap_view

    action = window._act_collapse_gaps
    try:
        action.setChecked(False)
        assert not gap_view.collapse_enabled()
        assert not window.transport.overview._collapse_gaps
        action.setChecked(True)
        assert gap_view.collapse_enabled() and window.transport.overview._collapse_gaps
    finally:
        action.setChecked(True)


@pytest.fixture
def window(qapp, qtbot):
    from avialsync.ui.main_window import MainWindow

    main = MainWindow()
    qtbot.addWidget(main)
    yield main
    main.close()


def test_an_aol_joined_camera_stops_between_its_trials(window, qtbot, tmp_path) -> None:
    from avialsync.core.registry import LoaderRegistry
    from avialsync.loaders.aol_camera_join import AOLJoinedCameraSource
    from avialsync.loaders.aol_microscope_session import AOLMicroscopeTrialSource
    from avialsync.ui.controllers import drop_controller, gap_view
    from tests.test_aol_camera_join import _camera
    from tests.test_aol_microscope_trial import _trial

    experiment = tmp_path / "2026-09-03" / "experiment_1"
    experiment.mkdir(parents=True)
    first = _trial(experiment / "12-00-00")
    second = _trial(experiment / "12-10-00", start_ms=1_700_000_600_000)
    _camera(first, "FaceCam", 5, 10.0, 40)
    _camera(second, "FaceCam", 5, 10.0, 140)
    layout = AOLMicroscopeTrialSource().scan(experiment, LoaderRegistry(plugin_dirs=[]))
    drop_controller.apply_session_layout(window, layout)
    item = next(item for item in layout.items if item.loader is AOLJoinedCameraSource)
    window._route_import_candidate(item.path, item.loader, dict(item.config))
    source_id = str(item.path)
    qtbot.waitUntil(lambda: source_id in window.video_grid.pane_paths(), timeout=10_000)
    qtbot.waitUntil(lambda: source_id in window.transport.overview._coverage, timeout=10_000)
    gap_view.refresh_holes(window)
    spans = window.transport.overview.source_spans(source_id)
    assert len(spans) == 2, spans


def test_plots_draw_the_collapsed_time_too(window, qtbot, tmp_path) -> None:
    """D-218: a plot row does not spend its width on time no source recorded."""
    import numpy as np

    from avialsync.loaders.aol_microscope_session import AOLMicroscopeTrialSource
    from avialsync.loaders.aol_trial_encoder import AOLTrialEncoderSource
    from avialsync.ui.controllers import drop_controller, gap_view
    from tests.test_aol_microscope_trial import _trial
    from tests.test_aol_trial_encoder import _wheel

    experiment = tmp_path / "experiment_1"
    experiment.mkdir()
    first = _trial(experiment / "12-00-00")
    second = _trial(experiment / "12-10-00", start_ms=1_700_000_600_000)
    for folder in (first, second):
        _wheel(folder, np.arange(0.0, 0.02, 0.001), np.ones(20))
    layout = AOLMicroscopeTrialSource().scan(experiment, None)
    drop_controller.apply_session_layout(window, layout)
    item = next(item for item in layout.items if item.loader is AOLTrialEncoderSource)
    window._route_import_candidate(item.path, item.loader, dict(item.config))
    qtbot.waitUntil(lambda: bool(window.plot_pane.channels), timeout=10_000)
    qtbot.waitUntil(lambda: str(item.path) in window.transport.overview._coverage, timeout=10_000)
    gap_view.refresh_holes(window)
    gap_view.set_collapse(window, True)
    pane = window.plot_pane
    assert pane._warp.gaps, "the plots were not given the collapsed gaps"
    pane.set_window_duration(1.0)
    window.player.seek(0.0)
    # Both trials fit on one page, the 10 minutes between them drawn as a break.
    assert pane.x_of(600.0) - pane.x_of(0.0) < 0.1
    assert pane.master_at(pane.x_of(600.005)) == pytest.approx(600.005)
    gap_view.set_collapse(window, False)
    assert not pane._warp
    assert pane.x_of(600.0) is None or pane.x_of(600.0) - pane.x_of(0.0) == pytest.approx(600.0)
    gap_view.set_collapse(window, True)
