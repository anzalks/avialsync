"""Coverage for the four import/inspection dialogs (P6.1).

`import_wizard`, `relink_dialog`, `import_report`, and `batch_import_dialog`
were at 0 % coverage — roughly 400 statements of user-facing code with no test
touching them at all. These exercise what each dialog is actually for: reading a
file's shape, producing a config the import pipeline can consume, resolving a
moved file, and reporting what an import found.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from avialview.core.inspection import ImportReport, IntegrityFlags, SourceInspection
from avialview.ui.batch_import_dialog import BatchImportDialog
from avialview.ui.import_report import ImportReportDialog
from avialview.ui.import_wizard import ImportWizard
from avialview.ui.relink_dialog import RelinkDialog


# ── ImportWizard ──────────────────────────────────────────────────────


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    path = tmp_path / "signals.csv"
    path.write_text(
        "timestamp,force_z,angle\n0.00,1.5,10\n0.01,1.6,11\n0.02,1.7,12\n",
        encoding="utf-8",
    )
    return path


def test_wizard_previews_the_headers_it_found(qapp: QApplication, qtbot, csv_file: Path) -> None:
    wizard = ImportWizard(csv_file)
    qtbot.addWidget(wizard)

    assert wizard._headers == ["timestamp", "force_z", "angle"]
    assert len(wizard._sample_rows) == 3


def test_wizard_guesses_the_time_column(qapp: QApplication, qtbot, csv_file: Path) -> None:
    """A column literally called "timestamp" must not need manual selection."""
    wizard = ImportWizard(csv_file)
    qtbot.addWidget(wizard)

    assert wizard.config()["time_col"] == "timestamp"


def test_wizard_config_is_shaped_for_the_import_pipeline(
    qapp: QApplication, qtbot, csv_file: Path
) -> None:
    wizard = ImportWizard(csv_file)
    qtbot.addWidget(wizard)

    config = wizard.config()

    for key in (
        "separator",
        "time_col",
        "time_format",
        "time_unit",
        "timezone",
        "sentinel",
        "euro_decimal",
    ):
        assert key in config, key
    assert config["separator"] == ","
    assert config["timezone"], "a concrete zone must be resolved, never 'local'"


def test_wizard_detects_a_semicolon_dialect(qapp: QApplication, qtbot, tmp_path: Path) -> None:
    path = tmp_path / "euro.csv"
    path.write_text("time;value\n0,0;1,5\n0,1;1,6\n", encoding="utf-8")

    wizard = ImportWizard(path)
    qtbot.addWidget(wizard)

    assert wizard.config()["separator"] == ";"


def test_wizard_survives_a_header_only_file(qapp: QApplication, qtbot, tmp_path: Path) -> None:
    """A file with no data rows must open, not raise, so the user can see why."""
    path = tmp_path / "empty.csv"
    path.write_text("time,value\n", encoding="utf-8")

    wizard = ImportWizard(path)
    qtbot.addWidget(wizard)

    assert wizard._headers == ["time", "value"]
    assert wizard._sample_rows == []


def test_wizard_euro_decimal_flag_round_trips(qapp: QApplication, qtbot, csv_file: Path) -> None:
    wizard = ImportWizard(csv_file)
    qtbot.addWidget(wizard)

    wizard._euro_chk.setChecked(True)

    assert wizard.config()["euro_decimal"] is True


# ── RelinkDialog ──────────────────────────────────────────────────────


def test_relink_starts_with_nothing_resolved(qapp: QApplication, qtbot) -> None:
    dialog = RelinkDialog(["/gone/cam.mp4", "/gone/data.csv"], {})
    qtbot.addWidget(dialog)

    assert dialog.resolved_mapping() == {}


def test_relink_records_the_replacement_the_user_picked(
    qapp: QApplication, qtbot, tmp_path: Path, monkeypatch
) -> None:
    """Browsing is the only way a path gets resolved, so drive that."""
    from PySide6.QtWidgets import QFileDialog

    replacement = tmp_path / "cam.mp4"
    replacement.write_bytes(b"\x00")
    dialog = RelinkDialog(["/gone/cam.mp4", "/gone/data.csv"], {})
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(replacement), ""))
    )

    dialog._browse(0, "/gone/cam.mp4")

    assert dialog.resolved_mapping() == {"/gone/cam.mp4": str(replacement)}


def test_relink_leaves_unbrowsed_paths_unresolved(
    qapp: QApplication, qtbot, tmp_path: Path, monkeypatch
) -> None:
    """Skipping a file must open the session without it, not invent a path."""
    from PySide6.QtWidgets import QFileDialog

    replacement = tmp_path / "cam.mp4"
    replacement.write_bytes(b"\x00")
    dialog = RelinkDialog(["/gone/cam.mp4", "/gone/data.csv"], {})
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(replacement), ""))
    )

    dialog._browse(0, "/gone/cam.mp4")

    assert "/gone/data.csv" not in dialog.resolved_mapping()


def test_relink_cancelled_browse_resolves_nothing(qapp: QApplication, qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog

    dialog = RelinkDialog(["/gone/cam.mp4"], {})
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))

    dialog._browse(0, "/gone/cam.mp4")

    assert dialog.resolved_mapping() == {}


def test_relink_mapping_is_a_copy(qapp: QApplication, qtbot) -> None:
    """Callers must not be able to mutate the dialog's state through the result."""
    dialog = RelinkDialog(["/gone/cam.mp4"], {})
    qtbot.addWidget(dialog)

    dialog.resolved_mapping()["/gone/cam.mp4"] = "/injected"

    assert dialog.resolved_mapping() == {}


# ── ImportReportDialog ────────────────────────────────────────────────


@pytest.fixture
def inspection() -> SourceInspection:
    return SourceInspection(
        path="/tmp/signals.csv",
        loader_id="CSVLoader",
        import_config={"time_col": "timestamp"},
        import_report=ImportReport(
            rows_parsed=1_000,
            gap_count=2,
            nan_count=7,
            gap_locations=(1.5, 9.25),
        ),
        integrity_flags=IntegrityFlags(has_gaps=True),
    )


def test_import_report_states_what_the_import_found(
    qapp: QApplication, qtbot, inspection: SourceInspection
) -> None:
    dialog = ImportReportDialog(inspection)
    qtbot.addWidget(dialog)

    text = dialog.as_plain_text()

    assert "1000" in text.replace(",", "")
    assert "CSVLoader" in text
    assert "signals.csv" in text


def test_import_report_copy_puts_the_same_text_on_the_clipboard(
    qapp: QApplication, qtbot, inspection: SourceInspection
) -> None:
    dialog = ImportReportDialog(inspection)
    qtbot.addWidget(dialog)

    dialog._copy()

    assert QApplication.clipboard().text() == dialog.as_plain_text()


def test_import_report_handles_a_source_with_no_report(qapp: QApplication, qtbot) -> None:
    """A v1 session carries no ImportReport; the dialog must still open."""
    dialog = ImportReportDialog(SourceInspection(path="/tmp/old.csv"))
    qtbot.addWidget(dialog)

    assert dialog.as_plain_text()


# ── BatchImportDialog ─────────────────────────────────────────────────


def test_batch_dialog_offers_one_row_per_dropped_file(
    qapp: QApplication, qtbot, tmp_path: Path
) -> None:
    from avialview.loaders.csv_loader import CSVLoader

    candidates = [
        (tmp_path / "a.csv", CSVLoader, None),
        (tmp_path / "b.csv", CSVLoader, None),
    ]

    dialog = BatchImportDialog(candidates)
    qtbot.addWidget(dialog)

    assert len(dialog._combos) == 2


def test_batch_dialog_returns_the_selected_loader_for_each_file(
    qapp: QApplication, qtbot, tmp_path: Path
) -> None:
    from avialview.loaders.csv_loader import CSVLoader

    candidates = [(tmp_path / "a.csv", CSVLoader, {"time_col": "t"})]

    dialog = BatchImportDialog(candidates)
    qtbot.addWidget(dialog)
    selections = dialog.get_selections()

    assert len(selections) == 1
    path, loader, config = selections[0]
    assert path == tmp_path / "a.csv"
    assert loader is CSVLoader
    assert config == {"time_col": "t"}


def test_batch_dialog_preserves_each_files_own_config(
    qapp: QApplication, qtbot, tmp_path: Path
) -> None:
    """Configs are per-file; one file's settings must not leak onto another."""
    from avialview.loaders.csv_loader import CSVLoader

    candidates = [
        (tmp_path / "a.csv", CSVLoader, {"time_col": "t_a"}),
        (tmp_path / "b.csv", CSVLoader, {"time_col": "t_b"}),
    ]

    dialog = BatchImportDialog(candidates)
    qtbot.addWidget(dialog)

    configs = [config for _path, _loader, config in dialog.get_selections()]
    assert configs == [{"time_col": "t_a"}, {"time_col": "t_b"}]
