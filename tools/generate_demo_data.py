import subprocess
from pathlib import Path

import numpy as np
import polars as pl

RNG = np.random.default_rng(42)


def _ffmpeg(*args: str, check: bool = True) -> None:
    subprocess.run(
        ["ffmpeg", "-y", *args],
        check=check,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _make_camera(path: Path, duration: float = 10.0, fps: int = 30) -> None:
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=640x360:rate={fps}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(path),
    )


def _make_camera_vfr(path: Path) -> None:
    """VFR video: drop every 7th frame using select filter, encode with vsync vfr."""
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=10:size=640x360:rate=30",
        "-vf",
        r"select=not(mod(n\,7))",
        "-vsync",
        "vfr",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(path),
    )


def _make_sensors_gaps(path: Path) -> None:
    """10 kHz, 10 s, with 3 deliberate time gaps, scattered NaNs, and sentinel -9999."""
    hz = 10_000
    n = hz * 10  # 100_000 samples
    t_full = np.linspace(0.0, 10.0, n)

    # Drop indices to create 3 gaps (~0.05 s each)
    gap_centers = [2.5, 5.0, 8.0]
    gap_half = int(hz * 0.025)
    keep = np.ones(n, dtype=bool)
    for gc in gap_centers:
        center_idx = int(gc / 10.0 * n)
        lo = max(0, center_idx - gap_half)
        hi = min(n, center_idx + gap_half)
        keep[lo:hi] = False
    t = t_full[keep]
    m = len(t)

    accel = np.sin(2 * np.pi * 5.0 * t) + RNG.normal(0, 0.05, m)
    gyro = np.cos(2 * np.pi * 2.0 * t) * np.exp(-t / 8)

    # Scatter NaN into ~0.1 % of samples
    nan_idx = RNG.integers(0, m, size=m // 1000)
    accel[nan_idx] = np.nan

    # Inject sentinel = -9999 into ~0.05 % of samples
    sentinel_idx = RNG.integers(0, m, size=m // 2000)
    gyro[sentinel_idx] = -9999.0

    pl.DataFrame({"time": t, "Accel_X": accel, "Gyro_Z": gyro}).write_csv(path)


def _make_pose_csv(path: Path) -> None:
    """Minimal DLC-style pose CSV (frame-indexed, no time column)."""
    n_frames = 300  # 10 s @ 30 fps
    frames = np.arange(n_frames)
    x_nose = 320.0 + 40 * np.sin(2 * np.pi * frames / 150) + RNG.normal(0, 2, n_frames)
    y_nose = 180.0 + 20 * np.cos(2 * np.pi * frames / 150) + RNG.normal(0, 2, n_frames)
    like_nose = np.clip(RNG.uniform(0.7, 1.0, n_frames), 0.0, 1.0)
    x_tail = 320.0 - 40 * np.sin(2 * np.pi * frames / 150) + RNG.normal(0, 2, n_frames)
    y_tail = 180.0 - 20 * np.cos(2 * np.pi * frames / 150) + RNG.normal(0, 2, n_frames)
    like_tail = np.clip(RNG.uniform(0.7, 1.0, n_frames), 0.0, 1.0)
    pl.DataFrame(
        {
            "frame": frames,
            "x_nose": x_nose,
            "y_nose": y_nose,
            "likelihood_nose": like_nose,
            "x_tail": x_tail,
            "y_tail": y_tail,
            "likelihood_tail": like_tail,
        }
    ).write_csv(path)


def main():
    out_dir = Path("examples/data")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Generating videos...")

    # camera_1: standard 30 fps reference
    vid_1 = out_dir / "camera_1.mp4"
    if not vid_1.exists():
        _make_camera(vid_1)
        print(f"Created {vid_1}")
    else:
        print(f"Already exists: {vid_1}")

    # camera_2: same content but caller applies +1.234 s session offset in the demo
    vid_2 = out_dir / "camera_2.mp4"
    if not vid_2.exists():
        _make_camera(vid_2)
        print(f"Created {vid_2}  (load with +1.234 s offset in demo)")
    else:
        print(f"Already exists: {vid_2}")

    # camera_3: slightly longer to simulate non-zero drift (~0.01 s over 10 s = 1000 ppm)
    vid_3 = out_dir / "camera_3.mp4"
    if not vid_3.exists():
        _make_camera(vid_3, duration=10.01)
        print(f"Created {vid_3}  (10.01 s → ~1000 ppm drift vs camera_1)")
    else:
        print(f"Already exists: {vid_3}")

    # camera_vfr: VFR video (every 7th frame dropped)
    vid_vfr = out_dir / "camera_vfr.mp4"
    if not vid_vfr.exists():
        _make_camera_vfr(vid_vfr)
        print(f"Created {vid_vfr}  (VFR — every 7th frame dropped)")
    else:
        print(f"Already exists: {vid_vfr}")

    print("Generating sensor data...")

    # sensors.csv: clean 1 kHz, 4 channels
    csv_path = out_dir / "sensors.csv"
    if not csv_path.exists():
        t = np.linspace(0, 10, 10_000)
        ch1 = np.sin(2 * np.pi * 1.5 * t) + RNG.normal(0, 0.1, len(t))
        ch2 = np.cos(2 * np.pi * 0.5 * t) * np.exp(-t / 5)
        ch3 = RNG.normal(0, 1, len(t)).cumsum() * 0.1
        ch4 = np.sign(np.sin(2 * np.pi * 0.2 * t)) * 2.0
        pl.DataFrame(
            {"time": t, "Accel_X": ch1, "Accel_Y": ch2, "Gyro_Z": ch3, "Steering_Angle": ch4}
        ).write_csv(csv_path)
        print(f"Created {csv_path}")
    else:
        print(f"Already exists: {csv_path}")

    # sensors_gaps.csv: 10 kHz with 3 gaps, NaNs, and sentinel values
    gaps_path = out_dir / "sensors_gaps.csv"
    if not gaps_path.exists():
        _make_sensors_gaps(gaps_path)
        print(f"Created {gaps_path}  (10 kHz, 3 gaps, NaNs, sentinel=-9999)")
    else:
        print(f"Already exists: {gaps_path}")

    # pose.csv: minimal DLC-style frame-indexed tracking
    pose_path = out_dir / "pose.csv"
    if not pose_path.exists():
        _make_pose_csv(pose_path)
        print(f"Created {pose_path}  (DLC-style, 300 frames @ 30 fps)")
    else:
        print(f"Already exists: {pose_path}")

    print("\nData generation complete — files are in examples/data/")
    print("  camera_1.mp4          30 fps reference")
    print("  camera_2.mp4          30 fps  (load with +1.234 s session offset)")
    print("  camera_3.mp4          30 fps  (~1000 ppm drift vs camera_1)")
    print("  camera_vfr.mp4        VFR  (every 7th frame dropped)")
    print("  sensors.csv           1 kHz, 4 channels, clean")
    print("  sensors_gaps.csv      10 kHz, 3 gaps, NaN, sentinel=-9999")
    print("  pose.csv              DLC-style, 300 frames @ 30 fps")


if __name__ == "__main__":
    main()
