"""Demo launcher — loads all example fixtures to exercise inspection-layer features."""

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from kinochronix.ui.main_window import MainWindow
from kinochronix.ui.theme import load_saved_font_size, load_saved_theme


def load_data(win: MainWindow) -> None:
    base_dir = Path("examples/data")
    if not base_dir.exists():
        print(
            "examples/data not found — run:\n"
            "  conda run -n kinochronix python tools/generate_demo_data.py"
        )
        return

    # ── Step 1: load pose.csv (DLC, frame-indexed) BEFORE any video ──────────
    # This exercises the provisional-fps path: TrackingLoader is frame-indexed,
    # no video fps available yet, so the source is held in _frame_indexed_sources.
    pose_path = base_dir / "pose.csv"
    if pose_path.exists():
        print("Loading pose.csv (provisional, frame-indexed) — will rebind when video loads…")
        win._frame_indexed_sources.append((pose_path, 30.0))

    # ── Step 2: load camera_1 (standard 30 fps) ───────────────────────────────
    # Triggers _rebind_frame_indexed_sources → pose.csv re-imported with fps=30.
    cam1 = base_dir / "camera_1.mp4"
    if cam1.exists():
        print(f"Loading {cam1.name}  (30 fps reference — triggers pose.csv rebind)")
        win._load_video(cam1)

    # ── Step 3: load camera_2 with +1.234 s session offset ────────────────────
    cam2 = base_dir / "camera_2.mp4"
    if cam2.exists():
        print(f"Loading {cam2.name}  (applying +1.234 s session offset)")
        win._load_video(cam2, offset=1.234)

    # ── Step 4: load camera_3 with a known drift mapping ─────────────────────
    cam3 = base_dir / "camera_3.mp4"
    if cam3.exists():
        print(f"Loading {cam3.name}  (~1000 ppm drift vs camera_1)")
        # _load_video is asynchronous. Pass the mapping into its worker-owned
        # completion path instead of accessing video_grid.panes immediately.
        win._load_video(cam3, drift_ppm=1000.0)

    # ── Step 5: load camera_vfr to demonstrate VFR detection ─────────────────
    cam_vfr = base_dir / "camera_vfr.mp4"
    if cam_vfr.exists():
        print(f"Loading {cam_vfr.name}  (VFR — integrity badge should appear)")
        win._load_video(cam_vfr)

    # ── Step 6: load sensors.csv (clean 1 kHz, with explicit units) ──────────
    from kinochronix.core.cache import CacheManager
    from kinochronix.core.inspection import ImportReport, IntegrityFlags, SourceInspection
    from kinochronix.engine.importer import ImportWorker

    sensors_path = base_dir / "sensors.csv"
    if sensors_path.exists():
        print(f"Loading {sensors_path.name}  (1 kHz, 4 channels, with units)")
        config = {
            "time_col": "time",
            "time_unit": "s",
            "separator": ",",
            "units": {
                "Accel_X": "m/s²",
                "Accel_Y": "m/s²",
                "Gyro_Z": "deg/s",
                "Steering_Angle": "deg",
            },
        }
        worker = ImportWorker(sensors_path, config)
        worker.run()
        cache_dir = CacheManager(loader_version=1).get_cache_dir(sensors_path)
        channels = ["Accel_X", "Accel_Y", "Gyro_Z", "Steering_Angle"]
        # Build a minimal SourceInspection so units reach ReadoutPanel via _inspections
        inspection = SourceInspection(
            path=str(sensors_path),
            loader_id="CSVLoader",
            import_config=config,
            integrity_flags=IntegrityFlags(),
        )
        win._on_import_finished(
            str(sensors_path), str(cache_dir), channels, (0.0, 10.0), inspection
        )

    # ── Step 7: load sensors_gaps.csv (10 kHz, gaps + NaN + sentinel) ────────
    gaps_path = base_dir / "sensors_gaps.csv"
    if gaps_path.exists():
        print(f"Loading {gaps_path.name}  (10 kHz, 3 gaps, NaN, sentinel=-9999)")
        config2 = {
            "time_col": "time",
            "time_unit": "s",
            "separator": ",",
            "sentinel": -9999.0,
            "units": {"Accel_X": "m/s²", "Gyro_Z": "deg/s"},
        }
        worker2 = ImportWorker(gaps_path, config2)
        worker2.run()
        cache_dir2 = CacheManager(loader_version=1).get_cache_dir(gaps_path)
        inspection2 = SourceInspection(
            path=str(gaps_path),
            loader_id="CSVLoader",
            import_config=config2,
            import_report=ImportReport(rows_parsed=94_500, gap_count=3, nan_count=94),
            integrity_flags=IntegrityFlags(has_gaps=True),
        )
        win._on_import_finished(
            str(gaps_path), str(cache_dir2), ["Accel_X", "Gyro_Z"], (0.0, 10.0), inspection2
        )

    print("\nDemo ready — all fixtures loaded. Playing…")
    win.player.play()


def main():
    app = QApplication(sys.argv)
    load_saved_theme(app)
    load_saved_font_size(app)

    win = MainWindow()
    win.show()

    # Schedule load_data after the event loop starts so the window renders first
    QTimer.singleShot(500, lambda: load_data(win))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
