"""Capture the screenshots for features the other generators do not cover.

The Props tab (ladder, belt and ball steps), the Tasks tab, the Exports page, the File and View
menus (including File → Cache and View → Overlays), the command palette,
Preferences, and the light appearance.

Run with ``conda run -n avialsync python tools/generate_feature_screenshots.py``.
Do **not** set ``QT_QPA_PLATFORM=offscreen`` — see ``tools/screenshot_kit.py``.

Uses the same synthetic inputs as the guide screenshots, so it is reproducible
from a clean clone and never touches private field data (AGENTS.md rule 5).
Nothing here changes a saved preference: appearance is pinned with
``persist=False``. Synthetic prop edits are accepted only in a temporary recording.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PySide6.QtWidgets import QApplication, QMenu
from scipy.spatial.transform import Rotation

from avialsync.core.calibration import Calibration, CameraModel, write_calibration
from avialsync.core.physical_props import BallProp, BeltProp, Ladder
from avialsync.core.visual_prop_tracking import ball_visual_state, belt_visual_state
from avialsync.core.wheel import LEFT, RIGHT, WheelGeometry, WheelSpec
from avialsync.loaders.video_standard import VideoStandardLoader
from avialsync.ui import theme
from avialsync.ui.controllers import calibration_controller, wheel_controller, wheel_display
from avialsync.ui.main_window import MainWindow
from avialsync.ui.wheel_dialogs import WheelSetup, _WheelSetupDialog

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_guide_screenshots import _load_session  # noqa: E402
from screenshot_kit import (  # noqa: E402
    capture,
    pin_appearance,
    pin_layout,
    settle,
    wait_until,
    write_synthetic_sync_fixture,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "docs" / "_static" / "screenshots"


def _show_tab(window: MainWindow, app: QApplication, label: str) -> None:
    tabs = window._left_tabs
    for index in range(tabs.count()):
        if tabs.tabText(index) == label:
            tabs.setCurrentIndex(index)
            settle(app)
            return
    raise RuntimeError(f"No inspector page called {label!r}.")


def _menu(window: MainWindow, title: str) -> QMenu:
    for menu in window.findChildren(QMenu):
        if menu.title().replace("&", "") == title:
            return menu
    raise RuntimeError(f"No menu called {title!r}.")


def _capture_menu(
    window: MainWindow, app: QApplication, title: str, path: Path, submenu: str | None = None
) -> None:
    """Photograph a menu, or one of its submenus, as the user sees it opened."""
    menu = _menu(window, title)
    if submenu is not None:
        menu = _menu(window, submenu)
    menu.ensurePolished()
    menu.adjustSize()
    menu.popup(window.mapToGlobal(window.rect().topLeft()))
    settle(app)
    menu.grab().save(str(path))
    menu.hide()
    settle(app)


def _camera(name: str, position: tuple[float, float, float]) -> CameraModel:
    """Pinhole view of the synthetic apparatus, in a 640×360 video frame."""
    centre = np.asarray(position, dtype=np.float64)
    forward = np.asarray((0.0, 0.0, 70.0)) - centre
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, (0.0, 0.0, 1.0))
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    rotation = np.vstack((right, down, forward))
    return CameraModel(
        name,
        (640, 360),
        np.asarray(((720.0, 0.0, 320.0), (0.0, 720.0, 180.0), (0.0, 0.0, 1.0))),
        rotation=Rotation.from_matrix(rotation).as_rotvec(),
        translation=-rotation @ centre,
    )


def _prepare_prop_viewers(
    window: MainWindow, app: QApplication, session: Path
) -> tuple[dict[str, CameraModel], dict[str, str]]:
    """Open three real panes and their temporary calibration for stereo examples."""
    positions = ((0.0, -260.0, 180.0), (-220.0, -160.0, 180.0), (220.0, -160.0, 180.0))
    models = {
        f"camera_{index}": _camera(f"camera_{index}", position)
        for index, position in enumerate(positions, 1)
    }
    folder = session / "pose-3d"
    folder.mkdir(exist_ok=True)
    write_calibration(folder / "calibration.toml", Calibration(tuple(models.values())))
    paths = {"camera_1": str(session / "camera_1.mp4")}
    for name in ("camera_2", "camera_3"):
        video = session / f"{name}.mp4"
        shutil.copyfile(session / "camera_1.mp4", video)
        loader = VideoStandardLoader()
        loader.open(video, {})
        window._on_video_opened(str(video), loader, str(video))
        paths[name] = str(video)
        pane = window.video_grid.panes[-1]
        wait_until(app, lambda pane=pane: pane.surface._buffer is not None, f"{name} frame")
    assert calibration_controller.resolve_calibration(window)
    assert len(wheel_display.camera_models(window)) == 3
    window.resize(1600, 900)
    settle(app)
    window._media_splitter.setSizes((950, 400))
    settle(app)
    return models, paths


def _click_world(
    window: MainWindow,
    models: dict[str, CameraModel],
    paths: dict[str, str],
    point: tuple[float, float, float],
) -> None:
    """Use the real Props click gesture in two calibrated camera panes."""
    for name in ("camera_1", "camera_2"):
        x, y = models[name].project(np.asarray(point))[0]
        assert window.props_app.on_clicked(paths[name], float(x), float(y))


def _capture_props(
    window: MainWindow,
    app: QApplication,
    out_dir: Path,
    models: dict[str, CameraModel],
    paths: dict[str, str],
) -> None:
    """The Props tab's declared geometry and evidence controls.

    The ladder is added through the panel's own Add control, so its prop file
    lands in the fixture's temporary ``pose-3d/`` and nowhere else.
    """
    panel = window.props_app.panel
    if panel is None:
        raise RuntimeError("The Props panel was not built.")
    window.tracking_3d_pane.set_up_axis(2, False)
    assert window.tracking_3d_pane.up_axis_combo.currentData() == (2, False)
    panel.select_prop("", "ladder")
    window.props_app.create("Ladder")
    settle(app)
    capture(window, out_dir / "feature_props_tab.png", (panel.kind, panel.name))
    assert window.props_app.tab is not None
    tab = window.props_app.tab
    tab.ensureWidgetVisible(panel.save_step)
    settle(app)
    capture(
        window,
        out_dir / "feature_props_ladder_steps.png",
        (panel.add_point, panel.add_rung, panel.save_step),
        crop=window._left_tabs,
    )
    panel.add_rung.click()
    _click_world(window, models, paths, (-35.0, -50.0, 70.0))
    settle(app)
    capture(window, out_dir / "feature_props_ladder_clicks.png", (panel.next_point,))
    panel.next_point.click()
    _click_world(window, models, paths, (35.0, -50.0, 70.0))
    panel.save_step.click()
    # Save and click next keeps clicking rung after rung; the last rung is
    # tagged as an irregular, raised place before it is saved.
    panel.add_rung.click()
    for along, height in ((0.0, 70.0), (50.0, 78.0)):
        if height != 70.0:
            panel.step_irregular.setCurrentIndex(panel.step_irregular.findData("raised"))
        _click_world(window, models, paths, (-35.0, along, height))
        panel.next_point.click()
        _click_world(window, models, paths, (35.0, along, height))
        (panel.save_next_step if along == 0.0 else panel.save_step).click()
    ladder = window.props_app.store.get("Ladder")
    assert isinstance(ladder, Ladder) and len(ladder.steps) == 3
    assert all(point.xyz is not None for step in ladder.steps for point in step.points)
    panel.ladder_support.setCurrentIndex(panel.ladder_support.findData("side_rails"))
    panel.ladder_support.activated.emit(panel.ladder_support.currentIndex())
    # The clicked, raised third rung replaces the third estimate of the run.
    panel.rung_count.setValue(5)
    panel.extrapolate.click()
    ladder = window.props_app.store.get("Ladder")
    assert isinstance(ladder, Ladder) and ladder.pattern is not None
    tab.ensureWidgetVisible(panel.extrapolate)
    settle(app)
    capture(
        window,
        out_dir / "feature_props_ladder_support.png",
        (panel.ladder_support, panel.rung_count, panel.extrapolate, panel.step_irregular),
        crop=window._left_tabs,
    )
    capture(window, out_dir / "feature_props_ladder_viewer.png", crop=window._media_splitter)
    window.props_app.remove_ladder("Ladder")

    panel.kind.setCurrentIndex(panel.kind.findData("belt"))
    panel.name.setText("Example belt")
    panel.belt_units.setCurrentIndex(panel.belt_units.findData("mm"))
    panel.belt_radius.setValue(10.0)
    panel.belt_centre_distance.setValue(80.0)
    panel.belt_placement.start.click()
    for index, corner in enumerate(
        ((-35.0, -8.0, 70.0), (-35.0, 8.0, 70.0), (35.0, -8.0, 70.0), (35.0, 8.0, 70.0))
    ):
        if index:
            panel.belt_placement.next_point.click()
        _click_world(window, models, paths, corner)
    settle(app)
    capture(window, out_dir / "feature_props_belt_corners.png", crop=window._media_splitter)
    panel.belt_placement.place.click()
    panel.save_belt.click()
    belt = window.props_app.store.get("Example belt")
    assert isinstance(belt, BeltProp) and belt.corners is not None and belt.rollers is not None
    assert abs(belt.rollers.width - 16.0) < 0.01 and abs(belt.rollers.run_length - 80.0) < 1e-6
    tab.verticalScrollBar().setValue(0)
    settle(app)
    capture(window, out_dir / "feature_props_belt.png", (panel.belt_geometry_mode,))
    tab.ensureWidgetVisible(panel.belt_placement.place)
    settle(app)
    capture(
        window,
        out_dir / "feature_props_belt_geometry.png",
        (panel.belt_centre_distance, panel.belt_radius, panel.belt_placement.start),
        crop=window._left_tabs,
    )
    tab.ensureWidgetVisible(panel.belt_normal_fields[2])
    settle(app)
    capture(
        window,
        out_dir / "feature_props_belt_surface_fields.png",
        (panel.belt_width, panel.belt_normal_fields[2]),
        crop=window._left_tabs,
    )
    tab.ensureWidgetVisible(panel.track_belt)
    settle(app)
    capture(
        window,
        out_dir / "feature_props_belt_evidence.png",
        (panel.belt_channel, panel.bind_belt, panel.track_belt),
        crop=window._left_tabs,
    )
    panel.track_belt.click()
    _click_world(window, models, paths, (10.0, 0.0, 70.0))
    belt = window.props_app.store.get("Example belt")
    assert isinstance(belt, BeltProp)
    assert belt.visual_reference_frame is not None
    assert belt_visual_state(belt, belt.visual_reference_frame, models) is not None
    settle(app)
    capture(window, out_dir / "feature_props_belt_viewer.png", crop=window._media_splitter)
    window.props_app.remove_prop("belt", "Example belt")

    # One camera, no stereo: hubs and the top above each, on the belt's near side.
    panel.belt_geometry_mode.setCurrentIndex(panel.belt_geometry_mode.findData("side"))
    panel.name.setText("Side belt")
    panel.belt_centre_distance.setValue(80.0)
    panel.belt_radius.setValue(10.0)
    panel.belt_width.setValue(16.0)
    panel.belt_placement.start.click()
    for index, (along, up) in enumerate(((-40.0, 0.0), (40.0, 0.0), (-40.0, 10.0), (40.0, 10.0))):
        if index:
            panel.belt_placement.next_point.click()
        x, y = models["camera_1"].project(np.asarray((along, -8.0, 60.0 + up)))[0]
        assert window.props_app.on_clicked(paths["camera_1"], float(x), float(y))
    panel.belt_placement.place.click()
    panel.save_belt.click()
    side = window.props_app.store.get("Side belt")
    assert isinstance(side, BeltProp) and side.side_view is not None
    settle(app)
    capture(window, out_dir / "feature_props_belt_side_view.png", crop=window._media_splitter)
    window.props_app.remove_prop("belt", "Side belt")

    panel.kind.setCurrentIndex(panel.kind.findData("ball"))
    panel.name.setText("Example ball")
    panel.ball_centre_fields[2].setValue(70.0)
    panel.ball_radius.setValue(35.0)
    panel.ball_units.setCurrentIndex(panel.ball_units.findData("mm"))
    panel.save_ball.click()
    tab.verticalScrollBar().setValue(0)
    settle(app)
    capture(
        window,
        out_dir / "feature_props_ball_geometry.png",
        (panel.ball_centre_fields[0], panel.ball_radius, panel.ball_units),
        crop=window._left_tabs,
    )
    tab.ensureWidgetVisible(panel.track_ball)
    settle(app)
    capture(
        window,
        out_dir / "feature_props_ball_evidence.png",
        (panel.ball_visual_mark, panel.track_ball),
        crop=window._left_tabs,
    )
    panel.track_ball.click()
    for index, point in enumerate(((35.0, 0.0, 70.0), (0.0, 35.0, 70.0), (0.0, 0.0, 105.0))):
        panel.ball_visual_mark.setCurrentIndex(panel.ball_visual_mark.findData(index))
        _click_world(window, models, paths, point)
    ball = window.props_app.store.get("Example ball")
    assert isinstance(ball, BallProp)
    assert ball.visual_reference_frame is not None
    assert ball_visual_state(ball, ball.visual_reference_frame, models) is not None
    settle(app)
    capture(window, out_dir / "feature_props_ball_viewer.png", crop=window._media_splitter)
    window.props_app.remove_prop("ball", "Example ball")

    panel.kind.setCurrentIndex(panel.kind.findData("ladder"))
    settle(app)

    # Show the first-use dialog even when the screenshot author's machine has
    # remembered a different wheel setup; no preference is read or changed.
    with patch("avialsync.ui.wheel_dialogs._saved_details", return_value=None):
        setup = _WheelSetupDialog((), None, (), window)
    setup.name_edit.setText("Example_wheel")
    setup.bars.setValue(36)
    setup.units.setCurrentIndex(setup.units.findData("mm"))
    setup.radius.setValue(100.0)
    setup.show()
    settle(app)
    capture(
        setup,
        out_dir / "feature_props_wheel_setup.png",
        (setup.name_edit, setup.bars, setup.units, setup.radius, setup.encoder),
        numbered=True,
    )
    setup.close()
    settle(app)
    _capture_wheel_viewer(window, app, out_dir, models, paths)


def _capture_wheel_viewer(
    window: MainWindow,
    app: QApplication,
    out_dir: Path,
    models: dict[str, CameraModel],
    paths: dict[str, str],
) -> None:
    """Record actual labelled bar-end clicks and their fitted wheel preview."""
    spec = WheelSpec("Example wheel", 16, radius=60.0, units="mm")
    truth = WheelGeometry((0.0, 0.0, 70.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), 60.0, 20.0, 16)
    with patch(
        "avialsync.ui.controllers.wheel_controller.ask_wheel_setup",
        return_value=WheelSetup(spec, channel=None),
    ):
        wheel_controller.toggled(window, True)
    ends = truth.bar_ends()
    for bar, slot in enumerate((1, 2)):
        for side_index, _side in enumerate((LEFT, RIGHT)):
            wheel_controller.select_end(window, bar * 2 + side_index)
            point = tuple(float(value) for value in ends[slot, side_index])
            for name in ("camera_1", "camera_2"):
                x, y = models[name].project(np.asarray(point))[0]
                assert wheel_controller.on_clicked(window, paths[name], float(x), float(y))
    wait_until(
        app,
        lambda: (
            window.wheel_state.placement is not None
            and window.wheel_state.placement.fit is not None
        ),
        "the wheel fit",
    )
    # The fit lands before the pane has its frame and calibration in hand on a
    # loaded machine, so wait for the drawing rather than assert it at once.
    wait_until(
        app,
        lambda: bool(
            getattr(wheel_display.pane_drawing(window, paths["camera_1"], 0.0), "bars", ())
        ),
        "the fitted wheel drawn on camera 1",
    )
    settle(app)
    capture(window, out_dir / "feature_props_wheel_review.png", (window.wheel_panel._accept,))
    capture(window, out_dir / "feature_props_wheel_preview.png", crop=window._media_splitter)
    window.wheel_panel._accept.click()
    settle(app)
    assert window.wheels.get("Example wheel") is not None
    capture(window, out_dir / "feature_props_wheel_viewer.png", crop=window._media_splitter)


def _generate(out_dir: Path, session: Path) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    pin_appearance(app)
    out_dir.mkdir(parents=True, exist_ok=True)

    window = MainWindow()
    window.resize(1280, 860)
    window.show()
    settle(app)
    pin_layout(window)
    settle(app)
    _load_session(window, app, session)
    # The fixture import is setup, not a tutorial edit. Do not put its
    # temporary absolute path into the command-palette screenshot as Undo Open.
    window.document.clear()
    window.transport.set_status("Ready")
    settle(app)

    try:
        # Tasks opens from the status bar (D-172), so the shot is its popover.
        # A menu is its own window, so the main window's grab cannot see it:
        # the popover is captured on its own.
        window.tasks_button.show_popover()
        settle(app)
        capture(window.tasks_button.popover, out_dir / "feature_tasks_tab.png")
        window.tasks_button.popover.close()
        # Every export is a button on its own page, following its File action
        # (D-197) and greyed out until it has something to write.
        _show_tab(window, app, "Exports")
        capture(window, out_dir / "exports_inspector.png", crop=window._left_tabs)
        _show_tab(window, app, "Sources")

        _capture_menu(window, app, "File", out_dir / "feature_menu_file.png")
        _capture_menu(window, app, "File", out_dir / "feature_menu_file_cache.png", "Cache")
        _capture_menu(window, app, "View", out_dir / "feature_menu_view.png")
        _capture_menu(window, app, "View", out_dir / "feature_menu_view_overlays.png", "Overlays")

        from avialsync.ui.command_palette import CommandPalette

        palette = CommandPalette(list(window._all_actions), window)
        palette.show()
        settle(app)
        palette.grab().save(str(out_dir / "feature_command_palette.png"))
        palette.close()

        window._help_controller.show_preferences()
        settle(app)
        dialog = window._help_controller._preferences_dialog
        dialog.grab().save(str(out_dir / "feature_preferences.png"))
        dialog.close()
        settle(app)

        theme._apply(app, theme.THEME_LIGHT, persist=False)
        settle(app)
        capture(window, out_dir / "feature_light_theme.png")

        pin_appearance(app)
        window.raise_()
        window.activateWindow()
        pin_layout(window)
        _show_tab(window, app, "Props")
        models, paths = _prepare_prop_viewers(window, app, session)
        _capture_props(window, app, out_dir, models, paths)
    finally:
        pin_appearance(app)
        window.close()
        settle(app)
    print(f"Wrote feature screenshots to {out_dir}")


def main(out_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    with tempfile.TemporaryDirectory() as scratch:
        _generate(out_dir, write_synthetic_sync_fixture(Path(scratch)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUTPUT_DIR, help="folder for the images (default: docs)"
    )
    main(parser.parse_args().out)
