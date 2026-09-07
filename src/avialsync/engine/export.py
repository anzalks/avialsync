"""Export utilities: data slice CSV/Parquet, region statistics, video clip.

Snapshot export lives in :mod:`avialsync.engine.snapshot`, which composes a
figure rather than saving a widget grab.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.engine.transcode import remux_clip


def _raw_slice(reader: Any, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return exact cached values in a time range without a recording-sized mask."""
    sliced: tuple[np.ndarray, np.ndarray, np.ndarray] = reader.raw_slice(t0, t1)
    return sliced


def _source_label(reader: Any) -> str:
    """Identify the owning source so equal channel names stay distinguishable."""
    source_id = getattr(reader, "source_id", "")
    return Path(source_id).name if source_id else reader.cache_dir.name


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
    """Trim a video clip by copying packets — no re-encode.

    The exported clip therefore holds the original pixels rather than a second
    generation of them, which matters for a tool whose output people measure.
    Done in-process with PyAV, so it needs no media runtime on the machine
    (D-075); the cut is keyframe-aligned at the start exactly as a stream copy
    has always been.
    """
    return remux_clip(video_path, output_path, t0, t1)
