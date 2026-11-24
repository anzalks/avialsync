"""Tests for signal grouping across Sources, Plots, and the Values inspector."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QLabel
from shiboken6 import isValid

from avialsync.core.channel_reader import ChannelKey
from avialsync.core.pyramid import PyramidBuilder
from avialsync.core.session import SessionState
from avialsync.ui import recovery
from avialsync.ui.channel_tree import channel_tree_paths, compact_channel_label
from avialsync.ui.main_window import MainWindow
from avialsync.ui.plot_modes import PLOT_MODE_GROUPED, PLOT_MODE_STACKED
from avialsync.ui.sidebar import SensorInfoWidget


def test_channel_tree_paths_groups_hyphens_stems_banks_and_elides_nwb_wrappers() -> None:
    imu = ["Acc-X", "Acc-Y", "Acc-Z", "Gyr-X", "Gyr-Y", "Gyr-Z", "TTL-1", "TTL-2"]
    imu_paths = channel_tree_paths(imu)
    assert imu_paths["Acc-X"] == ["Acc", "X"]
    assert imu_paths["Gyr-Z"] == ["Gyr", "Z"]
    assert imu_paths["TTL-1"] == ["TTL", "1"]

    # Preserves first-token prefix grouping while nesting branching compound stems
    pose = [
        "head_bar_x",
        "head_bar_y",
        "tail_base_x",
        "tail_base_y",
        "tail_tip_x",
        "tail_tip_y",
    ]
    pose_paths = channel_tree_paths(pose)
    assert pose_paths["head_bar_x"] == ["head", "bar_x"]
    assert pose_paths["tail_base_x"] == ["tail", "base", "x"]
    assert pose_paths["tail_tip_y"] == ["tail", "tip", "y"]

    # Multi-animal pose nests animal -> bodypart -> axis
    multi = [
        "mouse1_snout_x",
        "mouse1_snout_y",
        "mouse1_ear_x",
        "mouse1_ear_y",
        "mouse2_snout_x",
        "mouse2_snout_y",
    ]
    multi_paths = channel_tree_paths(multi)
    assert multi_paths["mouse1_snout_x"] == ["mouse1", "snout", "x"]

    # Multi-bank numbered hardware channels group without wrapping a single-bank sensor
    mixed_hw = [f"CH{i}" for i in range(1, 9)] + [f"ADC{i}" for i in range(1, 4)]
    hw_paths = channel_tree_paths(mixed_hw)
    assert hw_paths["CH1"] == ["CH", "CH1"]
    assert hw_paths["ADC2"] == ["ADC", "ADC2"]
    assert channel_tree_paths(["ch0", "ch1", "ch2", "ch3"])["ch0"] == ["ch0"]

    # NWB redundant wrapper segments (RoiResponseSeries / SpatialSeries) collapse cleanly
    nwb = [
        "Position.SpatialSeries.x",
        "Position.SpatialSeries.y",
        "ophys.DfOverF.RoiResponseSeries.roi0",
        "ophys.DfOverF.RoiResponseSeries.roi1",
        "ophys.Fluorescence.RoiResponseSeries.roi0",
        "ophys.Fluorescence.RoiResponseSeries.roi1",
        "trials",
    ]
    nwb_paths = channel_tree_paths(nwb)
    assert nwb_paths["Position.SpatialSeries.x"] == ["Position", "x"]
    assert nwb_paths["ophys.DfOverF.RoiResponseSeries.roi0"] == ["ophys", "DfOverF", "roi0"]
    assert nwb_paths["ophys.Fluorescence.RoiResponseSeries.roi1"] == [
        "ophys",
        "Fluorescence",
        "roi1",
    ]
    assert nwb_paths["trials"] == ["trials"]
    assert (
        compact_channel_label(
            "ophys.DfOverF.RoiResponseSeries.roi0",
            nwb_paths["ophys.DfOverF.RoiResponseSeries.roi0"],
        )
        == "DfOverF · roi0"
    )


def test_sidebar_sensor_tree_shows_group_counts_and_auto_collapses_dense_or_hidden_groups(
    qapp, qtbot
) -> None:
    channels = (
        ["Position.SpatialSeries.x", "Position.SpatialSeries.y"]
        + [f"ophys.DfOverF.RoiResponseSeries.roi{i}" for i in range(24)]
        + [f"ophys.Fluorescence.RoiResponseSeries.roi{i}" for i in range(10)]
    )
    visibility = {ch: not ch.startswith("ophys.Fluorescence.") for ch in channels}
    for i in range(16, 24):
        visibility[f"ophys.DfOverF.RoiResponseSeries.roi{i}"] = False

    card = SensorInfoWidget("/tmp/session.nwb", channels, channel_visibility=visibility)
    qtbot.addWidget(card)

    by_name = {g.text(0): g for g in card._group_items}
    assert {"Position", "ophys", "DfOverF", "Fluorescence"} <= set(by_name)
    assert by_name["Position"].text(1) == "2/2"
    assert by_name["Position"].isExpanded() is True

    # ophys container stays open so its child series groups are visible, while
    # the 24-ROI DfOverF bank (>16) and unchecked Fluorescence (0/10) start collapsed.
    assert by_name["ophys"].isExpanded() is True
    assert by_name["DfOverF"].text(1) == "16/24"
    assert by_name["DfOverF"].isExpanded() is False
    assert by_name["Fluorescence"].text(1) == "0/10"
    assert by_name["Fluorescence"].isExpanded() is False


def test_grouped_plot_mode_and_values_ux_present_clean_grouped_signals(
    qapp, qtbot, tmp_path: Path, monkeypatch
) -> None:
    rec = tmp_path / "recovery"
    rec.mkdir(exist_ok=True)
    monkeypatch.setattr(recovery, "recovery_dir", lambda: rec)

    cache_dir = tmp_path / "nwb_like_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    times = np.linspace(0.0, 5.0, 201, dtype=np.float64)
    channels = (
        ["Position.SpatialSeries.x", "Position.SpatialSeries.y"]
        + [f"ophys.DfOverF.RoiResponseSeries.roi{i}" for i in range(10)]
        + [f"ophys.Fluorescence.RoiResponseSeries.roi{i}" for i in range(4)]
        + ["trials"]
    )
    for idx, ch in enumerate(channels):
        PyramidBuilder(cache_dir, ch).build_and_save(times, np.sin(times) + idx * 0.5)

    visibility = {ch: not ch.startswith("ophys.Fluorescence.") for ch in channels}

    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1200, 780)
    window.show()
    try:
        src = "session.nwb"
        window.clock.set_bounds(0.0, 5.0)
        window.plot_pane.set_timeline_bounds(0.0, 5.0)
        window.plot_pane.set_window_duration(5.0)
        window.plot_pane.load_channels(cache_dir, channels, source_id=src, visibility=visibility)
        window.plot_pane.wait_for_pending_rows()
        units = {
            ChannelKey(src, "Position.SpatialSeries.x"): "m",
            ChannelKey(src, "Position.SpatialSeries.y"): "m",
            **{
                ChannelKey(src, f"ophys.DfOverF.RoiResponseSeries.roi{i}"): "a.u."
                for i in range(10)
            },
        }
        window._channel_units.update(units)
        window.plot_pane.set_channel_units(dict(units))
        window.sidebar.add_sensor(src, channels, channel_visibility=visibility)
        qtbot.waitUntil(lambda: window.plot_pane._last_installed_generation > 0, timeout=5000)

        # 1. Stacked plot gutters use concise "DfOverF · roi0" instead of overflowing full path
        roi0_row = next(
            ch
            for ch in window.plot_pane.channels
            if ch.name.endswith(".DfOverF.RoiResponseSeries.roi0")
        )
        assert "DfOverF · roi0" in roi0_row.plot_item.getAxis("left").labelText

        # 2. Grouped plot mode partitions visible channels into 3 independent signal bands:
        #    Position (2 overlaid traces), DfOverF (10 ROIs -> raster), and trials (1 trace)
        window.plot_pane.set_view_mode(PLOT_MODE_GROUPED)
        assert window.plot_pane.view_mode == PLOT_MODE_GROUPED
        mode_view = window.plot_pane._mode_view
        assert mode_view.isVisible()
        assert 1 + len(mode_view._extra_plots) == 3
        assert len(mode_view._extra_images) == 1  # DfOverF (10 > 8) rendered as per-group raster

        # SessionState round-trips "grouped" plot_view_mode
        state = SessionState(plot_view_mode=PLOT_MODE_GROUPED)
        reloaded = SessionState.from_dict(state.to_dict())
        assert reloaded.plot_view_mode == PLOT_MODE_GROUPED
        window.plot_pane.set_view_mode(PLOT_MODE_STACKED)

        # 3. Values inspector shows ONLY visible channels (Fluorescence hidden -> excluded)
        window._left_tabs.setCurrentWidget(window.readout_panel)
        window.readout_panel.set_cursor(1.25)
        qapp.processEvents()

        shown_keys = {k.channel_id for k in window.readout_panel._rows}
        assert not any(c.startswith("ophys.Fluorescence.") for c in shown_keys)
        assert "Position.SpatialSeries.x" in shown_keys

        # Small group Position (2 <= 6) starts expanded with concise leaf labels ("x", "y");
        # dense group DfOverF (10 > 6) starts collapsed to a clean "μ … [min…max]" summary.
        sections = {sec.group_title: sec for sec, _ in window.readout_panel._group_sections}
        assert sections["Position"].is_expanded is True
        assert sections["ophys / DfOverF"].is_expanded is False
        assert "μ " in sections["ophys / DfOverF"].summary_lbl.text()

        # No visual label inside ReadoutPanel shows raw "[sample_idx]" brackets,
        # while textual_summary() ("Text view…") retains "(sample N)" diagnostics.
        visible_texts = [
            lbl.text()
            for lbl in window.readout_panel.findChildren(QLabel)
            if lbl.isVisibleTo(window.readout_panel)
        ]
        assert not any(
            t.startswith("[") and t.endswith("]") and t[1:-1].isdigit() for t in visible_texts
        )
        summary = window.readout_panel.textual_summary()
        assert "(sample " in summary

        # Clicking the collapsed DfOverF group expands its concise "roi0".."roi9" rows
        sections["ophys / DfOverF"].toggle_btn.click()
        assert sections["ophys / DfOverF"].is_expanded is True

        # Hiding Position.SpatialSeries.x removes it live from Values
        window._on_channel_visibility_changed(src, "Position.SpatialSeries.x", False)
        assert ChannelKey(src, "Position.SpatialSeries.x") not in window.readout_panel._rows
    finally:
        if isValid(window):
            window.close()


def test_empty_values_page_has_no_playhead_header_or_blank_scroll_gap(qapp, qtbot) -> None:
    from avialsync.ui.readout_panel import ReadoutPanel

    panel = ReadoutPanel()
    qtbot.addWidget(panel)
    panel.resize(260, 620)
    panel.show()
    qapp.processEvents()

    assert panel.empty_note.isVisibleTo(panel)
    assert not panel._scroll.isVisibleTo(panel)
    assert not panel._toolbar.isVisibleTo(panel)
    assert panel.empty_note.height() > 200
    assert panel.empty_note.label.height() >= panel.empty_note.label.sizeHint().height()
    shown_labels = [lbl.text() for lbl in panel.findChildren(QLabel) if lbl.isVisibleTo(panel)]
    assert not any("Playhead" in text for text in shown_labels)


def test_no_missing_font_aliases_or_scene_remove_warnings(
    qapp, qtbot, tmp_path: Path, monkeypatch
) -> None:
    import re

    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    from avialsync.ui.batch_import_dialog import BatchImportDialog
    from avialsync.ui.feedback.text_dialog import TextDialog
    from avialsync.ui.import_report import ImportReportDialog
    from avialsync.ui.plot_modes import PLOT_MODE_HEATMAP, PLOT_MODE_OVERLAY
    from avialsync.ui.preferences_dialog import PreferencesDialog
    from avialsync.ui.shortcuts_dialog import ShortcutsDialog

    # 1. Source guard against missing X11/CSS/OS-specific font family literals
    bad_font_re = re.compile(
        r'(?:QFont|setFamily)\(\s*["\'](?:monospace|Monospace|sans-serif|Arial|Helvetica)["\']'
    )
    offenders: list[str] = []
    for py_path in sorted(Path("src/avialsync").rglob("*.py")):
        text = py_path.read_text(encoding="utf-8")
        if bad_font_re.search(text):
            offenders.append(str(py_path))
    assert offenders == [], f"Hardcoded non-portable font family literals found: {offenders}"

    # 2. Live Qt warning guard across dialogs and plot modes
    rec = tmp_path / "rec"
    rec.mkdir(exist_ok=True)
    monkeypatch.setattr(recovery, "recovery_dir", lambda: rec)

    warnings_seen: list[str] = []

    def _capture(mode: QtMsgType, _ctx, message: str) -> None:
        if mode == QtMsgType.QtDebugMsg:
            return
        if "propagateSizeHints" in message:
            return
        warnings_seen.append(message)

    previous_handler = qInstallMessageHandler(_capture)
    try:
        cache_dir = tmp_path / "warn_cache"
        cache_dir.mkdir()
        times = np.linspace(0.0, 2.0, 50, dtype=np.float64)
        for name in ("Grp.a", "Grp.b", "solo"):
            PyramidBuilder(cache_dir, name).build_and_save(times, np.cos(times))

        win = MainWindow()
        qtbot.addWidget(win)
        win.resize(1100, 720)
        win.show()
        win.plot_pane.set_timeline_bounds(0.0, 2.0)
        win.plot_pane.set_window_duration(2.0)
        win.plot_pane.load_channels(cache_dir, ["Grp.a", "Grp.b", "solo"], source_id="s.nwb")
        win.plot_pane.wait_for_pending_rows()
        qtbot.waitUntil(lambda: win.plot_pane._last_installed_generation > 0, timeout=3000)

        for mode in (PLOT_MODE_GROUPED, PLOT_MODE_OVERLAY, PLOT_MODE_HEATMAP, PLOT_MODE_STACKED):
            win.plot_pane.set_view_mode(mode)
            qapp.processEvents()

        td = TextDialog("Values", "line 1\nline 2", parent=win)
        td.show()
        pd = PreferencesDialog(win)
        pd.show()
        sd = ShortcutsDialog({"File": [win._act_open_video]}, win)
        sd.show()
        ird = ImportReportDialog(None, win, properties="k: v", title="Props")
        ird.show()
        bid = BatchImportDialog([], win)
        bid.show()
        qapp.processEvents()

        for dlg in (bid, ird, sd, pd, td):
            dlg.close()
        win.close()
    finally:
        qInstallMessageHandler(previous_handler)

    assert warnings_seen == [], f"Unexpected Qt runtime warnings: {warnings_seen}"
