"""Import Report dialog — shows ImportReport stats with a copy-as-text button."""

from __future__ import annotations

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from avialsync.core.inspection import SourceInspection
from avialsync.ui.design_tokens import spacing
from avialsync.ui.i18n import tr
from avialsync.ui.theme import set_font_family


class ImportReportDialog(QDialog):
    """Scrollable plain-text view of an ImportReport with a Copy button."""

    def __init__(
        self,
        inspection: SourceInspection | None,
        parent: QWidget | None = None,
        *,
        properties: str = "",
        title: str = "",
    ) -> None:
        super().__init__(parent)
        self._inspection = inspection
        # The source's own properties first (resolution, depth, codec, rates),
        # then what the import found: one dialog answers "what is this file".
        self._properties = properties
        name = inspection.path.split("/")[-1] if inspection is not None else ""
        self.setWindowTitle(title or f"Import Report — {name}")
        self.resize(520, 380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(spacing("m"), spacing("m"), spacing("m"), spacing("m"))

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        set_font_family(self._text, mono_font)
        self._text.setPlainText(self.as_plain_text())

        scroll = QScrollArea()
        scroll.setWidget(self._text)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)

        btn_row = QHBoxLayout()
        copy_btn = QPushButton(tr("Copy as text"))
        copy_btn.clicked.connect(self._copy)
        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.as_plain_text())

    def as_plain_text(self) -> str:
        report = self._report_text() if self._inspection is not None else ""
        return "\n\n".join(part for part in (self._properties, report) if part)

    def _report_text(self) -> str:
        ins = self._inspection
        assert ins is not None
        lines = [
            "Import Report",
            f"{'=' * 50}",
            f"Path        : {ins.path}",
            f"Loader      : {ins.loader_id}",
            f"FPS binding : {ins.fps_binding or '(n/a)'}",
        ]

        cfg = ins.import_config
        if cfg:
            lines.append(f"Config      : {cfg}")

        rep = ins.import_report
        if rep:
            import datetime as _dt

            ts = _dt.datetime.fromtimestamp(rep.import_timestamp).strftime("%Y-%m-%d %H:%M:%S")
            lines += [
                "",
                "Statistics",
                f"{'-' * 30}",
                f"Imported at          : {ts}",
                f"Rows parsed          : {rep.rows_parsed:,}",
                f"Dropped (duplicate)  : {rep.rows_dropped_duplicate:,}",
                f"Dropped (non-monoton): {rep.rows_dropped_nonmonotonic:,}",
                f"NaN values           : {rep.nan_count:,}",
                f"Sentinel-mapped      : {rep.sentinel_count:,}",
                f"Gap count            : {rep.gap_count}",
            ]
            if rep.gap_locations:
                locs = ", ".join(f"{t:.3f}s" for t in rep.gap_locations[:10])
                n = len(rep.gap_locations)
                suffix = f"  (first {n} shown)" if n > 10 else ""
                lines.append(f"Gap positions        : {locs}{suffix}")
        else:
            lines.append("(no import report recorded)")

        flags = ins.integrity_flags
        flag_labels = flags.flag_labels()
        lines += ["", "Integrity flags", f"{'-' * 30}"]
        if flag_labels:
            for lbl in flag_labels:
                lines.append(f"  ⚠  {lbl}")
        else:
            lines.append("  (none)")

        return "\n".join(lines)
