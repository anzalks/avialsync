"""Exact mappings: prepared once on a worker, shared everywhere after (D-201).

Two proofs. On a variable-rate fixture whose frames carry their own index in
their pixels, the accepted mapping still shows frame *k* at exposure *k* after
undo, redo, and a saved session reopened. At a million frames, accepting,
undoing, redoing, and reopening install the worker's frozen buffers without
scanning or copying them on the UI thread -- timed, and traced for memory.
"""

from __future__ import annotations

import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pytest
from shiboken6 import isValid

from avialsync.core.session import SessionState, exact_mapping_dir
from avialsync.core.sync import AlignmentMethod, fit_exact_index_mapping
from avialsync.core.timeline import TimeMap
from avialsync.engine.pyav_reader import PyAVReader, to_rgb_array
from avialsync.loaders.video_standard import VideoStandardLoader
from avialsync.ui.job_manager import drain_abandoned
from avialsync.ui.main_window import MainWindow
from avialsync.ui.video_pane import drain_abandoned_decoders
from tests.util_framestrip import decode_frame_strip
from tests.util_pyav_fixtures import vfr_times, write_video

pytest.importorskip("av")

FRAMES = 120
MILLION = 1_000_000
#: The DAQ that recorded the strobe runs on its own placed clock.
DAQ_MAP = TimeMap(2.0, 162.0)
#: One float64 copy of a million-frame side is 8 MB; nothing near it may appear.
COPY_BYTES = MILLION * 8


@pytest.fixture(scope="module")
def vfr_video(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, np.ndarray]:
    path = tmp_path_factory.mktemp("exact") / "vfr.mp4"
    return path, np.asarray(write_video(path, frame_times=vfr_times(FRAMES), gop_size=30))


def _window(qtbot, monkeypatch, video: Path) -> MainWindow:
    window = MainWindow()
    qtbot.addWidget(window)
    # Sessions restore by hand-driving the open, as the probe worker would.
    monkeypatch.setattr(window, "_load_video", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(window, "_start_data_import", lambda *_args, **_kwargs: None)
    loader = VideoStandardLoader()
    loader.open(video, {})
    window._on_video_opened(str(video), loader, str(video))
    return window


def _reopen(qtbot, monkeypatch, window: MainWindow, video: Path, session: Path) -> MainWindow:
    window._build_session_state().save(session)
    window.close()
    reopened = MainWindow()
    qtbot.addWidget(reopened)
    monkeypatch.setattr(reopened, "_load_video", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(reopened, "_start_data_import", lambda *_args, **_kwargs: None)
    reopened._restore_session(SessionState.load(session))
    loader = VideoStandardLoader()
    loader.open(video, {})
    reopened._on_video_opened(str(video), loader, str(video))
    return reopened


def _assert_every_frame_is_shown_at_its_exposure(
    window: MainWindow, video: Path, master: np.ndarray
) -> None:
    """Decode the pixels at each exposure's master time; they must name that frame."""
    pane = window.video_grid.panes[0]
    with PyAVReader(video) as reader:
        for index in range(FRAMES):
            # Just inside the exposure's interval on the master clock.
            probe = master[index] + 0.25 * (
                (master[index + 1] if index + 1 < FRAMES else master[index] + 0.03) - master[index]
            )
            frame = reader.frame_at_time(pane.time_map.to_source(probe))
            assert decode_frame_strip(to_rgb_array(frame)) == index


def test_an_exact_mapping_shows_every_frame_through_undo_redo_and_reopen(
    qtbot, monkeypatch, tmp_path: Path, vfr_video: tuple[Path, np.ndarray]
) -> None:
    video, pts = vfr_video
    # The camera's own clock runs 30 ppm fast and started 100 s into the session.
    master = (pts - pts[0]) / (1.0 + 30e-6) + 100.0
    strobe_raw = DAQ_MAP.to_source_array(master)
    proposal = fit_exact_index_mapping(
        DAQ_MAP.to_master_array(strobe_raw),
        pts,
        reference_id="daq : strobe",
        target_id=str(video),
        verified_shared_strobe=True,
    )
    window = _window(qtbot, monkeypatch, video)

    window._accept_sync_proposal(str(video), proposal)
    _assert_every_frame_is_shown_at_its_exposure(window, video, master)
    window.document.undo(window._mutations)
    assert not window.video_grid.panes[0].time_map.has_exact_mapping
    window.document.redo(window._mutations)
    _assert_every_frame_is_shown_at_its_exposure(window, video, master)

    reopened = _reopen(qtbot, monkeypatch, window, video, tmp_path / "exact.avv")
    _assert_every_frame_is_shown_at_its_exposure(reopened, video, master)
    if isValid(reopened):
        reopened.close()


@pytest.fixture(scope="module")
def million() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(11)
    source = np.cumsum(rng.uniform(1 / 32, 1 / 28, MILLION))
    master = source / (1.0 + 30e-6) + 100.0
    return master, source


#: CPython 3.11's ``tracemalloc.stop()`` races allocations on other threads and
#: can segfault (fixed in 3.12). The decoder threads a video pane starts are
#: exactly such threads, so 3.11 checks the no-copy claim by identity alone.
TRACE_MEMORY = sys.version_info >= (3, 12)


class _Measured:
    """Wall time and peak traced allocation per step, under one tracing session.

    Tracing starts once, before any window exists, and stops only after every
    window has closed and its threads are joined: starting and stopping around
    each step is what raced the decoder threads.
    """

    def __init__(self) -> None:
        self.steps: dict[str, tuple[float, int]] = {}

    def __enter__(self) -> _Measured:
        drain_abandoned()
        if TRACE_MEMORY:
            tracemalloc.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        drain_abandoned()
        drain_abandoned_decoders(timeout_ms=5000)
        if TRACE_MEMORY:
            tracemalloc.stop()

    def __call__(self, step: str, action) -> None:
        before = 0
        if TRACE_MEMORY:
            tracemalloc.reset_peak()
            before, _ = tracemalloc.get_traced_memory()
        started = time.perf_counter()
        action()
        elapsed = time.perf_counter() - started
        peak = tracemalloc.get_traced_memory()[1] - before if TRACE_MEMORY else 0
        self.steps[step] = (elapsed, peak)


def test_a_million_frame_mapping_is_installed_shared_never_copied(
    qtbot,
    monkeypatch,
    tmp_path: Path,
    vfr_video: tuple[Path, np.ndarray],
    million: tuple[np.ndarray, np.ndarray],
    record_property,
) -> None:
    video, _ = vfr_video
    master, source = million
    # The worker's part: validate once and freeze.
    started = time.perf_counter()
    proposal = fit_exact_index_mapping(
        master,
        source,
        reference_id="daq : strobe",
        target_id=str(video),
        verified_shared_strobe=True,
    )
    record_property("worker_prepare_s", round(time.perf_counter() - started, 4))
    prepared = proposal.fit.prepared_mapping
    assert proposal.fit.method is AlignmentMethod.EXACT and prepared is not None

    with _Measured() as measure:
        window = _window(qtbot, monkeypatch, video)
        # Acceptance checks the strobe against the stored-frame table; this pane
        # stands in for a million-frame recording, whose table is this one.
        window._video_frame_times[str(video)] = source
        pane = window.video_grid.panes[0]

        measure("accept", lambda: window._accept_sync_proposal(str(video), proposal))
        assert pane.time_map._exact_master is prepared.master
        assert window._sync_provenance[-1].exact_master is prepared.master
        measure("undo", lambda: window.document.undo(window._mutations))
        assert not pane.time_map.has_exact_mapping
        measure("redo", lambda: window.document.redo(window._mutations))
        assert pane.time_map._exact_master is prepared.master
        assert pane.time_map._exact_source is prepared.source

        session = tmp_path / "million.avv"
        window._build_session_state().save(session)
        assert any(exact_mapping_dir(session).glob("exact-sync-*.npz"))
        window.close()
        # The load worker's part: read the sidecar, validate it, freeze it.
        state = SessionState.load(session)
        reopened = MainWindow()
        qtbot.addWidget(reopened)
        monkeypatch.setattr(reopened, "_load_video", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(reopened, "_start_data_import", lambda *_args, **_kwargs: None)
        reopened._restore_session(state)
        loader = VideoStandardLoader()
        loader.open(video, {})
        measure("reopen", lambda: reopened._on_video_opened(str(video), loader, str(video)))
        restored = reopened.video_grid.panes[0].time_map
        assert restored._exact_master is state.sync_provenance[0].exact_master
        for index in (0, 1, MILLION // 2, MILLION - 1):
            assert restored.to_source(float(master[index])) == pytest.approx(
                source[index], abs=1e-9
            )
        reopened.close()

    measured = measure.steps
    for step, (seconds, peak) in measured.items():
        record_property(f"{step}_s", round(seconds, 4))
        record_property(f"{step}_peak_bytes", peak)
        if step == "reopen":
            # Building the pane starts its decoder, whose frames are traced
            # too; identity above is the proof that nothing was copied.
            continue
        # Half of one side: a decoded frame or two from the seek fits under
        # it, any copy of the mapping cannot.
        assert peak < COPY_BYTES // 2, f"{step} allocated {peak / 1e6:.1f} MB: a copy was made"
        assert seconds < 0.25, f"{step} held the UI thread {seconds * 1000:.0f} ms"
