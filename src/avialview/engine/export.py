"""Export utilities: snapshot PNG, data slice CSV/Parquet, video clip."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path

import numpy as np
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget


def snapshot_widget(widget: QWidget) -> QPixmap:
    """Grab a widget's current visual content as a QPixmap."""
    return widget.grab()


def save_snapshot(
    video_pixmap: QPixmap | None,
    plot_pixmap: QPixmap | None,
    path: Path,
) -> None:
    """Stack video and plot snapshots vertically and save as PNG."""
    pixmaps = [p for p in (video_pixmap, plot_pixmap) if p and not p.isNull()]
    if not pixmaps:
        return

    total_w = max(p.width() for p in pixmaps)
    total_h = sum(p.height() for p in pixmaps)

    combined = QPixmap(total_w, total_h)
    combined.fill()

    painter = QPainter(combined)
    y = 0
    for p in pixmaps:
        painter.drawPixmap(0, y, p)
        y += p.height()
    painter.end()

    combined.save(str(path), "PNG")


def export_data_slice_csv(
    readers: list,
    t0: float,
    t1: float,
    path: Path,
) -> None:
    """Export the raw data for all channels in [t0, t1] to CSV."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        for reader in readers:
            t_arr, v_arr, _, _ = reader._load_level(1)
            if len(t_arr) == 0:
                continue

            mask = (t_arr >= t0) & (t_arr <= t1)
            t_slice = t_arr[mask]
            v_slice = v_arr[mask]

            writer.writerow([f"# Channel: {reader.channel_id}"])
            writer.writerow(["time", reader.channel_id])
            for t_val, v_val in zip(t_slice, v_slice, strict=False):
                writer.writerow([f"{t_val:.9g}", f"{v_val:.9g}"])
            writer.writerow([])


def export_data_slice_parquet(
    readers: list,
    t0: float,
    t1: float,
    path: Path,
) -> None:
    """Export the raw data for all channels in [t0, t1] to Parquet.

    Falls back to CSV if pyarrow is not installed.
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        csv_path = path.with_suffix(".csv")
        export_data_slice_csv(readers, t0, t1, csv_path)
        return

    arrays: dict[str, np.ndarray] = {}
    time_col: np.ndarray | None = None

    for reader in readers:
        t_arr, v_arr, _, _ = reader._load_level(1)
        if len(t_arr) == 0:
            continue

        mask = (t_arr >= t0) & (t_arr <= t1)
        t_slice = t_arr[mask]
        v_slice = v_arr[mask]

        if time_col is None:
            time_col = t_slice
            arrays["time"] = time_col
        arrays[reader.channel_id] = v_slice

    if not arrays:
        return

    table = pa.table(arrays)
    pq.write_table(table, str(path))


def compute_region_stats(
    readers: list,
    t0: float,
    t1: float,
) -> list[dict]:
    """Compute min/max/mean/rms for each channel in [t0, t1]."""
    results = []
    for reader in readers:
        t_arr, v_arr, _, _ = reader._load_level(1)
        if len(t_arr) == 0:
            results.append({"channel": reader.channel_id})
            continue

        mask = (t_arr >= t0) & (t_arr <= t1)
        v_slice = v_arr[mask]
        valid = v_slice[~np.isnan(v_slice)] if len(v_slice) > 0 else v_slice

        if len(valid) == 0:
            results.append({"channel": reader.channel_id})
            continue

        results.append(
            {
                "channel": reader.channel_id,
                "n": len(valid),
                "min": float(np.min(valid)),
                "max": float(np.max(valid)),
                "mean": float(np.mean(valid)),
                "rms": float(np.sqrt(np.mean(valid**2))),
            }
        )

    return results


def trim_video_clip(
    video_path: str,
    t0: float,
    t1: float,
    output_path: Path,
) -> bool:
    """Trim a video clip using ffmpeg stream copy (no re-encode)."""
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{t0:.6f}",
        "-to",
        f"{t1:.6f}",
        "-i",
        str(video_path),
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        str(output_path),
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=120,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
