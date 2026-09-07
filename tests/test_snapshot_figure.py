"""Snapshot export composes a figure, and never a quarter-empty screen grab.

The export used to grab `_media_splitter` and `plot_pane`, stack the two
pixmaps, and save the result.  On any display with a device pixel ratio above 1
that produced a file three quarters transparent: the canvas was sized in device
pixels while `QPainter.drawImage` positions a captured image at its
*device-independent* size, so everything landed in the top-left quadrant.  What
did land was also whatever had fitted on the monitor — an elided OSD, a 3D
label cut at the pane edge, and the channel rows below the scroll fold missing
entirely.

These tests pin both halves of the fix: the composed figure is opaque and
complete, and each surface is captured from its own content rather than from
the pixels the window happened to be showing.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPalette

from avialsync.engine.export_worker import SnapshotWorker
from avialsync.engine.snapshot import (
    SnapshotFigure,
    SnapshotTheme,
    SnapshotTile,
    content_width_for,
    figure_size,
    plan_media_layout,
    render_figure,
    save_figure,
)
from avialsync.ui.snapshot_capture import (
    _subtitle,
    capture_figure,
    capture_plot_image,
    capture_theme,
    capture_tracking_tile,
    capture_video_tile,
    plot_aspect,
)
from avialsync.ui.time_format import TimeDisplayMode


def _tile(width: int, height: int, color: str = "red", title: str = "cam") -> SnapshotTile:
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return SnapshotTile(image, title, "frame 1")


def _figure(tiles: list[SnapshotTile] | None = None, plot: QImage | None = None) -> SnapshotFigure:
    tiles = tiles if tiles is not None else [_tile(320, 240)]
    layout = plan_media_layout(tiles)
    return SnapshotFigure(
        layout=layout,
        plot=plot,
        title="Session",
        subtitle="t = 00:00:01.000",
        footer="AvialSync",
        theme=SnapshotTheme.light(),
    )


def _transparent_fraction(image: QImage) -> float:
    """Share of pixels that are not fully opaque."""
    buffer = image.convertToFormat(QImage.Format.Format_ARGB32)
    pointer = buffer.constBits()
    pixels = np.frombuffer(pointer, dtype=np.uint8).reshape(buffer.height(), -1, 4)
    return float(np.mean(pixels[:, : buffer.width(), 3] < 255))


# ── the regression: an opaque, fully-covered canvas ──────────────────


def test_rendered_figure_has_no_transparent_region(qapp) -> None:
    """Every pixel is painted, whatever the display's device pixel ratio.

    The old composer left three quarters of the file transparent on a 2x
    display; the tiles carry a device pixel ratio here to prove the composed
    figure no longer inherits one.
    """
    del qapp
    tile = _tile(640, 480)
    tile.image.setDevicePixelRatio(2.0)
    plot = QImage(800, 300, QImage.Format.Format_ARGB32_Premultiplied)
    plot.fill(QColor("blue"))
    plot.setDevicePixelRatio(2.0)

    image = render_figure(_figure([tile], plot))

    assert _transparent_fraction(image) == 0.0


def test_rendered_size_matches_the_planned_size(qapp) -> None:
    """`figure_size` is what the capture side sizes against, so it must agree."""
    del qapp
    figure = _figure([_tile(640, 480), _tile(640, 480)])
    image = render_figure(figure)
    assert (image.width(), image.height()) == figure_size(figure)


def test_tiles_and_plot_are_drawn_where_the_layout_says(qapp) -> None:
    """Content lands at its planned rect rather than at a scaled-down offset."""
    del qapp
    tile = _tile(640, 480, "red")
    plot = QImage(800, 200, QImage.Format.Format_ARGB32_Premultiplied)
    plot.fill(QColor("blue"))
    figure = _figure([tile], plot)
    image = render_figure(figure)

    placement = figure.layout.placements[0]
    centre = placement.rect.center()
    # The media band starts below the header; the plan is in band coordinates.
    assert image.pixelColor(28 + centre.x(), 88 + centre.y()) == QColor("red")
    # And the plot spans the full content width, not half of it.
    plot_row = figure_size(figure)[1] - 42 - 100
    assert image.pixelColor(image.width() - 29, plot_row) == QColor("blue")


# ── layout ───────────────────────────────────────────────────────────


def test_rows_are_justified_flush_to_the_content_width(qapp) -> None:
    del qapp
    layout = plan_media_layout([_tile(640, 480) for _ in range(3)])
    right_edges = {p.rect.right() for p in layout.placements}
    assert max(right_edges) == layout.content_width - 1


def test_tiles_wrap_instead_of_overflowing_the_page(qapp) -> None:
    del qapp
    layout = plan_media_layout([_tile(640, 480) for _ in range(8)])
    rows = {placement.rect.y() for placement in layout.placements}
    assert len(rows) > 1
    assert all(p.rect.right() < layout.content_width for p in layout.placements)


def test_a_tall_channel_stack_narrows_the_page_rather_than_stretching(qapp) -> None:
    """A forty-row stack must not be inflated to a five-camera row's width.

    Width is the only lever on a stack drawn whole: its height follows from it.
    Cropping the stack is what the old export did, so the page gives way.
    """
    del qapp
    wide = content_width_for(3200, plot_aspect=None)
    with_tall_plot = content_width_for(3200, plot_aspect=800 / 6000)
    assert with_tall_plot < wide


def test_page_never_narrows_below_a_legible_width(qapp) -> None:
    del qapp
    assert content_width_for(3200, plot_aspect=1 / 500) >= 1000


# ── capture: each surface from its own content ───────────────────────


@pytest.fixture
def pane(qtbot):
    from avialsync.ui.video_pane import VideoPane

    pane = VideoPane()
    qtbot.addWidget(pane)
    pane.resize(400, 400)
    pane.show()
    qtbot.waitExposed(pane)
    return pane


def test_camera_tile_carries_the_frame_at_its_own_resolution(pane, qtbot) -> None:
    """A 320x240 frame in a square pane yields a 4:3 tile, not a square one.

    The pane letterboxes; a figure must not.  The crop uses the same transform
    the surface drew through, so it cannot disagree with where the tracking
    overlay put its marks.
    """
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frame[:, :] = (200, 30, 30)
    pane.surface.set_frame(frame)
    qtbot.wait(50)

    tile = capture_video_tile(pane, "camera_1.mp4")

    assert tile is not None
    assert tile.title == "camera_1.mp4"
    assert tile.image.width() / tile.image.height() == pytest.approx(320 / 240, abs=0.02)
    # Rendered from the decoded frame, so it is not limited to the 400px pane.
    assert tile.image.width() >= 320


def test_camera_tile_keeps_the_pane_zoom_the_user_framed(pane, qtbot) -> None:
    """Zoom is part of what the user chose to show, so the tile inherits it."""
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frame[:, :] = (200, 30, 30)
    pane.surface.set_frame(frame)
    pane.surface.zoom_by(2.0, QPointF(200, 200))
    qtbot.wait(50)

    tile = capture_video_tile(pane, "camera_1.mp4")

    assert tile is not None
    assert not tile.image.isNull()


def test_a_pane_outside_its_coverage_captures_the_placeholder(pane, qtbot) -> None:
    """D-010's placeholder is a locked overlay: it must reach the figure too."""
    pane.set_has_footage(False)
    qtbot.wait(20)

    tile = capture_video_tile(pane, "camera_1.mp4")

    assert tile is not None
    assert not pane.shows_footage
    assert not tile.image.isNull()


def test_camera_caption_carries_the_pane_readout_unelided(pane, qtbot) -> None:
    """The OSD is clipped to the pane on screen; the caption is not."""
    del qtbot
    tile = capture_video_tile(pane, "camera_1.mp4")
    assert tile is not None
    assert "Time:" in tile.detail
    assert "\n" not in tile.detail


# ── capture: the whole channel stack, not the scroll viewport ────────


@pytest.fixture
def plot_pane(qtbot, tmp_path: Path):
    from avialsync.core.pyramid import PyramidBuilder
    from avialsync.ui.plot_pane import PlotPane

    times = np.arange(2000, dtype=np.float64) * 0.001
    for index in range(12):
        PyramidBuilder(tmp_path, f"ch{index}").build_and_save(times, np.sin(times + index))

    pane = PlotPane()
    qtbot.addWidget(pane)
    # Deliberately short: the point is that rows below the fold still export.
    pane.resize(600, 180)
    pane.show()
    qtbot.waitExposed(pane)
    pane.load_channels(tmp_path, [f"ch{index}" for index in range(12)])
    pane.wait_for_pending_rows()
    qtbot.wait(100)
    return pane


def test_plot_capture_includes_rows_below_the_scroll_fold(plot_pane) -> None:
    """Twelve rows in a 180px pane: the export carries all twelve."""
    image = capture_plot_image(plot_pane, 1200)

    assert image is not None
    assert image.width() == 1200
    # The stack is taller than the viewport that was showing it.
    assert image.height() > plot_pane._plot_scroll.viewport().height() * 2


def test_plot_aspect_describes_the_whole_stack(plot_pane) -> None:
    """The width negotiation reads the stack, not the viewport around it."""
    aspect = plot_aspect(plot_pane)

    assert aspect is not None
    stack = plot_pane.graphics_layout
    assert aspect == pytest.approx(stack.width() / stack.height())


def test_no_channels_means_no_plot_band(qtbot) -> None:
    from avialsync.ui.plot_pane import PlotPane

    pane = PlotPane()
    qtbot.addWidget(pane)
    assert capture_plot_image(pane, 1200) is None
    assert plot_aspect(pane) is None


# ── the 3D pose is re-projected, not magnified ───────────────────────


def test_tracking_canvas_projects_into_the_target_it_is_given(qtbot) -> None:
    """`render_scene` must use the tile's size, so labels are not cut at the pane edge."""
    from avialsync.ui.tracking_3d_pane import Tracking3DCanvas

    canvas = Tracking3DCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(200, 200)

    points = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
    narrow, _ = canvas._project(points, 200, 200)
    wide, _ = canvas._project(points, 800, 400)

    assert wide[0][0] != narrow[0][0], "projection ignored the requested width"
    assert wide[0][0] == pytest.approx(400.0, abs=1.0), "not centred on the target"


def test_tracking_canvas_paints_a_larger_target_without_clipping(qtbot) -> None:
    from PySide6.QtGui import QPainter

    from avialsync.ui.tracking_3d_pane import Tracking3DCanvas

    canvas = Tracking3DCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(120, 90)

    image = QImage(760, 570, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    canvas.render_scene(painter, 760, 570)
    painter.end()

    assert _transparent_fraction(image) == 0.0


# ── the worker writes what was composed ──────────────────────────────


def test_snapshot_worker_writes_the_composed_figure(qapp, tmp_path: Path) -> None:
    del qapp
    figure = _figure([_tile(640, 480)])
    path = tmp_path / "snapshot.png"
    results: list[str] = []
    worker = SnapshotWorker(figure, path)
    worker.finished.connect(results.append)

    worker.run()

    assert results == [str(path)]
    written = QImage(str(path))
    assert (written.width(), written.height()) == figure_size(figure)


def test_saving_to_an_unwritable_path_raises(qapp, tmp_path: Path) -> None:
    del qapp
    with pytest.raises(OSError):
        save_figure(_figure(), tmp_path / "missing" / "snapshot.png")


# ── the theme is the workspace's, read off the palette ───────────────


def test_theme_is_read_from_the_application_palette(qapp) -> None:
    """An exported figure carries the workspace's appearance, not a fixed one."""
    original = QPalette(qapp.palette())
    palette = QPalette(original)
    palette.setColor(QPalette.ColorRole.Window, QColor(12, 24, 36))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(238, 238, 238))
    qapp.setPalette(palette)
    try:
        # Read back rather than assumed. `theme.py` installs a palette listener
        # once per QApplication, so whether one is watching depends on which
        # tests ran first; the claim under test is that the figure follows the
        # palette that actually won, not that setPalette is uncontested.
        live = qapp.palette()
        background = live.color(QPalette.ColorRole.Window)
        foreground = live.color(QPalette.ColorRole.WindowText)
        theme = capture_theme()
    finally:
        qapp.setPalette(original)

    assert theme.background == background
    assert theme.foreground == foreground
    assert theme.background != theme.foreground, "the palette under test never took effect"
    # Captions state measured values — a frame number, a rate — so the muted
    # role is the foreground mixed towards the background, and lands between
    # the two on every channel rather than at either end.
    for channel in ("red", "green", "blue"):
        low, high = sorted((getattr(background, channel)(), getattr(foreground, channel)()))
        assert low <= getattr(theme.muted, channel)() <= high


# ── the 3D pose tile ─────────────────────────────────────────────────


def _tracking_readers(cache_dir: Path):
    from avialsync.core.pyramid import PyramidBuilder, PyramidReader

    cache_dir.mkdir(parents=True)
    times = np.array([0.0, 0.5, 1.0], dtype=np.float64)
    channels = {
        "nose_x": np.array([0.0, 10.0, 20.0]),
        "nose_y": np.array([1.0, 11.0, 21.0]),
        "nose_z": np.array([2.0, 12.0, 22.0]),
        "tail_x": np.array([3.0, 13.0, 23.0]),
        "tail_y": np.array([4.0, 14.0, 24.0]),
        "tail_z": np.array([5.0, 15.0, 25.0]),
    }
    for name, values in channels.items():
        PyramidBuilder(cache_dir, name).build_and_save(times, values)
    return [PyramidReader(cache_dir, name) for name in channels]


def test_no_pose_means_no_tracking_tile(qtbot) -> None:
    """A session without 3D tracking must not gain an empty tile."""
    from avialsync.ui.tracking_3d_pane import Tracking3DPane

    pane = Tracking3DPane()
    qtbot.addWidget(pane)

    assert capture_tracking_tile(pane) is None


def test_tracking_tile_is_rendered_at_the_tile_size_and_captioned(qtbot, tmp_path: Path) -> None:
    """The pose is re-projected into its own tile, opaque and fully covered."""
    from avialsync.ui.tracking_3d_pane import Tracking3DPane

    pane = Tracking3DPane()
    qtbot.addWidget(pane)
    pane.resize(160, 120)
    pane.set_readers(_tracking_readers(tmp_path / "tracking.avialcache"))
    pane.set_cursor(0.5)

    tile = capture_tracking_tile(pane)

    assert tile is not None
    assert tile.title == "3D Tracking"
    assert tile.detail == pane.status_label.text()
    # Its own size, not the 160x120 the pane happened to be at.
    assert (tile.image.width(), tile.image.height()) > (160, 120)
    assert _transparent_fraction(tile.image) == 0.0


# ── the window-level capture and its entry points ────────────────────


@pytest.fixture
def main_window(qapp, qtbot):
    from shiboken6 import isValid

    from avialsync.ui.main_window import MainWindow

    del qapp
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    yield window
    if isValid(window):
        window.close()


def test_a_window_with_nothing_loaded_captures_an_empty_figure(main_window) -> None:
    """`is_empty` is what stops Export Snapshot writing a header and a footer."""
    figure = capture_figure(main_window)

    assert figure.is_empty
    assert figure.layout.placements == ()
    assert figure.plot is None


def test_export_snapshot_reports_instead_of_asking_where_to_write_nothing(
    main_window, monkeypatch
) -> None:
    """Never block, always inform (AGENTS rule 10): a status line, not a modal."""
    from avialsync.ui.controllers import export_controller

    class _NoDialog:
        @staticmethod
        def getSaveFileName(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("a filename was asked for with nothing to save")

    monkeypatch.setattr(export_controller, "QFileDialog", _NoDialog)

    export_controller.export_snapshot(main_window)

    assert "Nothing to snapshot" in main_window.transport.status_text()
    assert not main_window._snapshot_jobs


def test_the_subtitle_writes_the_time_the_transport_is_showing(main_window) -> None:
    """One authority for how a master time reads (D-020, AGENTS rule 15).

    The subtitle used to re-derive it from a `_t_epoch` the window does not
    have, so a figure exported in UTC silently came out relative.
    """
    main_window.transport.set_t_epoch(1_700_000_000.0)
    main_window.transport.set_time_mode(TimeDisplayMode.UTC)
    main_window.clock.set_bounds(0.0, 60.0)
    main_window.clock.seek(12.5)

    subtitle = _subtitle(main_window, tiles=0)

    # 1_700_000_000 + 12.5 s, written the way the seek row writes it.
    assert subtitle == "t = 22:13:32.500 UTC"
    assert subtitle == f"t = {main_window.transport.format_master_time(12.5)}"


# ── the single-pane entry point captures before it asks ──────────────


def _stub_window(pane, recorded: list, qtbot) -> SimpleNamespace:
    """The attributes `export_snapshot_for_pane` and the capture actually touch.

    A real `Transport`, because the subtitle's time and the status line both
    come from it; everything else the pane path reads is a plain value.
    """
    from avialsync.ui.transport import Transport

    transport = Transport()
    qtbot.addWidget(transport)
    return SimpleNamespace(
        video_grid=SimpleNamespace(_paths=["camera_1.mp4"], panes=[pane]),
        transport=transport,
        clock=SimpleNamespace(state=SimpleNamespace(t=1.0)),
        plot_pane=SimpleNamespace(channels=[]),
        _session_path=None,
        _start_snapshot_export=lambda figure, path: recorded.append((figure, path)),
    )


def test_a_pane_snapshot_is_captured_before_the_filename_is_chosen(
    pane, qtbot, tmp_path: Path, monkeypatch
) -> None:
    """The figure records the frame the user asked about, not a later one.

    Naming a file takes seconds; a playing pane decodes many frames in that
    time.  The dialog stand-in here advances the pane while it is open, and the
    exported tile must still be the frame that was on screen when the user
    reached for the menu.
    """
    from avialsync.ui.controllers import export_controller

    red = np.zeros((240, 320, 3), dtype=np.uint8)
    red[:, :] = (200, 30, 30)
    pane.surface.set_frame(red)
    qtbot.wait(50)

    class _AdvancingDialog:
        @staticmethod
        def getSaveFileName(*args, **kwargs):
            green = np.zeros((240, 320, 3), dtype=np.uint8)
            green[:, :] = (30, 200, 30)
            pane.surface.set_frame(green)
            return str(tmp_path / "snapshot.png"), "PNG Images (*.png)"

    monkeypatch.setattr(export_controller, "QFileDialog", _AdvancingDialog)

    recorded: list = []
    export_controller.export_snapshot_for_pane(_stub_window(pane, recorded, qtbot), "camera_1.mp4")

    assert len(recorded) == 1
    figure, path = recorded[0]
    assert path == tmp_path / "snapshot.png"
    tile = figure.layout.placements[0].tile
    centre = tile.image.pixelColor(tile.image.width() // 2, tile.image.height() // 2)
    assert centre.red() > centre.green(), "the tile carries the frame shown after the dialog"


def test_a_pane_with_no_drawable_surface_reports_rather_than_writing_a_blank(
    pane, qtbot, monkeypatch
) -> None:
    """A pane with nothing to draw into has nothing to export; say so.

    Never block, always inform (AGENTS rule 10): a status line, not a modal and
    not a file containing only a header and a footer.
    """
    # No event loop turn between here and the assertions: a queued layout pass
    # would give the surface its size back and the test would stop testing the
    # guard it is named after.
    pane.surface.resize(0, 0)
    assert capture_video_tile(pane, "camera_1.mp4") is None

    from avialsync.ui.controllers import export_controller

    class _NoDialog:
        @staticmethod
        def getSaveFileName(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("a filename was asked for with nothing to save")

    monkeypatch.setattr(export_controller, "QFileDialog", _NoDialog)

    recorded: list = []
    window = _stub_window(pane, recorded, qtbot)
    export_controller.export_snapshot_for_pane(window, "camera_1.mp4")

    assert recorded == []
    assert "Nothing to snapshot" in window.transport.status_text()


# ── failures reach the user as a signal, never as a traceback ────────


def test_snapshot_worker_reports_a_write_failure_instead_of_raising(qapp, tmp_path: Path) -> None:
    """`SnapshotWorker.run` is a thread entry point: it must not let OSError out."""
    del qapp
    errors: list[str] = []
    finished: list[str] = []
    worker = SnapshotWorker(_figure(), tmp_path / "missing" / "snapshot.png")
    worker.error.connect(errors.append)
    worker.finished.connect(finished.append)

    worker.run()

    assert finished == []
    assert len(errors) == 1
