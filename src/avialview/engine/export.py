"""Export utilities: snapshot PNG, data slice CSV/Parquet, video clip."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from avialview.runtime import no_window_kwargs


def _raw_slice(reader: Any, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return exact cached values in a time range without a recording-sized mask."""
    sliced: tuple[np.ndarray, np.ndarray, np.ndarray] = reader.raw_slice(t0, t1)
    return sliced


def _source_label(reader: Any) -> str:
    """Identify the owning source so equal channel names stay distinguishable."""
    source_id = getattr(reader, "source_id", "")
    return Path(source_id).name if source_id else reader.cache_dir.name


def snapshot_widget(widget: QWidget) -> QPixmap:
    """Grab a widget's current visual content as a QPixmap."""
    return widget.grab()


def save_snapshot(
    video_pixmap: QPixmap | None,
    plot_pixmap: QPixmap | None,
    path: Path,
) -> None:
    """Stack video and plot snapshots vertically and save as PNG."""
    save_snapshot_images(
        video_pixmap.toImage() if video_pixmap and not video_pixmap.isNull() else None,
        plot_pixmap.toImage() if plot_pixmap and not plot_pixmap.isNull() else None,
        path,
    )


def save_snapshot_images(
    video_image: QImage | None,
    plot_image: QImage | None,
    path: Path,
) -> None:
    """Encode widget-grab images to disk without requiring a GUI-thread QPixmap."""
    images = [image for image in (video_image, plot_image) if image and not image.isNull()]
    if not images:
        return

    total_w = max(image.width() for image in images)
    total_h = sum(image.height() for image in images)

    combined = QImage(total_w, total_h, QImage.Format.Format_ARGB32_Premultiplied)
    combined.fill(0)

    painter = QPainter(combined)
    y = 0
    for image in images:
        painter.drawImage(0, y, image)
        y += image.height()
    painter.end()

    # PySide6's stub declares QImage.save's `format` as bytes, but the runtime
    # rejects bytes and accepts str:
    #   QImage.save(path, b"PNG") -> ValueError: called with wrong argument values
    #   QImage.save(path, "PNG")  -> True
    # (QPixmap.save's stub correctly says str; QImage's does not.) Matching the
    # stub would break snapshot export, so the stub is what is wrong here.
    if not combined.save(str(path), "PNG"):  # type: ignore[call-overload]
        raise OSError(f"Could not write snapshot: {path}")


def export_data_slice_csv(
    readers: list,
    t0: float,
    t1: float,
    path: Path,
) -> None:
    """Export the raw data for all channels in [t0, t1] to CSV.

    One block per channel, each with its own time column.  Channels are never
    merged into shared rows: sources sampled at different rates, or offset
    against each other, do not share a time axis (P3.5 P1 identity).
    """
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        for reader in readers:
            t_slice, v_slice, _ = _raw_slice(reader, t0, t1)
            if len(t_slice) == 0:
                continue

            writer.writerow([f"# Source: {_source_label(reader)}"])
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

    source_columns: list[np.ndarray] = []
    channel_columns: list[np.ndarray] = []
    time_columns: list[np.ndarray] = []
    value_columns: list[np.ndarray] = []
    gap_columns: list[np.ndarray] = []

    for reader in readers:
        t_slice, v_slice, gap_slice = _raw_slice(reader, t0, t1)
        if len(t_slice) == 0:
            continue

        source_columns.append(np.full(len(t_slice), _source_label(reader), dtype=str))
        channel_columns.append(np.full(len(t_slice), reader.channel_id, dtype=str))
        time_columns.append(t_slice)
        value_columns.append(v_slice)
        gap_columns.append(gap_slice)

    if not time_columns:
        return

    table = pa.table(
        {
            "source": np.concatenate(source_columns),
            "channel": np.concatenate(channel_columns),
            "time": np.concatenate(time_columns),
            "value": np.concatenate(value_columns),
            "gap_before": np.concatenate(gap_columns),
        }
    )
    pq.write_table(table, str(path))


def compute_region_stats(
    readers: list,
    t0: float,
    t1: float,
) -> list[dict]:
    """Compute min/max/mean/rms for each channel in [t0, t1].

    Each row carries its owning source, so two files contributing a channel of
    the same name produce two distinct rows instead of one overwriting the other.
    """
    results = []
    for reader in readers:
        identity = {"channel": reader.channel_id, "source": _source_label(reader)}
        _, v_slice, _ = _raw_slice(reader, t0, t1)
        if len(v_slice) == 0:
            results.append(dict(identity))
            continue
        valid = v_slice[~np.isnan(v_slice)] if len(v_slice) > 0 else v_slice

        if len(valid) == 0:
            results.append(dict(identity))
            continue

        results.append(
            {
                **identity,
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
            **no_window_kwargs(),
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
