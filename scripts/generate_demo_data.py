import subprocess
import numpy as np
import polars as pl
from pathlib import Path
import sys

def main():
    out_dir = Path("examples/data")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Generating videos...")
    for i in range(1, 4):
        vid_path = out_dir / f"camera_{i}.mp4"
        if not vid_path.exists():
            # Use testsrc to generate a test pattern. 
            cmd = [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"testsrc=duration=10:size=640x360:rate=30",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(vid_path)
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"Created {vid_path}")
        else:
            print(f"Already exists: {vid_path}")

    print("Generating random time series...")
    csv_path = out_dir / "sensors.csv"
    if not csv_path.exists():
        # 10 seconds at 1kHz = 10,000 points
        t = np.linspace(0, 10, 10000)
        
        # 4 random channels
        ch1 = np.sin(2 * np.pi * 1.5 * t) + np.random.normal(0, 0.1, len(t))
        ch2 = np.cos(2 * np.pi * 0.5 * t) * np.exp(-t/5)
        ch3 = np.random.normal(0, 1, len(t)).cumsum() * 0.1
        ch4 = np.sign(np.sin(2 * np.pi * 0.2 * t)) * 2.0
        
        df = pl.DataFrame({
            "time": t,
            "Accel_X": ch1,
            "Accel_Y": ch2,
            "Gyro_Z": ch3,
            "Steering_Angle": ch4
        })
        
        df.write_csv(csv_path)
        print(f"Created {csv_path}")
    else:
        print(f"Already exists: {csv_path}")

    print("\nData generation complete! You can find the files in examples/data/")

    # Generate the launch script
    launch_script = Path("scripts/launch_demo.py")
    launch_script.parent.mkdir(exist_ok=True)
    launch_code = """
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette

from kinochronix.ui.main_window import MainWindow

def load_data(win):
    print("Loading videos...")
    base_dir = Path("examples/data")
    for i in range(1, 4):
        win.video_grid.add_pane(str(base_dir / f"camera_{i}.mp4"))
    
    print("Loading CSV (mocking the finish signal directly for demo)...")
    from kinochronix.engine.importer import ImportWorker
    from kinochronix.core.cache import CacheManager
    
    # We just run the import worker synchronously for the demo launch
    config = {"time_col": "time", "time_unit": "s", "separator": ","}
    worker = ImportWorker(base_dir / "sensors.csv", config)
    worker.run() # blocks, but it's only 10k points so instant
    
    cache_mgr = CacheManager(loader_version=1)
    cache_dir = cache_mgr.get_cache_dir(base_dir / "sensors.csv")
    
    win._on_import_finished(cache_dir, ["Accel_X", "Accel_Y", "Gyro_Z", "Steering_Angle"], (0.0, 10.0))
    print("App is ready! Playing now...")
    
    # Auto-play
    win.player.play()

def main():
    app = QApplication(sys.argv)
    
    app.setStyle("Fusion")
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Base, QColor(18, 18, 18))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(30, 30, 30))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(dark_palette)
    
    win = MainWindow()
    win.show()
    
    # Schedule load_data after the event loop starts so the window renders first
    QTimer.singleShot(500, lambda: load_data(win))
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
"""
    launch_script.write_text(launch_code)
    print("Created launch script at scripts/launch_demo.py")

if __name__ == "__main__":
    main()
