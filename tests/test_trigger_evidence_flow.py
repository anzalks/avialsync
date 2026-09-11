"""From a CSV on disk to evidence the alignment wizard will offer.

The plugin, the dialog, the worker and the wizard are separate pieces; this is
the path a user actually walks through them.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox
from shiboken6 import isValid

from avialsync.core.triggers import TriggerKind
from avialsync.engine.trigger_worker import TriggerReadWorker
from avialsync.loaders.trigger_csv import LEVEL, TriggerCSVSource
from avialsync.ui.main_window import MainWindow
from avialsync.ui.trigger_dialog import TriggerEvidenceDialog


def _write_daq(path: Path, *, seconds: float = 4.0, rate: float = 1000.0) -> Path:
    times = np.arange(0.0, seconds, 1.0 / rate)
    front = np.zeros_like(times)
    sync = np.zeros_like(times)
    for index in range(int(seconds * 20)):
        rise = 0.01 + index * 0.05
        front[(times >= rise) & (times < rise + 0.004)] = 1.0
    for index in range(int(seconds)):
        rise = 0.02 + index * 1.0
        sync[(times >= rise) & (times < rise + 0.05)] = 1.0
    rows = ["t,front_strobe,sync_ttl"]
    rows += [f"{t:.6f},{f:.1f},{y:.1f}" for t, f, y in zip(times, front, sync, strict=True)]
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


@pytest.fixture
def window(qapp: QApplication, qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    yield win
    if isValid(win):
        win.close()


class TestTheDialogAsksTheQuestionThatMatters:
    def test_nothing_is_preselected_as_a_strobe(self, qtbot, tmp_path: Path) -> None:
        """Which way the wire ran is not in the file, and it decides the model."""
        path = _write_daq(tmp_path / "ttl.csv")
        dialog = TriggerEvidenceDialog(path, TriggerCSVSource.suggest_trains(path)[0], [])
        qtbot.addWidget(dialog)

        kinds = {choice.kind for choice in dialog.choices()}
        assert kinds == {TriggerKind.SYNC_TRAIN}

    def test_the_user_can_say_a_line_is_a_strobe(self, qtbot, tmp_path: Path) -> None:
        path = _write_daq(tmp_path / "ttl.csv")
        dialog = TriggerEvidenceDialog(path, TriggerCSVSource.suggest_trains(path)[0], [])
        qtbot.addWidget(dialog)

        combo = dialog._table.cellWidget(0, 3)
        assert isinstance(combo, QComboBox)
        combo.setCurrentIndex(combo.findData(str(TriggerKind.FRAME_STROBE)))

        assert dialog.choices()[0].kind is TriggerKind.FRAME_STROBE
        assert dialog.config()["trains"][0]["kind"] == "frame_strobe"

    def test_an_unticked_line_is_left_out(self, qtbot, tmp_path: Path) -> None:
        path = _write_daq(tmp_path / "ttl.csv")
        dialog = TriggerEvidenceDialog(path, TriggerCSVSource.suggest_trains(path)[0], [])
        qtbot.addWidget(dialog)

        use = dialog._table.cellWidget(0, 0)
        assert isinstance(use, QCheckBox)
        use.setChecked(False)

        assert [choice.train_id for choice in dialog.choices()] == ["sync_ttl"]

    def test_a_train_can_be_pointed_at_a_camera(self, qtbot, tmp_path: Path) -> None:
        path = _write_daq(tmp_path / "ttl.csv")
        dialog = TriggerEvidenceDialog(
            path, TriggerCSVSource.suggest_trains(path)[0], ["/tmp/front.mp4"]
        )
        qtbot.addWidget(dialog)

        targets = dialog._table.cellWidget(0, 4)
        assert isinstance(targets, QComboBox)
        targets.setCurrentIndex(targets.findData("/tmp/front.mp4"))

        assert dialog.choices()[0].target == "/tmp/front.mp4"


class TestReadingItOffTheUiThread:
    def test_every_declared_train_comes_back(self, tmp_path: Path) -> None:
        path = _write_daq(tmp_path / "ttl.csv")
        worker = TriggerReadWorker(
            TriggerCSVSource(),
            path,
            {
                "time_column": "t",
                "trains": [
                    {
                        "id": "front",
                        "column": "front_strobe",
                        "kind": str(TriggerKind.FRAME_STROBE),
                        "mode": LEVEL,
                    },
                    {
                        "id": "sync",
                        "column": "sync_ttl",
                        "kind": str(TriggerKind.SYNC_TRAIN),
                        "mode": LEVEL,
                    },
                ],
            },
        )
        results: list[object] = []
        errors: list[str] = []
        worker.finished.connect(results.append)
        worker.error.connect(errors.append)

        worker.run()

        assert errors == []
        trains = results[0]
        assert [train.train_id for train in trains] == ["front", "sync"]
        assert trains[0].kind is TriggerKind.FRAME_STROBE
        assert trains[0].count == pytest.approx(80, abs=1)

    def test_a_line_that_never_transitions_is_reported_not_returned_empty(
        self, tmp_path: Path
    ) -> None:
        """A partial set would leave the user to notice which train was missing."""
        path = tmp_path / "flat.csv"
        path.write_text(
            "t,ttl\n" + "\n".join(f"{i * 0.001:.3f},0.0" for i in range(500)),
            encoding="utf-8",
        )
        worker = TriggerReadWorker(
            TriggerCSVSource(),
            path,
            {
                "time_column": "t",
                "trains": [
                    {
                        "id": "ttl",
                        "column": "ttl",
                        "kind": str(TriggerKind.SYNC_TRAIN),
                        "mode": LEVEL,
                    }
                ],
            },
        )
        errors: list[str] = []
        worker.error.connect(errors.append)

        worker.run()

        assert errors and "check the threshold" in errors[0]


class TestItReachesTheWizard:
    def test_loaded_trains_make_alignment_available(
        self, window: MainWindow, tmp_path: Path
    ) -> None:
        """A trigger file is evidence on its own terms, with no video loaded."""
        assert not window._has_alignment_evidence()

        path = _write_daq(tmp_path / "ttl.csv")
        source = TriggerCSVSource()
        config = {
            "time_column": "t",
            "trains": [
                {
                    "id": "sync",
                    "column": "sync_ttl",
                    "kind": str(TriggerKind.SYNC_TRAIN),
                    "mode": LEVEL,
                }
            ],
        }
        worker = TriggerReadWorker(source, path, config)
        worker.finished.connect(lambda results: window._on_trigger_trains_read(str(path), results))
        worker.run()

        assert window._trigger_trains
        assert window._has_alignment_evidence()

    def test_a_train_with_gaps_says_so_on_arrival(
        self, window: MainWindow, tmp_path: Path, qtbot
    ) -> None:
        """A train that skips beats is the evidence frames were lost, and the
        reason an index-paired mapping would be wrong."""
        path = tmp_path / "gappy.csv"
        times = np.arange(0.0, 4.0, 0.001)
        values = np.zeros_like(times)
        for index in range(40):
            if index == 20:
                continue  # one exposure never happened
            rise = 0.01 + index * 0.1
            values[(times >= rise) & (times < rise + 0.01)] = 1.0
        path.write_text(
            "t,strobe\n"
            + "\n".join(f"{t:.6f},{v:.1f}" for t, v in zip(times, values, strict=True)),
            encoding="utf-8",
        )
        source = TriggerCSVSource()
        worker = TriggerReadWorker(
            source,
            path,
            {
                "time_column": "t",
                "trains": [
                    {
                        "id": "strobe",
                        "column": "strobe",
                        "kind": str(TriggerKind.FRAME_STROBE),
                        "mode": LEVEL,
                    }
                ],
            },
        )
        seen: list[object] = []
        worker.finished.connect(seen.append)
        worker.run()

        assert seen[0][0].drops, "the missing exposure was not located"
        window._on_trigger_trains_read(str(path), seen[0])
        assert window._trigger_trains[str(path)][0].drops
