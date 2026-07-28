import sys
import numpy as np
from pathlib import Path
from PySide6.QtWidgets import QApplication
from avialview.ui.main_window import MainWindow
from avialview.ui.sync_wizard import SyncWizard
from avialview.loaders.neo_loader import NeoLoader
from avialview.loaders.video_standard import VideoStandardLoader
from avialview.engine.sync_worker import SignalEvidenceSpec, EventEvidenceSpec
from avialview.core.cache import CacheManager
from avialview.engine.importer import ImportWorker

def test_sync():
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    
    # 1. Load Ephys
    print("Loading Ephys...")
    ephys_path = Path("TENSS26_Anzal/2026-06-21_17-54-56").resolve()
    # Mock the importer since it's a background thread
    worker = ImportWorker(ephys_path, {}, NeoLoader)
    def on_ephys_finished(p, c, ch, b, i):
        print("Ephys loaded!")
        window._on_import_finished(p, c, ch, b, i)
    worker.finished.connect(on_ephys_finished)
    worker.error.connect(lambda p, e: print("Ephys Error:", e))
    worker.run() # Synchronous run
    
    # 2. Load Video
    print("Loading Video...")
    video_path = Path("TENSS26_Anzal/camera_top2026-06-21T17_54_59.avi").resolve()
    video_loader = VideoStandardLoader()
    video_loader.open(video_path, {})
    window._on_video_opened(str(video_path), video_loader, str(video_path))
    
    # Process events to let UI update
    for _ in range(50): app.processEvents()
    
    # 3. Open Sync Wizard
    print("Opening Sync Wizard...")
    window._open_sync_wizard()
    wizards = window.findChildren(SyncWizard)
    wizard = wizards[0]
    
    # Set Reference: Evt-Acquisition Board TTL Input
    ref_idx = -1
    for i in range(wizard._reference_combo.count()):
        if "Evt-Acquisition Board TTL Input" in wizard._reference_combo.itemText(i):
            ref_idx = i
            break
    if ref_idx != -1:
        wizard._reference_combo.setCurrentIndex(ref_idx)
    else:
        print("COULD NOT FIND Evt-Acquisition Board TTL Input in reference combo!")
        return
        
    # Target should already be the video
    
    # Strategy: Event Match (TTL Pulse Sequence)
    wizard._strategy_combo.setCurrentIndex(0) # 0 is affine
    
    print("Clicking Preview...")
    wizard._preview_button.click()
    
    import time
    timeout = time.time() + 30.0
    while wizard._thread is not None and time.time() < timeout:
        app.processEvents()
        time.sleep(0.05)
        
    if wizard.proposal is not None:
        print(f"Proposal generated! Acceptable: {wizard.proposal.acceptable}")
        wizard.accept()
        print("Accepted!")
        
        # Check alignment
        pane = window.video_grid.panes[0]
        # Where does t=9.14 (first event) map to?
        print(f"Video mapping at master t=9.14: {pane.time_map.to_source(9.14)}")
    else:
        print("Proposal FAILED!")

if __name__ == "__main__":
    test_sync()
