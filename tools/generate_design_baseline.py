"""Photograph every main surface at three sizes and both themes, for design review.

The interface design plan (``INTERFACE_DESIGN_PLAN.md`` DS-0) compares each
work package against images taken before it, so this writes a dated folder of
plain captures rather than the annotated documentation images:

* the main window with one camera and one signal, then three cameras, at
  1280×800, 1600×900 and the 640×480 compact floor, in Dark and Light;
* each inspector page at 1280×800, in Dark and Light.

Run with ``conda run -n avialsync python tools/generate_design_baseline.py --out <folder>``.
Settings, the recovery snapshot and the cache are sandboxed by
``screenshot_kit`` on import, so a run never touches the operator's own state,
and the inputs are the synthetic fixtures the guide screenshots use.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QApplication

from avialsync.loaders.video_standard import VideoStandardLoader
from avialsync.ui import theme
from avialsync.ui.main_window import MainWindow

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_guide_screenshots import _load_session  # noqa: E402
from screenshot_kit import (  # noqa: E402
    pin_layout,
    settle,
    wait_until,
    write_synthetic_sync_fixture,
)

SIZES = ((1280, 800), (1600, 900), (640, 480))
THEMES = (("dark", theme.THEME_DARK), ("light", theme.THEME_LIGHT))


def _add_cameras(window: MainWindow, app: QApplication, session: Path) -> None:
    """Open two more copies of the sample camera through the ordinary path."""
    for name in ("camera_2", "camera_3"):
        video = session / f"{name}.mp4"
        shutil.copyfile(session / "camera_1.mp4", video)
        loader = VideoStandardLoader()
        loader.open(video, {})
        window._on_video_opened(str(video), loader, str(video))
        pane = window.video_grid.panes[-1]
        wait_until(app, lambda pane=pane: pane.surface._buffer is not None, f"{name} frame")
    settle(app)


def _shoot(window: MainWindow, app: QApplication, out_dir: Path, stem: str) -> None:
    for theme_name, theme_id in THEMES:
        theme._apply(app, theme_id, persist=False)
        settle(app)
        for width, height in SIZES:
            window.resize(width, height)
            settle(app)
            pin_layout(window)
            settle(app)
            window.grab().save(str(out_dir / f"{stem}_{theme_name}_{width}x{height}.png"))


def _shoot_inspector(window: MainWindow, app: QApplication, out_dir: Path) -> None:
    pages = window.inspector_pages() if hasattr(window, "inspector_pages") else None
    tabs = window._left_tabs
    count = len(pages) if pages is not None else tabs.count()
    for theme_name, theme_id in THEMES:
        theme._apply(app, theme_id, persist=False)
        window.resize(1280, 800)
        settle(app)
        pin_layout(window)
        for index in range(count):
            if pages is not None:
                label = pages[index]
                window.show_inspector_page(label)
            else:
                label = tabs.tabText(index)
                tabs.setCurrentIndex(index)
            settle(app)
            name = label.lower().replace(" ", "_")
            window.grab().save(str(out_dir / f"inspector_{name}_{theme_name}.png"))


def generate(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    with tempfile.TemporaryDirectory() as scratch:
        session = write_synthetic_sync_fixture(Path(scratch))
        window = MainWindow()
        window.resize(1280, 800)
        window.show()
        settle(app)
        pin_layout(window)
        try:
            _shoot(window, app, out_dir, "empty")
            _load_session(window, app, session)
            window.document.clear()
            window.transport.set_status("Ready")
            settle(app)
            _shoot(window, app, out_dir, "one_camera")
            _shoot_inspector(window, app, out_dir)
            _add_cameras(window, app, session)
            _shoot(window, app, out_dir, "three_cameras")
        finally:
            theme._apply(app, theme.THEME_DARK, persist=False)
            window.close()
            settle(app)
    print(f"Wrote design baseline to {out_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(tempfile.gettempdir()) / f"avialsync-design-{date.today().isoformat()}"
    parser.add_argument("--out", type=Path, default=default, help=f"output folder ({default})")
    generate(parser.parse_args().out)
