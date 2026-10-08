"""Export utilities: data slice CSV/Parquet, region statistics, video clip.

Snapshot export lives in :mod:`avialsync.engine.snapshot`, which composes a
figure rather than saving a widget grab.
"""

from __future__ import annotations

import csv
import json
from itertools import chain
from pathlib import Path
from typing import Any

import numpy as np

from avialsync.core.artifact_io import publish
from avialsync.core.artifact_provenance import record
from avialsync.core.errors import ExportError
from avialsync.engine.transcode import remux_clip


def _source_label(reader: Any) -> str:
    """Identify the owning source so equal channel names stay distinguishable."""
    source_id = getattr(reader, "source_id", "")
    return Path(source_id).name if source_id else reader.cache_dir.name


def export_data_slice_csv(
    readers: list,
    t0: float,
    t1: float,
    path: Path,
    *,
    session: Path | None = None,
) -> None:
    """Export the raw data for all channels in [t0, t1] to CSV.

    One block per channel, each with its own time column.  Channels are never
    merged into shared rows: sources sampled at different rates, or offset
    against each other, do not share a time axis (P3.5 P1 identity).
    """

    def write(temporary: Path) -> None:
        with open(temporary, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            for reader in readers:
                wrote_header = False
                for times, values, _ in reader.iter_raw_chunks_with_gaps(t0=t0, t1=t1):
                    if not wrote_header:
                        writer.writerow([f"# Source: {_source_label(reader)}"])
                        writer.writerow([f"# Channel: {reader.channel_id}"])
                        writer.writerow(["time", reader.channel_id])
                        wrote_header = True
                    for t_val, v_val in zip(times, values, strict=True):
                        writer.writerow([repr(float(t_val)), repr(float(v_val))])
                if wrote_header:
                    writer.writerow([])
            provenance = record(
                "data-slice-csv",
                _source_paths(readers),
                session=session,
                time_maps=_time_maps(readers),
            )
            writer.writerow(["# avialsync: " + json.dumps(provenance)])

    publish(path, write, kind="data-slice-csv", sources=_source_paths(readers))


def export_data_slice_parquet(
    readers: list,
    t0: float,
    t1: float,
    path: Path,
    *,
    session: Path | None = None,
) -> Path:
    """Export the raw data for all channels in [t0, t1] to Parquet.

    Falls back to CSV if pyarrow is not installed.
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        csv_path = path.with_suffix(".csv")
        export_data_slice_csv(readers, t0, t1, csv_path, session=session)
        return csv_path

    chunks = (
        (reader, times, values, gaps)
        for reader in readers
        for times, values, gaps in reader.iter_raw_chunks_with_gaps(t0=t0, t1=t1)
    )
    first = next(chunks, None)
    if first is None:
        raise ExportError("The selected time range contains no samples to export.")

    schema = pa.schema(
        [
            ("source", pa.string()),
            ("channel", pa.string()),
            ("time", pa.float64()),
            ("value", pa.float64()),
            ("gap_after", pa.bool_()),
        ]
    )
    metadata = dict(schema.metadata or {})
    metadata[b"avialsync"] = json.dumps(
        record(
            "data-slice-parquet",
            _source_paths(readers),
            session=session,
            time_maps=_time_maps(readers),
        )
    ).encode("utf-8")
    schema = schema.with_metadata(metadata)

    def write(temporary: Path) -> None:
        with pq.ParquetWriter(str(temporary), schema) as writer:
            for reader, times, values, gaps in chain((first,), chunks):
                table = pa.table(
                    {
                        "source": pa.array([_source_label(reader)] * len(times), type=pa.string()),
                        "channel": pa.array([reader.channel_id] * len(times), type=pa.string()),
                        "time": times,
                        "value": values,
                        "gap_after": gaps,
                    },
                    schema=schema,
                )
                writer.write_table(table)

    publish(
        path,
        write,
        kind="data-slice-parquet",
        sources=_source_paths(readers),
    )
    return path


def _source_paths(readers: list) -> tuple[Path, ...]:
    """Return real source paths, omitting synthetic readers without one."""
    return tuple(Path(reader.source_id) for reader in readers if getattr(reader, "source_id", ""))


def _time_maps(readers: list) -> dict[str, dict[str, float]]:
    """Record each exported source's accepted mapping in its original units."""
    return {
        str(reader.source_id): {
            "offset_seconds": float(reader.time_map.offset),
            "drift_ms_per_hour": float(reader.time_map.drift_ms_per_hour),
        }
        for reader in readers
        if getattr(reader, "source_id", "") and getattr(reader, "time_map", None) is not None
    }


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
        count = 0
        total = 0.0
        total_sq = 0.0
        minimum = float("inf")
        maximum = float("-inf")
        for _times, values, _gaps in reader.iter_raw_chunks_with_gaps(t0=t0, t1=t1):
            valid = values[~np.isnan(values)]
            if not len(valid):
                continue
            count += len(valid)
            total += float(np.sum(valid, dtype=np.float64))
            total_sq += float(np.sum(valid**2, dtype=np.float64))
            minimum = min(minimum, float(np.min(valid)))
            maximum = max(maximum, float(np.max(valid)))
        if not count:
            results.append(dict(identity))
            continue
        results.append(
            {
                **identity,
                "n": count,
                "min": minimum,
                "max": maximum,
                "mean": total / count,
                "rms": float(np.sqrt(total_sq / count)),
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
