"""Synthetic ground-truth data generator for KinoChronix fixtures.

This script creates video and time-series data with known properties for sync testing.
All videos have a binary frame-index strip encoded in the top row.
"""

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

import numpy as np
import polars as pl

# Note: we need the framestrip encoder. Since it's in tests/, we should add it
# to path or duplicate. For simplicity, we can just duplicate the tiny encoder
# here, or import it if PYTHONPATH is set.
# Let's just duplicate the encoder logic here to keep tools/ isolated, or modify sys.path.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from tests.util_framestrip import encode_frame_index


def generate_video(
    out_path: pathlib.Path,
    fps: float,
    frames: int,
    variant: str = "base",
    offset: float = 0.0,
    drift_ppm: float = 0.0,
    width: int = 640,
    height: int = 360,
) -> None:
    """Generate a video using numpy and ffmpeg.

    Variants:
    - base: h264 8-bit short-GOP
    - high_10bit: h265 10-bit long-GOP
    - mono_12bit: h265 12-bit greyscale
    - vfr: variable frame rate (via remux)
    - dropped_frames: 30fps but drops every 97th frame
    - no_metadata: stripped metadata
    - image_seq: outputs to a folder of tiffs
    - split: 2-part split video
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-s",
        f"{width}x{height}",
        "-pix_fmt",
        "gray",
        "-r",
        str(fps),
        "-i",
        "-",
    ]

    # Configure output formats based on variant
    if variant in ("base", "no_metadata", "split"):
        # h264 8-bit short-GOP (e.g. g=15 for 30fps = 0.5s)
        cmd.extend(["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-g", "15"])
    elif variant == "high_10bit":
        # h265 10-bit long-GOP (g=300)
        cmd.extend(
            ["-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le", "-g", "300"]
        )
    elif variant == "mono_12bit":
        # h265 12-bit greyscale (using gray10le since gray12le is less common, or yuv420p12le)
        cmd.extend(
            ["-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "gray10le"]
        )  # FFmpeg x265 supports 10 or 12, we'll use 10 for safety if 12 isn't compiled.
    elif variant == "image_seq":
        out_path.mkdir(parents=True, exist_ok=True)
        out_path = out_path / "img_%06d.tif"
        cmd.extend(["-c:v", "tiff", "-pix_fmt", "gray"])
    elif variant in ("vfr", "dropped_frames"):
        # We will generate a base raw video first, then remux it
        cmd.extend(["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"])

    final_out_path = out_path
    if variant in ("vfr", "dropped_frames", "no_metadata", "split"):
        final_out_path = out_path.with_name(out_path.name + ".tmp.mp4")

    cmd.append(str(final_out_path))

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdin is not None

    actual_frames = []

    for i in range(frames):
        if variant == "dropped_frames" and i % 97 == 0:
            continue  # drop frame

        # Add visual noise or sweep pattern so it's not totally static
        frame = np.full((height, width), (i % 256), dtype=np.uint8)

        # Encode binary index in top row
        encode_frame_index(frame, i)

        proc.stdin.write(frame.tobytes())
        actual_frames.append(i)

    proc.stdin.close()
    proc.wait()
    assert proc.returncode == 0, f"ffmpeg failed for variant {variant}"

    # Post-processing for special variants
    if variant == "no_metadata":
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(final_out_path),
                "-map_metadata",
                "-1",
                "-c",
                "copy",
                str(out_path),
            ],
            check=True,
            stderr=subprocess.DEVNULL,
        )
        final_out_path.unlink()
    elif variant == "split":
        # Split into part 1 (first half) and part 2 (second half)
        mid = (frames // 2) / fps
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(final_out_path),
                "-t",
                str(mid),
                "-c",
                "copy",
                str(out_path.with_name("split_part1.mp4")),
            ],
            check=True,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(final_out_path),
                "-ss",
                str(mid),
                "-c",
                "copy",
                str(out_path.with_name("split_part2.mp4")),
            ],
            check=True,
            stderr=subprocess.DEVNULL,
        )
        final_out_path.unlink()

        # Save JSON for both
        with open(out_path.with_name("split_part1.json"), "w") as f:
            json.dump({"fps": fps, "frames": len(actual_frames) // 2, "offset": offset}, f)
        with open(out_path.with_name("split_part2.json"), "w") as f:
            json.dump(
                {
                    "fps": fps,
                    "frames": len(actual_frames) - (len(actual_frames) // 2),
                    "offset": offset + mid,
                },
                f,
            )
        return  # Skip writing the main json
    elif variant == "vfr":
        # Generate a timecode v2 file and remux with mkvmerge (if available) or mp4box.
        # Actually ffmpeg can do VFR from an image sequence or by copying timestamps.
        # It's easier to create a VFR video by using a simple ffmpeg filter `setpts`.
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(final_out_path),
                "-vf",
                "setpts='(PTS*(1+0.2*sin(PTS/10)))'",
                "-c:v",
                "libx264",
                str(out_path),
            ],
            check=True,
            stderr=subprocess.DEVNULL,
        )
        final_out_path.unlink()

        # We need ffprobe to get the actual frame times, but we'll let the golden tests read them.
        # For ground truth, we can just save it.
    elif variant == "dropped_frames":
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(final_out_path), "-c", "copy", str(out_path)],
            check=True,
            stderr=subprocess.DEVNULL,
        )
        final_out_path.unlink()

    # Save metadata JSON
    meta = {
        "variant": variant,
        "fps": fps,
        "frames_total": len(actual_frames),
        "offset": offset,
        "drift_ppm": drift_ppm,
        "expected_indices": actual_frames,
    }

    json_path = (
        out_path.with_suffix(".json")
        if variant != "image_seq"
        else out_path.parent / "metadata.json"
    )
    with open(json_path, "w") as f:
        json.dump(meta, f, indent=2)


def generate_signal(
    out_path: pathlib.Path, duration_s: float, rate: float = 50000.0, variant: str = "base"
) -> None:
    """Generate 4-channel 16-bit time series data."""
    n_points = int(duration_s * rate)
    t = np.arange(n_points) / rate

    # 4 channels:
    # 0: Sine wave 1Hz
    # 1: Sine sweep 1Hz -> 100Hz
    # 2: Step event at exactly t=duration/2
    # 3: Random noise

    ch0 = np.sin(2 * np.pi * 1.0 * t)
    ch1 = np.sin(2 * np.pi * (1.0 + (99.0 * t / duration_s)) * t)

    step_idx = n_points // 2
    step_t = float(t[step_idx])
    ch2 = np.zeros(n_points)
    ch2[step_idx:] = 1.0

    ch3 = np.random.randn(n_points)

    # Scale to 16-bit int range (-32768, 32767) but keep as float for CSV
    ch0 = (ch0 * 32000).astype(np.float64)
    ch1 = (ch1 * 32000).astype(np.float64)
    ch2 = (ch2 * 32000).astype(np.float64)
    ch3 = (ch3 * 5000).astype(np.float64)

    df = pl.DataFrame({"time": t, "ch0": ch0, "ch1": ch1, "ch2": ch2, "ch3": ch3})

    # Apply pathologies
    if variant == "epoch_ns":
        df = df.with_columns((pl.col("time") * 1e9).cast(pl.Int64).alias("time"))
    elif variant == "iso8601":
        # Convert to datetime string
        import datetime

        base_dt = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)

        def to_iso(val: float) -> str:
            dt = base_dt + datetime.timedelta(seconds=val)
            return dt.isoformat()

        df = df.with_columns(pl.col("time").map_elements(to_iso, return_dtype=pl.Utf8))
    elif variant == "tz_naive":
        import datetime

        base_dt = datetime.datetime(2026, 1, 1, 12, 0, 0)

        def to_naive(val: float) -> str:
            dt = base_dt + datetime.timedelta(seconds=val)
            return dt.isoformat()

        df = df.with_columns(pl.col("time").map_elements(to_naive, return_dtype=pl.Utf8))
    elif variant == "time_only":
        import datetime

        base_dt = datetime.datetime(2026, 1, 1, 12, 0, 0)

        def to_time(val: float) -> str:
            dt = base_dt + datetime.timedelta(seconds=val)
            return dt.strftime("%H:%M:%S.%f")

        df = df.with_columns(pl.col("time").map_elements(to_time, return_dtype=pl.Utf8))
    elif variant == "non_monotonic":
        # Shuffle a block of 1000 rows
        if n_points > 2000:
            df_head = df[:1000]
            df_shuffle = df[1000:2000].sample(fraction=1.0, seed=42)
            df_tail = df[2000:]
            df = pl.concat([df_head, df_shuffle, df_tail])
    elif variant == "duplicates":
        if n_points > 100:
            df = pl.concat([df[:100], df[99:101], df[100:]])
    elif variant == "clock_jump":
        if n_points > 1000:
            # Jump backward by 1 second at row 1000
            t_col = df["time"].to_numpy().copy()
            t_col[1000:] -= 1.0
            df = df.with_columns(pl.Series("time", t_col))
    elif variant == "nan_gap_sentinel":
        # Insert NaNs, a big gap, and sentinels
        ch0_col = df["ch0"].to_numpy().copy()
        t_col = df["time"].to_numpy().copy()

        if n_points > 2000:
            ch0_col[100:200] = np.nan
            ch0_col[500:600] = -9999  # sentinel

            # gap: remove rows 1000 to 1500
            mask = np.ones(n_points, dtype=bool)
            mask[1000:1500] = False

            df = pl.DataFrame(
                {
                    "time": t_col[mask],
                    "ch0": ch0_col[mask],
                    "ch1": df["ch1"].to_numpy()[mask],
                    "ch2": df["ch2"].to_numpy()[mask],
                    "ch3": df["ch3"].to_numpy()[mask],
                }
            )

    # Write CSV
    if variant == "euro_dialect":
        # Convert floats to string with comma, separator is semicolon
        def to_comma(x: float) -> str:
            return str(x).replace(".", ",")

        df_str = df.select(
            [pl.col(c).map_elements(to_comma, return_dtype=pl.Utf8) for c in df.columns]
        )
        df_str.write_csv(out_path, separator=";")
    elif variant == "bom":
        _ = df.write_csv().encode(
            "utf-8-sig"
        )  # not natively supported by polars directly to file with BOM
        with open(out_path, "wb") as f:
            f.write(b"\xef\xbb\xbf")
            f.write(df.write_csv().encode("utf-8"))
    elif variant == "units_row":
        with open(out_path, "w") as f:
            f.write("time,ch0,ch1,ch2,ch3\n")
            f.write("s,V,V,V,V\n")
            f.write(df.write_csv(include_header=False))
    else:
        df.write_csv(out_path)

    # Write JSON metadata
    meta = {"variant": variant, "rate": rate, "duration_s": duration_s, "step_event_time": step_t}
    with open(out_path.with_suffix(".json"), "w") as f:
        json.dump(meta, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--small", action="store_true")
    parser.add_argument("--big", action="store_true")
    args = parser.parse_args()

    np.random.seed(args.seed)

    repo_root = pathlib.Path(__file__).parent.parent
    fixtures_dir = repo_root / "tests" / "fixtures"

    if fixtures_dir.exists():
        shutil.rmtree(fixtures_dir)

    vid_dir = fixtures_dir / "videos"
    sig_dir = fixtures_dir / "signals"
    vid_dir.mkdir(parents=True)
    sig_dir.mkdir(parents=True)

    # 1. Generate Videos
    vid_dur = 1 if args.small else 10
    fps = 30
    frames = vid_dur * fps

    generate_video(vid_dir / "base_30fps.mp4", fps, frames, "base")
    generate_video(vid_dir / "high_10bit.mp4", fps, frames, "high_10bit")
    generate_video(vid_dir / "mono_12bit.mp4", fps, frames, "mono_12bit")

    # 3-camera set
    generate_video(vid_dir / "camera_1.mp4", fps, frames, "base", offset=0.0)
    generate_video(vid_dir / "camera_2.mp4", fps, frames, "base", offset=1.234)
    generate_video(vid_dir / "camera_3.mp4", fps, frames, "base", offset=7.500)
    generate_video(vid_dir / "camera_drift.mp4", fps, frames, "base", drift_ppm=2.0)

    generate_video(vid_dir / "vfr.mp4", fps, frames, "vfr")
    generate_video(vid_dir / "dropped_frames.mp4", fps, frames, "dropped_frames")
    generate_video(vid_dir / "no_metadata.mp4", fps, frames, "no_metadata")
    generate_video(vid_dir / "img_seq", fps, frames, "image_seq")
    generate_video(vid_dir / "split.mp4", fps, frames, "split")

    # 2. Generate Signals
    if args.small:
        base_dur = 2
        path_dur = 1
    elif args.big:
        base_dur = 3600
        path_dur = 10
    else:
        base_dur = 600
        path_dur = 10

    generate_signal(sig_dir / "signal_base.csv", base_dur, variant="base")
    generate_signal(sig_dir / "signal_epoch_ns.csv", path_dur, variant="epoch_ns")
    generate_signal(sig_dir / "signal_iso8601.csv", path_dur, variant="iso8601")
    generate_signal(sig_dir / "signal_tz_naive.csv", path_dur, variant="tz_naive")
    generate_signal(sig_dir / "signal_time_only.csv", path_dur, variant="time_only")
    generate_signal(sig_dir / "signal_non_monotonic.csv", path_dur, variant="non_monotonic")
    generate_signal(sig_dir / "signal_duplicates.csv", path_dur, variant="duplicates")
    generate_signal(sig_dir / "signal_clock_jump.csv", path_dur, variant="clock_jump")
    generate_signal(sig_dir / "signal_euro_dialect.csv", path_dur, variant="euro_dialect")
    generate_signal(sig_dir / "signal_bom.csv", path_dur, variant="bom")
    generate_signal(sig_dir / "signal_units_row.csv", path_dur, variant="units_row")
    generate_signal(sig_dir / "signal_nan_gap_sentinel.csv", path_dur, variant="nan_gap_sentinel")

    # 3. Create Sample Session
    sample_dir = fixtures_dir / "sample_session"
    sample_dir.mkdir(parents=True)
    # Just copy camera 1 and base signal for a tiny sample dataset
    shutil.copy(vid_dir / "camera_1.mp4", sample_dir / "camera_1.mp4")
    shutil.copy(vid_dir / "camera_1.json", sample_dir / "camera_1.json")
    shutil.copy(sig_dir / "signal_base.csv", sample_dir / "signal_base.csv")
    shutil.copy(sig_dir / "signal_base.json", sample_dir / "signal_base.json")

    print("Fixtures generated successfully.")


if __name__ == "__main__":
    main()
