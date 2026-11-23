"""Record separate, real-time AvialSync showcase clips from local recordings.

Run on a real display (do not set QT_QPA_PLATFORM=offscreen)::

    conda run -n avialsync python tools/record_demo_videos.py --list
    conda run -n avialsync python tools/record_demo_videos.py
    conda run -n avialsync python tools/record_demo_videos.py data/09-35-24

Defaults to one representative session per immediate data/ subfolder, preferring
leaf sessions over experiments containing multiple trials. Each recording gets a
fresh process, isolated preferences/recovery, a 20-second MP4, a preview PNG and a
JSON report. Outputs live in the already git-ignored data/demo_videos/ directory.
Existing clips are never overwritten: each invocation creates a dated directory.
No source files, application code, accepted mappings or user settings are edited.
Coverage means the loaded sources' current placement, not verified alignment.
Short recordings use a slower transport rate so all 20 seconds contain data.
Loose tracking folders prefer CSV over same-name HDF5 exports and original
videos over DLC-annotated renders of those same videos.
Untimed stacks use the user's provisional 30 fps choice (--imaging-fps).
Timing already present in a recording always takes priority.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "demo_videos"


def discover(root: Path) -> list[Path]:
    """Find one representative recording per data category without mixing trials."""
    from avialsync.core.registry import LoaderRegistry
    from avialsync.core.source import VideoSource

    registry = LoaderRegistry()
    selected = []
    for category in sorted(root.iterdir()):
        if not category.is_dir() or category.name == "demo_videos":
            continue
        # A camera may be beside the acquisition tree rather than inside it.
        # Descending to its leaf recording would silently leave that camera out.
        if registry.find_best_session(category) and any(
            (loader := registry.find_best_loader(path)) is not None
            and issubclass(loader, VideoSource)
            for path in category.iterdir()
            if path.is_file()
        ):
            selected.append(category)
            continue
        folders = [category]
        for current, directories, _files in os.walk(category):
            parent = Path(current)
            directories[:] = sorted(
                name
                for name in directories
                if not name.startswith(".")
                and "avialcache" not in name
                and len((parent / name).relative_to(category).parts) <= 3
            )
            folders.extend(parent / name for name in directories)
        sessions = [path for path in folders if registry.find_best_session(path)]
        leaves = [path for path in sessions if not any(path in p.parents for p in sessions)]
        if leaves:
            selected.append(sorted(leaves, key=lambda p: ("sample" not in p.name, str(p)))[0])
        else:
            containers = sorted(category.rglob("*.nwb"))
            stacks = sorted(category.rglob("*.tif")) + sorted(category.rglob("*.tiff"))
            selected.append((containers or stacks or [category])[0])
    return selected


def shared_interval(coverage: Sequence[Any]) -> tuple[float, float]:
    """Find the longest common interval, subtracting declared coverage gaps."""
    if not coverage:
        raise RuntimeError("No loaded source coverage was reported.")
    start = max(float(source.data[0]) for source in coverage)
    end = min(float(source.data[1]) for source in coverage)
    intervals = [(start, end)] if end > start else []
    for source in coverage:
        for gap_start, gap_end in source.gaps:
            remaining = []
            for left, right in intervals:
                if gap_end <= left or gap_start >= right:
                    remaining.append((left, right))
                else:
                    if left < gap_start:
                        remaining.append((left, gap_start))
                    if gap_end < right:
                        remaining.append((gap_end, right))
            intervals = remaining
    if not intervals:
        raise RuntimeError("Loaded streams have no common gap-free coverage; no mapping invented.")
    return max(intervals, key=lambda pair: pair[1] - pair[0])


def _channel_coverage(readers: list[Any]) -> Any:
    """Intersect channel bounds and find timestamp gaps off the UI thread."""
    import numpy as np

    from avialsync.ui.coverage_lanes import SourceCoverage

    spans = []
    gaps: set[tuple[float, float]] = set()
    for reader in readers:
        span = reader.coverage()
        if span is None:
            raise RuntimeError("A loaded channel has no sample coverage.")
        spans.append(span)
        times, _values, mask = reader.mapped_columns()
        if not len(mask) or (mask.strides[0] == 0 and not mask[0]):
            continue
        for index in np.flatnonzero(mask):
            if index + 1 < len(times):
                gaps.add(
                    (
                        reader.time_map.to_master(times[index]),
                        reader.time_map.to_master(times[index + 1]),
                    )
                )
    if not spans:
        return None
    return SourceCoverage(
        label="All displayed channels",
        data=(max(s[0] for s in spans), min(s[1] for s in spans)),
        gaps=tuple(sorted(gaps)),
    )


def _scan(path: Path, registry: Any, imaging_fps: float | None) -> tuple[list[Any], Any]:
    """Scan with the same plugin/pairing machinery used by drag and drop."""
    from avialsync.core.errors import ImagingChoiceRequired
    from avialsync.core.source import ImagingSource
    from avialsync.engine.drop_worker import DropScanWorker

    worker = DropScanWorker([path], registry)
    results: list[Any] = []
    errors: list[str] = []
    worker.finished.connect(lambda candidates, layout: results.extend([candidates, layout]))
    worker.error.connect(errors.append)
    worker.run()
    if errors or not results:
        raise RuntimeError("; ".join(errors) or "Folder scan returned no result.")
    candidates, layout = results
    if not layout.items:
        candidates = _loose_tracking(candidates)
    prepared = []
    for source, loader, config in candidates:
        config = dict(config or {})
        if loader and issubclass(loader, ImagingSource):
            reader = loader()
            try:
                try:
                    reader.open(source, config)
                except ImagingChoiceRequired as choice:
                    if choice.choice != "fps" or imaging_fps is None:
                        raise
                    config["fps"] = imaging_fps
                    reader.close()
                    reader.open(source, config)
            finally:
                reader.close()
        prepared.append((source, loader, config))
    return prepared, layout


def _loose_tracking(candidates: list[Any]) -> list[Any]:
    """Choose original video and one pose export in a loose DLC folder."""
    from avialsync.core.source import VideoSource

    paths = {path for path, _, _ in candidates}
    videos = [path for path, loader, _ in candidates if loader and issubclass(loader, VideoSource)]
    originals = [
        path
        for path in videos
        if not any(path.stem.startswith(other.stem + "DLC") for other in videos if other != path)
    ]
    selected = []
    for path, loader, config in candidates:
        if path in videos and path not in originals:
            continue
        if path.suffix.lower() in (".h5", ".hdf5") and path.with_suffix(".csv") in paths:
            continue
        config = dict(config or {})
        if loader and "overlay2d" in getattr(loader, "pose_roles", lambda: ())():
            matches = [video for video in originals if path.stem.startswith(video.stem + "DLC")]
            if len(matches) == 1:
                config.update(role="overlay2d", overlay_video=str(matches[0]))
        selected.append((path, loader, config))
    return selected


def _load(
    window: Any, app: Any, path: Path, pool: ThreadPoolExecutor, imaging_fps: float | None
) -> list[str]:
    """Run intake off-thread and wait for imports and deferred plot rows."""
    from screenshot_kit import wait_until

    from avialsync.ui.controllers.drop_controller import apply_session_layout

    scan = pool.submit(_scan, path, window._registry, imaging_fps)
    wait_until(app, scan.done, "session scan", timeout_ms=300_000)
    candidates, layout = scan.result()
    apply_session_layout(window, layout)
    supported = [entry for entry in candidates if entry[1] is not None]
    if not supported:
        raise RuntimeError("No supported sources found in this recording.")
    window.video_grid.begin_batch_add()
    try:
        for source, loader, config in supported:
            window._route_import_candidate(source, loader, config)
    finally:
        window.video_grid.end_batch_add()
    # Imports enqueue their successor with singleShot; require continuous quiet
    # so a gap between jobs cannot be mistaken for the end of the batch.
    quiet_since = time.perf_counter()

    def ready() -> bool:
        nonlocal quiet_since
        busy = (
            window._job_manager.is_busy()
            or window.import_state.pending
            or window.import_state.active_thread is not None
            or window.plot_pane._pending_rows
            or window.imaging_pending
        )
        if busy:
            quiet_since = time.perf_counter()
        return not busy and time.perf_counter() - quiet_since > 2.0

    wait_until(app, ready, "all source imports", timeout_ms=600_000)
    actual = set(window.video_grid.pane_paths()) | set(window._sensor_cache_dirs)
    actual.update(window.imaging_pane.source_paths())
    actual.update(window._pose_cache_dirs)
    actual.update(window._pose_3d_sources)
    missing = [str(source) for source, _, _ in supported if str(source) not in actual]
    if missing:
        raise RuntimeError(f"Some sources failed to load; not recording a partial demo: {missing}")
    return [str(source) for source, _, _ in supported]


def _record(
    window: Any, app: Any, movie: Path, seconds: float, fps: int, pool: Any
) -> dict[str, Any]:
    """Capture actual playback; encode off-thread with a bounded frame queue."""
    import numpy as np
    from PySide6.QtCore import QEventLoop, Qt, QTimer
    from PySide6.QtGui import QImage

    from avialsync.engine.transcode import encode_video

    pending: queue.Queue[tuple[np.ndarray, float] | None] = queue.Queue(maxsize=8)

    def frames() -> Iterator[tuple[np.ndarray, float]]:
        while (item := pending.get()) is not None:
            yield item

    encoding = pool.submit(
        encode_video,
        movie,
        frames(),
        rate=Fraction(fps),
        end_seconds=seconds,
        encoder_preset="ultrafast",
        encoder_crf="18",
    )
    loop = QEventLoop(app)
    timer = QTimer(loop)
    timer.setTimerType(Qt.TimerType.PreciseTimer)
    timer.setInterval(round(1000 / fps))
    captured = 0
    dropped = 0
    errors: list[Exception] = []
    started = time.perf_counter()

    def grab() -> None:
        nonlocal captured, dropped
        elapsed = time.perf_counter() - started
        if elapsed >= seconds:
            loop.quit()
            return
        try:
            if encoding.done():
                encoding.result()
                raise RuntimeError("Encoder stopped before capture ended.")
            image = window.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
            pixels = np.frombuffer(image.constBits(), dtype=np.uint8)
            rows = pixels.reshape(image.height(), image.bytesPerLine())
            rgb = rows[:, : image.width() * 3].reshape(image.height(), image.width(), 3).copy()
            pending.put_nowait((rgb, 0.0 if captured == 0 else elapsed))
            captured += 1
        except queue.Full:
            dropped += 1
        except Exception as error:
            errors.append(error)
            loop.quit()

    window.player.play()
    grab()
    timer.timeout.connect(grab)
    timer.start()
    loop.exec()
    timer.stop()
    window.player.set_playing(False)
    # No blocking queue operation on the UI thread, including the sentinel.
    finish = pool.submit(pending.put, None, timeout=30)
    from screenshot_kit import wait_until

    wait_until(app, lambda: encoding.done() or finish.done(), "encoder queue drain", 60_000)
    wait_until(app, encoding.done, "video encoding", 60_000)
    encoding.result()
    if errors:
        raise errors[0]
    return {"frames": captured, "dropped_captures": dropped, "wall_seconds": seconds}


def record_one(args: argparse.Namespace) -> None:
    """Open exactly one dataset in an isolated application process."""
    from PySide6.QtWidgets import QApplication
    from screenshot_kit import USER_STATE_SANDBOX, pin_appearance, pin_layout, wait_until

    from avialsync.ui.job_manager import drain_abandoned
    from avialsync.ui.main_window import MainWindow

    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    pin_appearance(app)
    window = MainWindow()
    window.resize(args.width, args.height)
    window.show()
    output = args.output
    report: dict[str, Any] = {"source": str(args.paths[0]), "status": "failed"}
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            report["sources"] = _load(window, app, args.paths[0], pool, args.imaging_fps)
            pin_layout(window)
            coverage = window._source_coverage()
            from avialsync.ui.coverage_lanes import SourceCoverage

            for path in set(window._pose_cache_dirs) | set(window._pose_3d_sources):
                readers = list(window._pose_3d_sources.get(path, ()))
                for sources in window._overlay_sources.values():
                    for pair in sources.get(path, {}).get("points", {}).values():
                        readers.extend(pair)
                spans = [span for reader in readers if (span := reader.coverage()) is not None]
                if not spans:
                    raise RuntimeError(f"No pose coverage available for {path}")
                coverage.append(
                    SourceCoverage(
                        label=Path(path).name,
                        data=(max(s[0] for s in spans), min(s[1] for s in spans)),
                    )
                )
            readers = [channel.reader for channel in window.plot_pane.channels]
            channel_scan = pool.submit(_channel_coverage, readers)
            wait_until(app, channel_scan.done, "channel gap inspection", 300_000)
            if (channels := channel_scan.result()) is not None:
                coverage.append(channels)
            left, right = shared_interval(coverage)
            # Stay away from boundary rounding; slow short trials, never loop
            # across a missing stream or freeze on the final frame.
            margin = min(0.1, (right - left) * 0.01)
            speed = min(1.0, (right - left - 2 * margin) / (args.duration + 0.5))
            if speed < 0.01 or not math.isfinite(speed):
                raise RuntimeError("Recording is too short even at the minimum playback rate.")
            start = left + margin
            window.plot_pane._sweep_control.set_window_duration(min(10.0, right - left))
            window.player.set_rate(speed)
            rate_combo = window.transport.rate_combo
            rate_index = rate_combo.findData(speed)
            if rate_index < 0:
                rate_combo.addItem(f"{speed:.3f}x", speed)
                rate_index = rate_combo.count() - 1
            rate_combo.setCurrentIndex(rate_index)
            window.player.seek(start, exact=True)
            wait_until(app, window.player.seeker.is_settled, "initial exact frame", 30_000)
            window.plot_pane.fit_all_y()
            window.notifications.clear_all()
            # Give scene fitting and deferred paints a real event-loop turn.
            from PySide6.QtCore import QEventLoop, QTimer

            loop = QEventLoop(app)
            QTimer.singleShot(1500, loop, loop.quit)
            loop.exec()
            window.transport.set_status("Ready")
            window.grab().save(str(output.with_suffix(".png")))
            report.update(
                common_coverage=[left, right],
                start=start,
                playback_speed=speed,
                coverage=[{"label": c.label, "data": c.data} for c in coverage],
            )
            report.update(_record(window, app, output, args.duration, args.fps, pool))
            report["status"] = "ok"
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        window.close()
        drain_abandoned()
        output.with_suffix(".json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        shutil.rmtree(USER_STATE_SANDBOX, ignore_errors=True)


def main() -> None:
    """Discover inputs, then run each clip sequentially in a fresh process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="*")
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument(
        "--imaging-fps",
        type=float,
        default=30.0,
        help="Provisional acquisition rate for untimed stacks only (default: 30)",
    )
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--one", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.duration <= 0 or not math.isfinite(args.duration) or not 1 <= args.fps <= 60:
        parser.error("duration must be positive and finite; fps must be between 1 and 60")
    if args.one:
        record_one(args)
        return
    if not args.paths and not args.data_root.is_dir():
        parser.error(f"no recordings given and {args.data_root} is not a folder")
    paths = [path.resolve() for path in args.paths] or discover(args.data_root.resolve())
    if not paths:
        parser.error(f"no recordings found under {args.data_root}")
    if args.list:
        for path in paths:
            print(path)
        return
    from avialsync.runtime import no_window_kwargs

    output = args.output.resolve() / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output.mkdir(parents=True)
    failures = []
    for index, path in enumerate(paths, 1):
        raw_name = path.stem if path.is_file() else path.name
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", raw_name).strip("_") or "session"
        movie = output / f"{index:02d}_{name}.mp4"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            str(path),
            "--one",
            "--output",
            str(movie),
            "--duration",
            str(args.duration),
            "--fps",
            str(args.fps),
            "--width",
            str(args.width),
            "--height",
            str(args.height),
        ]
        if args.imaging_fps is not None:
            command.extend(["--imaging-fps", str(args.imaging_fps)])
        print(f"[{index}/{len(paths)}] {path} -> {movie}", flush=True)
        with movie.with_suffix(".log").open("w", encoding="utf-8") as log:
            try:
                result = subprocess.run(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=1200,
                    **no_window_kwargs(),
                )
                if result.returncode:
                    failures.append(str(path))
            except subprocess.TimeoutExpired:
                failures.append(str(path))
                log.write("\nCapture exceeded the 20-minute session timeout.\n")
    (output / "summary.json").write_text(
        json.dumps({"inputs": [str(p) for p in paths], "failed": failures}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Clips and reports: {output}", flush=True)
    if failures:
        print(f"{len(failures)} dataset(s) could not be recorded; see individual logs.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
