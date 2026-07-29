import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from avialview.engine.importer import ImportWorker
from avialview.loaders.neo_loader import NeoLoader
from avialview.loaders.video_standard import VideoStandardLoader
from avialview.ui.main_window import MainWindow
from avialview.ui.sync_wizard import SyncWizard


def generate_screenshots():
    app = QApplication.instance() or QApplication(sys.argv)

    window = MainWindow()
    window.resize(1024, 768)
    window.show()

    out_dir = Path(
        "/Users/anzalks/.gemini/antigravity-ide/brain/6e255d75-de3c-4175-9c68-bac59d332866/"
    )

    def save_shot(name):
        app.processEvents()
        window.grab().save(str(out_dir / name))
        print(f"Saved {name}")

    save_shot("tenss_step1_empty.png")

    # 1. Load Ephys
    print("Loading Ephys...")
    ephys_path = Path("TENSS26_Anzal/2026-06-21_17-54-56").resolve()
    worker = ImportWorker(ephys_path, {}, NeoLoader)

    def on_finished(p, c, ch, b, i):
        window._on_import_finished(p, c, ch, b, i)

    worker.finished.connect(on_finished)
    worker.error.connect(lambda p, e: print("Ephys Error:", e))
    worker.run()

    for _ in range(20):
        app.processEvents()
    save_shot("tenss_step2_ephys_loaded.png")

    # 2. Load Video
    print("Loading Video...")
    video_path = Path("TENSS26_Anzal/camera_top2026-06-21T17_54_59.avi").resolve()
    video_loader = VideoStandardLoader()
    video_loader.open(video_path, {})
    window._on_video_opened(str(video_path), video_loader, str(video_path))

    for _ in range(20):
        app.processEvents()
    save_shot("tenss_step3_video_loaded.png")

    # 3. Open Sync Wizard
    print("Opening Sync Wizard...")
    SyncWizard.exec = lambda self: self.show()
    window._open_sync_wizard()

    wizards = window.findChildren(SyncWizard)
    wizard = wizards[0]
    for _ in range(20):
        app.processEvents()

    # 4. Set Reference: Evt-Acquisition Board TTL Input
    ref_idx = -1
    for i in range(wizard._reference_combo.count()):
        if "Evt-Acquisition Board TTL Input" in wizard._reference_combo.itemText(i):
            ref_idx = i
            break
    if ref_idx != -1:
        wizard._reference_combo.setCurrentIndex(ref_idx)

    # 5. Set Target: Video (should be selected by default, index 0 is likely the first video)
    # Strategy: Event Match (TTL Pulse Sequence)
    wizard._strategy_combo.setCurrentIndex(0)  # affine
    for _ in range(10):
        app.processEvents()
    wizard.grab().save(str(out_dir / "tenss_step4_wizard_configured.png"))

    # Click Preview
    wizard._preview_button.click()

    import time

    timeout = time.time() + 10.0
    while wizard._thread is not None and time.time() < timeout:
        app.processEvents()
        time.sleep(0.05)

    for _ in range(20):
        app.processEvents()
    wizard.grab().save(str(out_dir / "tenss_step5_wizard_previewed.png"))

    # 6. Accept Mapping
    wizard.accept()

    # Play to show alignment!
    window.clock.seek(254.590)  # First TTL pulse mapping time
    for _ in range(20):
        app.processEvents()
    save_shot("tenss_step6_mapping_applied.png")


if __name__ == "__main__":
    generate_screenshots()
