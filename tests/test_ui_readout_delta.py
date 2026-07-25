"""Tests for ReadoutPanel.show_delta and set_camera_states."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(app):
    from avialview.ui.readout_panel import ReadoutPanel

    p = ReadoutPanel()
    p.show()
    return p


class TestShowDelta:
    def test_show_delta_no_crash(self, panel):
        panel.show_delta(1.0, 4.0)

    def test_show_delta_dt_positive(self, panel):
        panel.show_delta(2.0, 5.0)
        text = panel._delta_t_lbl.text()
        assert "3.000" in text or "+3.000" in text

    def test_show_delta_dt_negative(self, panel):
        panel.show_delta(5.0, 2.0)
        assert "-3.000" in panel._delta_t_lbl.text()

    def test_clear_delta_hides_label(self, panel):
        panel.show_delta(1.0, 2.0)
        panel.clear_delta()
        assert not panel._delta_label.isVisible() or panel._delta_rows == {}

    def test_show_delta_with_camera_states(self, panel):
        panel.show_delta(0.0, 1.0, camera_states=[("cam1", 0.0, 30.0)])

    def test_show_delta_clears_previous(self, panel):
        panel.show_delta(1.0, 3.0)
        initial_rows = len(panel._delta_rows)
        panel.show_delta(2.0, 4.0)
        assert len(panel._delta_rows) == initial_rows


class TestSetCameraStates:
    def test_empty_states_clears_rows(self, panel):
        panel.set_camera_states([("cam1", 1.0, 30.0)])
        panel.set_camera_states([])
        assert panel._cam_rows == []

    def test_populated_states_adds_rows(self, panel):
        panel.set_camera_states([("cam1", 0.5, 25.0)])
        assert len(panel._cam_rows) == 1

    def test_multiple_cameras(self, panel):
        states = [("cam1", 1.0, 30.0), ("cam2", 2.0, 60.0)]
        panel.set_camera_states(states)
        assert len(panel._cam_rows) == 2

    def test_replaces_previous(self, panel):
        panel.set_camera_states([("cam1", 0.0, 30.0), ("cam2", 0.0, 30.0)])
        panel.set_camera_states([("cam1", 0.0, 30.0)])
        assert len(panel._cam_rows) == 1
