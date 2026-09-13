"""Capture the synchronization walkthrough used in the README.

Run with ``conda run -n avialsync python tools/generate_demo_screenshots.py``.
Uses the checked-in sample session, so the images are reproducible from a
clean clone and never depend on private field data (AGENTS.md rule 5).

**Do not set QT_QPA_PLATFORM=offscreen for this.** The offscreen plugin has no
native menu bar, so Qt draws one inside the window and every captured image
gains a File/View/Help strip that a real macOS user never sees. These run on a
real display.

The appearance is pinned to Dark below for the same reason the session is
checked in: an unpinned theme follows whichever preference the developer last
saved, so the same command produced light-mode images on one machine and
dark-mode on another, and the docs ended up with a mix.
"""

import argparse
import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

from avialsync.engine.importer import ImportWorker
from avialsync.loaders.csv_loader import CSVLoader
from avialsync.loaders.video_standard import VideoStandardLoader
from avialsync.ui.main_window import MainWindow
from avialsync.ui.sync_wizard import SyncWizard

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screenshot_kit import pin_appearance, pin_layout, settle  # noqa: E402

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "docs" / "_static" / "screenshots"

#: Wide enough for the Data Streams header to lay its buttons out at their full
#: width. Below roughly 1200 px that row overflows and Qt clips "Fullscreen
#: Toggle" to "ullscreen Togg", which reads as a rendering fault rather than as
#: the window simply being narrow.
WINDOW_SIZE = (1280, 860)


def _select_by_text(combo, fragment: str) -> None:
    """Choose the first entry containing *fragment*, or leave it alone.

    By text rather than by index: channel order depends on what the importer
    found, and an index picked out of one run silently selects something else
    in the next.
    """
    for index in range(combo.count()):
        if fragment in combo.itemText(index):
            combo.setCurrentIndex(index)
            return


def generate_screenshots(out_dir: Path = DEFAULT_OUTPUT_DIR):
    app = QApplication.instance() or QApplication(sys.argv)
    out_dir.mkdir(parents=True, exist_ok=True)
    pin_appearance(app)

    window = MainWindow()
    window.resize(*WINDOW_SIZE)
    window.show()
    settle(app)
    pin_layout(window)

    def save_shot(name):
        settle(app)
        # The status line latches until something replaces it, and driving the
        # UI synchronously from a script trips the stall detector. Reset it so
        # the capture shows the state a user reaches, not the harness's.
        window.transport.set_status("Ready")
        settle(app)
        window.grab().save(str(out_dir / name))
        print(f"Saved {name}")

    save_shot("demo_step1_empty.png")

    # 1. Load Video
    video_path = REPOSITORY_ROOT / "tests/fixtures/sample_session/camera_1.mp4"
    video_loader = VideoStandardLoader()
    video_loader.open(video_path, {})
    window._on_video_opened(str(video_path), video_loader, str(video_path))

    # Needs to process events so it loads in the UI
    settle(app)
    save_shot("demo_step2_video_loaded.png")

    # 2. Load CSV synchronously!
    csv_path = REPOSITORY_ROOT / "tests/fixtures/sample_session/signal_base.csv"
    worker = ImportWorker(csv_path, {}, CSVLoader)

    def on_finished(p, c, ch, b, i):
        window._on_import_finished(p, c, ch, b, i)

    worker.finished.connect(on_finished)
    worker.run()

    settle(app)
    save_shot("demo_step3_csv_loaded.png")

    # 2b. Load the camera strobe as trigger evidence, the way a user would
    # through Align -> Open Trigger Evidence. Read synchronously here; the
    # application does it on a worker.
    from avialsync.core.triggers import TriggerKind
    from avialsync.engine.trigger_worker import TriggerReadWorker
    from avialsync.loaders.trigger_csv import LEVEL, TriggerCSVSource

    trigger_path = REPOSITORY_ROOT / "tests/fixtures/sample_session/frame_triggers.csv"
    trigger_config = {
        "time_column": "t",
        "trains": [
            {
                "id": "cam_strobe",
                "column": "cam_strobe",
                "kind": str(TriggerKind.FRAME_STROBE),
                "mode": LEVEL,
                "target": "",
            }
        ],
    }
    reader = TriggerReadWorker(TriggerCSVSource(), trigger_path, trigger_config)
    reader.finished.connect(
        lambda results: window._on_trigger_trains_read(str(trigger_path), results)
    )
    window._trigger_configs[str(trigger_path)] = trigger_config
    reader.run()
    settle(app)

    # 3. Open Sync Wizard. No `exec` monkeypatch any more: it is shown without
    # blocking, so it can be read against the window it asks about (D-108).
    window._open_sync_wizard()

    wizards = window.findChildren(SyncWizard)
    wizard = wizards[0]
    settle(app)
    wizard.grab().save(str(out_dir / "demo_step4_wizard_open.png"))

    # 4. Point it at the camera strobe, and let the evidence choose the model.
    #
    # This demo has been shipping a picture of a *failure*: the committed
    # step-6 screenshot reads "No mapping proposed", and has for as long as the
    # file has existed. It selected `ch0` -- a continuous analogue trace with
    # no events in it -- and ticked "use all samples as events", feeding a
    # hundred thousand dense samples in where per-frame trigger timestamps
    # belong. Nor could any other channel have rescued it: `ch2` is the only
    # logical line in the fixture and it has exactly one edge, a step rather
    # than a train. The session had nothing to align *from*.
    #
    # `frame_triggers.csv` is that missing evidence: the camera's exposure
    # strobe as a DAQ would have recorded it, generated from the video's own
    # frame timestamps so the alignment it demonstrates is a real one.
    _select_by_text(wizard._reference_combo, "cam_strobe")
    wizard._use_all_times_chk.setChecked(False)
    # Automatic, because the point being demonstrated is that the model follows
    # the evidence (D-108). A declared strobe whose count matches the container
    # earns the exact mapping; forcing a strategy would hide that.
    wizard._strategy_combo.setCurrentIndex(wizard._strategy_combo.findData("auto"))
    settle(app)
    wizard.grab().save(str(out_dir / "demo_step5_wizard_configured.png"))

    # Click Preview
    wizard._preview_button.click()

    # Wait for thread
    timeout = time.time() + 5.0
    while wizard._thread is not None and time.time() < timeout:
        app.processEvents()
        time.sleep(0.05)

    settle(app)
    wizard.grab().save(str(out_dir / "demo_step6_wizard_previewed.png"))

    # 5. Accept Mapping
    wizard.accept()
    # accept normally closes it

    settle(app)
    save_shot("demo_step7_mapping_applied.png")

    # Close explicitly rather than letting the interpreter drop the window.
    # Each VideoPane owns a decode thread, and Qt aborts the process if one is
    # still running when its QThread is destroyed (AGENTS.md: shutdown
    # ownership is explicit, never left to garbage collection).
    window.close()
    settle(app)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Where to write the PNGs (default: docs/_static/screenshots).",
    )
    generate_screenshots(parser.parse_args().output_dir)


if __name__ == "__main__":
    main()
